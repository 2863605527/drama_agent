"""启动时任务对账（reconcile）。

进程 / 容器重启后，内存里的 asyncio 后台任务全部消失，但数据库里的任务状态还停在运行态，
若不处理会出现「永远卡 PENDING」的悬挂任务。按状态分类恢复：

- pending（剧本解析中）：解析依赖一次性连续 LLM 调用，无法断点续跑，直接标记 failed 并写日志，
  引导用户点「重新开始」，避免永久转圈。
- generating_asset / human_review / generating_video / generating_shot：这些是**人工断点驱动**阶段，
  每张图 / 每段视频都由用户点击发起独立请求，任务数据完整，重启后保持原状态即可继续，无需改动。
- done / failed：终态，不动。

同时返回可恢复任务数量，供启动日志观测。
"""
import time

from db.database import AsyncSessionLocal
from db import crud
from schema.drama_schema import TaskStatus
from tools.logger_tool import get_logger

logger = get_logger("drama.reconcile")

# 人工断点阶段：重启后保持，用户可继续点击操作
_RESUMABLE = [
    TaskStatus.GENERATE_ASSET.value,
    TaskStatus.HUMAN_REVIEW.value,
    TaskStatus.GENERATE_VIDEO.value,
    TaskStatus.GENERATE_SHOT.value,
]


async def reconcile_on_startup() -> dict:
    """启动时恢复 / 标记悬挂任务。返回 {"failed": n, "resumable": m}。"""
    result = {"failed": 0, "resumable": 0}
    async with AsyncSessionLocal() as db:
        stuck = await crud.list_tasks_by_status(db, [TaskStatus.PENDING.value])
        for row in stuck:
            logs = list(row.logs or [])
            logs.append({
                "seq": int(time.time() * 1000),
                "message": "♻️ 检测到服务重启，该任务在剧本解析阶段中断且无法续跑，已标记失败，请点「重新开始」。",
            })
            await crud.update_task(db, row.task_id,
                                   status=TaskStatus.FAILED.value,
                                   logs=logs[-300:])
            result["failed"] += 1
        if result["failed"]:
            logger.warning("reconcile: %d stuck PENDING task(s) marked failed after restart",
                           result["failed"])

        resumable = await crud.list_tasks_by_status(db, _RESUMABLE)
        result["resumable"] = len(resumable)
        if result["resumable"]:
            logger.info("reconcile: %d task(s) at manual stages kept resumable", result["resumable"])
    return result
