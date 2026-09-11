# -*- coding: utf-8 -*-
"""视频 MCP Server（stdio）：视频生成（提交/轮询）+ 本地 ffmpeg 后处理工具。

所有「模型调用」工具支持可选 profile（用户运行时通道配置，由 mcp_client 经 ContextVar 注入）；
本地后处理与通道无关，不需要 profile。
"""
import sys
import json
import asyncio
from pathlib import Path
from typing import Optional, Union, List
sys.path.append(str(Path(__file__).parent.parent))

from mcp.server.fastmcp import FastMCP
from tools import video_tool

mcp = FastMCP("drama-video")


@mcp.tool()
async def submit_video(prompt: str,
                       reference_image_url: Optional[Union[str, List[str]]] = "",
                       duration: int = 5,
                       profile: Optional[dict] = None) -> str:
    """提交视频生成任务，返回供应商任务 id（异步，需再用 poll_video 轮询）。
    reference_image_url 支持单张 URL 字符串或多张参考图列表（场景图在前、角色立绘随后）。
    宽高比由 profile.ratio 携带。"""
    ref = reference_image_url or None
    return await asyncio.to_thread(
        video_tool.submit_video_task, prompt, ref, duration, profile)


@mcp.tool()
async def poll_video(task_id: str, timeout_seconds: int = 300,
                     profile: Optional[dict] = None) -> str:
    """轮询视频任务直到完成，返回 JSON：{ok: bool, video_url: str, msg: str}。"""
    result = await asyncio.to_thread(video_tool.query_video_result, task_id, timeout_seconds, profile)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
async def download_video(remote_url: str, local_path: str) -> str:
    """下载远程视频到本地路径，返回本地路径。"""
    return await asyncio.to_thread(video_tool.download_video, remote_url, local_path)


@mcp.tool()
async def mix_segment_audio(video_path: str, audio_items: list, duration: float,
                            trim: Optional[bool] = None) -> str:
    """把多条 TTS 配音按起始毫秒混入片段视频，返回输出路径。audio_items=[[mp3,start_ms],...]。"""
    return await asyncio.to_thread(
        video_tool.mix_segment_audio, video_path, [tuple(x) for x in (audio_items or [])],
        duration, trim)


@mcp.tool()
async def finalize_video(video_path: str, duration: float, audio_path: Optional[str] = None,
                         trim: Optional[bool] = None) -> str:
    """片段收尾：补静音/配音轨、按需裁剪到目标时长，返回输出路径。"""
    return await asyncio.to_thread(
        video_tool.finalize_shot_video, video_path, duration, audio_path, trim)


@mcp.tool()
async def compose_videos(video_paths: list, output_path: str) -> str:
    """把多个片段视频按顺序拼接为完整短剧，返回输出路径。"""
    return await asyncio.to_thread(video_tool.compose_videos, list(video_paths), output_path)


if __name__ == "__main__":
    mcp.run(transport="stdio")
