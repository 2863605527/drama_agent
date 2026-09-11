# -*- coding: utf-8 -*-
"""媒体通道抽象层：让「图片/视频生成」可以在多个供应商通道之间无缝切换。

通道来源有两层（后者优先）：
  1. 服务端 .env 全局默认（进程启动时读取，向后兼容）；
  2. 用户在前端配置、随任务下发的运行时 profile（dict，已解密明文），
     profile 为空或 channel in ("", "env") 时完全回退到 .env 默认 —— 老行为 100% 保留。

支持的通道类型：
  - volc_cv        火山即梦「视觉服务」通道（cv_process / cv_sync2async_*），默认
  - volc_ark       火山方舟通道（ark.../api/v3）：Seedream 图片 / Seedance 视频
  - generic_http   通用 HTTP 通道：第三方供应商，提交/轮询 URL 与结果 JSON 路径可配
"""
import os
import json
import time
import requests
from dotenv import load_dotenv
from tools.logger_tool import get_logger
from tools.http_presets import normalize_http_media

logger = get_logger("drama.channel")

load_dotenv()

# ===== 通道类型常量 =====
CH_VOLC_CV = "volc_cv"
CH_VOLC_ARK = "volc_ark"
CH_GENERIC_HTTP = "generic_http"
_VALID = (CH_VOLC_CV, CH_VOLC_ARK, CH_GENERIC_HTTP)

# ===== 当前生效通道（.env 默认，向后兼容）=====
IMAGE_CHANNEL = os.getenv("IMAGE_CHANNEL", CH_VOLC_CV).strip().lower()
VIDEO_CHANNEL = os.getenv("VIDEO_CHANNEL", CH_VOLC_CV).strip().lower()
if IMAGE_CHANNEL not in _VALID:
    logger.warning("unknown IMAGE_CHANNEL=%s, fallback to volc_cv", IMAGE_CHANNEL)
    IMAGE_CHANNEL = CH_VOLC_CV
if VIDEO_CHANNEL not in _VALID:
    logger.warning("unknown VIDEO_CHANNEL=%s, fallback to volc_cv", VIDEO_CHANNEL)
    VIDEO_CHANNEL = CH_VOLC_CV

# ===== 火山即梦 CV 通道（.env 默认）=====
VOLC_ACCESS_KEY = os.getenv("VOLC_ACCESS_KEY")
VOLC_SECRET_KEY = os.getenv("VOLC_SECRET_KEY")
IMAGE_REQ_KEY = os.getenv("IMAGE_REQ_KEY", "jimeng_high_aes_general_v21_L")
# 图生图（以参考图做图像编辑，用于「黑夜场景图以白天图为底图改夜景」）：即梦图生图3.0智能参考
IMAGE_I2I_REQ_KEY = os.getenv("IMAGE_I2I_REQ_KEY", "jimeng_i2i_v30").strip()
IMAGE_I2I_SCALE = float(os.getenv("IMAGE_I2I_SCALE", "0.5"))   # 文本影响强度 [0,1]，越小越保留参考图
IMAGE_I2I_POLL_INTERVAL = float(os.getenv("IMAGE_I2I_POLL_INTERVAL", "2.0"))
IMAGE_I2I_POLL_TIMEOUT = float(os.getenv("IMAGE_I2I_POLL_TIMEOUT", "120"))

