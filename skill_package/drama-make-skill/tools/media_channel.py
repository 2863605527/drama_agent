# -*- coding: utf-8 -*-
"""媒体通道抽象层：让「图片/视频生成」可以在多个供应商通道之间无缝切换，换供应商只改 .env、不改代码。

支持的通道类型（IMAGE_CHANNEL / VIDEO_CHANNEL 取值）：
  - volc_cv        火山即梦「视觉服务」通道（cv_process / cv_sync2async_*），当前默认通道
                    req_key 制：jimeng_t2v_v30 / jimeng_high_aes_general_v21_L 等
  - volc_ark       火山方舟通道（ark.cn-beijing.volces.com/api/v3）：
                    视频用 Seedance 2.0 系列（doubao-seedance-2-0-260128，原生音频+参考图）
                    图片用 Seedream 系列（doubao-seedream-5-0-260128 等）
                    需要独立的 ARK_API_KEY（volc-sk-xxx），与即梦 AK/SK 不通用
  - generic_http   通用 HTTP 通道：任意第三方供应商，提交/轮询 URL 与结果 JSON 路径全可配

通道选择原则：
  - 换「同通道内模型」只改 IMAGE_REQ_KEY / VIDEO_REQ_KEY（或 ARK_*_MODEL）
  - 换「供应商/通道」只改 IMAGE_CHANNEL / VIDEO_CHANNEL + 对应通道的凭据与模型参数
"""
import os
import json
import time
import requests
from dotenv import load_dotenv
from tools.logger_tool import get_logger

logger = get_logger("drama.channel")

load_dotenv()

# ===== 通道类型常量 =====
CH_VOLC_CV = "volc_cv"          # 火山即梦视觉服务通道（默认）
CH_VOLC_ARK = "volc_ark"        # 火山方舟通道（Seedance 2.0 / Seedream）
CH_GENERIC_HTTP = "generic_http"  # 通用 HTTP 通道

# ===== 当前生效通道（默认 volc_cv，向后兼容）=====
IMAGE_CHANNEL = os.getenv("IMAGE_CHANNEL", CH_VOLC_CV).strip().lower()
VIDEO_CHANNEL = os.getenv("VIDEO_CHANNEL", CH_VOLC_CV).strip().lower()
if IMAGE_CHANNEL not in (CH_VOLC_CV, CH_VOLC_ARK, CH_GENERIC_HTTP):
    logger.warning("unknown IMAGE_CHANNEL=%s, fallback to volc_cv", IMAGE_CHANNEL)
    IMAGE_CHANNEL = CH_VOLC_CV
if VIDEO_CHANNEL not in (CH_VOLC_CV, CH_VOLC_ARK, CH_GENERIC_HTTP):
    logger.warning("unknown VIDEO_CHANNEL=%s, fallback to volc_cv", VIDEO_CHANNEL)
    VIDEO_CHANNEL = CH_VOLC_CV

# ===== 火山即梦 CV 通道（volc_cv）=====
VOLC_ACCESS_KEY = os.getenv("VOLC_ACCESS_KEY")
VOLC_SECRET_KEY = os.getenv("VOLC_SECRET_KEY")
# cv 通道文生图/文生视频模型 req_key（jimeng_high_aes_general_v21_L / jimeng_t2v_v30 等）
IMAGE_REQ_KEY = os.getenv("IMAGE_REQ_KEY", "jimeng_high_aes_general_v21_L")

