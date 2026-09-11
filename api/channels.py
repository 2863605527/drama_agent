"""用户模型通道配置接口：通道元数据 / 配置读写 / 连通性测试"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from auth.deps import get_current_user
from core import crypto
from db import crud
from db.database import get_db
from mcp_client.agent_mcp_client import mcp_client
from schema import channel_schema as chs
from tools.logger_tool import get_logger

router = APIRouter(tags=["channels"])
logger = get_logger("drama.api.channels")


@router.get("/api/channels/meta")
async def channels_meta(current_user=Depends(get_current_user)):
    """通道与模型预设元数据，供前端渲染「通道配置」表单（不含任何密钥）。"""
    return chs.CHANNEL_META


@router.get("/api/user/channel-config")
async def get_channel_config(current_user=Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    """读取当前用户通道配置；敏感字段只回掩码，不回明文 Key。"""
    enc = await crud.get_user_channel_config(db, current_user.id)
    plain = crypto.decrypt_config(enc) if enc else None
    return {"config": chs.mask_sensitive(plain)}


@router.put("/api/user/channel-config")
async def put_channel_config(payload: chs.ChannelConfigPayload,
                             current_user=Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    """保存当前用户通道配置：未改动的掩码字段沿用旧值，校验必填后加密落库。"""
    incoming = payload.model_dump(exclude_none=True)
    old_enc = await crud.get_user_channel_config(db, current_user.id)
    old_plain = crypto.decrypt_config(old_enc) if old_enc else None
    merged = chs.merge_profiles(incoming, old_plain)
    merged = chs.deactivate_empty_segments(merged)  # 全空的自定义段自动降级为系统默认，不卡另一段保存
    problems = []
    for kind in ("llm", "image", "video"):
        problems += chs.validate_profile(kind, merged.get(kind))
    if problems:
        raise HTTPException(status_code=400, detail="；".join(problems))
    enc_config = crypto.encrypt_config(merged)
    await crud.upsert_user_channel_config(db, current_user.id, enc_config)
    logger.info("channel config saved | user=%s | llm=%s image=%s video=%s",
                current_user.id,
                (merged.get("llm") or {}).get("channel"),
                (merged.get("image") or {}).get("channel"),
                (merged.get("video") or {}).get("channel"))
    return {"ok": True, "config": chs.mask_sensitive(merged)}


@router.post("/api/user/channel-test")
async def channel_test(payload: chs.ChannelTestRequest,
                       current_user=Depends(get_current_user),
                       db: AsyncSession = Depends(get_db)):
    """通道连通性测试：LLM 发一次极简真实请求；图片/视频通用HTTP做只读真实探测（不烧额度）。
    弹窗回显的 Token 是掩码，这里先用库中已保存的真值把掩码/空值还原，避免拿掩码去测导致 401。"""
    kind = (payload.kind or "llm").strip()
    if kind not in ("llm", "image", "video"):
        raise HTTPException(status_code=400, detail="kind 只能是 llm / image / video")
    old_enc = await crud.get_user_channel_config(db, current_user.id)
    old_plain = crypto.decrypt_config(old_enc) if old_enc else None
    merged = chs.merge_profiles({kind: payload.profile or {}}, old_plain)
    profile = merged.get(kind) or payload.profile or {}
    problems = chs.validate_profile(kind, profile)
    if problems:
        raise HTTPException(status_code=400, detail="；".join(problems))
    if kind == "llm":
        msg = [{"role": "user", "content": "连通性测试：请只回复两个字 pong"}]
        use_profile = profile if chs.is_custom(profile) else None
        mcp_client.bind_profile(use_profile)  # ContextVar 绑定本次测试的通道配置
        try:
            reply = await asyncio.wait_for(
                mcp_client.call_llm(msg, 0.0), timeout=60)
            return {"ok": True, "reply": (reply or "")[:80]}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"LLM 连通失败：{str(e)[:200]}")
    # 图片/视频：通用 HTTP 做真实只读探测（地址可达 + Token 有效），不烧钱出图/出片
    if (profile or {}).get("channel") == chs.CH_GENERIC_HTTP:
        from tools.http_presets import probe_http_auth
        ok, msg = await asyncio.to_thread(probe_http_auth, profile, kind)
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        return {"ok": True, "reply": msg}
    return {"ok": True, "reply": "凭据完整性校验通过（该通道不实际出图/出片以节省额度）"}