# ===== 火山方舟通道（.env 默认）=====
ARK_API_URL = os.getenv("ARK_API_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
ARK_API_KEY = os.getenv("ARK_API_KEY", "").strip()
ARK_IMAGE_MODEL = os.getenv("ARK_IMAGE_MODEL", "doubao-seedream-5-0-260128")
ARK_VIDEO_MODEL = os.getenv("ARK_VIDEO_MODEL", "doubao-seedance-2-0-260128")
ARK_VIDEO_RESOLUTION = os.getenv("ARK_VIDEO_RESOLUTION", "720p")
ARK_VIDEO_RATIO = os.getenv("ARK_VIDEO_RATIO", "9:16")
ARK_VIDEO_AUDIO = os.getenv("ARK_VIDEO_AUDIO", "true").strip().lower() in ("1", "true", "yes", "on")
ARK_VIDEO_DUR_MIN = int(os.getenv("ARK_VIDEO_DUR_MIN", "4"))
ARK_VIDEO_DUR_MAX = int(os.getenv("ARK_VIDEO_DUR_MAX", "15"))

# ===== 通用 HTTP 通道（.env 默认）=====
IMAGE_HTTP_URL = os.getenv("IMAGE_HTTP_URL", "").strip()
IMAGE_HTTP_TOKEN = os.getenv("IMAGE_HTTP_TOKEN", "").strip()
IMAGE_HTTP_URL_PATH = os.getenv("IMAGE_HTTP_URL_PATH", "data[0].url")
# 图生图时参考图透传给第三方接口所用的字段名（按对方文档调整）
IMAGE_HTTP_REF_FIELD = os.getenv("IMAGE_HTTP_REF_FIELD", "image").strip() or "image"
VIDEO_HTTP_SUBMIT_URL = os.getenv("VIDEO_HTTP_SUBMIT_URL", "").strip()
VIDEO_HTTP_POLL_URL = os.getenv("VIDEO_HTTP_POLL_URL", "").strip()
VIDEO_HTTP_TOKEN = os.getenv("VIDEO_HTTP_TOKEN", "").strip()
VIDEO_HTTP_TASK_ID_PATH = os.getenv("VIDEO_HTTP_TASK_ID_PATH", "data.task_id")
VIDEO_HTTP_STATUS_PATH = os.getenv("VIDEO_HTTP_STATUS_PATH", "data.status")
VIDEO_HTTP_POLL_METHOD = os.getenv("VIDEO_HTTP_POLL_METHOD", "get").strip().lower()
VIDEO_HTTP_POLL_BODY = os.getenv("VIDEO_HTTP_POLL_BODY", "").strip()
VIDEO_HTTP_SUCCESS_STATUS = os.getenv("VIDEO_HTTP_SUCCESS_STATUS", "succeeded").strip().lower()
VIDEO_HTTP_VIDEO_URL_PATH = os.getenv("VIDEO_HTTP_VIDEO_URL_PATH", "data.content.video_url")
VIDEO_HTTP_EXTRA_FIELDS = os.getenv("VIDEO_HTTP_EXTRA_FIELDS", "").strip()
_VIDEO_HTTP_EXTRA = {}
if VIDEO_HTTP_EXTRA_FIELDS:
    try:
        _VIDEO_HTTP_EXTRA = json.loads(VIDEO_HTTP_EXTRA_FIELDS)
    except Exception as e:
        logger.warning("VIDEO_HTTP_EXTRA_FIELDS is not valid JSON, ignored | %s", e)

logger.info("media channel | image=%s | video=%s | ark=%s | ark_video_model=%s | ark_audio=%s | ark_ratio=%s",
            IMAGE_CHANNEL, VIDEO_CHANNEL,
            "configured" if ARK_API_KEY else "NO_KEY", ARK_VIDEO_MODEL, ARK_VIDEO_AUDIO, ARK_VIDEO_RATIO)


# ==================== 运行时 profile 解析（用户前端配置覆盖 .env） ====================

def _p(profile, key, default):
    """从 profile 取非空字段，否则回退 .env 默认值。"""
    if profile:
        val = profile.get(key)
        if val is not None and str(val) != "":
            return val
    return default


def _as_segment(profile, kind: str):
    """兼容整包 {llm,image,video} 与单段两种 profile：整包则取出 kind 段，单段原样返回。
    门面层已拆段，这里是纵深防御，杜绝整包被误判为空而回退 .env 默认通道。"""
    if isinstance(profile, dict) and isinstance(profile.get(kind), dict):
        return profile[kind]
    return profile


def effective_channel(profile, default_channel: str) -> str:
    """本次调用实际使用的通道名：profile.channel 优先，env/空 → .env 默认。"""
    ch = (profile or {}).get("channel")
    if not ch or ch == "env":
        return default_channel
    ch = str(ch).strip().lower()
    return ch if ch in _VALID else default_channel


def effective_image_channel(profile=None) -> str:
    return effective_channel(_as_segment(profile, "image"), IMAGE_CHANNEL)


def effective_video_channel(profile=None) -> str:
    return effective_channel(_as_segment(profile, "video"), VIDEO_CHANNEL)


# ---------------- 即梦 CV 服务（.env 单例 + profile 独立实例缓存） ----------------

_visual_service = None
_profile_services = {}


def _cv_service(profile=None):
    """返回火山 VisualService：profile 带 AK/SK 时用独立实例（按 AK 缓存），否则用 .env 单例。"""
    global _visual_service
    ak = _p(profile, "access_key", None)
    sk = _p(profile, "secret_key", None)
    if not ak or not sk:
        if _visual_service is None:
            from volcengine.visual.VisualService import VisualService
            svc = VisualService()
            svc.set_ak(VOLC_ACCESS_KEY)
            svc.set_sk(VOLC_SECRET_KEY)
            _visual_service = svc
        return _visual_service
    cache_key = ak
    if cache_key not in _profile_services:
        from volcengine.visual.VisualService import VisualService
        svc = VisualService()
        svc.set_ak(ak)
        svc.set_sk(sk)
        _profile_services[cache_key] = svc
    return _profile_services[cache_key]


def cv_submit(req: dict, profile=None) -> dict:
    """即梦 cv 通道提交，供 video_tool 复用（支持 profile AK/SK 覆盖）。"""
    return _cv_service(profile).cv_sync2async_submit_task(req)


def cv_get_result(req: dict, profile=None) -> dict:
    """即梦 cv 通道查询，供 video_tool 复用（支持 profile AK/SK 覆盖）。"""
    return _cv_service(profile).cv_sync2async_get_result(req)


# ---------------- JSON 路径提取 ----------------

def _json_get(data, path: str):
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


# ==================== 图片生成 ====================

def generate_image(prompt: str, width: int, height: int, profile=None, ref_image_url: str = "") -> str:
    """按有效通道分发图片生成，返回图片 url（重试由调用方负责）。

    ref_image_url 非空时为「图生图/参考图编辑」（如黑夜场景图以白天图为底图改夜景），
    三个通道均支持参考图：
      - volc_cv       走即梦图生图3.0（jimeng_i2i_v30，异步提交+轮询）；
      - volc_ark      Seedream 同一 images/generations 接口，请求体带 image 参考图；
      - generic_http  向第三方接口额外透传参考图字段（字段名由 IMAGE_HTTP_REF_FIELD 配置，默认 image）。
    """
    channel = effective_image_channel(profile)
    profile = _as_segment(profile, "image")
    if channel == CH_VOLC_ARK:
        return _image_ark(prompt, width, height, profile, ref_image_url)
    if channel == CH_GENERIC_HTTP:
        return _image_http(prompt, width, height, profile, ref_image_url)
    if ref_image_url:
        return _edit_image_cv(prompt, ref_image_url, width, height, profile)
    return _image_cv(prompt, width, height, profile)


def _edit_image_cv(prompt: str, ref_image_url: str, width: int, height: int, profile=None) -> str:
    """火山即梦图生图3.0智能参考（异步接口）：以 ref_image_url 为唯一参考图，按 prompt 编辑出图。

    参考图支持远程 URL（image_urls）或本地 /assets 图（自动读文件转 binary_data_base64）。"""
    req_key = _p(profile, "i2i_req_key", IMAGE_I2I_REQ_KEY)
    submit_req = {
        "req_key": req_key,
        "prompt": prompt,
        "scale": IMAGE_I2I_SCALE,
        "seed": -1,
    }
    local_data = _local_image_to_data_url(ref_image_url)
    if local_data and local_data.startswith("data:"):
        submit_req["binary_data_base64"] = [local_data.split(",", 1)[1]]
    else:
        submit_req["image_urls"] = [ref_image_url]
    if width and height:
        submit_req["width"] = width
        submit_req["height"] = height
    sub = cv_submit(submit_req, profile)
    if sub.get("code") not in (0, 10000):
        raise Exception(f"图生图提交失败:{sub}")
    task_id = (sub.get("data") or {}).get("task_id")
    if not task_id:
        raise Exception(f"图生图未返回 task_id:{sub}")
    poll_req = {"req_key": req_key, "task_id": task_id,
                "req_json": json.dumps({"return_url": True, "logo_info": {"add_logo": False}})}
    deadline = time.time() + IMAGE_I2I_POLL_TIMEOUT
    last_status = None
    while time.time() < deadline:
        time.sleep(IMAGE_I2I_POLL_INTERVAL)
        resp = cv_get_result(poll_req, profile)
        if resp.get("code") not in (0, 10000):
            raise Exception(f"图生图查询失败:{resp}")
        data = resp.get("data") or {}
        status = data.get("status")
        last_status = status
        if status == "done":
            urls = data.get("image_urls") or []
            if urls:
                return urls[0]
            b64 = data.get("binary_data_base64") or []
            if b64:  # 兜底：理论上 return_url=true 不会走到
                raise Exception("图生图仅返回 base64（未取到 URL），请检查 return_url 配置")
            raise Exception(f"图生图完成但无图片:{str(data)[:160]}")
        if status in ("not_found", "expired"):
            raise Exception(f"图生图任务状态异常:{status}")
        # in_queue / generating 继续轮询
    raise Exception(f"图生图轮询超时（{IMAGE_I2I_POLL_TIMEOUT}s，last_status={last_status}）")


def _image_cv(prompt: str, width: int, height: int, profile=None) -> str:
    req_key = _p(profile, "req_key", IMAGE_REQ_KEY)
    req = {
        "req_key": req_key,
        "prompt": prompt,
        "width": width,
        "height": height,
        "return_url": True,
    }
    resp = _cv_service(profile).cv_process(req)
    if resp.get("code") not in (0, 10000):
        raise Exception(f"图片生成失败:{resp}")
    return resp["data"]["image_urls"][0]


def _image_ark(prompt: str, width: int, height: int, profile=None, ref_image_url: str = "") -> str:
    api_url = str(_p(profile, "api_url", ARK_API_URL)).rstrip("/")
    api_key = _p(profile, "api_key", ARK_API_KEY)
    model = _p(profile, "model", ARK_IMAGE_MODEL)
    if not api_key:
        raise Exception("方舟通道需要配置 API Key（volc-sk-xxx）")
    size = f"{width}x{height}" if width and height else "1024x1024"
    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "response_format": "url",
        "watermark": False,
    }
    if ref_image_url:
        # Seedream 图生图：同一接口带 image（远程 URL 或本地图转 base64 dataURL），即以参考图为底做编辑
        payload["image"] = _local_image_to_data_url(ref_image_url) or ref_image_url
    resp = requests.post(f"{api_url}/images/generations",
                         json=payload, headers=_ark_headers(api_key), timeout=120)
    _raise_for_http(resp, "方舟图片生成")
    data = resp.json()
    url = _json_get(data, "data[0].url")
    if not url:
        raise Exception(f"方舟图片生成返回异常:{str(data)[:200]}")
    logger.info("ark image ok | model=%s | size=%s | ref=%s", model, size, bool(ref_image_url))
    return url


