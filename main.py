from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, Response, JSONResponse
from fastapi.exceptions import RequestValidationError
from schema.drama_schema import SubmitDramaRequest, HumanReviewConfirm, DramaTask, RegenerateRequest, UpdateCharacterRequest, UpdateShotRequest, UpdateSceneRequest, ComposeVideoRequest, UpdateScriptRequest, UpdateAudioModeRequest
from agent.drama_agent import DramaAgent
from agent.progress_hub import progress_hub
from tools.logger_tool import get_logger
import os
import asyncio
import json
import uuid

logger = get_logger("drama.api")


class NoCacheStaticFiles(StaticFiles):
    """StaticFiles 扩展：给静态资源响应强制加 no-cache 头，避免浏览器缓存旧版前端。"""
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

app = FastAPI(title="Drama‑Agent 小云雀复刻项目")
agent = DramaAgent()


@app.middleware("http")
async def add_no_cache_header(request: Request, call_next):
    """所有响应默认禁用缓存，避免 API 和静态资源被浏览器缓存。"""
    response = await call_next(request)
    if "Cache-Control" not in response.headers:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


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
        # 翻译缺失字段
        if typ == "missing":
            msgs.append(f"缺少必填字段「{field or '未知'}」")
        # 翻译 Pydantic v2 类型错误（typ 形如 string_type / int_type / bool_type ...）
        elif typ.endswith("_type") or typ == "type_error":
            base = typ.replace("_type", "").replace("type_error.", "").lower()
            type_map = {
                "string": "应为字符串",
                "str": "应为字符串",
                "integer": "应为整数",
                "int": "应为整数",
                "float": "应为数字",
                "number": "应为数字",
                "boolean": "应为布尔值(true/false)",
                "bool": "应为布尔值(true/false)",
                "list": "应为数组",
                "array": "应为数组",
                "dict": "应为对象",
                "object": "应为对象",
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
    """兜底：把未处理异常翻译成友好中文，前端直接展示"""
    msg = str(exc) or exc.__class__.__name__
    if len(msg) > 300:
        msg = msg[:300] + "…"
    return JSONResponse(status_code=500, content={"detail": f"服务器内部错误：{msg}"})

os.makedirs("./assets", exist_ok=True)
os.makedirs("./assets/uploads", exist_ok=True)
os.makedirs("./assets/videos", exist_ok=True)
os.makedirs("./assets/final", exist_ok=True)
os.makedirs("./storage/milvus_db", exist_ok=True)
app.mount("/static", NoCacheStaticFiles(directory="static"), name="static")
app.mount("/assets", NoCacheStaticFiles(directory="assets"), name="assets")

@app.post("/api/task/submit", response_model=DramaTask)
async def submit_task(req: SubmitDramaRequest):
    logger.info("POST /submit | style=%s | prompt=%s…", req.style, req.user_prompt[:60])
    task = await agent.submit_new_task(req.user_prompt, req.style or "anime")
    logger.info("task created: %s", task.task_id)
    return task

@app.post("/api/task/review", response_model=DramaTask|None)
async def human_review(req: HumanReviewConfirm):
    return await agent.human_review_handle(req)

@app.get("/api/task/{task_id}", response_model=DramaTask|None)
async def get_task_info(task_id: str):
    return agent.get_task(task_id)

@app.post("/api/task/{task_id}/replace_image", response_model=DramaTask|None)
async def replace_image(task_id: str, target_type: str = Form(...), target_id: str = Form(...), file: UploadFile = File(...)):
    """手动替换角色形象图 / 场景图（昼夜）：上传本地图片文件"""
    content = await file.read()
    if not content:
        raise Exception("上传文件为空")
    ext = os.path.splitext(file.filename or "")[1].lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        ext = ".png"
    fname = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join("assets", "uploads", fname)
    with open(path, "wb") as f:
        f.write(content)
    url = f"/assets/uploads/{fname}"
    return await agent.replace_image(task_id, target_type, target_id, url)

@app.post("/api/task/{task_id}/regenerate", response_model=DramaTask|None)
async def regenerate(task_id: str, req: RegenerateRequest):
    """失败重试：重新生成角色图 / 场景图（昼夜）/ 片段视频"""
    logger.info("POST /regenerate | task=%s | %s:%s", task_id, req.target_type, req.target_id)
    return await agent.regenerate(task_id, req.target_type, req.target_id)

@app.post("/api/task/{task_id}/update_character", response_model=DramaTask|None)
async def update_character(task_id: str, req: UpdateCharacterRequest):
    """手动编辑角色姓名 / 性格详情"""
    return await agent.update_character(task_id, req.char_id, req.name, req.description)

@app.post("/api/task/{task_id}/update_scene", response_model=DramaTask|None)
async def update_scene(task_id: str, req: UpdateSceneRequest):
    """手动编辑场景环境描述（重新生成场景图时生效）"""
    return await agent.update_scene(task_id, req.scene_key, req.description)

@app.post("/api/task/{task_id}/update_audio_mode", response_model=DramaTask|None)
async def update_audio_mode(task_id: str, req: UpdateAudioModeRequest):
    """切换配音方式：auto（按通道自动）/ native（强制原生音频）/ tts（强制 TTS 配音）"""
    return await agent.update_audio_mode(task_id, req.audio_mode)

@app.post("/api/task/{task_id}/update_shot", response_model=DramaTask|None)
async def update_shot(task_id: str, req: UpdateShotRequest):
    """手动编辑分镜文案 / 镜头 / 光影 / 画面描述 prompt（时长由大模型自动分配）"""
    return await agent.update_shot(task_id, req.shot_id, req.content, req.camera, req.lighting, req.prompt)

@app.post("/api/task/{task_id}/update_script", response_model=DramaTask|None)
async def update_script(task_id: str, req: UpdateScriptRequest):
    """手动编辑剧本标题与原始剧本内容"""
    logger.info("POST /update_script | task=%s | title=%s", task_id, req.title)
    return await agent.update_script(task_id, req.title, req.raw_content)

@app.post("/api/task/{task_id}/compose_video", response_model=DramaTask|None)
async def compose_video(task_id: str, req: ComposeVideoRequest):
    """将全部分镜视频合成为一个完整短剧视频（后台执行，进度走 SSE）"""
    logger.info("POST /compose_video | task=%s", task_id)
    # 前置校验：门槛不满足时直接返回 400 + 中文 detail（避免 200 假成功 + 长时间转圈）
    task = agent.task_store.get(task_id)
    if not task or not task.script:
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
    return await agent.compose_video(task_id)

@app.get("/api/task/stream/{task_id}")
async def task_stream(task_id: str):
    """SSE 进度流：订阅任务流水线的实时进度事件"""
    history, queue = await progress_hub.subscribe(task_id)

    async def event_gen():
        try:
            # 先重放历史事件（客户端中途接入不丢进度）
            for evt in history:
                yield f"event: {evt['event']}\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"
                if evt["event"] in ("done", "fail"):
                    # 历史里已经有终态，继续守听后续手动操作事件
                    continue
            # 实时事件
            while True:
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"event: {evt['event']}\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"
                # done/fail 只表示某个阶段结束，不关闭 SSE；
                # 后续手动生成分镜视频、合成视频仍可能产生事件。
        except asyncio.CancelledError:
            # 客户端断开连接
            pass

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8010, reload=True)
