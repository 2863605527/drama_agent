# -*- coding: utf-8 -*-
"""本轮健壮性增强测试：剧本自检断点、图片 URL 合法性、参考图列表、孤儿资产回收。"""
import asyncio
import os

import schema.drama_schema as ds
from schema.drama_schema import Character, Scene, Shot, Segment, DramaScript
from skill.drama_make_skill import DramaMakeSkill
from mcp_client.agent_mcp_client import DramaMcpClient
import tools.media_channel as mc
import tasks.asset_gc as agc


def _script(characters=None, scenes=None, shots=None, segments=None):
    return DramaScript(
        script_id="s1", title="t", raw_content="",
        characters=characters or [], scenes=scenes or [],
        shots=shots or [], segments=segments or [],
    )


def _shot(shot_id="sh1", scene_key="家", names=None, duration=4):
    return Shot(shot_id=shot_id, content="家内", camera="中景", lighting="暖光",
                prompt="p", character_names=names or [], duration=duration, scene_key=scene_key)


# ---------------- 需求1：剧本自检 ----------------
def test_self_check_clean_script_no_error():
    ch = Character(char_id="c1", name="林夏", description="d")
    sc = Scene(scene_key="家", description="室内")
    seg = Segment(segment_id="g1", shot_ids=["sh1"], duration=4, scene_key="家")
    script = _script([ch], [sc], [_shot(names=["林夏"])], [seg])
    errors, warnings = DramaMakeSkill._self_check_script(script)
    assert errors == []
    assert warnings == []  # 角色被引用、场景被使用，无孤立提示


def test_self_check_drops_undefined_character_ref():
    ch = Character(char_id="c1", name="林夏", description="d")
    sc = Scene(scene_key="家", description="室内")
    seg = Segment(segment_id="g1", shot_ids=["sh1"], duration=4, scene_key="家")
    shot = _shot(names=["林夏", "不存在的人"])
    script = _script([ch], [sc], [shot], [seg])
    errors, warnings = DramaMakeSkill._self_check_script(script)
    assert errors == []
    assert any("未定义角色" in w for w in warnings)
    assert shot.character_names == ["林夏"]  # 悬空引用被自动剔除


def test_self_check_empty_structure_blocks():
    """空角色/场景/分镜/片段必须报硬错误，在烧钱前拦下。"""
    errors, _ = DramaMakeSkill._self_check_script(_script())
    assert errors  # 结构性硬错误非空


def test_self_check_segment_missing_shot_is_error():
    seg = Segment(segment_id="g1", shot_ids=["ghost"], duration=0, scene_key="家")
    script = _script(segments=[seg])
    errors, _ = DramaMakeSkill._self_check_script(script)
    assert any("不存在的分镜" in e for e in errors)
    assert any("时长为 0" in e for e in errors)


# ---------------- 需求5：图片返回值必须是合法 URL ----------------
def test_require_img_url_accepts_valid():
    for u in ["http://a/x.png", "https://a/x", "data:image/png;base64,ZZ", "/assets/images/x.png"]:
        assert DramaMcpClient._require_img_url(u) == u.strip()


def test_require_img_url_rejects_error_text():
    bad = "Error executing tool gen_image: code=50400 Access Denied"
    try:
        DramaMcpClient._require_img_url(bad)
        assert False, "错误文本必须被拦截，不能当图片 URL"
    except RuntimeError as e:
        assert "有效图片地址" in str(e)


# ---------------- 需求6：参考图列表归一化 ----------------
def test_ref_list_normalizes():
    assert mc._ref_list(None) == []
    assert mc._ref_list("http://a") == ["http://a"]
    assert mc._ref_list(["http://a", "", "http://b"]) == ["http://a", "http://b"]
    assert mc._ref_list(("x", None)) == ["x"]


# ---------------- 需求4：孤儿资产回收 ----------------
class _Row:
    def __init__(self, script_data=None, final_video_url=None):
        self.script_data = script_data
        self.final_video_url = final_video_url


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def test_iter_asset_refs_extracts_local_paths():
    from tasks import asset_store
    sd = {
        "characters": [{"reference_image": "/assets/images/c1.png"}],
        "scenes": [{"day_image_url": "https://remote/x.png",
                    "night_image_url": "/assets/images/s1n.png"}],
        "shots": [{"video_url": "/assets/videos/t1_g1.mp4"}],
        "segments": [{"video_url": "/assets/videos/t1_g1.mp4"}],
    }
    refs = {rel for _u, rel, _t in asset_store.iter_typed_asset_refs(sd)}
    assert "images/c1.png" in refs
    assert "images/s1n.png" in refs
    assert "videos/t1_g1.mp4" in refs
    assert not any(r.startswith("http") for r in refs)  # 远程 URL 不算本地资产


class _AssetRow:
    """模拟 assets 元数据表一行。"""
    def __init__(self, rel_path, source="ai"):
        self.rel_path = rel_path
        self.source = source
        self.url = "/assets/" + rel_path


class _GCSession:
    """支持 select(Asset) / delete / commit 的最小异步会话。"""
    def __init__(self, assets):
        self.assets = list(assets)
        self.deleted = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, _stmt):
        class _R:
            def __init__(self, rows):
                self._rows = rows

            def scalars(self_inner):
                class _S:
                    def all(self_s):
                        return list(self.assets)
                return _S()
        return _R(self.assets)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        pass