def _image_http(prompt: str, width: int, height: int, profile=None, ref_image_url: str = "") -> str:
    profile = normalize_http_media(profile, "image")  # 平台预设自动补全（幂等，用户已填值优先）
    url = _p(profile, "endpoint", IMAGE_HTTP_URL)
    token = _p(profile, "token", IMAGE_HTTP_TOKEN)
    result_path = _p(profile, "result_path", IMAGE_HTTP_URL_PATH)
    if not url:
        raise Exception("generic_http 图片通道需要配置接口地址")
    payload = {"prompt": prompt}
    # 模型名（硅基流动 / OpenAI 兼容接口必填）
    model = _p(profile, "model", "")
    if model:
        payload["model"] = model
    # 尺寸：供应商用单一尺寸字段（如硅基 image_size）时配 size_field，否则给 width/height
    size_field = str(_p(profile, "size_field", "") or "").strip()
    size_val = f"{width}x{height}" if width and height else "1024x1024"
    if size_field:
        payload[size_field] = size_val
    else:
        payload["width"], payload["height"] = width, height
    if ref_image_url:
        # 参考图：字段名 image_field（硅基为 image）；本地 /assets 图第三方拉不到，统一转 base64 dataURL
        img_field = str(_p(profile, "image_field", IMAGE_HTTP_REF_FIELD) or "image").strip()
        payload[img_field] = _local_image_to_data_url(ref_image_url) or ref_image_url
    # 剔除供应商不接受的默认字段
    omit_fields = str(_p(profile, "omit_fields", "") or "").strip()
    if omit_fields:
        for k in [s.strip() for s in omit_fields.split(",") if s.strip()]:
            payload.pop(k, None)
    # 用户级附加字段（JSON 对象，覆盖同名键）
    extra_raw = _p(profile, "extra_fields", "")
    if extra_raw:
        try:
            extra = json.loads(extra_raw) if isinstance(extra_raw, str) else extra_raw
            if isinstance(extra, dict):
                payload.update(extra)
        except Exception as e:
            logger.warning("image extra_fields invalid JSON, ignored | %s", e)
    resp = requests.post(url, json=payload, headers=_http_headers(token), timeout=120)
    _raise_for_http(resp, "HTTP 图片生成")
    img_url = _json_get(resp.json(), result_path)
    if not img_url:
        raise Exception(f"HTTP 图片返回中未找到路径 {result_path}:{str(resp.json())[:200]}")
    logger.info("http image ok | model=%s | ref=%s | url=%s…", model, bool(ref_image_url), str(img_url)[:70])
    return img_url


