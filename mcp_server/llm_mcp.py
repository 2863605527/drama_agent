import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import os
from dotenv import load_dotenv
import httpx
from mcp.server.fastmcp import FastMCP

load_dotenv()
mcp = FastMCP("llm_server")

LLM_API_URL = os.getenv("LLM_API_URL")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")


@mcp.tool()
async def call_llm(messages: list, temperature: float = 0.7) -> str:
    """
    调用大模型对话
    :param messages: 消息列表 [{"role":"user","content":"xxx"}]
    :param temperature: 温度
    :return: llm返回文本
    """
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content‑Type": "application/json"
    }
    payload = {
        "model": "deepseek‑v4‑flash",
        "messages": messages,
        "temperature": temperature
    }

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            LLM_API_URL,
            json=payload,
            headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


if __name__ == "__main__":
    mcp.run(transport="stdio")
