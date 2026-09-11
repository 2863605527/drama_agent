"""越权访问防护测试（P0）：用户只能访问自己的任务"""
import pytest
import uuid

from db import crud


async def _register(client, username, password="secret123"):
    resp = await client.post("/api/auth/register",
                             json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


@pytest.mark.asyncio
class TestRegisterValidation:
    async def test_chinese_username_rejected(self, client):
        resp = await client.post("/api/auth/register", json={"username": "张三账号", "password": "abc123456"})
        assert resp.status_code == 400

    async def test_special_char_password_rejected(self, client):
        resp = await client.post("/api/auth/register", json={"username": "gooduser", "password": "abc@12345!"})
        assert resp.status_code == 400

    async def test_username_start_with_digit_rejected(self, client):
        resp = await client.post("/api/auth/register", json={"username": "1abc", "password": "abc123456"})
        assert resp.status_code == 400

    async def test_valid_register_ok(self, client):
        resp = await client.post("/api/auth/register", json={"username": "good_user1", "password": "abc123456"})
        assert resp.status_code == 200



async def _make_task(db_session_factory, user_id):
    """直接在 DB 插入一条任务，绕过真实 LLM/MCP 流水线"""
    task_id = str(uuid.uuid4())
    async with db_session_factory() as db:
        await crud.create_task(db, task_id, user_id, "测试剧本", "anime", "auto")
    return task_id


@pytest.mark.asyncio
class TestOwnership:
    async def test_owner_can_read(self, client, db_session):
        token_a = await _register(client, "owner_a")
        # 查出 owner_a 的 user_id
        async with db_session() as db:
            user = await crud.get_user_by_username(db, "owner_a")
            uid = user.id
        task_id = await _make_task(db_session, uid)
        resp = await client.get(f"/api/task/{task_id}",
                                headers={"Authorization": f"Bearer {token_a}"})
        assert resp.status_code == 200
        assert resp.json()["task_id"] == task_id

    async def test_other_user_forbidden(self, client, db_session):
        token_a = await _register(client, "owner_x")
        token_b = await _register(client, "owner_y")
        async with db_session() as db:
            user_a = await crud.get_user_by_username(db, "owner_x")
            uid_a = user_a.id
        task_id = await _make_task(db_session, uid_a)

        # B 访问 A 的任务 -> 403
        resp = await client.get(f"/api/task/{task_id}",
                                headers={"Authorization": f"Bearer {token_b}"})
        assert resp.status_code == 403

    async def test_nonexistent_task_404(self, client):
        token = await _register(client, "ghost")
        resp = await client.get(f"/api/task/{uuid.uuid4()}",
                                headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 404

    async def test_other_user_cannot_update(self, client, db_session):
        token_a = await _register(client, "script_owner")
        token_b = await _register(client, "script_attacker")
        async with db_session() as db:
            user_a = await crud.get_user_by_username(db, "script_owner")
            uid_a = user_a.id
        task_id = await _make_task(db_session, uid_a)

        resp = await client.post(
            f"/api/task/{task_id}/update_audio_mode",
            json={"audio_mode": "tts"},
            headers={"Authorization": f"Bearer {token_b}"})
        assert resp.status_code == 403

    async def test_user_list_only_own_tasks(self, client, db_session):
        token_a = await _register(client, "list_a")
        token_b = await _register(client, "list_b")
        async with db_session() as db:
            ua = (await crud.get_user_by_username(db, "list_a")).id
            ub = (await crud.get_user_by_username(db, "list_b")).id
        await _make_task(db_session, ua)
        await _make_task(db_session, ua)
        await _make_task(db_session, ub)

        resp = await client.get("/api/task/list",
                                headers={"Authorization": f"Bearer {token_a}"})
        assert resp.status_code == 200
        assert len(resp.json()) == 2  # 只能看到自己的 2 条，看不到 B 的
