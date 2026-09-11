# -*- coding: utf-8 -*-
"""用户级「模型通道」配置模型与元数据。

设计目标
--------
1. 通道/模型/Key 不再只能写死在 .env：登录用户可在前端「个人信息 → 通道配置」里
   为 LLM / 图片 / 视频分别选择通道（系统默认 / 火山即梦 CV / 火山方舟 ARK / 通用 HTTP）
   并填写自己的模型名与 Key。
2. 配置落库时敏感字段（Key / SK / Token）由 core.crypto 对称加密；接口读出时只回掩码，
   前端原样提交掩码时后端保留旧值，避免明文在网络/页面长期暴露。
3. 任务提交时把当时的配置**快照**到任务行（tasks.channel_config），任务执行全程使用快照，
   用户事后修改配置不会影响已经在跑的任务（可复现）。

channel 取值约定："env" 或空 = 沿用服务端 .env 全局默认；其余为用户显式选择的通道。
"""
from typing import Optional, List
from pydantic import BaseModel, Field

# ---------------- 通道取值常量 ----------------
CH_ENV = "env"                  # 沿用服务端 .env 默认
CH_VOLC_CV = "volc_cv"          # 火山即梦视觉服务（AK/SK + req_key）
CH_VOLC_ARK = "volc_ark"        # 火山方舟（Bearer Key + model 名）
CH_GENERIC_HTTP = "generic_http"  # 通用 OpenAI 风格 / 第三方 HTTP
CH_LLM_OPENAI = "openai"        # LLM 的 OpenAI 兼容通道

MEDIA_CHANNELS = [CH_VOLC_CV, CH_VOLC_ARK, CH_GENERIC_HTTP]

# 敏感字段集合：落库加密、读出掩码
SENSITIVE_KEYS = {
    "api_key", "access_key", "secret_key", "token",
}

# 掩码前缀：前端未修改该字段时原样回传，后端据此保留库中旧值
MASK_PREFIX = "__MASKED__"


class LLMChannelProfile(BaseModel):
    """大模型通道配置。channel=env 时全部字段可为空（走 .env）。"""
    channel: str = CH_ENV
    api_url: Optional[str] = None       # OpenAI 兼容基地址，如 https://api.deepseek.com
    api_key: Optional[str] = None       # Bearer Key（敏感，加密存储）
    model: Optional[str] = None         # 模型名，如 deepseek-chat
    temperature: Optional[float] = None


class MediaChannelProfile(BaseModel):
    """图片 / 视频通道配置（两类共用同一结构，按 channel 取需要的字段）。"""
    channel: str = CH_ENV

    # —— 火山即梦 CV 通道 ——
    access_key: Optional[str] = None    # VOLC AccessKey（敏感）
    secret_key: Optional[str] = None    # VOLC SecretKey（敏感）
    req_key: Optional[str] = None       # CV 模型 req_key（图片/视频各自的模型标识）
    resolution: Optional[str] = None    # 视频分辨率（CV/ARK 通用）：720p/1080p

    # —— 火山方舟 ARK 通道 ——
    api_url: Optional[str] = None       # 方舟基地址，默认 https://ark.cn-beijing.volces.com/api/v3
    api_key: Optional[str] = None       # volc-sk-xxx（敏感）
    model: Optional[str] = None         # 方舟模型 ID（Seedream/Seedance）
    ratio: Optional[str] = None         # 视频宽高比 9:16/16:9 ...
    generate_audio: Optional[bool] = None  # 方舟视频是否原生生成音频

    # —— 通用 HTTP 通道 ——
    base_url: Optional[str] = None         # 第三方服务根地址（如 https://api.siliconflow.cn），后端按平台自动拼路径
    endpoint: Optional[str] = None          # 图片：提交 URL（高级，一般留空由 base_url 自动推导）
    submit_url: Optional[str] = None        # 视频：提交 URL（高级，一般留空由 base_url 自动推导）
    poll_url: Optional[str] = None          # 视频：轮询 URL（支持 {task_id} 占位）
    token: Optional[str] = None             # Bearer Token（敏感）
    result_path: Optional[str] = None       # 图片结果 JSON 路径
    task_id_path: Optional[str] = None
    status_path: Optional[str] = None
    success_status: Optional[str] = None
    video_url_path: Optional[str] = None
    poll_method: Optional[str] = None       # 视频轮询方式：get（默认）/ post
    poll_body: Optional[str] = None         # POST 轮询请求体 JSON 模板，支持 {task_id} 占位
    extra_fields: Optional[str] = None      # 提交附加字段 JSON（如 {"image_size": "1280x720"}）
    image_field: Optional[str] = None       # 参考图字段名（默认 image_url；硅基流动用 image）
    image_mode: Optional[str] = None        # 参考图格式：url（默认）/ base64（本地图转 data URL）
    size_field: Optional[str] = None        # 图片单一尺寸字段名（硅基 image_size、OpenAI size）；空则发 width/height
    omit_fields: Optional[str] = None       # 提交时剔除的默认字段，逗号分隔（如 duration）


