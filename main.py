"""应用入口：组装 lifespan / 中间件 / 异常处理 / 路由 / 静态托管。

业务接口按类拆分在 api/ 包：
- api/system.py       运维：/health /metrics
- api/auth.py         认证：/api/auth/*
- api/channels.py     通道配置：/api/channels/meta /api/user/channel-* 
- api/tasks.py        任务业务：/api/task/*（创建/查询/审核/资产/编辑/合成）
- api/task_stream.py  SSE 进度流：/api/task/stream/{task_id}
路由通过 api/__init__.py 的 register_routers() 统一注册，注册顺序必须在 SPA 托管之前。
"""
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

import api as api_routes
from api import context
from agent.drama_agent import DramaAgent
from agent.progress_hub import progress_hub
from core import metrics, observability
from core.config import settings
from db.database import init_db, engine
from mcp_client.agent_mcp_client import mcp_client
from tasks.asset_gc import gc_orphan_assets
from tasks.reconcile import reconcile_on_startup
from tools.logger_tool import get_logger

logger = get_logger("drama.api")


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles 扩展：给静态资源响应强制加 no-cache 头，避免浏览器缓存旧版前端。"""
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


class CacheStaticFiles(StaticFiles):
    """/assets 媒体资源托管（P2-7）。

    - images/、uploads/ 的文件名是 uuid（内容变则 URL 变，天然不可变）→ 长缓存 immutable，
      重复浏览/生成预览不再重复下载大图；
    - videos/、audio/、final/ 按 task_id 命名，任务重跑会覆盖同名文件（URL 不变内容变）→
      保持 no-cache，避免用户看到旧成片/旧片段。
    """
    _IMMUTABLE_PREFIXES = ("images/", "uploads/")

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if path.startswith(self._IMMUTABLE_PREFIXES) and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


class SPAStaticFiles(NoCacheStaticFiles):
    """Vue 单页应用托管：静态文件存在则返回，否则回退 index.html（支持前端 history 路由刷新）。"""
    async def get_response(self, path: str, scope):
        from starlette.exceptions import HTTPException as StarletteHTTPException
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动初始化 + 优雅关闭"""
    # ---------- startup ----------
    for dirpath in ("assets", "assets/uploads", "assets/videos", "assets/final", "storage/milvus_db"):
        os.makedirs(dirpath, exist_ok=True)
    problems = settings.validate_required()
    for p in problems:
        logger.warning("CONFIG WARNING | %s", p)
    observability.init_sentry()       # 配了 SENTRY_DSN 才启用，否则空操作
    await init_db()
    context.init_agent()
    await context.agent.initialize()
    # 启动对账：把重启前卡在解析阶段（pending）的任务标记失败，人工断点阶段任务保持可续
    try:
        rec = await reconcile_on_startup()
        logger.info("startup reconcile done | stuck_failed=%d | resumable=%d",
                    rec["failed"], rec["resumable"])
        # 先把存量任务引用到的资产回填进 assets 元数据表（幂等、不移动文件），再做安全 GC
        try:
            from tasks.asset_store import backfill_all_assets
            bf = await backfill_all_assets()
            logger.info("startup asset backfill | tasks=%d | registered=%d",
                        bf["tasks"], bf["registered"])
        except Exception as be:
            logger.error("startup asset backfill error: %s", be)
        gc = await gc_orphan_assets()
        if gc.get("removed") or gc.get("unregistered"):
            logger.info("startup asset gc | removed=%d | freed=%.2fMB | unregistered_kept=%d",
                        gc.get("removed", 0), gc.get("freed_mb", 0.0), gc.get("unregistered", 0))
    except Exception as e:
        logger.error("startup reconcile error: %s", e)
    logger.info("startup complete | env=%s | port=%d", settings.environment, settings.app_port)
    yield
    # ---------- shutdown（优雅关闭：MCP 子进程连接 + DB 连接池）----------
    logger.info("shutdown: closing mcp channels ...")
    try:
        await mcp_client.close()
    except Exception as e:
        logger.error("mcp close error: %s", e)
    logger.info("shutdown: disposing database engine ...")
    try:
        await engine.dispose()
    except Exception as e:
        logger.error("engine dispose error: %s", e)
    logger.info("shutdown complete")


app = FastAPI(title="Drama-Agent 短剧生成系统", lifespan=lifespan)

