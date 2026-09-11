"""通用业务依赖：任务加载与归属校验（防越权）"""
from fastapi import HTTPException
from schema.drama_schema import DramaTask


async def load_owned_task(task_id: str, user, agent) -> DramaTask:
    """加载任务并校验归属：任务不存在返回 404，非本人任务返回 403。

    - user: 当前登录用户（get_current_user 依赖产物，含 id）
    - agent: DramaAgent 实例，调用其 load_task（内存优先、DB 兜底）
    """
    task = await agent.load_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    # user_id 为 None 的历史遗留任务放行；正常任务必须属于当前用户
    if task.user_id is not None and task.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该任务")
    return task
