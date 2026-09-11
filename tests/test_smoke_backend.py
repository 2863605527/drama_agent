# -*- coding: utf-8 -*-
"""后端改造冒烟测试：导入链 / 加密脱敏 / 通道 profile 解析 / MCP 参数签名 / 门面方法齐全。"""
import inspect
import pytest


def test_main_app_importable_and_routes():
    import main
    assert type(main.app).__name__ == "FastAPI"
    # 新版 FastAPI 的 include_router 懒加载展开（app.routes 里是 _IncludedRouter 包装），
    # 改用 OpenAPI schema 统计真实接口数量（跨版本稳定）
    paths = main.app.openapi().get("paths", {})
    n_ops = sum(len(m) for m in paths.values())
    assert n_ops > 20


def test_channel_validate_mask_merge():
    from schema import channel_schema as chs
    bad = chs.validate_profile("image", {"channel": "volc_ark"})
    assert bad and "API Key" in bad[0]
    assert chs.validate_profile("image", {"channel": "volc_ark", "api_key": "k", "model": "m"}) == []

    cfg = {"llm": None,
           "image": {"channel": "volc_ark", "api_key": "sk-secret-1234", "model": "m"},
           "video": None}
    masked = chs.mask_sensitive(cfg)
    assert masked["image"]["api_key"].startswith(chs.MASK_PREFIX)

    incoming = {"llm": None,
                "image": {"channel": "volc_ark", "api_key": masked["image"]["api_key"], "model": "m2"},
                "video": None}
    merged = chs.merge_profiles(incoming, cfg)
    assert merged["image"]["api_key"] == "sk-secret-1234"  # 掩码沿用旧值
    assert merged["image"]["model"] == "m2"               # 非敏感字段更新


def test_crypto_roundtrip():
    from core import crypto
    token = crypto.encrypt_str("sk-secret-1234")
    assert token.startswith("enc:")
    assert crypto.decrypt_str(token) == "sk-secret-1234"
    cfg = {"image": {"api_key": "sk-secret-1234"}}
    ec = crypto.encrypt_config(cfg)
    assert ec["image"]["api_key"].startswith("enc:")
    assert crypto.decrypt_config(ec)["image"]["api_key"] == "sk-secret-1234"


def test_media_channel_profile_resolution():
    from tools import media_channel as mc
    assert mc.effective_image_channel(None) == mc.IMAGE_CHANNEL
    assert mc.effective_image_channel({"channel": "env"}) == mc.IMAGE_CHANNEL
    assert mc.effective_image_channel({"channel": "volc_ark"}) == "volc_ark"
    assert mc.video_has_native_audio({"channel": "volc_ark", "generate_audio": True}) is True
    assert mc.video_has_native_audio({"channel": "volc_cv"}) is False


def test_mcp_tools_have_profile_param():
    from mcp_server import llm_mcp, image_mcp, video_mcp
    assert "profile" in inspect.signature(llm_mcp.call_llm).parameters
    assert "profile" in inspect.signature(image_mcp.gen_image).parameters
    assert "profile" in inspect.signature(video_mcp.submit_video).parameters
    assert "profile" in inspect.signature(video_mcp.poll_video).parameters


def test_mcp_client_facade_methods_present():
    from mcp_client.agent_mcp_client import mcp_client, DramaMcpClient, _PersistentChannel
    assert isinstance(mcp_client, DramaMcpClient)
    for meth in ["call_llm", "gen_image", "submit_video", "poll_video", "download_video",
                 "tts_synthesize", "mix_segment_audio", "finalize_video", "compose_videos",
                 "bind_profile", "close"]:
        assert hasattr(mcp_client, meth)
    assert callable(_PersistentChannel.call) and callable(_PersistentChannel.aclose)


def test_drama_task_has_channel_profile():
    from schema.drama_schema import DramaTask, TaskStatus
    t = DramaTask(task_id="x", thread_id="x", user_prompt="p", status=TaskStatus.PENDING)
    assert t.channel_profile is None

# ==================== P0/P1 安全加固回归（2026-09-10）====================

def test_channel_meta_no_env_option():
    """前端已删除「系统默认(.env)」选项：三段元数据都不含 env，用户必须手动配置通道。"""
    from schema import channel_schema as chs
    for kind in ("llm", "image", "video"):
        vals = [c["value"] for c in chs.CHANNEL_META[kind]["channels"]]
        assert chs.CH_ENV not in vals, f"{kind} 仍含 env 选项"
        assert vals, f"{kind} 至少一个真实通道"


def test_encrypt_config_idempotent_and_decrypt_roundtrip():
    """encrypt_config 幂等（已加密不二次加密）；解密往返一致。"""
    from core import crypto
    cfg = {"llm": {"channel": "openai", "api_key": "sk-a1b2c3d4"},
           "image": {"channel": "generic_http", "token": "sk-xyz-1234", "model": "m"},
           "video": None}
    e1 = crypto.encrypt_config(cfg)
    e2 = crypto.encrypt_config(e1)          # 幂等：二次加密值不变
    assert e1 == e2
    dec = crypto.decrypt_config(e1)
    assert dec["llm"]["api_key"] == "sk-a1b2c3d4"
    assert dec["image"]["token"] == "sk-xyz-1234"


