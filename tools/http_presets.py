# -*- coding: utf-8 -*-
"""通用 HTTP（第三方）媒体通道的「平台预设自动适配」。

目标：前端配置 generic_http 时用户只需要填 3 样东西——
    服务根地址 base_url（如 https://api.siliconflow.cn）、Token、模型名；
其余技术字段（图片结果路径、尺寸字段、视频提交/轮询地址、轮询方式、
任务 id 路径、状态路径、成功状态值、视频 URL 路径、参考图字段、需剔除字段等）
全部由本模块按 **域名识别平台** 后自动补全；用户在「高级设置」里显式填写的值优先，
因此对任何未内置的平台也能用 OpenAI 兼容兜底默认跑通，特殊平台可手动覆盖。

该模块是纯函数、无外部请求、幂等（只补空字段，不覆盖用户已填值），
在图片/视频每次提交、轮询前调用，保证任何客户端（前端旧版本/API 直连）都能被兜底。
"""
from urllib.parse import urlparse
from typing import Optional, Tuple, Dict, Any

from tools.logger_tool import get_logger

logger = get_logger("drama.http_presets")

CH_GENERIC_HTTP = "generic_http"


# ============================ 平台预设表 ============================
# 说明：
# - match：命中 host 的关键字（小写包含匹配），从上到下首个命中者生效；
# - image.path：文生/图生图提交路径（拼在服务根地址后）；
# - video.poll_path 中的 {task_id} 为占位，运行时替换；POST 轮询（如硅基）则固定地址、id 放 body。
PLATFORM_PRESETS = [
    {
        "id": "siliconflow",
        "name": "硅基流动 SiliconFlow",
        "match": ["siliconflow.cn", "siliconflow.com"],
        "image": {
            "path": "/v1/images/generations",
            "size_field": "image_size",
            "image_field": "image",
            "result_path": "images[0].url",
        },
        "video": {
            "submit_path": "/v1/video/submit",
            "poll_path": "/v1/video/status",
            "poll_method": "post",
            "poll_body": '{"requestId": "{task_id}"}',
            "task_id_path": "requestId",
            "status_path": "status",
            "success_status": "Succeed",
            "fail_status": ["Failed"],
            "video_url_path": "results.videos[0].url",
            "image_field": "image",
            "omit_fields": "duration",
        },
    },
    {
        "id": "zhipu",
        "name": "智谱 AI BigModel",
        "match": ["bigmodel.cn", "zhipuai.cn", "zhipu.ai"],
        "image": {
            "path": "/api/paas/v4/images/generations",
            "size_field": "size",
            "image_field": "image",
            "result_path": "data[0].url",
        },
        "video": {
            "submit_path": "/api/paas/v4/videos/generations",
            "poll_path": "/api/paas/v4/async-result/{task_id}",
            "poll_method": "get",
            "poll_body": "",
            "task_id_path": "id",
            "status_path": "task_status",
            "success_status": "SUCCESS",
            "fail_status": ["FAIL", "FAILED"],
            "video_url_path": "video_result[0].url",
            "image_field": "image",
        },
    },
    {
        "id": "openai",
        "name": "OpenAI 官方",
        "match": ["openai.com", "oaistatic.com", "oaiusercontent.com", "chatgpt.com"],
        "image": {
            "path": "/v1/images/generations",
            "size_field": "size",
            "image_field": "image",
            "result_path": "data[0].url",
        },
        "video": {  # OpenAI 视频接口形态不统一，给 OpenAI 风格兜底，可用高级设置覆盖
            "submit_path": "/v1/videos/generations",
            "poll_path": "/v1/videos/{task_id}",
            "poll_method": "get",
            "poll_body": "",
            "task_id_path": "id",
            "status_path": "status",
            "success_status": "completed",
            "fail_status": ["failed", "error", "cancelled"],
            "video_url_path": "data[0].url",
            "image_field": "image",
        },
    },
]

# 未识别平台：OpenAI 兼容风格兜底（绝大多数国产中转/兼容站适用）
DEFAULT_PRESET = {
    "id": "openai_compatible",
    "name": "OpenAI 兼容（通用默认）",
    "match": [],
    "image": {
        "path": "/v1/images/generations",
        "size_field": "size",
        "image_field": "image",
        "result_path": "data[0].url",
    },
    "video": {
        "submit_path": "/v1/videos/generations",
        "poll_path": "/v1/videos/{task_id}",
        "poll_method": "get",
        "poll_body": "",
        "task_id_path": "id",
        "status_path": "status",
        "success_status": "succeeded",
        "fail_status": ["failed", "fail", "error", "cancelled"],
        "video_url_path": "data[0].url",
        "image_field": "image",
    },
}


