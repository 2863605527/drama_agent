# -*- coding: utf-8 -*-
"""敏感配置（用户 API Key / SK / Token）对称加密工具。

- 首选 cryptography.Fernet（AES-128-CBC + HMAC），密钥由 JWT_SECRET_KEY 经 SHA-256 派生，
  不引入额外密钥配置；密文以 ``enc:`` 前缀标识。
- 若运行环境未安装 cryptography，则降级为 base64 混淆（**仅防肉眼可见，不等价于加密**），
  密文以 ``b64:`` 前缀标识并打印一次告警，保证功能可用的同时不隐瞒安全级别。

这样：换 JWT_SECRET_KEY 后旧密文解不开（会返回 None，由上层回退为空配置），符合预期。
"""
import base64
import hashlib

from core.config import settings
from tools.logger_tool import get_logger

logger = get_logger("drama.crypto")

_FERNET = None
_TRIED = False
_WARNED = False


def _fernet():
    """惰性初始化 Fernet（缺失时返回 None 走降级路径）。"""
    global _FERNET, _TRIED
    if _TRIED:
        return _FERNET
    _TRIED = True
    try:
        from cryptography.fernet import Fernet
        digest = hashlib.sha256(settings.jwt_secret_key.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(digest)
        _FERNET = Fernet(key)
    except Exception as e:  # pragma: no cover - 环境缺包时的降级
        _FERNET = None
        logger.warning("cryptography 未安装，用户 Key 将以 base64 混淆存储（非强加密）：%s", e)
    return _FERNET


def encrypt_str(plain: str) -> str:
    """加密字符串；空值原样返回空串。"""
    if plain is None or plain == "":
        return ""
    plain = str(plain)
    f = _fernet()
    if f is not None:
        return "enc:" + f.encrypt(plain.encode("utf-8")).decode("ascii")
    return "b64:" + base64.b64encode(plain.encode("utf-8")).decode("ascii")


def decrypt_str(token: str) -> str:
    """解密字符串；无法识别/解密失败返回空串（上层按未配置处理）。"""
    global _WARNED
    if not token:
        return ""
    try:
        if token.startswith("enc:"):
            f = _fernet()
            if f is None:
                return ""
            return f.decrypt(token[4:].encode("ascii")).decode("utf-8")
        if token.startswith("b64:"):
            return base64.b64decode(token[4:].encode("ascii")).decode("utf-8")
        # 历史明文（理论上不会出现）：原样返回，兼容一次
        return token
    except Exception as e:
        if not _WARNED:
            logger.warning("decrypt failed (密钥可能已变更): %s", e)
            _WARNED = True
        return ""


def encrypt_config(config: dict) -> dict:
    """对配置 dict 中所有敏感字段加密（返回新 dict）。幂等：已加密(enc:/b64: 前缀)的值跳过。"""
    from schema.channel_schema import SENSITIVE_KEYS, iter_profile_dicts
    out = {}
    for kind, prof in iter_profile_dicts(config):
        if not prof:
            out[kind] = None
            continue
        p = dict(prof)
        for key in SENSITIVE_KEYS:
            v = p.get(key)
            if v and not (str(v).startswith("enc:") or str(v).startswith("b64:")):
                p[key] = encrypt_str(str(v))
        out[kind] = p
    return out


def decrypt_config(config: dict) -> dict:
    """对配置 dict 中所有敏感字段解密（返回新 dict）。"""
    from schema.channel_schema import SENSITIVE_KEYS, iter_profile_dicts
    out = {}
    for kind, prof in iter_profile_dicts(config):
        if not prof:
            out[kind] = None
            continue
        p = dict(prof)
        for key in SENSITIVE_KEYS:
            if p.get(key):
                p[key] = decrypt_str(str(p[key]))
        out[kind] = p
    return out
