"""资产存储登记层（个人资产元数据中心）。

设计原则：
- 文件本体存磁盘 assets/（未来可平滑替换为 MinIO/OSS 对象存储，业务层只认 /assets URL）；
- 数据库 assets 表只登记元数据（归属用户、类型、来源、体积、引用数），不存二进制；
- 登记全部幂等（按 url 唯一），任何登记失败都只告警、不阻断主业务；
- 兼容历史扁平目录（images/videos/audio/final/uploads），新上传按用户分目录 u{user_id}/uploads。

对外主要接口：
- sync_task_assets(db, row)：任务落库时把其 script_data/final 里引用到的本地资产登记进表（不 commit）；
- backfill_all_assets()：启动时全量回填存量任务资产（不移动任何文件）；
- rebuild_ref_counts()：扫描全部任务，重算每个资产的引用次数；
- save_user_upload(user_id, content, ext)：用户上传落盘（按用户分目录）并返回 URL。
"""
import hashlib
import os
import uuid

from sqlalchemy import select

from db.database import AsyncSessionLocal
from db.models import Asset
from tools.logger_tool import get_logger

logger = get_logger("drama.asset_store")

ASSETS_ROOT = "assets"
_URL_PREFIX = "/assets/"
# 计算哈希的体积上限：超过则只登记体积、不算 sha256（避免大视频拖慢启动/落库）
_HASH_MAX_BYTES = 20 * 1024 * 1024

_EXT_MIME = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    ".mp4": "video/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav",
}


def is_local_asset_url(url) -> bool:
    """是否为本服务托管的 /assets 本地资产（远程 http、data:、空值都不是）。"""
    return isinstance(url, str) and url.startswith(_URL_PREFIX)


def url_to_rel(url: str) -> str:
    """/assets/images/a.png -> images/a.png（规整为正斜杠）。"""
    rel = url[len(_URL_PREFIX):] if url.startswith(_URL_PREFIX) else url
    return rel.replace("\\", "/").lstrip("/")


def rel_to_url(rel: str) -> str:
    return _URL_PREFIX + rel.replace("\\", "/")


def rel_to_disk(rel: str) -> str:
    return os.path.join(ASSETS_ROOT, *rel.replace("\\", "/").split("/"))


def _asset_type_from_rel(rel: str) -> str:
    """按目录粗分类型（精确类型在遍历任务字段时给出，这里兜底）。"""
    parts = rel.split("/")
    sub = parts[1] if len(parts) > 1 and parts[0].startswith("u") else parts[0]
    return {
        "uploads": "upload", "images": "image", "videos": "segment_video",
        "audio": "shot_audio", "final": "final_video",
    }.get(sub, "unknown")


def _is_upload_rel(rel: str) -> bool:
    parts = rel.split("/")
    return "uploads" in parts


