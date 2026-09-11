"""资产生命周期与孤儿回收。

本地资产目录（历史扁平结构，新上传按用户分目录 u{user_id}/uploads）：
- assets/videos/  片段/分镜视频，命名 {task_id}_{segment_id|shot_id}.mp4（任务专属）
- assets/audio/   TTS 配音，命名 {task_id}_{shot_id}.mp3（任务专属）
- assets/final/   合成成片 {task_id}.mp4
- assets/images/  生成并落盘的角色/场景图，img_{uuid} 命名（可能被多集续写共享）
- assets/uploads/ 与 assets/u*/uploads/ 用户手动上传原始素材（**永不自动删除**）

安全回收原则（2026-09-10 误删事故后加固）：
1. 数据库引用集合为空时直接跳过（空库/连接失败绝不能等于"全部是孤儿"）；
2. 只回收「已在 assets 元数据表登记」且「不被任何任务引用」且「非用户上传」的文件；
3. 未在元数据表登记的磁盘文件一律保留（可能是手动放入或新功能产物），只计数不删除；
4. 元数据表中磁盘已不存在且无引用的悬空记录一并清理。
"""
import os

from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models import Asset
from db import crud
from tasks import asset_store
from tools.logger_tool import get_logger

logger = get_logger("drama.asset_gc")

_ASSETS_ROOT = asset_store.ASSETS_ROOT


async def _referenced_rel_set(db) -> set:
    """汇总所有任务仍在引用的本地资产「相对路径」集合（覆盖扁平目录与按用户分目录）。"""
    referenced: set = set()
    for row in await crud.list_all_tasks(db):
        for _url, rel, _t in asset_store.iter_typed_asset_refs(row.script_data, row.final_video_url):
            referenced.add(rel)
    return referenced


def _is_upload_path(rel: str) -> bool:
    return "uploads" in rel.split("/")


def remove_task_assets(task_id: str) -> int:
    """删除某任务前缀专属的视频/音频/成片文件（images 交给引用计数 GC，uploads 永不删）。

    返回删除文件数。元数据表残留记录由后续 gc_orphan_assets 统一清理。"""
    removed = 0
    for sub in ("videos", "audio", "final"):
        folder = os.path.join(_ASSETS_ROOT, sub)
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            # 任务专属文件均以 task_id 开头；final 成片名也带 task_id
            if name.startswith(f"{task_id}_") or task_id in name:
                try:
                    os.remove(os.path.join(folder, name))
                    removed += 1
                except OSError as e:
                    logger.warning("remove task asset failed | %s | %s", name, str(e)[:100])
    if removed:
        logger.info("remove_task_assets | task=%s | removed=%d", task_id, removed)
    return removed


async def gc_orphan_assets() -> dict:
    """安全回收孤儿资产。返回 {"removed": n, "freed_mb": x.x, "unregistered": n}。"""
    async with AsyncSessionLocal() as db:
        referenced = await _referenced_rel_set(db)

        if not referenced:
            # 引用集合为空 = 数据库为空 / 连接失败 / 引用收集失败。
            # 绝不能把"没有任何引用"当作"所有文件都是孤儿"而全删（2026-09-10 真实事故根因）。
            logger.warning("gc_orphan_assets skipped: referenced set is empty, abort to protect existing files")
            return {"removed": 0, "freed_mb": 0.0, "skipped": True}

        rows = list((await db.execute(select(Asset))).scalars().all())
        registered = {a.rel_path: a for a in rows}

        removed, freed, unregistered = 0, 0, 0
        deleted_rows = []

        # 递归遍历磁盘资产（兼容扁平目录与 u{uid}/ 分目录）
        for dirpath, _dirs, files in os.walk(_ASSETS_ROOT):
            for name in files:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, _ASSETS_ROOT).replace("\\", "/")
                if _is_upload_path(rel):
                    continue                                   # 用户上传，永不自动删
                if rel in referenced:
                    continue                                   # 仍被任务引用，保留
                asset_row = registered.get(rel)
                if asset_row is None:
                    unregistered += 1
                    continue                                   # 未登记 = 来源不明，保留不删
                if asset_row.source == "upload":
                    continue                                   # 双保险：登记为上传的也不删
                try:
                    size = os.path.getsize(full)
                    os.remove(full)
                    removed += 1
                    freed += size
                    deleted_rows.append(asset_row)
                except OSError as e:
                    logger.warning("gc orphan failed | %s | %s", rel, str(e)[:100])

        # 清理悬空元数据记录：磁盘文件已不存在、且当前无任务引用
        dangling = 0
        for rel, asset_row in registered.items():
            disk = asset_store.rel_to_disk(rel)
            if not os.path.isfile(disk) and rel not in referenced:
                await db.delete(asset_row)
                dangling += 1
        for asset_row in deleted_rows:
            try:
                await db.delete(asset_row)
            except Exception:
                pass
        await db.commit()

    freed_mb = round(freed / 1024 / 1024, 2)
    if removed or unregistered or dangling:
        logger.info("gc_orphan_assets | removed=%d | freed=%.2fMB | unregistered_kept=%d | dangling_rows=%d",
                    removed, freed_mb, unregistered, dangling)
    return {"removed": removed, "freed_mb": freed_mb,
            "unregistered": unregistered, "dangling_rows": dangling}
