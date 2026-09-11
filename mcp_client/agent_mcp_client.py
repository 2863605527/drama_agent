# -*- coding: utf-8 -*-
"""
Agent 侧 MCP 客户端：用 stdio 拉起 4 个 MCP Server 子进程（LLM / 图片 / 视频 / TTS），
每个通道一条常驻连接（_PersistentChannel），多次调用复用、断线自动重建并重试。

关键实现：每个 _PersistentChannel 用一个专属 owner task 串行驱动「连接 / 调用 / 重建 /
关闭」，保证 anyio stdio_client / ClientSession 的进入与退出始终在同一 task（否则会抛
"exit cancel scope in a different task"），同时天然实现同一通道调用串行化、并发安全。

用户运行时通道配置 profile（dict）不放在方法签名上层层透传，而是通过 ContextVar
按「任务执行上下文」绑定（并发任务互不串扰；为空时 MCP Server 100% 回退 .env 默认）。
本地 ffmpeg 后处理（下载 / 混音 / 裁剪 / 合成）以工具形式注册在 video MCP Server，
统一走 self._video 通道调用。
"""
import os
import sys
import json
import contextvars
import asyncio
from typing import Union
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tools.logger_tool import get_logger
from mcp_server._mcp_io import unwrap_large

logger = get_logger("drama.mcp.client")

ROOT = Path(__file__).resolve().parent.parent

# 图片通道连接池大小：与 skill 侧 IMAGE_MAX_CONCURRENCY 保持一致（默认 3）。
# 单条 _PersistentChannel 是「单连接+单 owner 串行队列」，多个并发 gen_image 请求即使
# 主进程侧 Semaphore 放行，也仍会排队串行执行；池化后每个并发请求落到独立子进程，
# 图片生成真正并行（子进程内已是 asyncio.to_thread，瓶颈只在 client 侧串行）。
_IMAGE_POOL_SIZE = max(1, int(os.getenv("IMAGE_MAX_CONCURRENCY", "3")))

# 当前任务上下文绑定的通道配置（asyncio Task / ContextVar 隔离，默认 None=走 .env）
_current_profile: contextvars.ContextVar = contextvars.ContextVar(
    "drama_channel_profile", default=None)


