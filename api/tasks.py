"""任务业务接口（全部需要登录 + 归属校验）：

- 任务生命周期：创建（submit / episode）/ 查询 / 重试 / 删除 / 人工审核
- 资产操作：图片上传替换 / 清除 / 重绘重生成
- 剧本编辑：角色 / 场景 / 分镜 / 剧本 / 配音方式
- 视频合成：片段视频合成完整短剧
"""
import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from agent.drama_agent import DramaAgent
from api.deps import get_agent
from auth.asset_sign import sign_nested_assets
from core import metrics
from core.deps import load_owned_task
from auth.deps import get_current_user
from schema import channel_schema as chs
from schema.drama_schema import (
    DramaTask, SubmitDramaRequest, EpisodeRequest, HumanReviewConfirm,
    RegenerateRequest, UpdateCharacterRequest, UpdateSceneRequest,
    UpdateShotRequest, UpdateScriptRequest, UpdateAudioModeRequest,
    ComposeVideoRequest,
)
from tasks.asset_gc import remove_task_assets, gc_orphan_assets
from tools.logger_tool import get_logger

router = APIRouter(prefix="/api/task", tags=["tasks"])
logger = get_logger("drama.api.tasks")


def _masked_task(task):
    """把任务返回给前端前掩码通道敏感字段（服务端内存保持明文供执行，仅出网掩码）。"""
    if task is None:
        return None
    return task.model_copy(update={"channel_profile": chs.mask_sensitive(task.channel_profile)})


def _serialize_task(task):
    """出网序列化：掩码敏感字段 + 给 /assets 媒体 URL 附加访问签名（P0）。"""
    return sign_nested_assets(_masked_task(task))


# ---------- 任务创建与查询 ----------

@router.post("/submit", response_model=DramaTask)
async def submit_task(req: SubmitDramaRequest, current_user=Depends(get_current_user),
                      agent: DramaAgent = Depends(get_agent)):
    logger.info("POST /submit | user=%s | style=%s | prompt=%s…",
                current_user.username, req.style, req.user_prompt[:60])
    task = await agent.submit_new_task(req.user_prompt, req.style or "anime", user_id=current_user.id)
    metrics.TASK_SUBMITTED.labels(current_user.username).inc()
    metrics.ACTIVE_TASKS.inc()
    logger.info("task created: %s", task.task_id)
    return _serialize_task(task)


