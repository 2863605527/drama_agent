# Drama-Agent 架构与 API 参考

## 技术栈

- **后端**：FastAPI + Uvicorn（端口 **8010**，非 reload 后台运行），Pydantic v2
- **Agent**：`agent/drama_agent.py` 任务状态机（submit 后异步后台执行，内存 task_store）
- **Skill 流水线**：`skill/drama_make_skill.py`（4 步 SOP，见 SKILL.md）
- **SSE 进度流**：`agent/progress_hub.py`（seq 自增去重，历史上限 500 条）
- **LLM**：DeepSeek（OpenAI 兼容），JSON 解析兜底 `strict=False` + 控制字符转义
- **媒体通道**：`tools/media_channel.py` 通道抽象层（换供应商不改代码）
  - `volc_cv`：火山即梦 `cv_process` / `cv_sync2async_*`（req_key 制，50430 并发退避重试）
  - `volc_ark`：火山方舟 `POST/GET /api/v3/contents/generations/tasks`（Seedance 2.0，原生音频+参考图）+ `POST /images/generations`（Seedream）
  - `generic_http`：通用 HTTP 提交/轮询，JSON 路径全可配
- **TTS**：edge-tts（本地免费，48kHz 立体声 AAC）；方舟 Seedance 原生音频时自动跳过
- **合成**：imageio-ffmpeg 自带 ffmpeg，concat demuxer + 归一化（有音轨保留原轨，无音轨加静音轨）

## 项目结构

```
F:/AI学习/drama_agent/
├── main.py                  # FastAPI 入口（NoCacheStaticFiles 禁缓存）
├── agent/
│   ├── drama_agent.py       # 任务状态机
│   └── progress_hub.py      # SSE 进度发布
├── skill/
│   └── drama_make_skill.py  # 4 步 SOP 流水线（剧本解析/角色/分镜/合成）
├── tools/
│   ├── media_channel.py     # 媒体通道抽象层（volc_cv / volc_ark / generic_http，换供应商零改码）
│   ├── llm_tool.py          # DeepSeek 调用 + 剧本起草
│   ├── image_tool.py        # 角色/场景出图（按 IMAGE_CHANNEL 分发）
│   ├── video_tool.py        # 视频提交/轮询/下载/裁剪/合成 + 时长策略（按 VIDEO_CHANNEL 分发）
│   ├── tts_tool.py          # edge-tts 配音
│   └── logger_tool.py       # 日志（logs/drama.log 按天滚动留 14 天）
├── schema/drama_schema.py   # Pydantic 模型
├── static/index.html        # 前端（深色影视风，SSE 进度）
├── assets/videos/           # 分镜视频与成片落盘
└── .env                     # 全部配置与密钥（勿外泄）
```

## API 端点

| 方法 | 路径 | 请求体 | 说明 |
|---|---|---|---|
| POST | `/api/task/submit` | `{"user_prompt": str, "style": "anime"}` | 提交短剧任务，返回任务（含 task_id） |
| POST | `/api/task/review` | `{"task_id": str, "accept": bool, "modify_characters": [...]?}` | 角色审核确认/驳回 |
| GET | `/api/task/{task_id}` | - | 查询任务全量状态（script/shots/characters） |
| POST | `/api/task/{task_id}/regenerate` | `{"task_id", "target_type": "character\|scene_image\|segment_video\|shot_video", "target_id"}` | 局部重新生成 |
| POST | `/api/task/{task_id}/replace_image` | multipart：`target_type`、`target_id`、`file` | 上传本地图替换角色/场景图 |
| POST | `/api/task/{task_id}/update_character` | `{"task_id", "char_id", "name", "description"}` | 改角色 |
| POST | `/api/task/{task_id}/update_scene` | `{"task_id", "scene_key", "description"}` | 改场景描述 |
| POST | `/api/task/{task_id}/update_shot` | `{"task_id", "shot_id", ...}` | 改分镜（content/camera/lighting/prompt） |
| POST | `/api/task/{task_id}/update_script` | `{"task_id", "title", "shots": [...]}` | 整剧替换分镜 |
| POST | `/api/task/{task_id}/compose_video` | `{"task_id"}` | 触发全部分镜视频合成成片 |
| GET | `/api/task/stream/{task_id}` | - | SSE 进度流（前端 EventSource） |

## 任务状态机

```
pending → parsing（剧本解析）→ generating_asset（角色立绘 + 场景图昼夜双图）
       → human_review（人工审核断点，等 accept）
       → generating_video（片段视频，用户逐片段手动触发）
       → composing（合成成片）→ done
```

失败路径：任一环节异常 → `failed`，可重新 submit。
