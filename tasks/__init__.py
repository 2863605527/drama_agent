"""异步任务层。

- ``job_runner``：与执行器无关的纯异步任务逻辑（从 DB 重建任务 → 跑 skill 长任务 → 落库），
  本地 asyncio 模式与 Celery worker 模式共用同一套实现，保证两条路径行为一致。
- ``celery_app`` / ``celery_jobs``：Celery 实例与同步任务薄封装（仅 USE_CELERY=true 时启用）。
"""
