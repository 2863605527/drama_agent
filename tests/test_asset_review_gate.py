# -*- coding: utf-8 -*-
"""手动逐张出图 → 进入人工审核的就绪判定测试。"""
from schema.drama_schema import (
    DramaTask, DramaScript, Character, Scene, TaskStatus,
)
from agent.drama_agent import DramaAgent


def _task(chars, scenes):
    script = DramaScript(script_id="s", title="t", raw_content="",
                         characters=chars, scenes=scenes, shots=[])
    return DramaTask(task_id="t1", thread_id="t1", user_prompt="p", style="anime",
                     status=TaskStatus.GENERATE_ASSET, script=script)


def test_not_ready_when_character_missing_image():
    t = _task([Character(char_id="c1", name="A", description="")],
              [Scene(scene_key="k", description="", day_image_url="d", night_image_url="n")])
    assert DramaAgent._all_assets_ready(t) is False


def test_not_ready_when_scene_variant_missing():
    t = _task([Character(char_id="c1", name="A", description="", reference_image="r")],
              [Scene(scene_key="k", description="", day_image_url="d")])  # 缺黑夜图
    assert DramaAgent._all_assets_ready(t) is False


def test_ready_when_all_assets_present():
    t = _task([Character(char_id="c1", name="A", description="", reference_image="r")],
              [Scene(scene_key="k", description="", day_image_url="d", night_image_url="n")])
    assert DramaAgent._all_assets_ready(t) is True


def test_not_ready_with_empty_assets():
    t = _task([], [])
    assert DramaAgent._all_assets_ready(t) is False


def test_no_fallback_after_review(monkeypatch):
    """一旦进入审核 / 视频阶段，重绘导致资产暂时不齐也不回退状态（状态只进不退）。"""
    import asyncio
    from agent.progress_hub import progress_hub as hub
    for from_status in (TaskStatus.HUMAN_REVIEW, TaskStatus.GENERATE_VIDEO):
        # 场景只有白天图、缺黑夜图
        t = _task([Character(char_id="c1", name="A", description="", reference_image="r")],
                  [Scene(scene_key="k", description="", day_image_url="d")])
        t.status = from_status
        agent = object.__new__(DramaAgent)  # 绕过 __init__ 的 DB 依赖

        async def fake_save(_): return None
        async def fake_pub(*a, **k): return None
        monkeypatch.setattr(agent, "_save_task", fake_save)
        monkeypatch.setattr(hub, "publish", fake_pub)

        asyncio.run(agent._maybe_advance_to_review(t))
        assert t.status == from_status  # 保持原状态，不退回待生成形象
