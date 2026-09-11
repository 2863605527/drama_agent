"""路由层共享依赖：限流工厂 + agent 注入"""
from fastapi import HTTPException, Request

from api import context
from agent.drama_agent import DramaAgent
from core.ratelimit import rate_limiter


def rate_limit(limit: str):
    """固定窗口限流，按 客户端IP + 路径 维度"""
    async def _dep(request: Request):
        ip = request.client.host if request.client else "unknown"
        key = f"{ip}:{request.url.path}"
        allowed, remaining = rate_limiter.is_allowed(key, limit)
        if not allowed:
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
    return _dep


def get_agent() -> DramaAgent:
    """运行时 DramaAgent 单例（lifespan 中重建，此处实时读取模块属性）"""
    return context.agent