def _split_root(raw: str) -> Tuple[str, str]:
    """从任意形态的地址（根地址 / 带 /v1 / 完整 endpoint）提取 (服务根, host)。

    服务根只保留 scheme://host[:port]，路径交给预设拼，避免 /v1 重复或漏前缀。
    """
    raw = (raw or "").strip()
    if not raw:
        return "", ""
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    u = urlparse(raw)
    root = f"{u.scheme}://{u.netloc}"
    return root, (u.hostname or "").lower()


def detect_platform(raw_url: str) -> Dict[str, Any]:
    """按地址域名返回命中的平台预设；未命中返回 OpenAI 兼容兜底预设。"""
    _, host = _split_root(raw_url)
    for preset in PLATFORM_PRESETS:
        if any(kw in host for kw in preset["match"]):
            return preset
    return DEFAULT_PRESET


def _is_blank(v: Any) -> bool:
    return v is None or str(v).strip() == ""


def normalize_http_media(profile: Optional[dict], kind: str) -> Optional[dict]:
    """补全 generic_http 图片/视频 profile 的技术字段（幂等，不覆盖用户已填值）。

    kind: "image" / "video"。非 generic_http 或缺少地址时原样返回。
    """
    if not isinstance(profile, dict):
        return profile
    if profile.get("channel") != CH_GENERIC_HTTP:
        return profile
    if kind not in ("image", "video"):
        return profile

    p = dict(profile)
    raw = p.get("base_url") or p.get("endpoint") or p.get("submit_url") or ""
    if _is_blank(raw):
        return p  # 没有地址，交给必填校验报错，不臆造

    root, host = _split_root(raw)
    preset = detect_platform(raw)
    spec = preset.get(kind) or {}
    p.setdefault("_platform", preset["name"])  # 仅用于日志/排查，不影响请求

    if kind == "image":
        if _is_blank(p.get("endpoint")):
            p["endpoint"] = root + spec.get("path", "/v1/images/generations")
        for key in ("result_path", "size_field", "image_field"):
            if _is_blank(p.get(key)) and not _is_blank(spec.get(key)):
                p[key] = spec[key]
    else:
        if _is_blank(p.get("submit_url")):
            p["submit_url"] = root + spec.get("submit_path", "/v1/videos/generations")
        expected_poll = root + spec.get("poll_path", "/v1/videos/{task_id}")
        user_poll = str(p.get("poll_url") or "").strip()
        if _is_blank(user_poll):
            p["poll_url"] = expected_poll
        elif preset["id"] != "openai_compatible":
            # 内置平台：用户把 id 误填进 query（如硅基 POST 应放 body）时，规范化为干净的预设 URL
            if user_poll.split("?", 1)[0].rstrip("/") == expected_poll.rstrip("/"):
                p["poll_url"] = expected_poll
        for key in ("poll_method", "poll_body", "task_id_path", "status_path",
                    "success_status", "video_url_path", "image_field", "omit_fields"):
            if _is_blank(p.get(key)) and not _is_blank(spec.get(key)):
                p[key] = spec[key]

    logger.info("generic_http normalized | kind=%s | platform=%s | host=%s",
                kind, preset["name"], host)
    return p


def probe_targets(profile: Optional[dict], kind: str) -> Dict[str, str]:
    """供连通测试使用：归一化后返回该平台要打到的提交/探测地址（不实际出图）。"""
    p = normalize_http_media(profile, kind) or {}
    if kind == "image":
        return {"submit": p.get("endpoint", ""), "platform": p.get("_platform", "")}
    return {"submit": p.get("submit_url", ""), "poll": p.get("poll_url", ""),
            "platform": p.get("_platform", "")}


def probe_http_auth(profile: Optional[dict], kind: str) -> Tuple[bool, str]:
    """generic_http 连通测试：不烧钱出图，改打只读的 /v1/models 验证地址可达与 Token 是否有效。

    返回 (是否通过, 说明)。401/403 = Token 问题；连接异常 = 地址问题；
    404 = 地址可达但该平台无 models 端点，仍判地址可达。
    """
    import requests
    p = normalize_http_media(profile, kind) or {}
    raw = p.get("base_url") or p.get("endpoint") or p.get("submit_url") or ""
    root, _ = _split_root(raw)
    if not root:
        return False, "未填写服务地址"
    token = (p.get("token") or "").strip()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    platform = p.get("_platform", "")
    try:
        resp = requests.get(root + "/v1/models", headers=headers, timeout=10)
    except Exception as e:
        return False, f"地址无法连接（{platform}）：{str(e)[:120]}"
    if resp.status_code in (401, 403):
        return False, f"Token 无效或无权限 HTTP {resp.status_code}（{platform}）：{resp.text[:80]}"
    if resp.status_code == 200:
        return True, f"地址可达、Token 有效（{platform}，/v1/models 探测通过）"
    if resp.status_code == 404:
        return True, f"地址可达（{platform} 无 /v1/models 探测端点，HTTP404 正常），可直接生成验证"
    return False, f"探测异常 HTTP {resp.status_code}（{platform}）：{resp.text[:100]}"