def _patch_gc_env(monkeypatch, tmp_path, task_rows, registered_assets):
    """把 GC 的资产根、DB 会话与任务列表都指向临时环境。返回捕获会话的容器。"""
    monkeypatch.setattr(agc, "_ASSETS_ROOT", str(tmp_path))
    monkeypatch.setattr(agc.asset_store, "ASSETS_ROOT", str(tmp_path))
    holder = {}

    def _open_session():
        holder["session"] = _GCSession(registered_assets)
        return holder["session"]

    monkeypatch.setattr(agc, "AsyncSessionLocal", _open_session)

    async def fake_all(_db):
        return task_rows

    monkeypatch.setattr(agc.crud, "list_all_tasks", fake_all)
    return holder


def test_gc_orphan_removes_unreferenced(monkeypatch, tmp_path):
    # 已登记的孤儿删；被任务引用的保留
    for sub in ("videos", "images"):
        os.makedirs(tmp_path / sub, exist_ok=True)
    keep = tmp_path / "videos" / "keep.mp4"
    orphan = tmp_path / "images" / "orphan.png"
    keep.write_bytes(b"keep")
    orphan.write_bytes(b"orphan")

    row = _Row(script_data={"segments": [{"video_url": "/assets/videos/keep.mp4"}]})
    registered = [_AssetRow("images/orphan.png", source="ai")]  # 孤儿已登记
    _patch_gc_env(monkeypatch, tmp_path, [row], registered)

    res = asyncio.run(agc.gc_orphan_assets())
    assert os.path.exists(keep)          # 被引用的保留
    assert not os.path.exists(orphan)    # 已登记且无引用的孤儿删除
    assert res["removed"] == 1


def test_gc_unregistered_file_is_kept(monkeypatch, tmp_path):
    # 未在元数据表登记的文件，即使无引用也绝不删（2026-09-10 事故的核心防线）
    os.makedirs(tmp_path / "images", exist_ok=True)
    os.makedirs(tmp_path / "videos", exist_ok=True)
    keep = tmp_path / "videos" / "keep.mp4"
    mystery = tmp_path / "images" / "mystery.png"
    keep.write_bytes(b"keep")
    mystery.write_bytes(b"x")
    # 一个被任务引用的文件保证引用集合非空；mystery 未登记
    row = _Row(script_data={"segments": [{"video_url": "/assets/videos/keep.mp4"}]})
    _patch_gc_env(monkeypatch, tmp_path, [row], [])  # 白名单为空

    res = asyncio.run(agc.gc_orphan_assets())
    assert os.path.exists(mystery)                  # 未登记 = 来源不明，保留
    assert os.path.exists(keep)                     # 被引用的保留
    assert res["removed"] == 0
    assert res["unregistered"] == 1


def test_gc_upload_never_removed(monkeypatch, tmp_path):
    # 用户上传目录（扁平 uploads 与按用户分目录 u3/uploads）即使无任务引用也不删
    up1 = tmp_path / "uploads"
    up2 = tmp_path / "u3" / "uploads"
    vd = tmp_path / "videos"
    os.makedirs(up1, exist_ok=True)
    os.makedirs(up2, exist_ok=True)
    os.makedirs(vd, exist_ok=True)
    f1, f2 = up1 / "a.png", up2 / "b.png"
    keep = vd / "keep.mp4"
    f1.write_bytes(b"a")
    f2.write_bytes(b"b")
    keep.write_bytes(b"keep")
    row = _Row(script_data={"segments": [{"video_url": "/assets/videos/keep.mp4"}]})
    _patch_gc_env(monkeypatch, tmp_path, [row], [])

    res = asyncio.run(agc.gc_orphan_assets())
    assert os.path.exists(f1) and os.path.exists(f2)
    assert res["removed"] == 0


def test_gc_empty_reference_set_skips(monkeypatch, tmp_path):
    # 引用集合为空（空库/连接失败）时整体跳过，绝不删文件
    os.makedirs(tmp_path / "images", exist_ok=True)
    f = tmp_path / "images" / "x.png"
    f.write_bytes(b"x")
    holder = _patch_gc_env(monkeypatch, tmp_path, [], [_AssetRow("images/x.png")])

    res = asyncio.run(agc.gc_orphan_assets())
    assert os.path.exists(f)
    assert res.get("skipped") is True
    assert res["removed"] == 0


def test_remove_task_assets_only_prefix(monkeypatch, tmp_path):
    for sub in ("videos", "audio"):
        os.makedirs(tmp_path / sub, exist_ok=True)
    mine = tmp_path / "videos" / "TASKA_g1.mp4"
    other = tmp_path / "videos" / "TASKB_g1.mp4"
    mine.write_bytes(b"1")
    other.write_bytes(b"2")
    monkeypatch.setattr(agc, "_ASSETS_ROOT", str(tmp_path))
    n = agc.remove_task_assets("TASKA")
    assert n == 1
    assert not os.path.exists(mine)
    assert os.path.exists(other)
