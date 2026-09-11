"""P1-3：图片通道连接池 _ChannelPool —— 接口兼容 + 并发分发到不同通道。"""
import asyncio
import contextlib
import pytest

import mcp_client.agent_mcp_client as mc
from mcp_client.agent_mcp_client import _ChannelPool


class _Text:
    def __init__(self, text):
        self.text = text


class _Result:
    def __init__(self, text):
        self.content = [_Text(text)]


class _Tool:
    def __init__(self, name):
        self.name = name


class _Tools:
    def __init__(self, names):
        self.tools = [_Tool(n) for n in names]


class FakeSession:
    instances = []

    def __init__(self, read, write):
        FakeSession.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def initialize(self):
        pass

    async def call_tool(self, name, args):
        return _Result(f"echo:{name}")

    async def list_tools(self):
        return _Tools(["gen_image"])


@contextlib.asynccontextmanager
async def _fake_stdio(params):
    yield object(), object()


@pytest.fixture
def fake_transport(monkeypatch):
    FakeSession.instances = []
    monkeypatch.setattr(mc, "stdio_client", lambda params: _fake_stdio(params))
    monkeypatch.setattr(mc, "ClientSession", FakeSession)
    return FakeSession


@pytest.mark.asyncio
async def test_pool_interface_matches_single_channel(fake_transport):
    """池对外暴露 call/list_tools/aclose，与 _PersistentChannel 同构（调用方无感知）。"""
    pool = _ChannelPool("x_mcp.py", "image", size=3)
    out = await pool.call("gen_image", {"prompt": "x"}, timeout=10, retries=0)
    assert out == "echo:gen_image"
    tools = await pool.list_tools()
    assert "gen_image" in tools
    await pool.aclose()
    # 池为惰性建连：单次调用只建一条连接；并发时才各自建（见并发用例）
    assert len(FakeSession.instances) == 1


@pytest.mark.asyncio
async def test_pool_concurrent_calls_spread_across_channels(fake_transport):
    """3 个并发请求应落在 3 条不同通道（各建一个 session），而不是挤在一条上串行。"""
    pool = _ChannelPool("x_mcp.py", "image", size=3)

    async def one(_):
        return await pool.call("gen_image", {"prompt": "x"}, timeout=10, retries=0)

    await asyncio.gather(*(one(i) for i in range(3)))
    await pool.aclose()
    assert len(FakeSession.instances) == 3


@pytest.mark.asyncio
async def test_pool_serializes_overflow(fake_transport):
    """并发超过池大小时超出的请求排队，不会报错；整体仍可全部完成。"""
    pool = _ChannelPool("x_mcp.py", "image", size=2)

    async def one(_):
        return await pool.call("gen_image", {"prompt": "x"}, timeout=10, retries=0)

    results = await asyncio.gather(*(one(i) for i in range(5)))
    assert all(r == "echo:gen_image" for r in results)
    await pool.aclose()


def test_pool_size_respects_env(monkeypatch):
    """池大小读取 IMAGE_MAX_CONCURRENCY（默认 3，最小 1），与 skill 侧并发上限一致。"""
    monkeypatch.delenv("IMAGE_MAX_CONCURRENCY", raising=False)
    import importlib
    mc2 = importlib.reload(mc)
    assert mc2._IMAGE_POOL_SIZE == 3
    monkeypatch.setenv("IMAGE_MAX_CONCURRENCY", "5")
    mc3 = importlib.reload(mc)
    assert mc3._IMAGE_POOL_SIZE == 5
    monkeypatch.setenv("IMAGE_MAX_CONCURRENCY", "0")
    mc4 = importlib.reload(mc)
    assert mc4._IMAGE_POOL_SIZE == 1