def test_drama_agent_channel_encrypt_migration_helpers():
    """任务通道快照：明文检测 -> 加密 -> 解密还原（P1-3 全链路）。"""
    from agent.drama_agent import DramaAgent
    plain = {"image": {"channel": "generic_http", "token": "sk-plain-9876", "model": "m"},
             "video": None, "llm": None}
    assert DramaAgent._has_plain_sensitive(plain) is True
    from core import crypto
    enc = crypto.encrypt_config(plain)
    assert DramaAgent._has_plain_sensitive(enc) is False
    dec = DramaAgent._decrypt_channel(enc)
    assert dec["image"]["token"] == "sk-plain-9876"
    assert DramaAgent._decrypt_channel(None) is None
    assert DramaAgent._decrypt_channel("not-a-dict") is None


def test_upload_magic_number_validation():
    """上传图片按魔数识别：PNG 真图通过；改名为 .png 的 SVG 被拒绝（防存储型 XSS）。"""
    from api.tasks import _detect_image_ext
    assert _detect_image_ext(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR") == ".png"
    assert _detect_image_ext(b"\xff\xd8\xff\xe0\x00\x10JFIF") == ".jpg"
    assert _detect_image_ext(b"RIFF\x24\x00\x00\x00WEBPVP8 ") == ".webp"
    assert _detect_image_ext(b"GIF89a\x01\x00\x01\x00") == ".gif"
    assert _detect_image_ext(b"<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>") == ""
    assert _detect_image_ext(b"MZ\x90\x00exe") == ""


@pytest.mark.asyncio
async def test_security_headers_present(client):
    """P1-5：安全响应头（CSP/nosniff/帧保护/来源策略）挂在所有响应上。
    注意：用 conftest 的 ASGITransport client（不触发 app lifespan），
    避免 TestClient 触发 startup 的孤儿资产 GC 在测试环境误删真实 assets（2026-09-10 事故根因）。"""
    r = await client.get("/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    csp = r.headers.get("content-security-policy") or ""
    assert "frame-ancestors 'none'" in csp
    assert "default-src 'self'" in csp

@pytest.mark.asyncio
async def test_retry_and_episode_follow_latest_llm_profile(db_session, monkeypatch):
    """401 修复回归：retry / 续写时 LLM 段跟随用户「当前最新」配置，
    不再继承旧快照 null 而走 .env 兜底的失效 Key（2026-09-10 鉴权失败根因）。"""
    import json
    from agent.drama_agent import DramaAgent
    from db.models import User, UserChannelConfig
    from core import crypto
    from schema.drama_schema import DramaScript, TaskStatus

    async def _noop(self, task):
        return task
    monkeypatch.setattr(DramaAgent, "_run_initial_pipeline", _noop)

    agent = DramaAgent()

    # 用户 + 用户级 LLM 配置（openai 自定义，等效真实 Key）
    async with db_session() as db:
        u = User(username="llm_fix_usr", password_hash="x")
        db.add(u); await db.commit(); await db.refresh(u)
        cfg = {"llm": {"channel": "openai", "api_url": "https://api.deepseek.com",
                       "api_key": "sk-good-key-1234", "model": "deepseek-flash"},
               "image": None, "video": None}
        db.add(UserChannelConfig(user_id=u.id, config=crypto.encrypt_config(cfg)))
        await db.commit()

    # 父任务：旧版快照 llm=null（未配置），并置为 failed 供重试
    parent = await agent.skill.create_task("父剧第一集", "anime")
    parent.user_id = u.id
    parent.channel_profile = None
    parent.status = TaskStatus.FAILED
    parent.script = DramaScript(script_id=parent.task_id, title="父剧", raw_content="测试剧情",
                                characters=[], scenes=[], shots=[])
    await agent._save_task(parent)

    # 1) 续写：新一集 llm 段跟随用户最新配置，且归属同系列
    ep = await agent.submit_new_task("续集走向", parent_id=parent.task_id, user_id=u.id)
    assert (ep.channel_profile or {}).get("llm", {}).get("api_key") == "sk-good-key-1234"
    assert ep.parent_id == parent.task_id
    assert ep.episode_no == 2

    # 2) retry：重跑后 llm 段应为用户最新配置（先续写再重试，避免重试清空父剧本影响续写）
    retried = await agent.retry_task(parent.task_id)
    assert (retried.channel_profile or {}).get("llm", {}).get("api_key") == "sk-good-key-1234"

@pytest.mark.asyncio
async def test_retry_episode_rebuilds_inherit_context(db_session, monkeypatch):
    """续集 retry 后重建 inherit_context（带父集角色立绘/场景昼夜图），
    不再退化为「全新剧本」、上一集资产全部丢失（2026-09-10 第二集资产丢失根因）。"""
    from agent.drama_agent import DramaAgent
    from db.models import User
    from schema.drama_schema import DramaScript, TaskStatus, Character, Scene

    async def _noop(self, task):
        return task
    monkeypatch.setattr(DramaAgent, "_run_initial_pipeline", _noop)
    agent = DramaAgent()

    async with db_session() as db:
        u = User(username="inh_fix_usr", password_hash="x")
        db.add(u); await db.commit(); await db.refresh(u)

    # 父任务：有角色立绘 + 场景昼夜图
    parent = await agent.skill.create_task("父剧", "anime")
    parent.user_id = u.id
    parent.status = TaskStatus.DONE
    parent.script = DramaScript(
        script_id=parent.task_id, title="父剧", raw_content="前情",
        characters=[Character(char_id="c1", name="雨姐", description="红裙",
                              reference_image="/assets/images/p1.png")],
        scenes=[Scene(scene_key="老城窄巷口", description="老城",
                      day_image_url="/assets/images/d1.png",
                      night_image_url="/assets/images/n1.png")],
        shots=[])
    await agent._save_task(parent)

    # 子任务（第二集）：inherit_context 不落库，从 DB 重建后必然为空（模拟 retry 场景）
    child = await agent.skill.create_task("第二集剧情", "anime")
    child.user_id = u.id
    child.parent_id = parent.task_id
    child.episode_no = 2
    child.series_title = "父剧"
    child.status = TaskStatus.FAILED
    child.script = None
    await agent._save_task(child)

    retried = await agent.retry_task(child.task_id)
    inh = retried.inherit_context or {}
    chars = inh.get("characters") or []
    scenes = inh.get("scenes") or []
    assert len(chars) == 1 and chars[0]["name"] == "雨姐"
    assert chars[0]["reference_image"] == "/assets/images/p1.png"
    assert len(scenes) == 1 and scenes[0]["scene_key"] == "老城窄巷口"
    assert scenes[0]["day_image_url"] == "/assets/images/d1.png"
    assert scenes[0]["night_image_url"] == "/assets/images/n1.png"
    assert inh.get("episode_no") == 2

@pytest.mark.asyncio
async def test_step1_inherit_fills_assets_from_parent(db_session, monkeypatch):
    """续写解析：inherit_context 里的父集角色立绘/场景昼夜图按名字/场景键回填到新剧本。
    覆盖真实第二集 bug：解析后雨姐立绘必须非空、旧场景图必须带入。"""
    from agent.drama_agent import DramaAgent
    from db.models import User
    from schema.drama_schema import DramaScript, TaskStatus, Character, Scene
    from skill.drama_make_skill import DramaMakeSkill

    async def _noop(self, task):
        return task
    monkeypatch.setattr(DramaAgent, "_run_initial_pipeline", _noop)
    agent = DramaAgent()

    # 父任务资产
    parent = await agent.skill.create_task("父剧", "anime")
    parent.script = DramaScript(
        script_id=parent.task_id, title="父剧", raw_content="前情",
        characters=[Character(char_id="c1", name="雨姐", description="红裙女子",
                              reference_image="/assets/images/yujie.png")],
        scenes=[Scene(scene_key="老城窄巷口", description="老城窄巷",
                      day_image_url="/assets/images/old_day.png",
                      night_image_url="/assets/images/old_night.png")],
        shots=[])

    child = await agent.skill.create_task("第二集", "anime")
    child.episode_no = 2
    child.series_title = "父剧"
    child.inherit_context = await agent._build_inherit_context(parent, 2, "父剧")

    # mock LLM：第一调用返回草稿，第二次返回结构化 JSON（雨姐名字一字不差 + 沿用老城窄巷口）
    draft = "第二集剧本：雨姐在老城窄巷口重逢。"
    parsed_json = {
        "title": "父剧第二集",
        "characters": [{"char_id": "c1", "name": "雨姐", "description": "红裙女子，长发，二十多岁"}],
        "scenes": [{"scene_key": "老城窄巷口", "description": "老城窄巷，青石板路"}],
        "shots": [{
            "shot_id": "s1", "scene_key": "老城窄巷口", "content": "雨姐走过窄巷",
            "camera": "中景", "lighting": "冷调自然光", "duration": 4, "lines": "", "mouth_open": False,
            "character_names": ["雨姐"],
            "prompt": "@雨姐 从巷口缓步走来，中景平视"
        }]
    }
    import json as _json
    async def fake_llm(self, messages):
        content = messages[0]["content"] if isinstance(messages, list) else messages
        if "把下面剧本解析为严格 JSON" in str(content):
            return _json.dumps(parsed_json, ensure_ascii=False)
        return draft
    monkeypatch.setattr(DramaMakeSkill, "_llm", fake_llm)

    done = await agent.skill.step1_parse_script(child)
    yj = next(c for c in done.script.characters if c.name == "雨姐")
    assert yj.reference_image == "/assets/images/yujie.png"
    assert yj.inherited is True
    sc = next(s for s in done.script.scenes if s.scene_key == "老城窄巷口")
    assert sc.day_image_url == "/assets/images/old_day.png"
    assert sc.night_image_url == "/assets/images/old_night.png"
    assert sc.inherited is True
