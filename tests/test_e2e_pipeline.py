"""端到端流水线测试：step1 剧本解析 → step2 出图 → step3 进视频阶段 →
逐片段生成视频 → compose 合成完整短剧。

所有外部能力（LLM/图片/视频/TTS/ffmpeg）全部 mock 掉 mcp_client，不联网、不烧 Key、
不依赖真实 ffmpeg；文件落盘在 tmp_path，避免污染工程 assets。
"""
import os
import json
import pytest

import skill.drama_make_skill as skill_mod
from schema.drama_schema import TaskStatus

# 2 场景 × 每场景 2 镜 → 代码按场景确定性切成 2 个片段（满足合成至少 2 段）
STORYBOARD = {
    "title": "E2E测试短剧",
    "characters": [{
        "char_id": "c1", "name": "阿明",
        "description": "18岁高中男生，黑色短碎发，浓眉单眼皮，身材清瘦，穿白色短袖校服、深蓝运动裤、白色球鞋，背黑色双肩包，神情倔强。"
    }],
    "scenes": [
        {"scene_key": "教室", "description": "明亮的高中教室，整齐课桌椅，前方墨绿色黑板，午后阳光斜照，无人物"},
        {"scene_key": "天台", "description": "学校顶层天台，灰色水泥围栏，远处城市天际线，风吹云动，无人物"},
    ],
    "shots": [
        {"shot_id": "s1", "scene_key": "教室", "content": "教室午后", "camera": "中景平视", "lighting": "自然光",
         "duration": 4, "lines": "阿明：我走了", "mouth_open": True,
         "prompt": "@阿明 背起书包走出教室，中景平视", "character_names": ["阿明"]},
        {"shot_id": "s2", "scene_key": "教室", "content": "教室回望", "camera": "近景", "lighting": "自然光",
         "duration": 4, "lines": "", "mouth_open": False,
         "prompt": "@阿明 回头看了一眼黑板", "character_names": ["阿明"]},
        {"shot_id": "s3", "scene_key": "天台", "content": "天台风吹", "camera": "远景", "lighting": "逆光",
         "duration": 4, "lines": "阿明：再见啦", "mouth_open": True,
         "prompt": "@阿明 走到天台围栏边远眺", "character_names": ["阿明"]},
        {"shot_id": "s4", "scene_key": "天台", "content": "天台微笑", "camera": "特写", "lighting": "逆光",
         "duration": 4, "lines": "", "mouth_open": False,
         "prompt": "@阿明 露出释然的微笑", "character_names": ["阿明"]},
    ],
}


@pytest.fixture
def mocked_mcp(monkeypatch, tmp_path):
    """把 skill 引用的全局 mcp_client 全部替换为内存假实现；工作目录切到临时目录。"""
    monkeypatch.chdir(tmp_path)
    client = skill_mod.mcp_client
    img_counter = {"n": 0}

    async def fake_llm(messages, temperature=0.7):
        # 第一次起草、第二次结构化解析
        if "短剧编剧" in messages[0]["content"]:
            return "标题：E2E测试短剧。角色：阿明。场景：教室、天台。分镜：四个。"
        return json.dumps(STORYBOARD, ensure_ascii=False)

    async def fake_gen_image(prompt, reference_image_url=""):
        img_counter["n"] += 1
        return f"http://img.example/{img_counter['n']}.png"

    async def fake_submit_video(prompt, reference_image_url="", duration=None, ratio="9:16"):
        return "fake-task-id"

    async def fake_poll_video(task_id, timeout=300):
        return {"ok": True, "video_url": "http://cdn.example/v.mp4"}

    async def fake_download(url, save_path):
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(b"FAKE-MP4-DATA")
        return save_path

    async def fake_tts(lines, out_path, voice=None, rate=None):
        return ""  # 模拟无 TTS，走 finalize 静音轨分支

    async def fake_finalize(video_path, duration, audio_path=None, trim=None):
        return video_path

    async def fake_mix(video_path, audio_items, duration, trim=None):
        return video_path

    async def fake_compose(video_paths, output_path):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(b"FAKE-FINAL")
        return output_path

    for name, fn in [
        ("call_llm", fake_llm), ("gen_image", fake_gen_image),
        ("submit_video", fake_submit_video), ("poll_video", fake_poll_video),
        ("download_video", fake_download), ("tts_synthesize", fake_tts),
        ("finalize_video", fake_finalize), ("mix_segment_audio", fake_mix),
        ("compose_videos", fake_compose),
    ]:
        monkeypatch.setattr(client, name, fn)
    return client


@pytest.mark.asyncio
async def test_full_pipeline_step1_to_compose(mocked_mcp):
    sk = skill_mod.DramaMakeSkill()

    # S1/S2：创意 -> 剧本 -> 结构化分镜
    task = await sk.create_task("拍一个少年告别教室走向天台的短剧", "anime")
    task = await sk.step1_parse_script(task)
    assert len(task.script.characters) == 1
    assert len(task.script.scenes) == 2
    assert len(task.script.shots) == 4
    # 场景切换即切段：教室 2 镜 + 天台 2 镜 => 2 个片段
    assert len(task.script.segments) == 2
    assert all(2 <= g.duration <= 15 for g in task.script.segments)

    # S3/S4：1 角色立绘 + 2 场景×昼夜 = 5 张图
    task = await sk.step2_gen_asset(task)
    assert task.script.characters[0].reference_image.startswith("http://img.example")
    for sc in task.script.scenes:
        assert sc.day_image_url and sc.night_image_url

    # 人工审核通过，进入视频阶段
    task.status = TaskStatus.HUMAN_REVIEW
    task = await sk.step3_after_human_review(task)
    assert task.status == TaskStatus.GENERATE_VIDEO

    # S5：逐片段生成视频（内部走 MCP：submit→poll→download→finalize）
    for seg in task.script.segments:
        ok = await sk._generate_segment_video(task, seg)
        assert ok is True
        assert seg.video_url
        local = os.path.join("assets", "videos", f"{task.task_id}_{seg.segment_id}.mp4")
        assert os.path.exists(local), "片段视频应已 mock 下载落盘"
        for shot_id in seg.shot_ids:
            shot = next(s for s in task.script.shots if s.shot_id == shot_id)
            assert shot.video_url == seg.video_url  # 段内分镜共享片段视频

    # S6：合成完整短剧
    task = await sk.compose_final_video(task)
    assert task.status == TaskStatus.DONE
    assert task.final_video_url == f"/assets/final/{task.task_id}.mp4"
    assert os.path.exists(os.path.join("assets", "final", f"{task.task_id}.mp4"))


@pytest.mark.asyncio
async def test_step1_llm_failure_propagates(mocked_mcp, monkeypatch):
    """step1 的 LLM 通道彻底失败时向上抛异常（由 agent 编排层捕获并标记 FAILED）。"""
    client = skill_mod.mcp_client

    async def boom(messages, temperature=0.7):
        raise RuntimeError("llm channel down")
    monkeypatch.setattr(client, "call_llm", boom)

    sk = skill_mod.DramaMakeSkill()
    task = await sk.create_task("测试失败路径")
    with pytest.raises(RuntimeError, match="llm channel down"):
        await sk.step1_parse_script(task)