# ==================== 视频生成 ====================

def submit_video(prompt: str, ref_url: str, dur_params: dict, gen_seconds: int,
                 profile=None) -> str:
    """提交视频任务，返回 task_id。"""
    channel = effective_video_channel(profile)
    profile = _as_segment(profile, "video")
    if channel == CH_VOLC_ARK:
        return _video_ark_submit(prompt, ref_url, dur_params, gen_seconds, profile)
    if channel == CH_GENERIC_HTTP:
        return _video_http_submit(prompt, ref_url, dur_params, gen_seconds, profile)
    raise RuntimeError("volc_cv 通道的提交请走 video_tool 内的 cv 分支（含 50430 退避重试）")


def poll_video(task_id: str, profile=None) -> dict:
    """轮询一次视频任务状态，返回 {status, video_url, error}。"""
    channel = effective_video_channel(profile)
    profile = _as_segment(profile, "video")
    if channel == CH_VOLC_ARK:
        return _video_ark_poll(task_id, profile)
    if channel == CH_GENERIC_HTTP:
        return _video_http_poll(task_id, profile)
    raise RuntimeError("volc_cv 通道的轮询请走 video_tool 内的 cv 分支")


def video_has_native_audio(profile=None) -> bool:
    """当前视频通道是否原生带音频（方舟 Seedance + generate_audio=true）。
    HTTP 通用通道若用户在配置里声明 native_audio=1/true（平台返回的视频自带音轨），
    auto 模式同样优先保留原生音频；其余通道无原生音频则走 TTS 配音。"""
    profile = _as_segment(profile, "video")
    channel = effective_video_channel(profile)
    if channel == CH_GENERIC_HTTP:
        na = _p(profile, "native_audio", None)
        if na is not None:
            return str(na).strip().lower() in ("1", "true", "yes", "on")
        return False
    if channel != CH_VOLC_ARK:
        return False
    audio = _p(profile, "generate_audio", ARK_VIDEO_AUDIO)
    if isinstance(audio, str):
        return audio.strip().lower() in ("1", "true", "yes", "on")
    return bool(audio)


