"""MCP 工具签名契约测试：调用方传参形态必须能通过 FastMCP 的 pydantic 校验。

背景（2026-09-04 线上 bug）：skill 片段视频向 submit_video 传参考图**列表**，
而工具签名是 `reference_image_url: str`，FastMCP pydantic 校验直接拒收
（报 "Input should be a valid str"），请求根本没发出去。
教训：MCP 工具签名就是 API 契约，调用方改参数形态时必须同步放宽工具签名。
本测试直接校验注册后的 Tool（schema + run 执行链），与运行时行为一致。
兼容 mcp SDK 新旧版本（Tool.args_model / Tool.parameters）。
"""
import asyncio

import pytest

pytest.importorskip("mcp")
pytest.importorskip("volcengine")

import mcp_server.video_mcp as video_mcp  # noqa: E402


def _get_tool(name: str):
    return video_mcp.mcp._tool_manager._tools[name]


class TestSubmitVideoContract:
    def test_reference_image_accepts_list_in_schema(self):
        """schema 层：reference_image_url 必须声明为 string|array|null"""
        t = _get_tool("submit_video")
        ref_schema = t.parameters["properties"]["reference_image_url"]
        types = set()
        for branch in ref_schema.get("anyOf", [ref_schema]):
            types.add(branch.get("type"))
        assert "string" in types, f"schema 缺少 string 分支: {ref_schema}"
        assert "array" in types, f"schema 缺少 array 分支（列表参考图会再次被拒）: {ref_schema}"

    def test_reference_image_accepts_list_at_runtime(self, monkeypatch):
        """执行链：Tool.run 的 pydantic 校验放行列表，并原样传到 video_tool"""
        captured = {}

        def fake_submit(prompt, ref, duration, profile):
            captured["ref"] = ref
            return "fake-task-id"

        monkeypatch.setattr(video_mcp.video_tool, "submit_video_task", fake_submit)
        t = _get_tool("submit_video")
        result = asyncio.run(t.run({
            "prompt": "p",
            "reference_image_url": ["http://x/scene.png", "http://x/char.png"],
            "duration": 6,
            "profile": None,
        }))
        assert result == "fake-task-id"
        assert isinstance(captured["ref"], list)
        assert captured["ref"] == ["http://x/scene.png", "http://x/char.png"]

    def test_reference_image_accepts_str_and_empty_default(self, monkeypatch):
        """向后兼容：单张字符串照常；缺省空串退化为文生视频（None）"""
        captured = {}

        def fake_submit(prompt, ref, duration, profile):
            captured["ref"] = ref
            return "fake-task-id"

        monkeypatch.setattr(video_mcp.video_tool, "submit_video_task", fake_submit)
        t = _get_tool("submit_video")
        asyncio.run(t.run({"prompt": "p", "reference_image_url": "http://x/one.png"}))
        assert captured["ref"] == "http://x/one.png"
        asyncio.run(t.run({"prompt": "p"}))
        assert captured["ref"] is None
