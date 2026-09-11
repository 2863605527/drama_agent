"""业务路由包：按类拆分的 FastAPI 子路由，register_routers() 统一注册到 app。

- system.py       运维：/health /metrics
- auth.py         认证：/api/auth/*
- channels.py     通道配置：/api/channels/meta /api/user/channel-*
- tasks.py        任务业务：/api/task/*（创建/查询/审核/资产/编辑/合成）
- task_stream.py  SSE 进度流：/api/task/stream/{task_id}
"""
from fastapi import FastAPI

from api import system, auth, channels, tasks, task_stream


def register_routers(app: FastAPI) -> None:
    """把全部业务路由注册到 app（调用时机：中间件/异常处理之后、SPA 托管之前）"""
    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(channels.router)
    app.include_router(tasks.router)
    app.include_router(task_stream.router)