def _ref_list(ref) -> list:
    """参考图归一化：允许单张 URL 字符串或列表，返回去空后的有序列表（场景图在前、角色立绘随后）。"""
    if not ref:
        return []
    if isinstance(ref, (list, tuple)):
        return [r for r in ref if r]
    return [ref]


def _video_ark_submit(prompt: str, ref, dur_params: dict, gen_seconds: int,
                      profile=None) -> str:
    api_url = str(_p(profile, "api_url", ARK_API_URL)).rstrip("/")
    api_key = _p(profile, "api_key", ARK_API_KEY)
    model = _p(profile, "model", ARK_VIDEO_MODEL)
    resolution = _p(profile, "resolution", ARK_VIDEO_RESOLUTION)
    ratio = _p(profile, "ratio", ARK_VIDEO_RATIO)
    audio = _p(profile, "generate_audio", ARK_VIDEO_AUDIO)
    if isinstance(audio, str):
        audio = audio.strip().lower() in ("1", "true", "yes", "on")
    dur_min = ARK_VIDEO_DUR_MIN
    dur_max = ARK_VIDEO_DUR_MAX
    if not api_key:
        raise Exception("方舟通道需要配置 API Key（volc-sk-xxx）")
    target = int(dur_params.get("duration") or gen_seconds or 5)
    target = max(dur_min, min(target, dur_max))
    refs = _ref_list(ref)
    content = [{"type": "text", "text": prompt}]
    for idx, ref_one in enumerate(refs, start=1):
        # 本地 /assets 图服务器拉不到，转 base64 dataURL；远程 URL 原样；多张按序作为参考图
        ref_val = _local_image_to_data_url(ref_one) or ref_one
        content.append({
            "type": "image_url",
            "image_url": {"url": ref_val},
            "role": "reference_image",
        })
    payload = {
        "model": model,
        "content": content,
        "resolution": resolution,
        "ratio": ratio,
        "duration": target,
        "generate_audio": bool(audio),
        "watermark": False,
    }
    resp = requests.post(f"{api_url}/contents/generations/tasks",
                         json=payload, headers=_ark_headers(api_key), timeout=120)
    _raise_for_http(resp, "方舟视频提交")
    data = resp.json()
    task_id = data.get("id")
    if not task_id:
        raise Exception(f"方舟视频提交未返回任务 id:{str(data)[:200]}")
    logger.info("ark video submit ok | model=%s | target=%ds | refs=%d | audio=%s | task=%s",
                model, target, len(refs), bool(audio), task_id)
    return task_id


