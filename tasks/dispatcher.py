"""长任务调度分发：按 USE_CELERY 在「进程内 asyncio」与「Celery 队列」间切换。

- USE_CELERY=false（默认，本地开发）：asyncio.create_task 在 Web 进程后台跑 job_runner 协程；
- USE_CELERY=true（生产）：投递到 Celery+Redis，由独立 worker 进程执行，Web 请求立即返回。

两条路径执行体都是 tasks.job_runner（只认 task_id、从 DB 重建、结果落库），保证行为一致；
进度统一经 progress_hub/SSE 推送。on_finish 回调支持同步或协程（用于刷新内存副本/释放忙锁）。
"""
import asyncio
import inspect
from typing import Callable, Optional, Union

from core.config import settings
from tools.logger_tool import get_logger

logger = get_logger("drama.dispatch")


def is_celery_mode() -> bool:
    return bool(settings.use_celery)


async def _call_finish(on_finish: Optional[Callable]):
    if on_finish is None:
        return
    result = on_finish()
    if inspect.isawaitable(result):
        await result


async def schedule_segment_video(task_id: str, segment_id: str,
                                 on_finish: Optional[Callable] = None) -> str:
    """调度单个片段视频生成，返回执行通道 'celery' / 'local'。"""
    if settings.use_celery:
        from tasks.celery_jobs import generate_segment_video_task
        generate_segment_video_task.delay(task_id, segment_id)
        logger.info("segment video -> celery | task=%s seg=%s", task_id, segment_id)
        return "celery"

    from tasks import job_runner

    async def _bg():
        try:
            await job_runner.run_segment_video_job(task_id, segment_id)
        finally:
            await _call_finish(on_finish)

    asyncio.create_task(_bg())
    return "local"


async def schedule_compose(task_id: str,
                           on_finish: Optional[Callable] = None) -> str:
    """调度完整短剧合成，返回执行通道 'celery' / 'local'。"""
    if settings.use_celery:
        from tasks.celery_jobs import compose_video_task
        compose_video_task.delay(task_id)
        logger.info("compose -> celery | task=%s", task_id)
        return "celery"

    from tasks import job_runner

    async def _bg():
        try:
            await job_runner.run_compose_job(task_id)
        finally:
            await _call_finish(on_finish)

    asyncio.create_task(_bg())
    return "local"