@router.post("/{parent_id}/episode", response_model=DramaTask)
async def create_next_episode(parent_id: str, req: EpisodeRequest, current_user=Depends(get_current_user),
                              agent: DramaAgent = Depends(get_agent)):
    """在指定一集基础上续写下一集：自动继承已有角色/场景资产与通道，剧情承接前情。"""
    await load_owned_task(parent_id, current_user, agent)
    logger.info("POST /episode | parent=%s | user=%s | prompt=%s…",
                parent_id, current_user.username, (req.user_prompt or "")[:40])
    try:
        task = await agent.submit_new_task(
            req.user_prompt, req.style or None,
            user_id=current_user.id, parent_id=parent_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    metrics.TASK_SUBMITTED.labels(current_user.username).inc()
    metrics.ACTIVE_TASKS.inc()
    return _serialize_task(task)


@router.get("/list")
async def list_tasks(current_user=Depends(get_current_user),
                     agent: DramaAgent = Depends(get_agent)):
    """获取当前用户的任务列表（通道 Key 掩码化，不暴露明文）"""
    tasks = await agent.list_user_tasks(current_user.id)
    out = []
    for t in tasks:
        d = sign_nested_assets(t.model_dump(mode="json"))
        d["channel_profile"] = chs.mask_sensitive(d.get("channel_profile"))
        out.append(d)
    return out


@router.post("/review", response_model=DramaTask | None)
async def human_review(req: HumanReviewConfirm, current_user=Depends(get_current_user),
                       agent: DramaAgent = Depends(get_agent)):
    # task_id 在 body 中，先做归属校验
    await load_owned_task(req.task_id, current_user, agent)
    return _serialize_task(await agent.human_review_handle(req))


@router.get("/{task_id}", response_model=DramaTask | None)
async def get_task_info(task_id: str, current_user=Depends(get_current_user),
                        agent: DramaAgent = Depends(get_agent)):
    """任务详情（通道 Key 掩码化，不暴露明文）"""
    task = await load_owned_task(task_id, current_user, agent)
    if task is None:
        return None
    return sign_nested_assets(task.model_copy(update={"channel_profile": chs.mask_sensitive(task.channel_profile)}))


# ---------- 任务级操作 ----------

@router.post("/{task_id}/retry", response_model=DramaTask)
async def retry_task(task_id: str, current_user=Depends(get_current_user),
                     agent: DramaAgent = Depends(get_agent)):
    """失败/已完成任务整体重新开始（原地重跑剧本解析流水线，保持同一 task_id）。"""
    await load_owned_task(task_id, current_user, agent)
    logger.info("POST /retry | task=%s", task_id)
    try:
        return _serialize_task(await agent.retry_task(task_id))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{task_id}")
async def delete_task(task_id: str, current_user=Depends(get_current_user),
                      agent: DramaAgent = Depends(get_agent)):
    """删除整个短剧任务（含内存工作副本、SSE 流与 MySQL 行）。"""
    await load_owned_task(task_id, current_user, agent)
    await agent.delete_task(task_id)
    # 资产生命周期：删除任务后清理其专属视频/音频/成片，并回收不再被任何任务引用的孤儿图片
    try:
        n = remove_task_assets(task_id)
        gc = await gc_orphan_assets()
        logger.info("DELETE /task assets | task=%s | task_files=%d | orphan_removed=%d",
                    task_id, n, gc["removed"])
    except Exception as e:
        logger.error("DELETE /task asset gc error: %s", e)
    logger.info("DELETE /task | task=%s | user=%s", task_id, current_user.username)
    from core.audit import audit
    from db.database import AsyncSessionLocal as _AuditSession
    async with _AuditSession() as _adb:
        await audit(_adb, current_user.id, "task_deleted", {"task_id": task_id})
    return {"ok": True}


@router.post("/{task_id}/compose_video", response_model=DramaTask | None)
async def compose_video(task_id: str, req: ComposeVideoRequest, current_user=Depends(get_current_user),
                        agent: DramaAgent = Depends(get_agent)):
    """将全部分镜视频合成为一个完整短剧视频（后台执行，进度走 SSE）"""
    task = await load_owned_task(task_id, current_user, agent)
    logger.info("POST /compose_video | task=%s", task_id)
    if not task.script:
        raise HTTPException(status_code=404, detail="任务不存在或剧本尚未生成")
    segs = task.script.segments or []
    if segs:
        total = len(segs)
        generated = sum(1 for s in segs if s.video_url)
    else:
        total = len(task.script.shots)
        generated = sum(1 for s in task.script.shots if s.video_url)
    if generated < 2 and total > 1:
        raise HTTPException(status_code=400, detail=f"目前仅生成 {generated}/{total} 个片段，至少生成 2 个片段才能合成（或全部生成后合成完整短剧）")
    if total == 0:
        raise HTTPException(status_code=400, detail="剧本为空，无法合成")
    return _serialize_task(await agent.compose_video(task_id))


# ---------- 资产图片操作 ----------

# 图片魔数校验表（按文件头识别真实类型，防止把 SVG/HTML 改名成 .png 上传造成存储型 XSS）
_IMG_MAGIC = [
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"RIFF", ".webp"),      # RIFF....WEBP
    (b"BM", ".bmp"),
]


def _detect_image_ext(content: bytes) -> str:
    """按魔数识别图片类型；无法识别返回空串（拒绝）。"""
    for magic, ext in _IMG_MAGIC:
        if content.startswith(magic):
            if ext == ".webp" and content[8:12] != b"WEBP":
                continue
            return ext
    return ""

