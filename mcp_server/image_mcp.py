# 第一行必须加路径
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import asyncio
from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import Tool, TextContent

from tools.image_tool import generate_character_image

load_dotenv()
app = Server("image-mcp-server")

# ----------------工具定义，不要用@app.tool()装饰器----------------
async def gen_char_image(char_desc: str):
    """生成角色图片工具"""
    url = generate_character_image(char_desc)
    return [TextContent(type="text", text=url)]


# 注册工具列表
@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="gen_char_image",
            description="根据人物描述生成角色图片，返回图片url",
            inputSchema={
                "type": "object",
                "properties": {
                    "char_desc": {"type": "string", "description": "角色人设描述"}
                },
                "required": ["char_desc"]
            }
        )
    ]

# 工具调用分发
@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "gen_char_image":
        return await gen_char_image(**arguments)
    raise ValueError(f"未知工具 {name}")


async def main():
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
