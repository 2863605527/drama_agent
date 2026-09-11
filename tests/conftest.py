"""pytest 公共 fixtures。

测试不依赖真实 MySQL / LLM / 火山 API：
- 数据库用 SQLite 内存库（aiosqlite），通过 monkeypatch 替换全局 AsyncSessionLocal；
- agent 的后台流水线（MCP/LLM 调用）在认证/越权测试中被 mock 掉。
"""
import os

# 必须在导入应用代码前设置测试环境变量
os.environ["ENVIRONMENT"] = "development"
os.environ["JWT_SECRET_KEY"] = "unit-test-secret-key"
os.environ["LLM_API_KEY"] = "test-key"
os.environ["VOLC_ACCESS_KEY"] = "test-ak"
os.environ["VOLC_SECRET_KEY"] = "test-sk"

import pytest
import pytest_asyncio
import logging
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import db.database as db_module
import agent.drama_agent as agent_module
from db.database import Base, get_db
from core.ratelimit import rate_limiter
from main import app

# 关闭 SQLAlchemy/aiosqlite 的 DEBUG 噪音
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("aiosqlite").setLevel(logging.WARNING)

# ---------- SQLite 内存测试库 ----------
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
test_engine = create_async_engine(TEST_DB_URL, future=True)
TestSessionLocal = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False, future=True)


async def _override_get_db():
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def db_session():
    """每个测试用例独立建表/清表"""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # 让所有以 `from db.database import AsyncSessionLocal` 取别名的模块都走测试库
    # （只改 db_module 不够：别名在各模块 import 时已绑定，需逐模块替换，杜绝测试连真实 MySQL）
    import tasks.asset_store as asset_store_module
    import tasks.asset_gc as asset_gc_module
    import tasks.job_runner as job_runner_module
    import tasks.reconcile as reconcile_module
    original = db_module.AsyncSessionLocal
    agent_original = agent_module.AsyncSessionLocal
    patched = [
        (db_module, db_module.AsyncSessionLocal),
        (agent_module, agent_module.AsyncSessionLocal),
        (asset_store_module, asset_store_module.AsyncSessionLocal),
        (asset_gc_module, asset_gc_module.AsyncSessionLocal),
        (job_runner_module, job_runner_module.AsyncSessionLocal),
        (reconcile_module, reconcile_module.AsyncSessionLocal),
    ]
    for mod, _orig in patched:
        mod.AsyncSessionLocal = TestSessionLocal
    app.dependency_overrides[get_db] = _override_get_db
    yield TestSessionLocal
    app.dependency_overrides.clear()
    for mod, orig in patched:
        mod.AsyncSessionLocal = orig
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client(db_session):
    """异步 HTTP 测试客户端（不触发 lifespan，避免真实外部连接）"""
    rate_limiter.reset()  # 每个用例独立限流窗口，避免相互干扰
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    rate_limiter.reset()


@pytest_asyncio.fixture
async def registered_user(client):
    """注册一个测试用户并返回 (token, username)"""
    resp = await client.post("/api/auth/register",
                             json={"username": "alice", "password": "secret123"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"], "alice"


@pytest_asyncio.fixture
async def auth_headers(registered_user):
    token, _ = registered_user
    return {"Authorization": f"Bearer {token}"}
