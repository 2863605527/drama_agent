"""TTS 配音 MCP Server：把 edge-tts 语音合成能力以 MCP 工具暴露（stdio）。

注意 tools.tts_tool.synthesize_speech 内部使用 asyncio.run，而 FastMCP 工具本身运行在
事件循环中，因此必须用 to_thread 丢到独立线程（该线程内新建事件循环），否则会抛
"asyncio.run() cannot be called from a running event loop"。
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import asyncio
import logging
from typing import Optional
logging.disable(logging.CRITICAL)
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from tools.tts_tool import synthesize_speech, ENABLE_TTS

load_dotenv()
mcp = FastMCP("tts_server")


@mcp.tool()
async def synthesize(lines: str, out_path: str,
                     voice: Optional[str] = None, rate: Optional[str] = None) -> str:
    """把台词/旁白合成为 mp3，返回音频路径；无台词、未启用或失败时返回空字符串（不阻断主流程）。"""
    if not ENABLE_TTS or not (lines or "").strip():
        return ""
    return await asyncio.to_thread(synthesize_speech, lines, out_path, voice, rate)


@mcp.tool()
async def tts_enabled() -> bool:
    """返回当前是否启用 TTS（读 .env 的 ENABLE_TTS 与 edge-tts 是否可用）。"""
    return bool(ENABLE_TTS)


if __name__ == "__main__":
    mcp.run(transport="stdio")
