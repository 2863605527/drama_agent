"""与执行器无关的异步任务逻辑：本地 asyncio 与 Celery worker 共用。

worker 是独立进程，不持有 Web 进程的内存任务表（DramaAgent.task_store），
因此这里的每个 job 都做到「只认 task_id」：从数据库重建任务 → 跑 skill 长任务 → 落库；
进度事件经 progress_hub 桥接到 Redis，Web 端 SSE 订阅者照常实时收到（跨进程）。

文件资产（assets/videos、assets/final）由 Web 与 worker 容器挂载同一个卷共享。
"""
import asyncio
from typing import Optional

from core.config import settings
from core import metrics
from db.database import AsyncSessionLocal, init_db
from db import crud
from db.models import Task as DBTask
from sqlalchemy import select
from schema.drama_schema import DramaTask, DramaScript
from skill.drama_make_skill import DramaMakeSkill
from agent.drama_agent import DramaAgent
from agent.progress_hub import progress_hub
from tools.logger_tool import get_logger, bind_log_context

logger = get_logger("drama.jobs")

_infra_ready = False
_skill: Optional[DramaMakeSkill] = None


def _get_skill() -> DramaMakeSkill:
    global _skill
    if _skill is None:
        _skill = DramaMakeSkill()
    return _skill


async def _ensure_infra() -> None:
    """幂等初始化：DB 表 + 进度 Redis 桥接（worker 进程首次执行任务时调用一次）。"""
    global _infra_ready
    if _infra_ready:
        return
    await init_db()
    redis_url = (settings.redis_url or "").strip()
    if redis_url:
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(redis_url, decode_responses=False)
            await progress_hub.attach_redis(client)
            logger.info("job progress bridge attached to redis")
        except Exception as e:
            logger.warning("attach redis bridge failed (fallback local-only): %s", e)
    _infra_ready = True


async def load_task(task_id: str) -> Optional[DramaTask]:
    """从 DB 重建 DramaTask（不依赖任何进程内存状态）。"""
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(DBTask).where(DBTask.task_id == task_id))).scalar_one_or_none()
        if not row:
            return None
        task = DramaTask(
            task_id=row.task_id, thread_id=row.task_id,
            user_prompt=row.user_prompt, style=row.style or "anime",
            status=row.status or "pending", audio_mode=row.audio_mode or "auto",
            final_video_url=row.final_video_url, user_id=row.user_id,
            channel_profile=DramaAgent._decrypt_channel(getattr(row, "channel_config", None)),
        )
        if row.script_data:
            task.script = DramaScript(**row.script_data)
        return task


async def persist_task(task: DramaTask) -> None:
    """任务状态/脚本/成片链接落库。"""
    script_data = task.script.model_dump(mode="json") if task.script else None
    status_val = task.status.value if hasattr(task.status, "value") else str(task.status)
    async with AsyncSessionLocal() as db:
        await crud.update_task(
            db, task.task_id, status=status_val, script_data=script_data,
            final_video_url=task.final_video_url, audio_mode=task.audio_mode)


async def run_segment_video_job(task_id: str, segment_id: str) -> bool:
    """生成单个片段视频（长任务：提交→轮询→下载→配音/混音，通常数分钟）。"""
    await _ensure_infra()
    bind_log_context(task_id=task_id, job="segment_video", segment_id=segment_id)
    metrics.ACTIVE_TASKS.inc()
    try:
        task = await load_task(task_id)
        if not task or not task.script:
            raise RuntimeError(f"task not found or empty script: {task_id}")
        seg = next((g for g in task.script.segments if g.segment_id == segment_id), None)
        if seg is None:
            raise RuntimeError(f"segment not found: {segment_id}")
        logger.info("job[segment_video] start | seg=%s", segment_id)
        ok = await _get_skill()._generate_segment_video(task, seg)
        await persist_task(task)   # 先落库，再广播 ok，保证前端回拉详情能读到 video_url
        if ok and getattr(seg, "video_url", None):
            seg_idx = task.script.segments.index(seg) + 1
            seg_total = len(task.script.segments)
            await progress_hub.publish(task_id, {
                "event": "segment", "index": seg_idx, "total": seg_total,
                "segment_id": seg.segment_id, "status": "ok",
                "video_url": seg.video_url, "duration": seg.duration,
                "shot_count": len(seg.shot_ids or []),
                "quality_warning": getattr(seg, "quality_warning", None),
            })
        logger.info("job[segment_video] done | ok=%s", ok)
        return bool(ok)
    except Exception as e:
        logger.error("job[segment_video] failed: %s", str(e)[:300])
        await progress_hub.publish(task_id, {"event": "log", "message": f"❌ 片段视频生成失败：{e}"})
        raise
    finally:
        metrics.ACTIVE_TASKS.dec()


async def run_compose_job(task_id: str) -> str:
    """合成完整短剧（长任务：ffmpeg 拼接全部片段）。"""
    await _ensure_infra()
    bind_log_context(task_id=task_id, job="compose")
    metrics.ACTIVE_TASKS.inc()
    try:
        task = await load_task(task_id)
        if not task or not task.script:
            raise RuntimeError(f"task not found or empty script: {task_id}")
        logger.info("job[compose] start")
        task = await _get_skill().compose_final_video(task)
        await persist_task(task)
        logger.info("job[compose] done | status=%s", task.status)
        return str(task.status)
    except Exception as e:
        logger.error("job[compose] failed: %s", str(e)[:300])
        await progress_hub.publish(task_id, {"event": "compose", "status": "failed",
                                            "message": f"❌ 合成失败：{e}"})
        raise
    finally:
        metrics.ACTIVE_TASKS.dec()


def run_async(coro):
    """同步上下文（Celery task）里跑一个协程：每个任务独立事件循环。"""
    return asyncio.run(coro)
