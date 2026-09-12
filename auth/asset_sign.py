"""P0：/assets 媒体资源访问签名（防未授权遍历/盗链/URL 嗅探）。

- 后端在所有下发给前端的媒体 URL 上附加短时 HMAC 签名（?exp=&sig=）；
- /assets 静态路由对无签名 / 过期 / 篡改的请求返回 403；
- 存储与生成链路保持相对路径不变（参考图转 base64 不依赖签名）；
- 前端回传的 script_data 在入库前统一去签名（raw_nested_assets），防止签名 URL 污染存储。
"""
import hashlib
import hmac
import time
import urllib.parse

from core.config import settings

_ASSET_PREFIX = "/assets/"
# 签名有效期：7 天。前端页面停留 + 历史任务回看足够；超期后重新从接口拉取即可刷新
_ASSET_SIGN_TTL = 7 * 24 * 3600


def is_asset_url(s: str) -> bool:
    return isinstance(s, str) and s.startswith(_ASSET_PREFIX)


def sign_asset_path(path: str, ttl: int = _ASSET_SIGN_TTL) -> str:
    """给 /assets/... 相对路径附加签名：/assets/x.png?exp=<ts>&sig=<hmac>（已带 query 则原样返回）。"""
    if "?" in path:
        return path
    exp = int(time.time()) + ttl
    sig = hmac.new(settings.jwt_secret_key.encode("utf-8"),
                   f"{path}:{exp}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{path}?exp={exp}&sig={sig}"


def verify_asset_signature(path: str, exp: str, sig: str) -> bool:
    """校验签名：exp 必须为数字、未过期、HMAC 一致。"""
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_i < int(time.time()):
        return False
    expected = hmac.new(settings.jwt_secret_key.encode("utf-8"),
                        f"{path}:{exp_i}".encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig or "")


def sign_nested_assets(obj):
    """递归给 dict/list 中所有 /assets/ 开头的字符串 URL 附加签名（已签名/非资产 URL 原样）。"""
    if isinstance(obj, dict):
        return {k: sign_nested_assets(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sign_nested_assets(v) for v in obj]
    if is_asset_url(obj) and "?" not in obj:
        return sign_asset_path(obj)
    return obj


def raw_nested_assets(obj):
    """递归去除 /assets/ URL 上的签名 query，恢复存储用的相对路径（入参入库前调用）。"""
    if isinstance(obj, dict):
        return {k: raw_nested_assets(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [raw_nested_assets(v) for v in obj]
    if is_asset_url(obj) and "?" in obj:
        return obj.split("?", 1)[0]
    return obj


def extract_query(query_string: str) -> dict:
    """解析 /assets 请求的 query_string（如 "exp=..&sig=.."），供静态路由校验。"""
    return urllib.parse.parse_qs(query_string or "")