class _PersistentChannel:
    """一条常驻 stdio MCP 通道。所有连接生命周期都在专属 owner task 内执行。"""

    def __init__(self, script_filename: str, name: str):
        self.name = name
        self.script_path = ROOT / "mcp_server" / script_filename
        self._cmds: asyncio.Queue = asyncio.Queue()
        self._owner: asyncio.Task | None = None

    def _server_params(self) -> StdioServerParameters:
        """构造 stdio 启动参数。

        MCP SDK 默认只用 get_default_environment()（PATH 等白名单系统变量）启动
        子进程，会导致 .env 注入的 LLM_API_KEY / LLM_API_URL / LLM_MODEL / VOLC_*
        等业务密钥在子进程全部丢失（表现为 LLM 401、图像/视频鉴权失败）。
        因此必须显式把父进程完整环境传给子进程。
        """
        return StdioServerParameters(
            command=sys.executable,
            args=[str(self.script_path)],
            env=os.environ.copy(),
        )

    # ---------- owner task：唯一持有连接的地方 ----------
    def _ensure_owner(self) -> asyncio.Task:
        if self._owner is None or self._owner.done():
            self._owner = asyncio.create_task(self._run())
        return self._owner

    async def _run(self):
        stdio_cm = session_cm = session = None
        while True:
            kind, args, fut = await self._cmds.get()
            try:
                if kind == "stop":
                    await self._close_conn(session_cm, stdio_cm)
                    if not fut.done():
                        fut.set_result(None)
                    break

                if kind == "list_tools":
                    if session is None:
                        params = self._server_params()
                        stdio_cm = stdio_client(params)
                        read, write = await stdio_cm.__aenter__()
                        session_cm = ClientSession(read, write)
                        session = await session_cm.__aenter__()
                        await asyncio.wait_for(session.initialize(), timeout=30)
                    tools = await session.list_tools()
                    if not fut.done():
                        fut.set_result(sorted(t.name for t in tools.tools))
                    continue

                retries = args.get("retries", 1)
                timeout = args.get("timeout", 900)
                last_err = None
                text = ""
                for attempt in range(retries + 1):
                    try:
                        if session is None:
                            params = self._server_params()
                            stdio_cm = stdio_client(params)
                            read, write = await stdio_cm.__aenter__()
                            session_cm = ClientSession(read, write)
                            session = await session_cm.__aenter__()
                            await asyncio.wait_for(session.initialize(), timeout=30)
                            try:
                                tools = await session.list_tools()
                                logger.info("MCP %s connected | tools=%s", self.name,
                                            [t.name for t in tools.tools])
                            except Exception:
                                pass
                        result = await asyncio.wait_for(
                            session.call_tool(args["tool"], args["arguments"]),
                            timeout=timeout)
                        text = result.content[0].text if result.content else ""
                        # 大文本信封还原（MCP stdio 大消息走文件旁路）
                        text = unwrap_large(text)
                        # MCP 工具内部抛异常时框架返回 isError=True、正文是 "Error executing tool …"，
                        # 必须当作失败进入重试/抛错，绝不能把错误文本当成正常结果（如图片 URL）返回
                        if getattr(result, "isError", False):
                            raise RuntimeError(f"工具 {args['tool']} 执行报错：{str(text)[:200]}")
                        last_err = None
                        break
                    except Exception as e:  # 断管 / 崩溃 / 超时：丢弃旧连接，下轮重建
                        last_err = e
                        logger.warning("MCP %s.%s failed (attempt %s): %s",
                                       self.name, args["tool"], attempt + 1, str(e)[:150])
                        await self._close_conn(session_cm, stdio_cm)
                        session_cm = stdio_cm = session = None
                        if attempt < retries:
                            await asyncio.sleep(1 + attempt)
                if not fut.done():
                    if last_err is not None:
                        fut.set_exception(
                            RuntimeError(f"MCP 调用 {self.name}.{args['tool']} 失败：{last_err}"))
                    else:
                        fut.set_result(text)
            except Exception as e:
                if not fut.done():
                    fut.set_exception(e)

    @staticmethod
    async def _close_conn(session_cm, stdio_cm):
        if session_cm is not None:
            try:
                await session_cm.__aexit__(None, None, None)
            except Exception:
                pass
        if stdio_cm is not None:
            try:
                await stdio_cm.__aexit__(None, None, None)
            except Exception:
                pass

    async def _submit(self, kind: str, args: dict):
        self._ensure_owner()  # 确保持有连接的 owner 协程在运行（副作用，返回值不用）
        fut = asyncio.get_event_loop().create_future()
        await self._cmds.put((kind, args, fut))
        return await asyncio.wait_for(fut, timeout=args.get("wait_timeout", 3600))

    async def call(self, tool: str, arguments: dict, timeout: float = 900, retries: int = 1) -> str:
        return await self._submit("call", {
            "tool": tool, "arguments": arguments, "timeout": timeout, "retries": retries,
        })

    async def list_tools(self):
        return await self._submit("list_tools", {})

    async def aclose(self):
        if self._owner is None or self._owner.done():
            return
        try:
            await self._submit("stop", {})
        except Exception:
            pass
        self._owner.cancel()
        try:
            await self._owner
        except Exception:
            pass
        self._owner = None


