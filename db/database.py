import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from core.config import settings

# 本地开发回退：设置 DRAMA_DB=sqlite 时用 SQLite（无需安装/启动 MySQL），生产默认仍走 MySQL
if os.getenv("DRAMA_DB", "").strip().lower() in ("sqlite", "sqlite3"):
    DATABASE_URL = "sqlite+aiosqlite:///./drama_agent.db"
else:
    DATABASE_URL = settings.database_url

engine = create_async_engine(
    DATABASE_URL, echo=settings.debug, pool_pre_ping=True,
    pool_size=10, max_overflow=20, pool_recycle=3600,
)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


async def init_db():
    """启动时创建所有表（生产环境建议改用 Alembic 迁移，见 migrations/）"""
    from db import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # 幂等补列：老库 tasks 表缺列时自动 ALTER 补上，避免手动迁移
        await conn.run_sync(_ensure_tasks_channel_config)
        await conn.run_sync(_ensure_tasks_episode_and_logs)
        await conn.run_sync(_ensure_users_token_version)


def _ensure_tasks_channel_config(sync_conn):
    """同步探测 tasks 表结构，缺 channel_config 列则 ALTER 补上（MySQL / SQLite 兼容）。"""
    from sqlalchemy import inspect, text
    inspector = inspect(sync_conn)
    if "tasks" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("tasks")}
    if "channel_config" in cols:
        return
    dialect = sync_conn.dialect.name
    col_type = "JSON" if dialect == "mysql" else "JSON"
    sync_conn.execute(text(f"ALTER TABLE tasks ADD COLUMN channel_config {col_type} NULL"))


# 多集续写 + 日志持久化所需的新列（老库幂等补齐）
_EPISODE_COLUMNS = {
    "parent_id": "VARCHAR(64) NULL",
    "episode_no": "INT DEFAULT 1",
    "series_title": "VARCHAR(255) NULL",
    "logs": "JSON NULL",
}


def _ensure_tasks_episode_and_logs(sync_conn):
    """缺 parent_id / episode_no / series_title / logs 列时逐个 ALTER 补上（MySQL / SQLite 兼容）。"""
    from sqlalchemy import inspect, text
    inspector = inspect(sync_conn)
    if "tasks" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("tasks")}
    for name, ddl in _EPISODE_COLUMNS.items():
        if name not in cols:
            sync_conn.execute(text(f"ALTER TABLE tasks ADD COLUMN {name} {ddl}"))


# P0：users 表 token_version 幂等补列（老库自动 ALTER，无需手动迁移）
def _ensure_users_token_version(sync_conn):
    from sqlalchemy import inspect, text
    inspector = inspect(sync_conn)
    if "users" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "token_version" not in cols:
        dialect = sync_conn.dialect.name
        default = "DEFAULT 0" if dialect == "mysql" else "DEFAULT 0"
        sync_conn.execute(text(f"ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL {default}"))


async def get_db():
    """FastAPI 依赖：获取数据库会话"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
