# -*- coding: utf-8 -*-
"""LLM MCP Server：暴露大模型调用工具（stdio）。

支持用户运行时通道 profile：profile 非空且 channel != env 时，用其中的
api_url / api_key / model / temperature 覆盖 .env 默认（OpenAI 兼容协议）。

URL 规则：.env 的 LLM_API_URL 与用户 profile 的 api_url 都经过 _normalize_chat_url
统一规范化，兼容「域名 / 带 /v1 / 已写完整端点」三种写法，保证严格按配置地址请求。
"""
import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from typing import Optional
import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from tools.logger_tool import get_logger
from mcp_server._mcp_io import wrap_large

load_dotenv()
logger = get_logger("drama.mcp.llm")

mcp = FastMCP("drama-llm")

LLM_API_URL = os.getenv("LLM_API_URL", "https://api.deepseek.com")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-v4-flash")
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "300"))


def _normalize_chat_url(base: str) -> str:
    """把任意形态的 base_url 规范化为 OpenAI 兼容的 .../chat/completions。

    兼容三种写法（.env 与用户 profile 统一走这里），与官方 OpenAI SDK 拼接一致：
      - https://api.deepseek.com                 -> https://api.deepseek.com/chat/completions
      - https://api.deepseek.com/v1              -> https://api.deepseek.com/v1/chat/completions
      - 已以 /chat/completions 结尾的完整端点      -> 原样
    DeepSeek 官方对 /chat/completions 与 /v1/chat/completions 均支持。
    """
    u = (base or "").strip().rstrip("/")
    if not u:
        u = "https://api.deepseek.com"
    if u.endswith("/chat/completions"):
        return u
    if u.endswith("/v1"):
        return u + "/chat/completions"
    return u + "/chat/completions"


def _resolve(profile):
    """合并 .env 默认与用户 profile，返回本次调用的的 (url, key, model, temperature)。"""
    # 兼容整包 {llm,image,video}（纵深防御，门面已拆段）：取出 llm 单段
    if isinstance(profile, dict) and isinstance(profile.get("llm"), dict):
        profile = profile["llm"]
    url, key, model, temp = _normalize_chat_url(LLM_API_URL), LLM_API_KEY, LLM_MODEL, None
    if profile and profile.get("channel") not in (None, "", "env"):
        base = str(profile.get("api_url") or "").strip()
        if base:
            url = _normalize_chat_url(base)
        key = profile.get("api_key") or key
        model = profile.get("model") or model
        temp = profile.get("temperature")
    logger.info("llm resolve | url=%s | model=%s | custom_profile=%s",
                url, model, bool(profile) and profile.get("channel") not in (None, "", "env"))
    return url, key, model, temp


@mcp.tool()
async def call_llm(messages: list, temperature: float = 0.7, profile: Optional[dict] = None) -> str:
    """
    调用大模型，messages 为 OpenAI 格式 [{"role":"user","content":"..."}]，返回文本
    :param messages: 对话消息列表
    :param temperature: 采样温度
    :param profile: 用户运行时 LLM 通道配置（可选，覆盖 .env）
    """
    url, key, model, p_temp = _resolve(profile)
    if p_temp is not None:
        temperature = float(p_temp)
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code in (401, 403):
            raise RuntimeError(
                f"HTTP {resp.status_code} 鉴权失败：当前 Key 在 {url} 不被认可"
                f"（请核对 LLM_API_KEY / LLM_API_URL / LLM_MODEL 是否为同一平台）。上游返回：{resp.text[:150]}")
        resp.raise_for_status()
        data = resp.json()
    content = data["choices"][0]["message"]["content"]
    # 大文本（剧本结构化 JSON 常达数十 KB）走文件旁路，规避 MCP stdio 大消息死锁
    return wrap_large(content)


if __name__ == "__main__":
    mcp.run(transport="stdio")
