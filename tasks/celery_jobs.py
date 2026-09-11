"""Celery 任务定义：把耗时的片段视频生成 / 合成从 Web 进程剥离到 worker。

每个 Celery task 在独立事件循环（asyncio.run）中执行 job_runner 协程；
结束时关闭全局 MCP 持久通道，使下一个任务在新 loop 里干净重连，
避免「Future bound to a different event loop」。
"""
import asyncio

from tasks.celery_app import celery_app
from tasks import job_runner
from tools.logger_tool import get_logger

logger = get_logger("drama.celery")


async def _run_then_cleanup(coro):
    """跑任务协程，并在当前事件循环结束前关闭 MCP 持久子进程连接。"""
    try:
        return await coro
    finally:
        try:
            from mcp_client.agent_mcp_client import mcp_client
            await mcp_client.close()
        except Exception as e:
            logger.warning("mcp cleanup in worker failed: %s", e)


@celery_app.task(name="drama.generate_segment_video", bind=True,
                 max_retries=1, default_retry_delay=10, queue="drama")
def generate_segment_video_task(self, task_id: str, segment_id: str):
    try:
        return asyncio.run(_run_then_cleanup(
            job_runner.run_segment_video_job(task_id, segment_id)))
    except Exception as exc:
        # 瞬时故障自动重试 1 次；确定性错误不重试
        logger.error("segment video task error: %s", exc)
        raise self.retry(exc=exc)


@celery_app.task(name="drama.compose_video", bind=True,
                 max_retries=1, default_retry_delay=10, queue="drama")
def compose_video_task(self, task_id: str):
    try:
        return asyncio.run(_run_then_cleanup(job_runner.run_compose_job(task_id)))
    except Exception as exc:
        logger.error("compose task error: %s", exc)
        raise self.retry(exc=exc)
