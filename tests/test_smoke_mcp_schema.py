# -*- coding: utf-8 -*-
"""验证 FastMCP 模型工具的 profile 参数 schema 允许 object/null（避免运行时参数校验报错）。"""
import pytest

MODEL_TOOLS = {
    "llm_mcp": ["call_llm"],
    "image_mcp": ["gen_image", "gen_character_image", "gen_scene_image"],
    "video_mcp": ["submit_video", "poll_video"],
}


@pytest.mark.asyncio
@pytest.mark.parametrize("module_name,tool_names", list(MODEL_TOOLS.items()))
async def test_profile_param_nullable(module_name, tool_names):
    import importlib
    mod = importlib.import_module(f"mcp_server.{module_name}")
    tools = await mod.mcp.list_tools()
    tool_list = tools if isinstance(tools, list) else tools.tools
    by_name = {t.name: t for t in tool_list}
    for name in tool_names:
        prop = by_name[name].inputSchema.get("properties", {}).get("profile")
        assert prop is not None, f"{module_name}.{name} 缺少 profile 参数"
        # anyOf 中应同时允许 object 与 null
        types = {list(x.values())[0] if "type" in x else x.get("anyOf") for x in prop.get("anyOf", [])}
        assert "null" in str(prop.get("anyOf")), f"{module_name}.{name} profile 不允许 null"