class ChannelConfig(BaseModel):
    """一个用户的完整通道配置（LLM / 图片 / 视频三段）。"""
    llm: Optional[LLMChannelProfile] = None
    image: Optional[MediaChannelProfile] = None
    video: Optional[MediaChannelProfile] = None


class ChannelConfigPayload(BaseModel):
    """PUT /api/user/channel-config 请求体。"""
    llm: Optional[LLMChannelProfile] = None
    image: Optional[MediaChannelProfile] = None
    video: Optional[MediaChannelProfile] = None


class ChannelTestRequest(BaseModel):
    """通道连通性测试请求（只实际调用 LLM，媒体通道只校验凭据完整性，不烧钱出图/出片）。"""
    kind: str = Field("llm", description="llm / image / video")
    profile: Optional[dict] = None


# ==================== 前端渲染用元数据（通道选项 + 模型预设） ====================

CHANNEL_META = {
    "llm": {
        "label": "大模型（剧本 / 分镜解析）",
        "channels": [
            {"value": CH_LLM_OPENAI, "label": "OpenAI 兼容接口（自定义地址 / Key / 模型）",
             "need_fields": ["api_url", "api_key", "model"]},
        ],
        "model_suggestions": [
            "deepseek-chat", "deepseek-reasoner",
            "moonshot-v1-8k", "qwen-plus", "gpt-4o-mini",
        ],
    },
    "image": {
        "label": "图片通道（角色立绘 / 场景图）",
        "channels": [
            {"value": CH_VOLC_CV, "label": "火山即梦 CV（视觉服务 AK/SK + req_key）",
             "need_fields": ["access_key", "secret_key", "req_key"]},
            {"value": CH_VOLC_ARK, "label": "火山方舟 ARK（Bearer Key + 模型 ID）",
             "need_fields": ["api_key", "model"]},
            {"value": CH_GENERIC_HTTP, "label": "通用 HTTP（第三方兼容接口，只需地址/Key/模型，平台自动识别）",
             "need_fields": ["base_url", "token", "model"]},
        ],
        "models": {
            CH_VOLC_CV: [
                {"value": "jimeng_high_aes_general_v21_L", "label": "即梦通用 2.1（高清）"},
                {"value": "jimeng_high_aes_general_v20_L", "label": "即梦通用 2.0"},
                {"value": "jimeng_t2i_v30", "label": "即梦文生图 3.0"},
            ],
            CH_VOLC_ARK: [
                {"value": "doubao-seedream-5-0-260128", "label": "Seedream 5.0"},
                {"value": "doubao-seedream-4-0-250828", "label": "Seedream 4.0"},
                {"value": "doubao-seedream-3-0-t2i-250415", "label": "Seedream 3.0"},
            ],
        },
    },
    "video": {
        "label": "视频通道（片段视频生成）",
        "channels": [
            {"value": CH_VOLC_CV, "label": "火山即梦 CV（视觉服务 AK/SK + req_key）",
             "need_fields": ["access_key", "secret_key", "req_key"]},
            {"value": CH_VOLC_ARK, "label": "火山方舟 ARK（Seedance，支持原生音频）",
             "need_fields": ["api_key", "model"]},
            {"value": CH_GENERIC_HTTP, "label": "通用 HTTP（第三方兼容接口，只需地址/Key/模型，平台自动识别）",
             "need_fields": ["base_url", "token", "model"]},
        ],
        "models": {
            CH_VOLC_CV: [
                {"value": "jimeng_t2v_v30", "label": "即梦文生视频 3.0"},
                {"value": "jimeng_t2v_v20", "label": "即梦文生视频 2.0"},
                {"value": "jimeng_i2v_v21", "label": "即梦图生视频 2.1"},
            ],
            CH_VOLC_ARK: [
                {"value": "doubao-seedance-2-0-260128", "label": "Seedance 2.0 标准版"},
                {"value": "doubao-seedance-2-0-fast-260128", "label": "Seedance 2.0 快速版"},
                {"value": "doubao-seedance-1-5-pro-250428", "label": "Seedance 1.5 Pro"},
            ],
        },
        "resolutions": ["480p", "720p", "1080p", "4k"],
        "ratios": ["16:9", "9:16", "4:3", "1:1", "3:4", "21:9", "adaptive"],
    },
}