def _video_ark_poll(task_id: str, profile=None) -> dict:
    api_url = str(_p(profile, "api_url", ARK_API_URL)).rstrip("/")
    api_key = _p(profile, "api_key", ARK_API_KEY)
    try:
        resp = requests.get(f"{api_url}/contents/generations/tasks/{task_id}",
                            headers=_ark_headers(api_key), timeout=60)
        _raise_for_http(resp, "方舟视频查询")
        data = resp.json()
    except Exception as e:
        logger.warning("ark poll request failed | task=%s | %s", task_id, str(e)[:100])
        return {"status": "pending", "video_url": None, "error": None}
    status = str(data.get("status", "pending")).lower()
    if status in ("succeeded", "done"):
        url = _json_get(data, "content.video_url")
        return {"status": "succeeded", "video_url": url, "error": None}
    if status in ("failed", "cancelled", "cancel"):
        err = _json_get(data, "error.message") or str(data.get("error")) or str(data)[:150]
        return {"status": status, "video_url": None, "error": str(err)}
    return {"status": "pending", "video_url": None, "error": None}


def _local_image_to_data_url(ref_url: str):
    """把本地 /assets/ 图片（或本地绝对路径）读成 data:image/...;base64。

    用于第三方接口无法访问我们本地 URL 的场景（如硅基流动 I2V 只接受公网 URL 或 base64）。
    外部 http(s) URL 直接返回 None（由调用方透传原 URL）。
    """
    import base64 as _b64
    import mimetypes as _mt
    import re as _re
    if not ref_url or ref_url.startswith("data:"):
        return ref_url if ref_url else None
    path = None
    m = _re.match(r"^https?://[^/]+/assets/(.+)$", ref_url)
    if m:
        path = os.path.join("assets", m.group(1).lstrip("/"))
    elif ref_url.startswith("/assets/"):
        path = os.path.join("assets", ref_url[len("/assets/"):])
    elif "/assets/" in ref_url:
        path = os.path.join("assets", ref_url.split("/assets/", 1)[1])
    elif os.path.exists(ref_url):
        path = ref_url
    if not path or not os.path.exists(path):
        return None
    mime = _mt.guess_type(path)[0] or "image/png"
    with open(path, "rb") as f:
        return f"data:{mime};base64,{_b64.b64encode(f.read()).decode()}"


