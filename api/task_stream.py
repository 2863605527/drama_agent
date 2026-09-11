"""SSE 实时进度流接口（P1-5：JWT 不再走 URL query）。

EventSource 不支持自定义 header，旧实现把 JWT 放 query 参数（会进访问/代理/历史日志）。
现改为两段式：
  1. POST /api/task/{task_id}/stream_token  用 Authorization 头签发「短时一次性」stream token
     （60s 有效、绑定 task_id+user_id、HMAC 签名），签发时已做任务归属校验；
  2. EventSource /api/task/stream/{task_id}?token=<stream_token> 只认 stream token，
     泄露窗口极小且无法用于其它接口/其它任务。
连接建立后先重放历史事件（刷新/重连不丢进度），再持续推送实时事件，15s 无事件发 keep-alive。
"""
import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from agent.progress_hub import progress_hub
from api.deps import get_agent
from auth.deps import get_current_user
from core.config import settings
from core.deps import load_owned_task
from db import crud
from db.database import get_db

router = APIRouter(prefix="/api/task", tags=["task-stream"])

# stream token 有效期（秒）：足够 EventSource 建立连接与自动重连，过期后前端需重新签发
_STREAM_TOKEN_TTL = 60


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def create_stream_token(task_id: str, user_id: int) -> str:
    """签发绑定 task_id+user_id 的短时 token：{task_id}.{user_id}.{exp}.{nonce} 签名。"""
    exp = int(time.time()) + _STREAM_TOKEN_TTL
    payload = f"{task_id}.{user_id}.{exp}.{secrets.token_hex(8)}"
    sig = hmac.new(settings.jwt_secret_key.encode("utf-8"),
                   payload.encode("utf-8"), hashlib.sha256).digest()
    return f"{_b64url(payload.encode('utf-8'))}.{_b64url(sig)}"


def verify_stream_token(token: str) -> dict | None:
    """校验 stream token，返回 {task_id, user_id}；任何异常/过期/签名不符返回 None。"""
    try:
        body, sig = token.split(".")
        payload_bytes = _b64url_decode(body)
        expected = hmac.new(settings.jwt_secret_key.encode("utf-8"),
                            payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_decode(sig), expected):
            return None
        task_id, user_id, exp, _nonce = payload_bytes.decode("utf-8").split(".")
        if int(exp) < time.time():
            return None
        return {"task_id": task_id, "user_id": int(user_id)}
    except Exception:
        return None


@router.post("/{task_id}/stream_token")
async def issue_stream_token(task_id: str, current_user=Depends(get_current_user),
                             agent=Depends(get_agent)):
    """用标准 JWT（Authorization 头）换取短时 stream token；签发时校验任务归属。"""
    await load_owned_task(task_id, current_user, agent)
    return {"token": create_stream_token(task_id, current_user.id), "expires_in": _STREAM_TOKEN_TTL}


@router.get("/stream/{task_id}")
async def task_stream(task_id: str, token: str = "", db: AsyncSession = Depends(get_db),
                      agent=Depends(get_agent)):
    """SSE 进度流：只接受短时 stream token（query），并二次校验任务归属。"""
    info = verify_stream_token(token)
    if not info or info["task_id"] != task_id:
        raise HTTPException(status_code=401, detail="流连接已过期，请刷新页面重试")
    # 归属校验：stream token 绑定签发用户，必须与任务归属一致（防 token 冒用）
    owned = await agent.load_task(task_id)
    if not owned:
        raise HTTPException(status_code=404, detail="任务不存在")
    if owned.user_id is not None and owned.user_id != info["user_id"]:
        raise HTTPException(status_code=403, detail="无权访问该任务")

    history, queue = await progress_hub.subscribe(task_id)

    async def event_gen():
        try:
            for evt in history:
                yield f"event: {evt['event']}\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"
                if evt["event"] in ("done", "fail"):
                    continue
            while True:
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: {evt['event']}\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            # 连接关闭（含 EventSource 自动重连留下的旧连接）必须注销本连接专属队列，
            # 否则僵尸订阅者会堆积；每个连接独立队列，事件扇出互不抢占。
            progress_hub.unsubscribe(task_id, queue)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )
