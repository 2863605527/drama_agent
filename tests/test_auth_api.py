"""认证流程集成测试（注册/登录/鉴权）"""
import pytest


@pytest.mark.asyncio
class TestAuthFlow:
    async def test_register_success(self, client):
        resp = await client.post("/api/auth/register",
                                 json={"username": "newbie", "password": "pass123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"]
        assert data["username"] == "newbie"
        assert data["token_type"] == "bearer"

    async def test_duplicate_register_rejected(self, client):
        await client.post("/api/auth/register",
                          json={"username": "dup", "password": "pass123"})
        resp = await client.post("/api/auth/register",
                                 json={"username": "dup", "password": "pass123"})
        assert resp.status_code == 400
        assert "已被注册" in resp.json()["detail"]

    async def test_login_success(self, registered_user, client):
        resp = await client.post("/api/auth/login",
                                 json={"username": "alice", "password": "secret123"})
        assert resp.status_code == 200
        assert resp.json()["access_token"]

    async def test_login_wrong_password(self, registered_user, client):
        resp = await client.post("/api/auth/login",
                                 json={"username": "alice", "password": "wrong"})
        assert resp.status_code == 401

    async def test_me_with_token(self, client, auth_headers):
        resp = await client.get("/api/auth/me", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["username"] == "alice"

    async def test_me_without_token(self, client):
        resp = await client.get("/api/auth/me")
        assert resp.status_code in (401, 403)

    async def test_task_list_requires_auth(self, client):
        resp = await client.get("/api/task/list")
        assert resp.status_code in (401, 403)

    async def test_register_validation_short_password(self, client):
        resp = await client.post("/api/auth/register",
                                 json={"username": "ok", "password": "123"})
        assert resp.status_code == 422

    async def test_health(self, client):
        # SQLite 测试库下 /health 应返回 200
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