def _video_http_submit(prompt: str, ref_url: str, dur_params: dict, gen_seconds: int,
                       profile=None) -> str:
    profile = normalize_http_media(profile, "video")  # 平台预设自动补全（幂等）
    submit_url = _p(profile, "submit_url", VIDEO_HTTP_SUBMIT_URL)
    token = _p(profile, "token", VIDEO_HTTP_TOKEN)
    task_id_path = _p(profile, "task_id_path", VIDEO_HTTP_TASK_ID_PATH)
    if not submit_url:
        raise Exception("generic_http 视频通道需要配置提交地址")
    target = int(dur_params.get("duration") or gen_seconds or 5)
    payload = {"prompt": prompt, "duration": target}
    model = _p(profile, "model", "")
    if model:
        payload["model"] = model
    refs = _ref_list(ref_url)
    if refs:
        # 通用 I2V 多为单首帧参考，取第一张（场景图）；本地图统一转 base64 dataURL
        img_field = str(_p(profile, "image_field", "image_url") or "image_url").strip()
        first = refs[0]
        payload[img_field] = _local_image_to_data_url(first) or first
    # 剔除供应商不接受的默认字段（如硅基流动没有 duration）
    omit_fields = str(_p(profile, "omit_fields", "") or "").strip()
    if omit_fields:
        for k in [s.strip() for s in omit_fields.split(",") if s.strip()]:
            payload.pop(k, None)
    payload.update(_VIDEO_HTTP_EXTRA)
    # 用户 profile 级附加字段（如硅基流动的 {"model": "..."}），覆盖 env 级同名键
    extra_raw = _p(profile, "extra_fields", "")
    if extra_raw:
        try:
            extra = json.loads(extra_raw) if isinstance(extra_raw, str) else extra_raw
            if isinstance(extra, dict):
                payload.update(extra)
            else:
                logger.warning("extra_fields must be a JSON object, ignored")
        except Exception as e:
            logger.warning("extra_fields is not valid JSON, ignored | %s", e)
    # logger.info(f"submit_url: {submit_url}")
    # logger.info(f"payload: {payload}")
    resp = requests.post(submit_url, json=payload, headers=_http_headers(token), timeout=120)
    # logger.info(f"status: {resp.status_code}, response: {resp.text[:200]}")
    _raise_for_http(resp, "HTTP 视频提交")
    data = resp.json()
    task_id = _json_get(data, task_id_path)
    if not task_id:
        raise Exception(f"HTTP 视频提交未找到任务 id（路径 {task_id_path}）:{str(data)[:200]}")
    return str(task_id)


