# -*- coding: utf-8 -*-
"""图片生成 MCP Server（stdio）。所有工具支持可选 profile（用户运行时通道配置）。"""
import sys
import asyncio
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from typing import Optional
from mcp.server.fastmcp import FastMCP
from tools.image_tool import generate_character_image

mcp = FastMCP("drama-image")


@mcp.tool()
async def gen_image(prompt: str, profile: Optional[dict] = None, ref_image_url: str = "") -> str:
    """通用生图：输入 prompt，返回图片可访问 url（角色/场景共用）。
    ref_image_url 非空时走图生图（以参考图为底图按 prompt 编辑），用于黑夜场景图参考白天图。"""
    return await asyncio.to_thread(generate_character_image, prompt, 5, profile, ref_image_url)


@mcp.tool()
async def gen_character_image(char_desc: str, profile: Optional[dict] = None) -> str:
    """生成角色立绘，输入角色中文描述，返回图片url（竖版）"""
    return await asyncio.to_thread(generate_character_image, char_desc, 5, profile)


@mcp.tool()
async def gen_scene_image(scene_desc: str, profile: Optional[dict] = None) -> str:
    """生成场景背景图，输入场景中文描述，返回图片url（横版）"""
    return await asyncio.to_thread(generate_character_image, scene_desc, 5, profile)


if __name__ == "__main__":
    mcp.run(transport="stdio")
