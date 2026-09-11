# -*- coding: utf-8 -*-
"""MCP stdio 大响应旁路传输。

背景：MCP Python SDK（stdio transport）在「单条 JSON-RPC 响应消息」较大时
（实测阈值约数 KB ~ 数十 KB，随管道缓冲与调度波动），子进程向 stdout 写响应、
父进程读取之间会死锁——上游 HTTP 已 200、body 已收完，但 session.call_tool
永远等不到回包，直到超时。剧本结构化解析（step1 第二次 LLM 调用）的 JSON 文本
恰好经常超过该阈值，表现为「解析偶发卡死、多等几分钟后超时失败」。

彻底绕开：超过阈值的大文本不经过 stdio 直接回传，而是落盘到父子进程共享的
临时目录，stdio 只回一个很短的 JSON 信封 {__mcp_large_file__: 路径}，
父进程（agent_mcp_client）收到信封后读文件还原。小响应原样直传、零开销。

父子 MCP 进程运行在同一容器 / 同一台机器，共享本地文件系统，故可直接用路径交换。
"""
import os
import json
import uuid
import tempfile

# 单条 stdio 消息内联上限（字符数）。实测 4KB 稳定、32KB 必卡，这里取保守值。
INLINE_MAX = int(os.getenv("MCP_INLINE_MAX", "8000"))
MARK = "__mcp_large_file__"


def _payload_dir() -> str:
    d = os.path.join(tempfile.gettempdir(), "drama_mcp_payload")
    os.makedirs(d, exist_ok=True)
    return d


def wrap_large(text) -> str:
    """MCP server 工具返回前调用：小文本原样返回，大文本落盘并返回短信封。"""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    if len(text) <= INLINE_MAX:
        return text
    path = os.path.join(_payload_dir(), f"{uuid.uuid4().hex}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return json.dumps({MARK: path}, ensure_ascii=False)


def unwrap_large(text) -> str:
    """MCP client 收到工具结果后调用：若是大文本信封则读文件还原，否则原样返回。"""
    if not (isinstance(text, str) and text.startswith("{") and MARK in text):
        return text
    try:
        obj = json.loads(text)
    except (TypeError, ValueError):
        return text
    path = obj.get(MARK) if isinstance(obj, dict) else None
    if not path:
        return text
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return text
    # 读完即删，避免临时载荷长期堆积（删除失败不影响主流程）
    try:
        os.remove(path)
    except OSError:
        pass
    return content
