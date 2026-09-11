"""资产存储登记层 tasks/asset_store.py 的单元测试。"""
import os

import pytest
from sqlalchemy import select

from db.models import User, Task, Asset
from tasks import asset_store


def test_iter_typed_refs_classifies_types():
    sd = {
        "characters": [{"reference_image": "/assets/images/c1.png"}],
        "scenes": [{"day_image_url": "/assets/images/d.png",
                    "night_image_url": "/assets/images/n.png"}],
        "shots": [{"audio_url": "/assets/audio/t_sh1.mp3",
                   "video_url": "/assets/videos/t_sh1.mp4"}],
        "segments": [{"video_url": "/assets/videos/t_g1.mp4"}],
    }
    typed = {rel: t for _u, rel, t in asset_store.iter_typed_asset_refs(
        sd, final_video_url="/assets/final/t.mp4")}
    assert typed["images/c1.png"] == "character"
    assert typed["images/d.png"] == "scene_day"
    assert typed["images/n.png"] == "scene_night"
    assert typed["audio/t_sh1.mp3"] == "shot_audio"
    assert typed["videos/t_sh1.mp4"] == "shot_video"
    assert typed["videos/t_g1.mp4"] == "segment_video"
    assert typed["final/t.mp4"] == "final_video"


def test_iter_typed_refs_ignores_remote_and_data():
    sd = {"characters": [{"reference_image": "https://x/1.png"},
                         {"reference_image": "data:image/png;base64,AAA"}]}
    out = list(asset_store.iter_typed_asset_refs(sd))
    assert out == []


def test_save_user_upload_uses_user_scoped_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(asset_store, "ASSETS_ROOT", str(tmp_path))
    url, rel = asset_store.save_user_upload(17, b"\x89PNG\r\n\x1a\nfake", ".png")
    assert url.startswith("/assets/u17/uploads/")
    assert rel.startswith("u17/uploads/") and rel.endswith(".png")
    assert os.path.isfile(asset_store.rel_to_disk(rel))


@pytest.mark.asyncio
async def test_sync_task_assets_registers_rows(db_session, monkeypatch, tmp_path):
    # 文件落在临时 assets，sync 后元数据表应登记并正确分类、识别 upload 来源
    monkeypatch.setattr(asset_store, "ASSETS_ROOT", str(tmp_path))
    img_dir = tmp_path / "images"
    img_dir.mkdir(parents=True)
    (img_dir / "c1.png").write_bytes(b"char")
    up_dir = tmp_path / "u17" / "uploads"
    up_dir.mkdir(parents=True)
    (up_dir / "up.png").write_bytes(b"up")

    async with db_session() as db:
        user = User(username="u17", password_hash="x")
        db.add(user)
        await db.flush()
        script = {
            "characters": [{"reference_image": "/assets/images/c1.png"}],
            "scenes": [], "shots": [], "segments": [],
        }
        task = Task(task_id="t1", user_id=user.id, user_prompt="p",
                    script_data=script, final_video_url=None)
        db.add(task)
        await db.flush()
        added = await asset_store.sync_task_assets(db, task)
        await db.commit()
        assert added == 1
        row = (await db.execute(select(Asset).where(Asset.url == "/assets/images/c1.png"))).scalar_one()
        assert row.asset_type == "character"
        assert row.source == "ai"
        assert row.user_id == user.id
        assert row.size_bytes == 4


@pytest.mark.asyncio
async def test_sync_is_idempotent(db_session, monkeypatch, tmp_path):
    monkeypatch.setattr(asset_store, "ASSETS_ROOT", str(tmp_path))
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "c.png").write_bytes(b"cc")
    async with db_session() as db:
        user = User(username="u18", password_hash="x")
        db.add(user)
        await db.flush()
        task = Task(task_id="t2", user_id=user.id, user_prompt="p",
                    script_data={"characters": [{"reference_image": "/assets/images/c.png"}]})
        db.add(task)
        await db.flush()
        first = await asset_store.sync_task_assets(db, task)
        await db.commit()
        second = await asset_store.sync_task_assets(db, task)
        await db.commit()
        assert first == 1 and second == 0  # 第二次不重复登记
        count = len((await db.execute(select(Asset).where(Asset.url == "/assets/images/c.png"))).scalars().all())
        assert count == 1
