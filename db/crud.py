import json
from typing import Optional
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import User, Task, UserChannelConfig


# ---------------- 用户 ----------------

async def get_user_by_username(db: AsyncSession, username: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def update_password(db: AsyncSession, user: User, new_password_hash: str) -> User:
    """改密码并吊销所有已签发 token（token_version +1）。"""
    user.password_hash = new_password_hash
    user.token_version = (user.token_version or 0) + 1
    await db.commit()
    await db.refresh(user)
    return user


async def bump_token_version(db: AsyncSession, user: User) -> User:
    """「退出所有设备」：token_version +1，旧 token 全部失效。"""
    user.token_version = (user.token_version or 0) + 1
    await db.commit()
    await db.refresh(user)
    return user


async def get_user_by_id(db: AsyncSession, user_id: int) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, username: str, password_hash: str) -> User:
    user = User(username=username, password_hash=password_hash, token_version=0)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ---------------- 用户通道配置 ----------------

async def get_user_channel_config_row(db: AsyncSession, user_id: int) -> Optional[UserChannelConfig]:
    result = await db.execute(
        select(UserChannelConfig).where(UserChannelConfig.user_id == user_id))
    return result.scalar_one_or_none()


async def get_user_channel_config(db: AsyncSession, user_id: int) -> Optional[dict]:
    row = await get_user_channel_config_row(db, user_id)
    return row.config if row else None


async def upsert_user_channel_config(db: AsyncSession, user_id: int, config: dict) -> dict:
    """新建或覆盖用户通道配置（config 应为已加密的 dict）。"""
    row = await get_user_channel_config_row(db, user_id)
    if row:
        row.config = config
    else:
        row = UserChannelConfig(user_id=user_id, config=config)
        db.add(row)
    await db.commit()
    await db.refresh(row)
    return row.config


# ---------------- 任务 ----------------

async def create_task(db: AsyncSession, task_id: str, user_id: int, user_prompt: str,
                      style: str = "anime", audio_mode: str = "auto",
                      channel_config: Optional[dict] = None,
                      parent_id: Optional[str] = None, episode_no: int = 1,
                      series_title: Optional[str] = None,
                      logs: Optional[list] = None) -> Task:
    task = Task(
        task_id=task_id,
        user_id=user_id,
        user_prompt=user_prompt,
        style=style,
        audio_mode=audio_mode,
        channel_config=channel_config,
        parent_id=parent_id,
        episode_no=episode_no,
        series_title=series_title,
        logs=logs,
        status="pending",
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


async def get_task_by_id(db: AsyncSession, task_id: str) -> Optional[Task]:
    result = await db.execute(select(Task).where(Task.task_id == task_id))
    return result.scalar_one_or_none()


async def list_user_tasks(db: AsyncSession, user_id: int, limit: int = 50) -> list[Task]:
    result = await db.execute(
        select(Task).where(Task.user_id == user_id).order_by(Task.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def list_tasks_by_status(db: AsyncSession, statuses: list[str]) -> list[Task]:
    """列出状态落在给定集合内的全部任务（跨用户），用于启动时 reconcile 悬挂任务。"""
    if not statuses:
        return []
    result = await db.execute(select(Task).where(Task.status.in_(statuses)))
    return list(result.scalars().all())


async def list_all_tasks(db: AsyncSession) -> list[Task]:
    """列出全部任务（仅用于资产孤儿回收时汇总被引用的本地文件）。"""
    result = await db.execute(select(Task))
    return list(result.scalars().all())


async def update_task(db: AsyncSession, task_id: str, **kwargs) -> Optional[Task]:
    """更新任务字段，script_data 需传入 dict 会自动 JSON 序列化"""
    task = await get_task_by_id(db, task_id)
    if not task:
        return None
    for key, value in kwargs.items():
        if hasattr(task, key):
            setattr(task, key, value)
    # 任务内容变更后，把其中引用到的本地资产幂等登记进 assets 元数据表（失败不阻断落库）
    if "script_data" in kwargs or "final_video_url" in kwargs:
        try:
            from tasks import asset_store
            await asset_store.sync_task_assets(db, task)
        except Exception:
            pass
    await db.commit()
    await db.refresh(task)
    return task


async def update_task_script(db: AsyncSession, task_id: str, script_dict: dict) -> Optional[Task]:
    """完整更新 script_data"""
    return await update_task(db, task_id, script_data=script_dict)


async def delete_task(db: AsyncSession, task_id: str) -> bool:
    """按 task_id 删除任务行；若为系列根任务，级联删除同系列所有子任务（续写各集）。
    不存在返回 False。"""
    task = await get_task_by_id(db, task_id)
    if not task:
        return False
    await db.execute(delete(Task).where(or_(Task.task_id == task_id, Task.parent_id == task_id)))
    await db.commit()
    return True
