"""Celery 应用实例（仅 USE_CELERY=true 时由 Web/Worker 导入）。

启动 worker（容器内或服务器）：
    celery -A tasks.celery_app.celery_app worker --loglevel=INFO --concurrency=2

Broker/结果后端统一走 Redis（REDIS_URL）。未安装 celery 时本模块导入即报错，
但默认（USE_CELERY=false）下 Web 不会导入它，因此本地零依赖照常运行。
"""
from core.config import settings


def _broker() -> str:
    url = (settings.celery_broker_url or settings.redis_url or "").strip()
    if not url:
        raise RuntimeError("USE_CELERY=true 时必须配置 REDIS_URL（或 CELERY_BROKER_URL）")
    # redis:// 到 rediss:// 原样透传
    return url


def _backend() -> str:
    return (settings.celery_result_backend or settings.redis_url or _broker()).strip()


try:
    from celery import Celery
except ImportError as e:  # pragma: no cover - 仅在未装 celery 且误启用时触发
    raise ImportError("启用 Celery 需先安装依赖：pip install celery redis") from e

celery_app = Celery(
    "drama_agent",
    broker=_broker(),
    backend=_backend(),
    include=["tasks.celery_jobs"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=False,
    task_track_started=True,
    task_acks_late=True,                       # worker 崩溃时任务重新入队，避免丢任务
    worker_prefetch_multiplier=1,             # 长任务公平分发，不囤积
    task_default_queue="drama",
    task_soft_time_limit=settings.task_soft_time_limit,
    task_time_limit=settings.task_hard_time_limit,
    broker_connection_retry_on_startup=True,
    result_expires=86400,                     # 结果保留 1 天
)

# 导入以注册任务
from tasks import celery_jobs  # noqa: E402,F401