class _ChannelPool:
    """同一 MCP 脚本的 N 条常驻通道池（用于图片并发）。

    接口与 _PersistentChannel 对齐（call / list_tools / aclose），调用方无感知。
    - 并发上限 = 池大小（与 IMAGE_MAX_CONCURRENCY 一致），超出自动排队；
    - 每个请求从「当前队列最短」的通道分发，避免集中排到同一条通道；
    - 每通道内部仍是串行队列，整体并发度 = 池大小 × 每通道单连接。
    """

    def __init__(self, script_filename: str, name: str, size: int):
        self.name = name
        self._channels = [_PersistentChannel(script_filename, f"{name}#{i}") for i in range(size)]
        self._sem = asyncio.Semaphore(size)

    def _pick(self) -> _PersistentChannel:
        """选当前待处理请求最少的通道（负载均衡，减少同通道排队）。"""
        return min(self._channels, key=lambda ch: ch._cmds.qsize())

    async def call(self, tool: str, arguments: dict, timeout: float = 900, retries: int = 1) -> str:
        async with self._sem:
            return await self._pick().call(tool, arguments, timeout=timeout, retries=retries)

    async def list_tools(self):
        return await self._channels[0].list_tools()

    async def aclose(self):
        for ch in self._channels:
            try:
                await ch.aclose()
            except Exception:
                pass


