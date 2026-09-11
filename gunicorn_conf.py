"""Gunicorn 生产配置：多 worker + Uvicorn worker + 优雅关闭。

启动：gunicorn main:app -c gunicorn_conf.py
注意：多 worker 下任务运行态在各自进程内存中，历史任务通过 MySQL 恢复（见 agent.load_task）；
SSE 实时事件为单实例内存推送，多实例部署需引入 Redis pub/sub（progress_hub 已预留扩展点）。
"""
import multiprocessing
import os

bind = f"0.0.0.0:{os.getenv('APP_PORT', '8010')}"
# worker 数：默认 1。本服务为 IO 密集（等待 LLM/视频 API），单进程 + asyncio 即可高并发；
# 且任务运行态、SSE 进度流与历史日志默认在进程内存，多 worker 会导致刷新后连到不同进程而丢日志/丢事件。
# 确需水平扩展时，显式设置 WEB_CONCURRENCY>1，并为 progress_hub 接入 Redis Pub/Sub。
workers = int(os.getenv("WEB_CONCURRENCY", "1"))
worker_class = "uvicorn.workers.UvicornWorker"

# 长任务（LLM/视频生成）需要较大超时
timeout = int(os.getenv("GUNICORN_TIMEOUT", "300"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = 5

# 优雅重启：处理完存量请求再退出
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = 50

# 日志
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