# ==================== 配置处理工具函数 ====================

def iter_profile_dicts(config: Optional[dict]):
    """遍历 config 中三段 profile dict，yield (kind, profile_dict|None)。"""
    config = config or {}
    for kind in ("llm", "image", "video"):
        yield kind, config.get(kind)


def is_custom(profile: Optional[dict]) -> bool:
    """该段是否为用户自定义通道（而非沿用 .env 默认）。"""
    return bool(profile) and profile.get("channel") not in (None, "", CH_ENV)


def mask_sensitive(config: Optional[dict]) -> Optional[dict]:
    """读出配置时对敏感字段打码：已配置 → __MASKED__+后4位；未配置 → 空串。"""
    if not config:
        return None
    out = {}
    for kind, prof in iter_profile_dicts(config):
        if not prof:
            out[kind] = None
            continue
        p = dict(prof)
        for key in SENSITIVE_KEYS:
            val = p.get(key)
            if val:
                tail = str(val)[-4:] if len(str(val)) >= 4 else "****"
                p[key] = f"{MASK_PREFIX}{tail}"
            else:
                p[key] = ""
        out[kind] = p
    return out


def merge_profiles(incoming: Optional[dict], stored: Optional[dict]) -> dict:
    """保存时合并：提交值为掩码（未改动）或空串时沿用库中已解密的旧值。"""
    merged = {}
    for kind, new_p in iter_profile_dicts(incoming):
        old_p = (stored or {}).get(kind) or {}
        if not new_p:
            merged[kind] = old_p or None
            continue
        p = dict(new_p)
        for key in SENSITIVE_KEYS:
            val = p.get(key)
            if val is None or str(val) == "" or str(val).startswith(MASK_PREFIX):
                # 前端没填新值 / 没动掩码 → 保留旧值
                p[key] = old_p.get(key)
        merged[kind] = p
    return merged


def deactivate_empty_segments(config: Optional[dict]) -> dict:
    """选了自定义通道、但该通道必填项【全部为空】的段，视为用户并未真正启用，自动降级为系统默认，
    避免「只配置了图片、视频段残留 generic_http 空壳」时保存被另一段的必填校验卡住。
    注意：填了任意一个必填项却没填全的段仍保留并在校验阶段如实报错。"""
    out = dict(config or {})
    for kind in ("llm", "image", "video"):
        p = out.get(kind)
        if not is_custom(p):
            continue
        meta = CHANNEL_META.get(kind, {})
        cdef = next((c for c in meta.get("channels", []) if c["value"] == p.get("channel")), None)
        need = (cdef or {}).get("need_fields", [])
        if need and not any(str(p.get(f) or "").strip() for f in need):
            p = dict(p)
            p["channel"] = CH_ENV
            out[kind] = p
    return out


def validate_profile(kind: str, profile: Optional[dict]) -> List[str]:
    """校验某段配置的必填字段，返回缺失项中文说明列表（空列表=通过）。"""
    if not is_custom(profile):
        return []
    channel = profile.get("channel")
    problems = []
    meta = CHANNEL_META.get(kind, {})
    channel_def = next((c for c in meta.get("channels", []) if c["value"] == channel), None)
    if channel_def is None:
        return [f"{meta.get('label', kind)}：不支持的通道类型 {channel}"]
    labels = {
        "api_url": "接口地址", "api_key": "API Key", "model": "模型",
        "access_key": "AccessKey", "secret_key": "SecretKey", "req_key": "模型 req_key",
        "base_url": "服务地址", "endpoint": "接口地址", "submit_url": "提交地址", "poll_url": "轮询地址",
        "token": "Token", "result_path": "结果路径",
    }
    for f in channel_def.get("need_fields", []):
        if not str(profile.get(f) or "").strip():
            problems.append(f"{channel_def['label'].split('（')[0]}：缺少必填项「{labels.get(f, f)}」")
    return problems
