"""MCP Client 通道测试：不拉起真实 stdio 子进程、不联网、不烧 Key。

用内存 Fake 替换 stdio_client / ClientSession，验证：
- 持久 worker 复用（多次调用只建一次连接）
- 调用失败后自动重建并重试
- poll_video 的 JSON 解析与坏 JSON 兜底
- mix_segment_audio 的 (path, ms) 元组→JSON 数组序列化
"""
import json
import contextlib
import pytest

import mcp_client.agent_mcp_client as mc


# ---------- 内存 Fake MCP 传输层 ----------
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
    initialize_count = 0
    fail_next = 0

    def __init__(self, read, write):
        self.tool_calls = []
        FakeSession.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def initialize(self):
        FakeSession.initialize_count += 1

    async def call_tool(self, name, args):
        self.tool_calls.append((name, args))
        if FakeSession.fail_next > 0:
            FakeSession.fail_next -= 1
            raise RuntimeError("simulated broken pipe")
        return _Result(f"echo:{name}")

    async def list_tools(self):
        return _Tools(["gen_image"])


@contextlib.asynccontextmanager
async def _fake_stdio(params):
    yield object(), object()


@pytest.fixture
def fake_transport(monkeypatch):
    FakeSession.instances = []
    FakeSession.initialize_count = 0
    FakeSession.fail_next = 0
    monkeypatch.setattr(mc, "stdio_client", lambda params: _fake_stdio(params))
    monkeypatch.setattr(mc, "ClientSession", FakeSession)
    return FakeSession


@pytest.mark.asyncio
async def test_persistent_session_reused(fake_transport):
    ch = mc._PersistentChannel("x_mcp.py", "t")
    r1 = await ch.call("tool_a", {"k": 1}, timeout=10, retries=0)
    r2 = await ch.call("tool_a", {"k": 2}, timeout=10, retries=0)
    assert r1 == "echo:tool_a" and r2 == "echo:tool_a"
    # 两次调用复用同一常驻 worker / session，只 initialize 一次
    assert len(FakeSession.instances) == 1
    assert FakeSession.initialize_count == 1
    assert FakeSession.instances[0].tool_calls[1][1] == {"k": 2}
    await ch.aclose()


@pytest.mark.asyncio
async def test_rebuild_and_retry_on_failure(fake_transport):
    FakeSession.fail_next = 1  # 第一次调用在旧 session 失败
    ch = mc._PersistentChannel("x_mcp.py", "t")
    out = await ch.call("tool_a", {}, timeout=10, retries=1)
    assert out == "echo:tool_a"
    # 失败后重建：产生两个 session 实例
    assert len(FakeSession.instances) == 2
    await ch.aclose()


@pytest.mark.asyncio
async def test_poll_video_json(monkeypatch):
    client = mc.DramaMcpClient()

    async def fake_call(tool, args, timeout):
        return json.dumps({"ok": True, "video_url": "http://x/v.mp4"}, ensure_ascii=False)
    monkeypatch.setattr(client._video, "call", fake_call)
    res = await client.poll_video("tid")
    assert res["ok"] is True and res["video_url"].endswith("v.mp4")

    # 坏 JSON 兜底为 ok=False，不抛异常
    async def bad_json(tool, args, timeout):
        return "not-a-json"
    monkeypatch.setattr(client._video, "call", bad_json)
    res2 = await client.poll_video("tid")
    assert res2["ok"] is False and "msg" in res2


@pytest.mark.asyncio
async def test_mix_segment_audio_serializes_tuples(monkeypatch):
    client = mc.DramaMcpClient()
    captured = {}

    async def fake_call(tool, arguments, timeout):
        captured.update(arguments)
        return arguments["video_path"]
    monkeypatch.setattr(client._video, "call", fake_call)

    out = await client.mix_segment_audio(
        "seg.mp4", [("a.mp3", 0), ("b.mp3", 4000)], 8)
    assert out == "seg.mp4"
    # 元组列表被序列化为 JSON 友好的 list[list]，毫秒为 int
    assert captured["audio_items"] == [["a.mp3", 0], ["b.mp3", 4000]]
    assert captured["duration"] == 8


@pytest.mark.asyncio
async def test_whole_profile_split_to_segment(monkeypatch):
    """回归：任务执行时 bind 的是整包 {llm,image,video}，门面必须拆成单段下发，
    否则 MCP 执行层读不到顶层 channel 会回退 .env（自定义通道整体失效的根因）。"""
    client = mc.DramaMcpClient()
    whole = {
        "llm": {"channel": "openai", "model": "gpt"},
        "image": {"channel": "generic_http", "model": "Kolors", "token": "sk-x"},
        "video": {"channel": "generic_http", "model": "Wan", "token": "sk-x"},
    }
    client.bind_profile(whole)
    cap = {}

    async def fake_img_call(tool, arguments, timeout=900, retries=1):
        cap[tool] = arguments
        return "http://x/a.png"
    monkeypatch.setattr(client._image, "call", fake_img_call)
    await client.gen_image("黑夜", "http://day.png")
    # 下发给图片 MCP 的必须是 image 单段，且带参考图
    assert cap["gen_image"]["profile"] == whole["image"]
    assert cap["gen_image"]["ref_image_url"] == "http://day.png"

    async def fake_vid_call(tool, arguments, timeout=900, retries=1):
        cap[tool] = arguments
        return "job-1"
    monkeypatch.setattr(client._video, "call", fake_vid_call)
    await client.submit_video("镜头", "http://x/a.png", duration=5, ratio="16:9")
    # 视频段单独下发，且 ratio 合并进视频段
    assert cap["submit_video"]["profile"]["channel"] == "generic_http"
    assert cap["submit_video"]["profile"]["model"] == "Wan"
    assert cap["submit_video"]["profile"]["ratio"] == "16:9"


def test_segment_helper_accepts_single_segment():
    """连通测试时 bind 的就是单段（无 image/video 子键），helper 应原样返回。"""
    client = mc.DramaMcpClient()
    client.bind_profile({"channel": "generic_http", "base_url": "https://x", "token": "t"})
    seg = mc.DramaMcpClient._seg("image")
    assert seg["channel"] == "generic_http" and seg["base_url"] == "https://x"
    client.bind_profile(None)
    assert mc.DramaMcpClient._seg("image") is None