def _video_http_poll(task_id: str, profile=None) -> dict:
    profile = normalize_http_media(profile, "video")  # 平台预设自动补全（幂等）
    poll_tpl = _p(profile, "poll_url", VIDEO_HTTP_POLL_URL)
    token = _p(profile, "token", VIDEO_HTTP_TOKEN)
    status_path = _p(profile, "status_path", VIDEO_HTTP_STATUS_PATH)
    success_status = str(_p(profile, "success_status", VIDEO_HTTP_SUCCESS_STATUS)).lower()
    video_url_path = _p(profile, "video_url_path", VIDEO_HTTP_VIDEO_URL_PATH)
    poll_method = str(_p(profile, "poll_method", VIDEO_HTTP_POLL_METHOD) or "get").strip().lower()
    poll_body_tpl = str(_p(profile, "poll_body", VIDEO_HTTP_POLL_BODY) or "").strip()
    try:
        url = poll_tpl.format(task_id=task_id)
    except Exception:
        url = poll_tpl
    try:
        if poll_method == "post":
            # POST 轮询（如硅基流动 /video/status）：body 模板里的 {task_id} 替换为真实任务 id
            body = None
            if poll_body_tpl:
                body = poll_body_tpl.replace("{task_id}", task_id)
                try:
                    body = json.loads(body)
                except Exception as e:
                    logger.warning("poll_body is not valid JSON, sent as raw string | %s", e)
            resp = requests.post(url, json=body, headers=_http_headers(token), timeout=60)
        else:
            resp = requests.get(url, headers=_http_headers(token), timeout=60)
        _raise_for_http(resp, "HTTP 视频查询")
        data = resp.json()
    except Exception as e:
        logger.warning("http poll request failed | task=%s | %s", task_id, str(e)[:100])
        return {"status": "pending", "video_url": None, "error": None}
    status = str(_json_get(data, status_path) or "pending").strip().lower()
    if status == success_status:
        return {"status": "succeeded", "video_url": _json_get(data, video_url_path), "error": None}
    if status in ("failed", "fail", "error", "cancelled", "cancel"):
        err = _json_get(data, "error.message") or _json_get(data, "reason") or str(data)[:150]
        return {"status": status, "video_url": None, "error": str(err)}
    return {"status": "pending", "video_url": None, "error": None}


# ---------------- 通用辅助 ----------------

def _ark_headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _http_headers(token: str) -> dict:
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _raise_for_http(resp, tag: str):
    if resp.status_code >= 400:
        raise Exception(f"{tag}失败 HTTP {resp.status_code}: {resp.text[:200]}")


def _ffmpeg_exe():
    """获取 ffmpeg 可执行路径：优先系统 PATH，回退 imageio-ffmpeg 自带二进制；都没有返回 None。"""
    import shutil
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def has_audio_stream(video_path: str) -> bool:
    """探测本地视频是否自带音轨（ffmpeg stderr 中出现 Audio: 即视为有音频）"""
    import subprocess
    ff = _ffmpeg_exe()
    if not ff:
        return False
    try:
        proc = subprocess.run([ff, "-i", video_path], capture_output=True, text=True, timeout=60)
        return "Audio:" in proc.stderr
    except Exception:
        return False


def probe_video_quality(video_path: str) -> dict:
    """用 ffmpeg -i 解析本地成片的实际时长（秒）与是否含音轨。

    返回 {"duration": float|None, "has_audio": bool, "parsed": bool}。
    镜像内通常没有独立 ffprobe，故统一从 ffmpeg -i 的 stderr 解析 Duration / Audio 行。
    """
    import re as _re
    import subprocess
    info = {"duration": None, "has_audio": False, "parsed": False}
    ff = _ffmpeg_exe()
    if not ff:
        return info
    try:
        proc = subprocess.run([ff, "-i", video_path], capture_output=True, text=True, timeout=60)
        err = proc.stderr or ""
        m = _re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
        if m:
            h, mm, ss = m.groups()
            info["duration"] = int(h) * 3600 + int(mm) * 60 + float(ss)
            info["parsed"] = True
        info["has_audio"] = "Audio:" in err
    except Exception as e:
        logger.warning("probe_video_quality failed | %s | %s", video_path, str(e)[:100])
    return info
