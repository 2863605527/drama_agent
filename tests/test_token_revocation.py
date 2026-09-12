"""P0：JWT token 吊销机制测试（token_version）"""
import pytest
from httpx import AsyncClient, ASGITransport

from auth.jwt import create_access_token
from auth.validators import validate_username, validate_password
from main import app


async def _register(client, name="tokprobe"):
    r = await client.post("/api/auth/register", json={"username": name, "password": "probe123456"})
    assert r.status_code == 200, r.text
    return r.json()


async def test_change_password_revokes_old_tokens(client):
    """改密码后 token_version+1，旧 token 立即失效，新登录 token 有效。"""
    data = await _register(client)
    old_token = data["access_token"]
    headers = {"Authorization": f"Bearer {old_token}"}

    # 改密前旧 token 可用
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200

    # 旧密码错误 → 拒绝
    r = await client.post("/api/auth/change-password", headers=headers,
                          json={"old_password": "wrong-pass", "new_password": "newpass123"})
    assert r.status_code == 400

    # 正确改密 → 全端吊销
    r = await client.post("/api/auth/change-password", headers=headers,
                          json={"old_password": "probe123456", "new_password": "newpass123"})
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # 旧 token 已被吊销
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 401

    # 用旧密码登录失败、新密码登录成功
    r = await client.post("/api/auth/login", json={"username": "tokprobe", "password": "probe123456"})
    assert r.status_code == 401
    r = await client.post("/api/auth/login", json={"username": "tokprobe", "password": "newpass123"})
    assert r.status_code == 200
    new_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = await client.get("/api/auth/me", headers=new_headers)
    assert r.status_code == 200


async def test_logout_all_revokes_tokens(client):
    """退出所有设备：token_version+1，已签发 token 全部失效。"""
    data = await _register(client, "tokout")
    token_a = data["access_token"]
    h = {"Authorization": f"Bearer {token_a}"}
    assert (await client.get("/api/auth/me", headers=h)).status_code == 200

    r = await client.post("/api/auth/logout-all", headers=h)
    assert r.status_code == 200

    # 旧 token 失效（含刚调用 logout-all 的这个）
    r = await client.get("/api/auth/me", headers=h)
    assert r.status_code == 401

    # 重新登录后新 token 可用
    r = await client.post("/api/auth/login", json={"username": "tokout", "password": "probe123456"})
    assert r.status_code == 200
    h2 = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await client.get("/api/auth/me", headers=h2)).status_code == 200


def test_token_version_in_payload():
    """payload 携带 ver 字段，且 decode 后一致。"""
    from auth.jwt import decode_access_token
    tok = create_access_token(1, "u", token_version=7)
    payload = decode_access_token(tok)
    assert payload["ver"] == 7
    assert payload["sub"] == "1"


def test_validators_still_ok():
    assert validate_username("abc_123") is None
    assert validate_username("中文名") is not None
    assert validate_password("pass1234") is None
    assert validate_password("pass@#$") is not None