class DramaMcpClient:
    """对 Skill 暴露的模型能力门面：方法签名保持稳定（测试 / Skill 直接 mock 这一层）。"""

    def __init__(self):
        self._llm = _PersistentChannel("llm_mcp.py", "llm")
        # 图片是多图并发生成的高频通道，用连接池打破单通道串行瓶颈（真正并行出图）
        self._image = _ChannelPool("image_mcp.py", "image", _IMAGE_POOL_SIZE)
        self._video = _PersistentChannel("video_mcp.py", "video")
        self._tts = _PersistentChannel("tts_mcp.py", "tts")

    # ---------- 任务级通道配置绑定（ContextVar，并发安全） ----------
    def bind_profile(self, profile):
        """在一个任务的执行流程开始时绑定其通道配置快照；传 None / {} 表示回退 .env。"""
        _current_profile.set(profile or None)

    @staticmethod
    def _seg(kind: str):
        """取当前任务 kind(llm/image/video) 的【单段】通道配置。
        ContextVar 里可能是整包 {llm,image,video}（任务执行时 bind），也可能已是单段
        （连通测试时直接 bind 某一段）；各 MCP Server 只认单段 profile.channel，必须在此拆段，
        否则整包没有顶层 channel 会被执行层误判为空、回退到 .env 默认通道（自定义通道失效的根因）。"""
        p = _current_profile.get()
        if not p or not isinstance(p, dict):
            return None
        seg = p.get(kind)
        if isinstance(seg, dict):           # 整包：取对应段
            return seg or None
        return p if p.get("channel") else None  # 已是单段

    @classmethod
    def _pa(cls, kind: str, arguments: dict) -> dict:
        """把 kind 单段配置注入本次工具调用 arguments（无配置则不带 profile，由 MCP 走 .env）。"""
        seg = cls._seg(kind)
        if seg:
            arguments["profile"] = seg
        return arguments

    # ---------------- LLM ----------------
    async def call_llm(self, messages: list, temperature: float = 0.7) -> str:
        return await self._llm.call("call_llm", self._pa("llm", {
            "messages": messages, "temperature": temperature,
        }))

    @staticmethod
    def _require_img_url(raw, what: str = "图片") -> str:
        """图片类工具必须返回合法图片地址，拦截把错误/说明文本误当 URL 回填（会导致前端裂图）。"""
        if isinstance(raw, str):
            s = raw.strip()
            if s.startswith(("http://", "https://", "data:image/", "/assets/")):
                return s
        raise RuntimeError(f"{what}生成未返回有效图片地址：{str(raw)[:160]}")

    # ---------------- 图片 ----------------
    async def gen_image(self, prompt: str, reference_image_url: str = "") -> str:
        # reference_image_url 非空时走图生图（以参考图为底图），用于黑夜场景图参考白天图
        raw = await self._image.call("gen_image",
                                     self._pa("image", {"prompt": prompt, "ref_image_url": reference_image_url or ""}))
        return self._require_img_url(raw, "图片")

    async def gen_character_image(self, char_desc: str) -> str:
        return self._require_img_url(
            await self._image.call("gen_character_image", self._pa("image", {"char_desc": char_desc})), "角色立绘")

    async def gen_scene_image(self, scene_desc: str) -> str:
        return self._require_img_url(
            await self._image.call("gen_scene_image", self._pa("image", {"scene_desc": scene_desc})), "场景图")

    # ---------------- 视频：提交 / 轮询 ----------------
    async def submit_video(self, prompt: str,
                           reference_image_url: Union[str, list, None] = "",
                           duration: int = 5, ratio: str = "9:16") -> str:
        """提交视频生成任务，返回供应商 task_id（失败抛异常）。reference_image_url 支持单张 URL 或列表。ratio 合并进【视频段】下发。"""
        profile = self._seg("video")
        if ratio:
            profile = {**(profile or {}), "ratio": ratio}
        return await self._video.call("submit_video", {
            "prompt": prompt,
            "reference_image_url": reference_image_url or "",
            "duration": duration,
            "profile": profile or None,
        })

    async def poll_video(self, task_id: str, timeout: int = 300) -> dict:
        """轮询直到出片，统一返回 {ok, video_url, msg}（坏 JSON / 异常都兜底为 ok=False）。"""
        try:
            text = await self._video.call("poll_video", self._pa("video", {
                "task_id": task_id, "timeout_seconds": timeout,
            }), timeout=timeout + 60)
            try:
                result = json.loads(text)
                if not isinstance(result, dict):
                    raise ValueError("not dict")
            except (TypeError, ValueError):
                if isinstance(text, str) and text.startswith(("http://", "https://", "/")):
                    result = {"ok": True, "video_url": text, "msg": ""}
                else:
                    return {"ok": False, "video_url": None,
                            "msg": f"无法解析的轮询结果：{str(text)[:80]}"}
            result.setdefault("ok", False)
            result.setdefault("video_url", None)
            result.setdefault("msg", "")
            return result
        except Exception as e:
            return {"ok": False, "video_url": None, "msg": str(e)}

    # ---------------- 本地后处理（注册在 video MCP Server，走 self._video）----------------
    async def download_video(self, url: str, save_path: str) -> str:
        return await self._video.call("download_video", {
            "remote_url": url, "local_path": save_path,
        }, timeout=300)

    async def tts_synthesize(self, lines: str, out_path: str, voice: str = None, rate: str = None) -> str:
        """TTS 配音；无台词 / 失败返回空串，不阻断主流程。"""
        try:
            return await self._tts.call("synthesize", {
                "lines": lines or "", "out_path": out_path, "voice": voice, "rate": rate,
            })
        except Exception as e:
            logger.warning("tts_synthesize failed: %s", str(e)[:150])
            return ""

    async def mix_segment_audio(self, video_path: str, audio_items, duration, trim=None) -> str:
        # (path, ms) 元组序列化为 JSON 友好的 list[list]，毫秒转 int
        items = [[p, int(ms)] for p, ms in (audio_items or [])]
        return await self._video.call("mix_segment_audio", {
            "video_path": video_path, "audio_items": items,
            "duration": duration, "trim": trim,
        }, timeout=300)

    async def finalize_video(self, video_path: str, duration, audio_path: str = None, trim=None) -> str:
        return await self._video.call("finalize_video", {
            "video_path": video_path, "duration": duration,
            "audio_path": audio_path, "trim": trim,
        }, timeout=300)

    async def compose_videos(self, video_paths: list, output_path: str) -> str:
        return await self._video.call("compose_videos", {
            "video_paths": list(video_paths), "output_path": output_path,
        }, timeout=1800)

    async def close(self):
        for ch in (self._llm, self._image, self._video, self._tts):
            try:
                await ch.aclose()
            except Exception as e:
                logger.warning("close %s error: %s", ch.name, str(e)[:100])


# 全局单例：整个 Agent 生命周期复用同一批持久连接
mcp_client = DramaMcpClient()