def _file_meta(rel: str):
    """返回 (size_bytes, sha256, mime)；文件不存在时返回 (None, None, None)。"""
    disk = rel_to_disk(rel)
    if not os.path.isfile(disk):
        return None, None, None
    size = os.path.getsize(disk)
    ext = os.path.splitext(rel)[1].lower()
    mime = _EXT_MIME.get(ext)
    sha = None
    if size <= _HASH_MAX_BYTES:
        try:
            h = hashlib.sha256()
            with open(disk, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            sha = h.hexdigest()
        except OSError:
            sha = None
    return size, sha, mime


def iter_typed_asset_refs(script_data: dict, final_video_url=None):
    """遍历一份 script_data + final URL，产出 (url, rel, asset_type)。

    只产出本地 /assets 引用；远程链接忽略（未落盘，不登记）。
    """
    def emit(url, atype):
        if is_local_asset_url(url):
            yield url, url_to_rel(url), atype

    if isinstance(script_data, dict):
        for ch in (script_data.get("characters") or []):
            if isinstance(ch, dict):
                yield from emit(ch.get("reference_image"), "character")
        for sc in (script_data.get("scenes") or []):
            if isinstance(sc, dict):
                yield from emit(sc.get("day_image_url"), "scene_day")
                yield from emit(sc.get("night_image_url"), "scene_night")
        for shot in (script_data.get("shots") or []):
            if isinstance(shot, dict):
                # 分镜可能有独立配音与视频
                for key, atype in (("audio_url", "shot_audio"), ("video_url", "shot_video")):
                    yield from emit(shot.get(key), atype)
        for seg in (script_data.get("segments") or []):
            if isinstance(seg, dict):
                yield from emit(seg.get("video_url"), "segment_video")
    yield from emit(final_video_url, "final_video")


async def _upsert(db, *, url, rel, user_id, asset_type, source, task_id):
    """幂等登记一个资产（新增或校正元数据），不 commit。返回是否新增。"""
    row = (await db.execute(select(Asset).where(Asset.url == url))).scalar_one_or_none()
    if row is None:
        size, sha, mime = _file_meta(rel)
        # 文件尚没落盘也先登记占位（size=0），落盘后下次落库/回填会校正
        db.add(Asset(
            url=url, rel_path=rel, user_id=user_id, asset_type=asset_type,
            source=source, task_id=task_id, mime=mime,
            size_bytes=size or 0, sha256=sha, ref_count=1,
        ))
        return True
    # 已存在：仅在仍是空占位（文件刚落盘）时补取体积/哈希，避免高频落库重复 hash
    if not row.size_bytes:
        size, sha, mime = _file_meta(rel)
        if size:
            row.size_bytes = size
        if sha:
            row.sha256 = sha
        if mime:
            row.mime = mime
    changed = False
    if not row.user_id and user_id:
        row.user_id, changed = user_id, True
    if row.asset_type in (None, "unknown", "image") and asset_type not in (None, "unknown", "image"):
        row.asset_type, changed = asset_type, True
    return False


async def sync_task_assets(db, task_row) -> int:
    """把一个任务 ORM 行当前引用到的本地资产登记进 assets 表（不 commit）。返回新增条数。"""
    if task_row is None:
        return 0
    added = 0
    try:
        user_id = getattr(task_row, "user_id", None)
        task_id = getattr(task_row, "task_id", None)
        script_data = getattr(task_row, "script_data", None)
        final_url = getattr(task_row, "final_video_url", None)
        seen = set()
        for url, rel, atype in iter_typed_asset_refs(script_data, final_url):
            if url in seen:
                continue
            seen.add(url)
            source = "upload" if _is_upload_rel(rel) else "ai"
            if await _upsert(db, url=url, rel=rel, user_id=user_id,
                             asset_type=atype, source=source, task_id=task_id):
                added += 1
    except Exception as e:  # 登记永不阻断主业务落库
        logger.warning("sync_task_assets failed | task=%s | %s",
                       getattr(task_row, "task_id", "?"), str(e)[:150])
    return added


async def backfill_all_assets() -> dict:
    """启动时全量回填：遍历所有任务，把引用到的本地资产登记进表（幂等，不移动文件）。"""
    from db import crud
    added, total = 0, 0
    async with AsyncSessionLocal() as db:
        rows = await crud.list_all_tasks(db)
        for row in rows:
            n = await sync_task_assets(db, row)
            added += n
            total += 1
        await db.commit()
        # 登记后顺手重算引用数
        await _rebuild_ref_counts_inner(db)
        await db.commit()
    logger.info("asset backfill done | tasks=%d | newly_registered=%d", total, added)
    return {"tasks": total, "registered": added}


async def _rebuild_ref_counts_inner(db) -> dict:
    """在给定 session 内扫描全部任务，重算每个资产 URL 的引用次数并写回。"""
    from db import crud
    counter: dict = {}
    for row in await crud.list_all_tasks(db):
        for url, _rel, _t in iter_typed_asset_refs(row.script_data, row.final_video_url):
            counter[url] = counter.get(url, 0) + 1
    assets = list((await db.execute(select(Asset))).scalars().all())
    touched = 0
    for a in assets:
        want = counter.get(a.url, 0)
        if a.ref_count != want:
            a.ref_count, touched = want, touched + 1
    return {"assets": len(assets), "updated": touched}


async def rebuild_ref_counts() -> dict:
    """对外：独立事务重算引用计数。"""
    async with AsyncSessionLocal() as db:
        stats = await _rebuild_ref_counts_inner(db)
        await db.commit()
    return stats


def save_user_upload(user_id, content: bytes, ext: str):
    """用户上传素材落盘：按用户分目录 assets/u{user_id}/uploads/{uuid}{ext}。

    返回 (url, rel)。调用方负责鉴权与体积/格式校验，本函数只负责落盘。
    """
    sub_dir = os.path.join(ASSETS_ROOT, f"u{user_id}" if user_id is not None else "u0", "uploads")
    os.makedirs(sub_dir, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    disk = os.path.join(sub_dir, name)
    with open(disk, "wb") as f:
        f.write(content)
    rel = f"{f'u{user_id}' if user_id is not None else 'u0'}/uploads/{name}"
    return rel_to_url(rel), rel


async def register_upload_row(db, *, url, user_id, task_id=None, commit: bool = False):
    """登记一条用户上传资产记录（upload 来源，GC 永不自动删）。"""
    rel = url_to_rel(url)
    size, sha, mime = _file_meta(rel)
    row = (await db.execute(select(Asset).where(Asset.url == url))).scalar_one_or_none()
    if row is None:
        db.add(Asset(url=url, rel_path=rel, user_id=user_id, asset_type="upload",
                     source="upload", task_id=task_id, mime=mime,
                     size_bytes=size or 0, sha256=sha, ref_count=1))
    if commit:
        await db.commit()