# ---------- CORS ----------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """安全响应头（P1-5）：CSP / nosniff / 防点击劫持 / 来源策略。
    - CSP 需兼容 Vue 构建产物（外链 JS、内联样式）与 SSE、blob 视频、第三方图片；
    - nosniff 强制浏览器按 Content-Type 解析，配合上传魔数校验阻断存储型 XSS。"""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https:; media-src 'self' blob: https:; "
        "connect-src 'self'; font-src 'self' data:; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'")
    return response


@app.middleware("http")
async def add_no_cache_header(request: Request, call_next):
    """所有响应默认禁用缓存，避免 API 和静态资源被浏览器缓存。"""
    response = await call_next(request)
    if "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.middleware("http")
async def prometheus_http_metrics(request: Request, call_next):
    """采集 HTTP 请求量与耗时（路径模板归一化，避免 task_id 造成高基数标签）。"""
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        cost = time.perf_counter() - start
        path = metrics.normalize_path(request)
        metrics.HTTP_LATENCY.labels(request.method, path).observe(cost)
        metrics.HTTP_REQUESTS.labels(request.method, path, str(status)).inc()


@app.exception_handler(RequestValidationError)
async def _validation_zh(request: Request, exc: RequestValidationError):
    """把 Pydantic 422 校验错误翻译成中文（前端直接展示给用户看）"""
    errs = exc.errors()
    if not errs:
        return JSONResponse(status_code=422, content={"detail": "请求参数错误"})
    msgs = []
    for e in errs:
        loc_list = e.get("loc", [])
        field = ".".join(str(x) for x in loc_list[1:]) if len(loc_list) > 1 else str(loc_list[0] or "")
        typ = e.get("type", "")
        raw_msg = e.get("msg", "")
        if typ == "missing":
            msgs.append(f"缺少必填字段「{field or '未知'}」")
        elif typ.endswith("_type") or typ == "type_error":
            base = typ.replace("_type", "").replace("type_error.", "").lower()
            type_map = {
                "string": "应为字符串", "str": "应为字符串",
                "integer": "应为整数", "int": "应为整数",
                "float": "应为数字", "number": "应为数字",
                "boolean": "应为布尔值(true/false)", "bool": "应为布尔值(true/false)",
                "list": "应为数组", "array": "应为数组",
                "dict": "应为对象", "object": "应为对象",
            }
            tip = type_map.get(base, f"类型不合法（{raw_msg or typ}）")
            msgs.append(f"字段「{field}」{tip}")
        elif typ == "extra_forbidden" or "extra fields" in raw_msg.lower():
            msgs.append(f"字段「{field}」不允许传入")
        elif typ == "string_too_long":
            ctx = e.get("ctx", {})
            msgs.append(f"字段「{field}」内容过长（最大 {ctx.get('max_length', '?')} 字符）")
        elif typ == "string_too_short":
            msgs.append(f"字段「{field}」内容过短（最少 {e.get('ctx', {}).get('min_length', '?')} 字符）")
        elif "value_error" in typ or typ == "value_error":
            msgs.append(f"字段「{field}」值不合法：{raw_msg}")
        elif "json_invalid" in typ:
            msgs.append("请求体不是合法 JSON")
        else:
            msgs.append(f"字段「{field or '未知'}」错误：{raw_msg or typ}")
    detail = "；".join(msgs) if msgs else "请求参数错误"
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(Exception)
async def _unhandled_zh(request: Request, exc: Exception):
    """兜底异常处理（P1-4）：不向前端回传内部细节（可能含 SQL/路径/表名），
    生成 trace id 便于日志定位，前端只看到通用提示+错误码。"""
    import traceback
    import uuid
    trace_id = uuid.uuid4().hex[:8]
    logger.error("unhandled error | trace=%s | path=%s | %s\n%s",
                 trace_id, request.url.path, exc,
                 "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    return JSONResponse(
        status_code=500,
        content={"detail": f"服务器内部错误，请稍后重试（错误码 {trace_id}）"},
    )


# ---------- 业务路由（按类注册，必须在 SPA 托管之前） ----------
api_routes.register_routers(app)

# /assets：images/uploads 长缓存（uuid 文件名不可变），videos/audio/final 保持 no-cache
app.mount("/assets", CacheStaticFiles(directory="assets"), name="assets")


# ---------- 前端 Vue 工程构建产物托管（SPA） ----------
# 构建命令：cd frontend && npm install && npm run build（产物输出到 frontend/dist）
# 必须放在所有 /api 路由之后注册：未被 API/静态资源匹配的路径全部回退到 Vue 单页应用。
_FRONTEND_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "dist")
if os.path.isdir(_FRONTEND_DIST):
    app.mount("/", SPAStaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
    logger.info("Vue frontend dist mounted at / | %s", _FRONTEND_DIST)
else:
    @app.get("/")
    async def _root_hint():
        return JSONResponse(content={
            "name": "Drama-Agent 短剧生成系统 API",
            "frontend": "未检测到 frontend/dist 构建产物：开发期请用 `cd frontend && npm run dev`，"
                        "或执行 `npm run build` 后由后端托管页面。",
            "docs": "/docs",
        })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.app_port, reload=settings.debug)