# ===== 火山方舟通道（volc_ark）=====
ARK_API_URL = os.getenv("ARK_API_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
ARK_API_KEY = os.getenv("ARK_API_KEY", "").strip()
# 方舟图片模型（Seedream 系列）
ARK_IMAGE_MODEL = os.getenv("ARK_IMAGE_MODEL", "doubao-seedream-5-0-260128")
# 方舟视频模型（Seedance 2.0 系列：标准版 doubao-seedance-2-0-260128 / 快速版 doubao-seedance-2-0-fast-260128）
ARK_VIDEO_MODEL = os.getenv("ARK_VIDEO_MODEL", "doubao-seedance-2-0-260128")
# 方舟视频分辨率：480p / 720p / 1080p / 4k
ARK_VIDEO_RESOLUTION = os.getenv("ARK_VIDEO_RESOLUTION", "720p")
# 方舟视频宽高比：16:9 / 4:3 / 1:1 / 3:4 / 9:16 / 21:9 / adaptive
ARK_VIDEO_RATIO = os.getenv("ARK_VIDEO_RATIO", "9:16")
# 是否让 Seedance 原生生成音频（true=视频自带声音，跳过 edge-tts 配音；false=静音视频，走 TTS）
ARK_VIDEO_AUDIO = os.getenv("ARK_VIDEO_AUDIO", "true").strip().lower() in ("1", "true", "yes", "on")
# Seedance 平台时长支持范围（秒）：[4, 15]；LLM 分配的秒数会 clamp 到此区间
ARK_VIDEO_DUR_MIN = int(os.getenv("ARK_VIDEO_DUR_MIN", "4"))
ARK_VIDEO_DUR_MAX = int(os.getenv("ARK_VIDEO_DUR_MAX", "15"))

# ===== 通用 HTTP 通道（generic_http）=====
# 图片：POST IMAGE_HTTP_URL，请求体 {"prompt","width","height"}，结果取 IMAGE_HTTP_URL_PATH 指向的字段
IMAGE_HTTP_URL = os.getenv("IMAGE_HTTP_URL", "").strip()
IMAGE_HTTP_TOKEN = os.getenv("IMAGE_HTTP_TOKEN", "").strip()
IMAGE_HTTP_URL_PATH = os.getenv("IMAGE_HTTP_URL_PATH", "data[0].url")
# 视频：POST VIDEO_HTTP_SUBMIT_URL 提交（请求体 {"prompt","image_url"(可选),"duration"}），
#       GET VIDEO_HTTP_POLL_URL 轮询（{task_id} 占位符替换为任务 id）
VIDEO_HTTP_SUBMIT_URL = os.getenv("VIDEO_HTTP_SUBMIT_URL", "").strip()
VIDEO_HTTP_POLL_URL = os.getenv("VIDEO_HTTP_POLL_URL", "").strip()
VIDEO_HTTP_TOKEN = os.getenv("VIDEO_HTTP_TOKEN", "").strip()
VIDEO_HTTP_TASK_ID_PATH = os.getenv("VIDEO_HTTP_TASK_ID_PATH", "data.task_id")
VIDEO_HTTP_STATUS_PATH = os.getenv("VIDEO_HTTP_STATUS_PATH", "data.status")
VIDEO_HTTP_SUCCESS_STATUS = os.getenv("VIDEO_HTTP_SUCCESS_STATUS", "succeeded").strip().lower()
VIDEO_HTTP_VIDEO_URL_PATH = os.getenv("VIDEO_HTTP_VIDEO_URL_PATH", "data.content.video_url")
VIDEO_HTTP_EXTRA_FIELDS = os.getenv("VIDEO_HTTP_EXTRA_FIELDS", "").strip()  # 附加字段 JSON，合并进提交体
_VIDEO_HTTP_EXTRA = {}
if VIDEO_HTTP_EXTRA_FIELDS:
    try:
        _VIDEO_HTTP_EXTRA = json.loads(VIDEO_HTTP_EXTRA_FIELDS)
    except Exception as e:
        logger.warning("VIDEO_HTTP_EXTRA_FIELDS is not valid JSON, ignored | %s", e)

logger.info("media channel | image=%s | video=%s | ark=%s | ark_video_model=%s | ark_audio=%s | ark_ratio=%s",
            IMAGE_CHANNEL, VIDEO_CHANNEL,
            "configured" if ARK_API_KEY else "NO_KEY", ARK_VIDEO_MODEL, ARK_VIDEO_AUDIO, ARK_VIDEO_RATIO)


# ---------------- 共享的即梦视觉服务单例（仅 volc_cv 通道需要） ----------------

_visual_service = None


def _cv_service():
    """惰性初始化火山即梦 VisualService（cv 通道专用），避免未使用 cv 通道时白初始化"""
    global _visual_service
    if _visual_service is None:
        from volcengine.visual.VisualService import VisualService
        svc = VisualService()
        svc.set_ak(VOLC_ACCESS_KEY)
        svc.set_sk(VOLC_SECRET_KEY)
        _visual_service = svc
    return _visual_service


# ---------------- JSON 路径提取 ----------------

def _json_get(data, path: str):
    """按点号路径从 dict/list 中取值，支持数组索引：
    "data[0].url" / "data.task_id" / "content.video_url" / "data" 等。
    取不到返回 None。"""
    if not path:
        return None
    cur = data
    for part in path.split("."):
        if cur is None:
            return None
        if "[" in part and part.endswith("]"):
            name, idx_s = part.split("[", 1)
            idx = int(idx_s.rstrip("]"))
            if name:
                cur = cur.get(name) if isinstance(cur, dict) else None
            if not isinstance(cur, (list, tuple)) or idx >= len(cur):
                return None
            cur = cur[idx]
        else:
            cur = cur.get(part) if isinstance(cur, dict) else None
    return cur


def cv_submit(req: dict) -> dict:
    """即梦 cv 通道提交（原 visual_service.cv_sync2async_submit_task），供 video_tool 复用"""
    return _cv_service().cv_sync2async_submit_task(req)


def cv_get_result(req: dict) -> dict:
    """即梦 cv 通道查询（原 visual_service.cv_sync2async_get_result），供 video_tool 复用"""
    return _cv_service().cv_sync2async_get_result(req)


# ---------------- 图片生成（按 IMAGE_CHANNEL 分发） ----------------

def generate_image(prompt: str, width: int, height: int) -> str:
    """按 IMAGE_CHANNEL 分发图片生成，返回图片 url（单次调用，重试由调用方负责）"""
    if IMAGE_CHANNEL == CH_VOLC_ARK:
        return _image_ark(prompt, width, height)
    if IMAGE_CHANNEL == CH_GENERIC_HTTP:
        return _image_http(prompt, width, height)
    return _image_cv(prompt, width, height)


def _image_cv(prompt: str, width: int, height: int) -> str:
    """火山即梦 cv_process 文生图（req_key 由 IMAGE_REQ_KEY 指定）"""
    req = {
        "req_key": IMAGE_REQ_KEY,
        "prompt": prompt,
        "width": width,
        "height": height,
        "return_url": True,
    }
    resp = _cv_service().cv_process(req)
    if resp.get("code") not in (0, 10000):
        raise Exception(f"图片生成失败:{resp}")
    return resp["data"]["image_urls"][0]


def _image_ark(prompt: str, width: int, height: int) -> str:
    """火山方舟文生图（Seedream）：POST /images/generations，返回 data[0].url"""
    if not ARK_API_KEY:
        raise Exception("方舟通道需要配置 ARK_API_KEY（volc-sk-xxx）")
    size = f"{width}x{height}" if width and height else "1024x1024"
    payload = {
        "model": ARK_IMAGE_MODEL,
        "prompt": prompt,
        "size": size,
        "response_format": "url",
        "watermark": False,
    }
    resp = requests.post(f"{ARK_API_URL}/images/generations",
                         json=payload,
                         headers=_ark_headers(),
                         timeout=120)
    _raise_for_http(resp, "方舟图片生成")
    data = resp.json()
    url = _json_get(data, "data[0].url")
    if not url:
        raise Exception(f"方舟图片生成返回异常:{str(data)[:200]}")
    logger.info("ark image ok | model=%s | size=%s", ARK_IMAGE_MODEL, size)
    return url


def _image_http(prompt: str, width: int, height: int) -> str:
    """通用 HTTP 文生图：POST IMAGE_HTTP_URL，请求体 {prompt,width,height}，结果按 IMAGE_HTTP_URL_PATH 提取"""
    if not IMAGE_HTTP_URL:
        raise Exception("generic_http 图片通道需要配置 IMAGE_HTTP_URL")
    payload = {"prompt": prompt, "width": width, "height": height}
    resp = requests.post(IMAGE_HTTP_URL, json=payload, headers=_http_headers(IMAGE_HTTP_TOKEN), timeout=120)
    _raise_for_http(resp, "HTTP 图片生成")
    url = _json_get(resp.json(), IMAGE_HTTP_URL_PATH)
    if not url:
        raise Exception(f"HTTP 图片返回中未找到路径 {IMAGE_HTTP_URL_PATH}:{str(resp.json())[:200]}")
    logger.info("http image ok | url=%s…", str(url)[:70])
    return url


# ---------------- 视频生成（按 VIDEO_CHANNEL 分发） ----------------

def submit_video(prompt: str, ref_url: str, dur_params: dict, gen_seconds: int) -> str:
    """提交视频任务，返回 task_id。dur_params 来自 resolve_duration_params（时长策略配置）"""
    if VIDEO_CHANNEL == CH_VOLC_ARK:
        return _video_ark_submit(prompt, ref_url, dur_params, gen_seconds)
    if VIDEO_CHANNEL == CH_GENERIC_HTTP:
        return _video_http_submit(prompt, ref_url, dur_params, gen_seconds)
    raise RuntimeError("volc_cv 通道的提交请走 video_tool 内的 cv 分支（含 50430 退避重试）")


def poll_video(task_id: str) -> dict:
    """轮询一次视频任务状态（非 cv 通道），返回 {"status": str, "video_url": str|None, "error": str|None}
    status 取值：succeeded / failed / cancelled / pending（进行中）"""
    if VIDEO_CHANNEL == CH_VOLC_ARK:
        return _video_ark_poll(task_id)
    if VIDEO_CHANNEL == CH_GENERIC_HTTP:
        return _video_http_poll(task_id)
    raise RuntimeError("volc_cv 通道的轮询请走 video_tool 内的 cv 分支")


def video_has_native_audio() -> bool:
    """当前视频通道是否原生带音频（方舟 Seedance + ARK_VIDEO_AUDIO=true）。
    true 时流水线应跳过 edge-tts 配音，避免覆盖模型原生声音。"""
    return VIDEO_CHANNEL == CH_VOLC_ARK and ARK_VIDEO_AUDIO


def _video_ark_submit(prompt: str, ref_url: str, dur_params: dict, gen_seconds: int) -> str:
    """火山方舟文生视频（Seedance 2.0）：POST /contents/generations/tasks
    支持参考图（role=reference_image）+ 原生音频（generate_audio）"""
    if not ARK_API_KEY:
        raise Exception("方舟通道需要配置 ARK_API_KEY（volc-sk-xxx）")
    # 时长：优先取任意时长制的 duration 字段；档位制则用档位秒数；再 clamp 到平台 [4,15]
    target = int(dur_params.get("duration") or gen_seconds or 5)
    target = max(ARK_VIDEO_DUR_MIN, min(target, ARK_VIDEO_DUR_MAX))
    content = [{"type": "text", "text": prompt}]
    if ref_url:
        content.append({
            "type": "image_url",
            "image_url": {"url": ref_url},
            "role": "reference_image",  # Seedance 2.0 参考图：保持角色/场景一致
        })
    payload = {
        "model": ARK_VIDEO_MODEL,
        "content": content,
        "resolution": ARK_VIDEO_RESOLUTION,
        "ratio": ARK_VIDEO_RATIO,
        "duration": target,
        "generate_audio": ARK_VIDEO_AUDIO,
        "watermark": False,
    }
    resp = requests.post(f"{ARK_API_URL}/contents/generations/tasks",
                         json=payload,
                         headers=_ark_headers(),
                         timeout=120)
    _raise_for_http(resp, "方舟视频提交")
    data = resp.json()
    task_id = data.get("id")
    if not task_id:
        raise Exception(f"方舟视频提交未返回任务 id:{str(data)[:200]}")
    logger.info("ark video submit ok | model=%s | target=%ds | ref=%s | audio=%s | task=%s",
                ARK_VIDEO_MODEL, target, bool(ref_url), ARK_VIDEO_AUDIO, task_id)
    return task_id


def _video_ark_poll(task_id: str) -> dict:
    """火山方舟轮询：GET /contents/generations/tasks/{id}
    成功时 content.video_url 为下载链接（有效期 24 小时，生成后需立即下载落盘）"""
    try:
        resp = requests.get(f"{ARK_API_URL}/contents/generations/tasks/{task_id}",
                            headers=_ark_headers(), timeout=60)
        _raise_for_http(resp, "方舟视频查询")
        data = resp.json()
    except Exception as e:
        logger.warning("ark poll request failed | task=%s | %s", task_id, str(e)[:100])
        return {"status": "pending", "video_url": None, "error": None}  # 网络抖动按进行中处理
    status = str(data.get("status", "pending")).lower()
    if status in ("succeeded", "done"):
        url = _json_get(data, "content.video_url")
        logger.info("ark video done | task=%s", task_id)
        return {"status": "succeeded", "video_url": url, "error": None}
    if status in ("failed", "cancelled", "cancel"):
        err = _json_get(data, "error.message") or str(data.get("error")) or str(data)[:150]
        logger.warning("ark video %s | task=%s | %s", status, task_id, str(err)[:120])
        return {"status": status, "video_url": None, "error": str(err)}
    return {"status": "pending", "video_url": None, "error": None}


def _video_http_submit(prompt: str, ref_url: str, dur_params: dict, gen_seconds: int) -> str:
    """通用 HTTP 视频提交：POST VIDEO_HTTP_SUBMIT_URL，请求体 {prompt,image_url?,duration}+附加字段"""
    if not VIDEO_HTTP_SUBMIT_URL:
        raise Exception("generic_http 视频通道需要配置 VIDEO_HTTP_SUBMIT_URL")
    target = int(dur_params.get("duration") or gen_seconds or 5)
    payload = {"prompt": prompt, "duration": target}
    if ref_url:
        payload["image_url"] = ref_url
    payload.update(_VIDEO_HTTP_EXTRA)
    resp = requests.post(VIDEO_HTTP_SUBMIT_URL, json=payload, headers=_http_headers(VIDEO_HTTP_TOKEN), timeout=120)
    _raise_for_http(resp, "HTTP 视频提交")
    data = resp.json()
    task_id = _json_get(data, VIDEO_HTTP_TASK_ID_PATH)
    if not task_id:
        raise Exception(f"HTTP 视频提交未找到任务 id（路径 {VIDEO_HTTP_TASK_ID_PATH}）:{str(data)[:200]}")
    logger.info("http video submit ok | task=%s", task_id)
    return str(task_id)


def _video_http_poll(task_id: str) -> dict:
    """通用 HTTP 视频轮询：GET VIDEO_HTTP_POLL_URL（{task_id} 替换为任务 id）"""
    try:
        url = VIDEO_HTTP_POLL_URL.format(task_id=task_id)
    except Exception:
        url = VIDEO_HTTP_POLL_URL
    try:
        resp = requests.get(url, headers=_http_headers(VIDEO_HTTP_TOKEN), timeout=60)
        _raise_for_http(resp, "HTTP 视频查询")
        data = resp.json()
    except Exception as e:
        logger.warning("http poll request failed | task=%s | %s", task_id, str(e)[:100])
        return {"status": "pending", "video_url": None, "error": None}
    status = str(_json_get(data, VIDEO_HTTP_STATUS_PATH) or "pending").strip().lower()
    if status == VIDEO_HTTP_SUCCESS_STATUS:
        url = _json_get(data, VIDEO_HTTP_VIDEO_URL_PATH)
        logger.info("http video done | task=%s", task_id)
        return {"status": "succeeded", "video_url": url, "error": None}
    if status in ("failed", "error", "cancelled", "cancel"):
        err = str(data)[:150]
        logger.warning("http video %s | task=%s", status, task_id)
        return {"status": status, "video_url": None, "error": err}
    return {"status": "pending", "video_url": None, "error": None}


# ---------------- 通用辅助 ----------------

def _ark_headers() -> dict:
    return {"Authorization": f"Bearer {ARK_API_KEY}", "Content-Type": "application/json"}


def _http_headers(token: str) -> dict:
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _raise_for_http(resp, tag: str):
    if resp.status_code >= 400:
        raise Exception(f"{tag}失败 HTTP {resp.status_code}: {resp.text[:200]}")


def has_audio_stream(video_path: str) -> bool:
    """探测本地视频是否自带音轨（ffmpeg stderr 中出现 Audio: 即视为有音频）"""
    import shutil
    import subprocess
    ff = shutil.which("ffmpeg")
    if not ff:
        try:
            import imageio_ffmpeg
            ff = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return False
    try:
        proc = subprocess.run([ff, "-i", video_path], capture_output=True, text=True, timeout=60)
        return "Audio:" in proc.stderr
    except Exception:
        return False
