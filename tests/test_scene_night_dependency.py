# -*- coding: utf-8 -*-
"""场景黑夜图必须以白天图为参考（图生图）的依赖约束测试。"""
import asyncio
import schema.drama_schema as ds
import skill.drama_make_skill as sk
import tools.media_channel as mc
from schema.drama_schema import DramaTask, DramaScript, Scene, TaskStatus
from skill.drama_make_skill import DramaMakeSkill


def _task_with_scene(day=None, night=None):
    scene = Scene(scene_key="便利店", description="深夜便利店内部",
                  day_image_url=day, night_image_url=night)
    script = DramaScript(script_id="s", title="t", raw_content="",
                         characters=[], scenes=[scene], shots=[])
    return DramaTask(task_id="t1", thread_id="t1", user_prompt="p",
                     status=TaskStatus.GENERATE_ASSET, script=script), scene


def test_night_requires_day_image():
    """没有白天图时生成黑夜图必须直接报错，且不得调用生图。"""
    skill = DramaMakeSkill()
    task, _ = _task_with_scene(day=None, night=None)
    called = {"n": 0}

    async def fake_gen(prompt, reference_image_url=""):
        called["n"] += 1
        return "http://x"

    async def fake_pub(*a, **k):
        return None

    sk.mcp_client.gen_image = fake_gen
    sk.progress_hub.publish = fake_pub
    try:
        asyncio.run(skill.regenerate_scene_image(task, "便利店:night"))
        raised = None
    except Exception as e:
        raised = e
    assert raised is not None and "白天图" in str(raised)
    assert called["n"] == 0  # 缺白天图时绝不能触发生图


def test_night_uses_day_as_reference():
    """有白天图时，黑夜图必须把白天图 URL 作为参考图传入图生图。"""
    skill = DramaMakeSkill()
    task, scene = _task_with_scene(day="http://day.png", night=None)
    captured = {}

    async def fake_gen(prompt, reference_image_url=""):
        captured["ref"] = reference_image_url
        return "http://night.png"

    async def fake_pub(*a, **k):
        return None

    sk.mcp_client.gen_image = fake_gen
    sk.progress_hub.publish = fake_pub
    asyncio.run(skill.regenerate_scene_image(task, "便利店:night"))
    assert captured["ref"] == "http://day.png"
    assert scene.night_image_url == "http://night.png"


def test_generate_image_routes_to_i2i_when_ref_given(monkeypatch):
    """cv 通道：有参考图走图生图 _edit_image_cv，无参考图走文生图 _image_cv。"""
    monkeypatch.setattr(mc, "effective_image_channel", lambda profile: mc.CH_VOLC_CV)

    monkeypatch.setattr(mc, "_edit_image_cv",
                        lambda prompt, ref, w, h, profile=None: f"i2i:{ref}")
    def _t2i(*a, **k):
        raise AssertionError("有参考图时不应走文生图")
    monkeypatch.setattr(mc, "_image_cv", _t2i)
    assert mc.generate_image("p", 1024, 1024, None, "http://day.png") == "i2i:http://day.png"

    monkeypatch.setattr(mc, "_image_cv", lambda prompt, w, h, profile=None: "t2i")
    assert mc.generate_image("p", 1024, 1024, None) == "t2i"
