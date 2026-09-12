"""P1-6：MySQL 兼容性测试（CI MySQL 8 矩阵专用）。

依赖环境变量 MYSQL_HOST 等指向真实 MySQL；本地/无 MySQL 时自动跳过。
覆盖：init_db 建表 + token_version 幂等补列 + 用户 CRUD（改密版本自增）。
"""
import asyncio
import os

import pytest

pytestmark = pytest.mark.mysql


@pytest.mark.skipif(not os.getenv("MYSQL_HOST"), reason="未配置 MYSQL_HOST（仅在 CI MySQL 矩阵中运行）")
def test_mysql_init_and_token_version_roundtrip():
    from sqlalchemy import inspect, text

    async def run():
        import db.database as dbmod
        assert "mysql" in dbmod.DATABASE_URL.lower(), f"期望 MySQL 连接，实际: {dbmod.DATABASE_URL}"

        # 1) init_db：建表 + 幂等补列（重复调用不报错 = 幂等）
        await dbmod.init_db()
        await dbmod.init_db()

        # 2) users.token_version 列存在且默认 0
        async with dbmod.engine.begin() as conn:
            inspector = inspect(conn)
            cols = {c["name"] for c in inspector.get_columns("users")}
            assert "token_version" in cols, f"users 缺 token_version 列: {cols}"

        # 3) CRUD + 改密版本自增（吊销语义）
        from db import crud
        from core.security import hash_password, verify_password
        from db.database import AsyncSessionLocal
        import uuid
        uname = f"mysqlprobe_{uuid.uuid4().hex[:8]}"
        async with AsyncSessionLocal() as sdb:
            user = await crud.create_user(sdb, uname, hash_password("initpass123"))
            uid = user.id
            assert user.token_version == 0
            await crud.update_password(sdb, user, hash_password("newpass123"))
            assert user.token_version == 1
            await crud.bump_token_version(sdb, user)
            assert user.token_version == 2
            # 清理
            await sdb.execute(text("DELETE FROM users WHERE id=:i"), {"i": uid})
            await sdb.commit()
    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("MYSQL_HOST"), reason="未配置 MYSQL_HOST（仅在 CI MySQL 矩阵中运行）")
def test_mysql_tasks_channel_columns_exist():
    """老库补列机制在 MySQL 上同样生效：tasks 表含 channel_config/episode/logs 列。"""
    import asyncio
    from sqlalchemy import inspect

    async def run():
        import db.database as dbmod
        async with dbmod.engine.begin() as conn:
            inspector = inspect(conn)
            cols = {c["name"] for c in inspector.get_columns("tasks")}
            for need in ("channel_config", "parent_id", "episode_no", "series_title", "logs"):
                assert need in cols, f"tasks 缺 {need} 列: {cols}"
    asyncio.run(run())