@router.post("/{task_id}/replace_image", response_model=DramaTask | None)
async def replace_image(task_id: str, target_type: str = Form(...), target_id: str = Form(...),
                        file: UploadFile = File(...), current_user=Depends(get_current_user),
                        agent: DramaAgent = Depends(get_agent)):
    """手动替换角色形象图 / 场景图（昼夜）：上传本地图片文件"""
    await load_owned_task(task_id, current_user, agent)
    content = await file.read()
    if not content:
        raise Exception("上传文件为空")
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片不能超过 10MB")
    ext = _detect_image_ext(content)   # 魔数优先：真图才收，SVG/HTML 改名上传直接拒绝
    if not ext:
        raise HTTPException(status_code=400,
                            detail="仅支持 PNG / JPG / GIF / WEBP / BMP 图片（按文件内容识别，请勿上传其他格式）")
    # 按用户分目录落盘 assets/u{user_id}/uploads/，并登记个人资产元数据（upload 来源永不自动回收）
    from tasks import asset_store
    from db.database import AsyncSessionLocal
    user_id = getattr(current_user, "id", None)
    url, _rel = asset_store.save_user_upload(user_id, content, ext)
    async with AsyncSessionLocal() as sdb:
        await asset_store.register_upload_row(sdb, url=url, user_id=user_id,
                                              task_id=task_id, commit=True)
    return _serialize_task(await agent.replace_image(task_id, target_type, target_id, url))


@router.post("/{task_id}/clear_image", response_model=DramaTask | None)
async def clear_image(task_id: str, req: RegenerateRequest, current_user=Depends(get_current_user),
                      agent: DramaAgent = Depends(get_agent)):
    """清除某张角色/场景图片（回到未生成状态，任务状态不回退）"""
    await load_owned_task(task_id, current_user, agent)
    logger.info("POST /clear_image | task=%s | %s:%s", task_id, req.target_type, req.target_id)
    return _serialize_task(await agent.clear_image(task_id, req.target_type, req.target_id))


@router.post("/{task_id}/regenerate", response_model=DramaTask | None)
async def regenerate(task_id: str, req: RegenerateRequest, current_user=Depends(get_current_user),
                     agent: DramaAgent = Depends(get_agent)):
    """失败重试：重新生成角色图 / 场景图（昼夜）/ 片段视频"""
    await load_owned_task(task_id, current_user, agent)
    logger.info("POST /regenerate | task=%s | %s:%s", task_id, req.target_type, req.target_id)
    return _serialize_task(await agent.regenerate(task_id, req.target_type, req.target_id))


# ---------- 剧本编辑 ----------

@router.post("/{task_id}/update_character", response_model=DramaTask | None)
async def update_character(task_id: str, req: UpdateCharacterRequest, current_user=Depends(get_current_user),
                           agent: DramaAgent = Depends(get_agent)):
    """手动编辑角色姓名 / 性格详情"""
    await load_owned_task(task_id, current_user, agent)
    return _serialize_task(await agent.update_character(task_id, req.char_id, req.name, req.description))


@router.post("/{task_id}/update_scene", response_model=DramaTask | None)
async def update_scene(task_id: str, req: UpdateSceneRequest, current_user=Depends(get_current_user),
                       agent: DramaAgent = Depends(get_agent)):
    """手动编辑场景环境描述（重新生成场景图时生效）"""
    await load_owned_task(task_id, current_user, agent)
    return _serialize_task(await agent.update_scene(task_id, req.scene_key, req.description))


@router.post("/{task_id}/update_audio_mode", response_model=DramaTask | None)
async def update_audio_mode(task_id: str, req: UpdateAudioModeRequest, current_user=Depends(get_current_user),
                            agent: DramaAgent = Depends(get_agent)):
    """切换配音方式：auto / native / tts"""
    await load_owned_task(task_id, current_user, agent)
    return _serialize_task(await agent.update_audio_mode(task_id, req.audio_mode))


@router.post("/{task_id}/update_shot", response_model=DramaTask | None)
async def update_shot(task_id: str, req: UpdateShotRequest, current_user=Depends(get_current_user),
                      agent: DramaAgent = Depends(get_agent)):
    """手动编辑分镜文案 / 镜头 / 光影 / 画面描述 prompt"""
    await load_owned_task(task_id, current_user, agent)
    return _serialize_task(await agent.update_shot(task_id, req.shot_id, req.content, req.camera, req.lighting, req.prompt))


@router.post("/{task_id}/update_script", response_model=DramaTask | None)
async def update_script(task_id: str, req: UpdateScriptRequest, current_user=Depends(get_current_user),
                        agent: DramaAgent = Depends(get_agent)):
    """手动编辑剧本标题与原始剧本内容"""
    await load_owned_task(task_id, current_user, agent)
    logger.info("POST /update_script | task=%s | title=%s", task_id, req.title)
    return _serialize_task(await agent.update_script(task_id, req.title, req.raw_content))