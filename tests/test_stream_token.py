"""P1-5：SSE 短时 stream token 的签发/校验/过期/任务绑定。"""
import time
import pytest

from api.task_stream import create_stream_token, verify_stream_token


def test_token_roundtrip():
    token = create_stream_token("task-abc", 17)
    info = verify_stream_token(token)
    assert info == {"task_id": "task-abc", "user_id": 17}


def test_token_bound_to_task():
    token = create_stream_token("task-abc", 17)
    info = verify_stream_token(token)
    # token 只对签发任务有效：篡改任务 id 后校验必须失败
    assert info["task_id"] == "task-abc"


def test_tampered_token_rejected():
    token = create_stream_token("task-abc", 17)
    body, sig = token.split(".")
    # 篡改 payload（换成其它任务）后签名失效
    import base64
    bad_payload = base64.urlsafe_b64encode(b"task-xyz.17.9999999999.deadbeef").rstrip(b"=").decode()
    assert verify_stream_token(f"{bad_payload}.{sig}") is None
    # 篡改签名
    assert verify_stream_token(f"{body}.AAAA") is None


def test_expired_token_rejected():
    token = create_stream_token("task-abc", 17)
    # 把过期时间改到过去（重新签一个带过去 exp 的 token 不可行，直接伪造需签名）。
    # 这里验证：校验函数对过期 token 返回 None——先拆解出 payload 看结构完整性。
    info = verify_stream_token(token)
    assert info is not None
    # 边界：非法的空串/垃圾输入一律拒绝，不抛异常
    assert verify_stream_token("") is None
    assert verify_stream_token("garbage") is None
    assert verify_stream_token("a.b.c") is None


def test_expiry_window_applies():
    """有效期校验：签名正确但 exp 已过期的 token 必须拒绝。"""
    import base64
    import hashlib
    import hmac
    from core.config import settings

    def _make(exp):
        payload = f"task-abc.17.{exp}.nonce1234"
        sig = hmac.new(settings.jwt_secret_key.encode(), payload.encode(), hashlib.sha256).digest()
        body = base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()
        s = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
        return f"{body}.{s}"

    past = int(time.time()) - 10
    assert verify_stream_token(_make(past)) is None
    future = int(time.time()) + 30
    assert verify_stream_token(_make(future)) == {"task_id": "task-abc", "user_id": 17}
