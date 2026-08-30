# Drama-Agent 小云雀短剧复刻项目

## 项目简介

Drama-Agent 是一个基于 **FastAPI + Agent + MCP** 架构的短剧自动生成系统。用户输入一段创意描述，系统通过 AI 自动完成"剧本解析 → 角色形象生成 → 人工审核 → 分镜图生成 → 分镜视频生成 → 合成完整短剧"的完整生产流水线。

该项目同时演示了 **MCP（Model Context Protocol）** 工具服务化的设计思路：将 LLM 对话、图片生成、RAG 检索等能力封装为独立的 MCP Server，供 Agent 通过标准协议调用。

## 架构概览

```
┌─────────────────────────────────────────────────────┐
│                    用户 (浏览器)                      │
│                  static/index.html                   │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP
┌──────────────────────▼──────────────────────────────┐
│              FastAPI Web Server (main.py)             │
│           端口 8010 | REST API + 静态资源              │
├─────────────────────────────────────────────────────┤
│              DramaAgent (agent/)                     │
│         任务编排 / 状态管理 / 人工审核断点               │
├──────────────────────┬──────────────────────────────┤
│  DramaMakeSkill      │      MCP Client (预留)         │
│  (skill/)            │   mcp_client/                 │
│  SOP 流水线           │                               │
├─────────┬──────┬─────┴──────────────────────────────┤
│ llm_tool│image │ video_tool│ rag_tool               │
│ (tools/)│_tool │ (tools/)  │ (tools/)               │
└────┬─────┴──────┴─────┬─────┴───────────────────────┘
     │                 │
     ▼                 ▼
┌─────────┐  ┌──────────────┐  ┌──────────┐
│ LLM API │  │ Image API    │  │ Video API│
│ :8001   │  │ :8002        │  │ :8003    │
└─────────┘  └──────────────┘  └──────────┘
```

## 目录结构

```
drama_agent/
├── main.py                    # FastAPI 入口，定义 REST 接口
├── requirements.txt           # Python 依赖清单
├── .env                       # 环境变量配置（API 地址等）
├── agent/
│   └── drama_agent.py         # Agent 核心：任务编排 + 状态机
├── schema/
│   └── drama_schema.py        # Pydantic 数据模型（Task/Script/Character/Shot）
├── skill/
│   └── drama_make_skill.py    # 短剧生产 SOP 流水线（3 步骤 + 人工审核断点）
├── tools/
│   ├── llm_tool.py            # LLM 对话 + 剧本生成
│   ├── image_tool.py          # 角色图片生成
│   ├── video_tool.py          # 分镜视频生成
│   └── rag_tool.py            # Milvus Lite 向量检索（镜头知识库）
├── mcp_server/
│   ├── llm_mcp.py             # MCP Server: LLM 工具服务
│   ├── image_mcp.py           # MCP Server: 图片生成工具服务
│   └── rag_mcp.py             # MCP Server: RAG 检索工具服务
├── mcp_client/
│   └── agent_mcp_client.py    # MCP Client 骨架（预留，可替换 tools 直调）
├── static/
│   └── index.html             # 前端演示页面
├── assets/                    # 生成的图片/视频存放目录
└── storage/
    ├── db.sqlite              # SQLite 数据库（预留）
    └── milvus_db/             # Milvus Lite 向量数据库
```

## 核心功能

### 1. 剧本解析 (Step 1)
- 用户输入创意描述（如"校园虐恋短剧，女主被误会..."）
- Agent 调用 LLM 生成完整剧本文本
- 再调用 LLM 将剧本解析为结构化 JSON（标题、角色列表、分镜列表）
- **角色一致性约束**：解析 prompt 要求 LLM 为每个角色输出详细外貌描述，并在每个分镜的 `prompt` 与 `character_names` 中明确标注出现的角色，确保后续分镜图与角色形象保持一致

### 2. 角色形象生成 (Step 2)
- 根据每个角色的描述，调用图片生成 API 生成角色参考图
- 生成完成后，任务进入"等待人工审核"状态

### 3. 人工审核断点 (Human Review)
- 用户可查看生成的角色信息
- **支持手动替换角色图**：鼠标悬停图片点击"替换图片"，上传本地图片即时生效
- **支持编辑角色信息**：点击角色卡"✏️ 编辑"按钮，可修改角色**姓名**与**性格详情**，保存后实时生效
- **失败单项可单独重试**：某张角色图生成失败不阻塞整体，点击"重试生成"仅重新生成该项（失败时加载动画自动取消，可反复点击）
- 确认通过后进入下一步

### 4. 分镜序列（图 + 文案编辑 + 视频）
- 每个分镜渲染为**一张独立卡片**（参考即梦/剪映风格）：左侧 16:9 分镜图 + 视频播放器，右侧可编辑分镜文案、镜头、光影、画面描述 Prompt
- **角色一致性**：生成分镜图时，后端会把该分镜 `character_names` 对应角色的外貌描述自动拼接到图片生成 prompt 中，使分镜角色形象与上方角色卡保持一致
- 分镜图支持**悬停替换图片**与失败重试；每个分镜可**单独点击"生成此镜视频"**
- 底部分镜缩略图时间线实时显示每个分镜的图片/视频就绪状态，点击可快速定位

### 5. 分镜视频生成
- **每个分镜独立生成一个视频**（图生视频），失败不中断流水线
- 单个分镜视频失败时卡片显示错误信息和"重新生成视频"按钮，加载动画自动取消

### 6. 合成完整短剧
- 所有分镜视频生成完毕后，点击顶部或合成区的"**合成全集**"按钮
- 后端自动**下载全部分镜视频 → ffmpeg 归一化拼接 → 生成一个完整短剧视频**（`assets/final/`）
- 合成进度通过 SSE `compose` 事件实时推送，完成后前端展示最终视频播放器
- 依赖 `imageio-ffmpeg`（自带 ffmpeg 7.1 二进制，无需系统安装）

### 7. RAG 镜头知识库
- 使用 Milvus Lite 存储镜头风格知识（如"近景人物情绪镜头，柔和侧光"）
- 可用于在生成分镜 prompt 时检索参考

### 8. MCP 工具服务
- LLM、图片生成、RAG 检索各自封装为独立 MCP Server
- 通过 stdio 协议通信，支持 Agent 以标准方式调用工具

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/task/submit` | 提交短剧生成任务（立即返回任务，流水线后台执行），body: `{"user_prompt": "创意描述"}` |
| POST | `/api/task/review` | 人工审核确认，body: `{"task_id": "...", "accept": true}` |
| GET  | `/api/task/{task_id}` | 查询任务状态和详情 |
| GET  | `/api/task/stream/{task_id}` | **SSE 实时进度流**：订阅流水线事件（status / log / char / shot_img / shot / done / fail），前端流式展示 |
| POST | `/api/task/{task_id}/replace_image` | **手动替换图片**（multipart 表单）：`target_type`(character/shot_image) + `target_id` + `file` 图片文件，保存到 `assets/uploads/` 并更新任务 |
| POST | `/api/task/{task_id}/regenerate` | **失败重试**：body: `{"task_id": "...", "target_type": "character"/"shot_image"/"shot_video", "target_id": "..."}`，后台重新生成单项并推事件 |
| POST | `/api/task/{task_id}/update_character` | **编辑角色姓名/性格**：body: `{"char_id": "...", "name": "...", "description": "..."}`，更新后推 `char_update` 事件 |
| POST | `/api/task/{task_id}/update_shot` | **编辑分镜文案/镜头/光影/Prompt**：body: `{"shot_id": "...", "content": "...", "camera": "...", "lighting": "...", "prompt": "..."}`，更新后推 `shot_update` 事件 |
| POST | `/api/task/{task_id}/compose_video` | **合成完整短剧视频**：body: `{"task_id": "..."}`，后台下载全部分镜视频并 ffmpeg 拼接，进度走 SSE `compose`/`final` 事件 |
| GET  | `/assets/*` | 上传的本地图片 / 分镜视频 / 合成视频静态访问 |
| GET  | `/docs` | Swagger API 文档 |
| GET  | `/static/index.html` | 前端演示页面 |

### SSE 进度流事件格式

前端提交任务拿到 `task_id` 后，通过 `EventSource` 订阅 `/api/task/stream/{task_id}`，实时收到以下事件：

| 事件 | 触发时机 | 关键字段 |
|------|---------|---------|
| `status` | 流水线阶段切换 | `status`: parsing / generating_asset / human_review / generating_shot / composing / done |
| `log`   | 每一步的进度日志 | `message`: 人类可读进度文本（前端以打字机效果逐字输出） |
| `char`  | 角色形象生成完成 / 替换 / 失败 | `name`, `image_url`, `index`, `total`, `status`(ok/failed), `error`, `manual` |
| `char_update` | 角色姓名/性格编辑完成 | `char_id`, `name`, `description`, `image_url` |
| `shot_img` | 分镜图生成完成 / 替换 / 失败 | `shot_id`, `image_url`, `index`, `total`, `status`(ok/failed), `error` |
| `shot_update` | 分镜文案/镜头/光影/Prompt 编辑完成 | `shot_id`, `content`, `camera`, `lighting`, `prompt`, `image_url`, `video_url` |
| `shot`  | 分镜视频生成完成 / 失败 | `shot_id`, `video_url`, `index`, `total`, `status`(ok/failed), `error` |
| `compose` | 合成视频进度 | `status`: progress / ok / failed，`message`, `index`, `total` |
| `final`  | 合成完成 | `final_video_url`: 完整短剧视频地址 |
| `done`  | 全部流程结束 | — |
| `fail`  | 流水线整体出错 | `message`: 错误详情 |

> 提示：`submit` 接口改为**异步模式**——提交后立即返回 `PENDING` 状态任务，剧本解析与角色生成在后台执行，进度通过 SSE 实时推送到前端，实现"流式输出"体验。

> SSE 去重：每个事件都带自增 `seq` 序号，前端维护 `seenSeqs` 集合；当网络闪断导致 EventSource 自动重连、服务器重放历史事件时，已处理过的 `seq` 不会重复渲染，避免日志循环刷屏。

> 缓存控制：后端对所有响应（包括 `/static/*` 和 `/assets/*` 静态资源）统一返回 `Cache-Control: no-cache, no-store, must-revalidate`，确保浏览器不会加载旧版前端页面。

> 容错设计：**单张图片/视频生成失败不会中断整个流水线**，后端发布 `status: "failed"` 事件，前端对应卡片显示"重试生成"按钮（同时取消加载动画），点击后调用 `regenerate` 接口只重新生成失败的那一项。

## 任务状态流转

```
PENDING → GENERATE_ASSET → HUMAN_REVIEW → GENERATE_SHOT → DONE
                                    ↓
                              (用户拒绝/修改) → 停留在 HUMAN_REVIEW
DONE 后用户手动逐镜生成 shot_video，
全部 shot_video 就绪后调用 /compose_video 触发合成（进度事件 composing），
合成结果写入 task.final_video_url
```

## 环境配置

### .env 文件

```env
# ====== 火山即梦 API 配置（图片/视频生成）======
VOLC_ACCESS_KEY=你的火山引擎AccessKey
VOLC_SECRET_KEY=你的火山引擎SecretKey
VOLC_REGION=cn-beijing

# ===== DeepSeek LLM 大模型 =====
LLM_API_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=你的DeepSeek API Key
```

> **注意**：
> - LLM 使用 DeepSeek（OpenAI 兼容接口），模型为 `deepseek-chat`，需在 https://platform.deepseek.com 申请 API Key
> - 图片生成使用火山即梦 Seedream（`jimeng_high_aes_general_v21_L`），需在火山引擎控制台开通「即梦AI」服务
> - 视频生成使用即梦视频生成3.0（`jimeng_t2v_v30`），需在火山引擎控制台开通「即梦AI-视频生成3.0 720P」服务，否则提交任务会返回 Access Denied
> - 火山引擎 AK/SK 在 https://console.volcengine.com/iam/keymanage 获取

## 快速启动

### 1. 安装依赖

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2. 配置环境变量

编辑 `.env` 文件，填入你的 DeepSeek API Key 和火山引擎 AK/SK。

### 3. 启动服务

```bash
python main.py
```

服务启动后访问：
- 前端演示页面: http://127.0.0.1:8010/static/index.html
- API 文档: http://127.0.0.1:8010/docs

### 4. 使用流程

1. 打开前端页面，输入短剧创意，点击"开始 AI 创作"
2. 系统自动解析剧本并生成角色形象图
3. 在"人工审核"区确认角色形象，可替换图片、编辑姓名/性格，然后点击"确认形象 · 生成分镜"
4. 系统**自动生成分镜图**（每个分镜一张 16:9 故事板）
5. 在每个分镜卡片中点击"🎥 生成此镜视频"，手动逐镜生成视频（失败可重试）
6. 所有分镜视频生成完毕后，点击"🎬 合成全集"，后端用 ffmpeg 拼接为完整短剧
7. 在前端播放完整短剧视频

## 技术栈

| 组件 | 技术 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| 数据模型 | Pydantic v2 |
| LLM 调用 | DeepSeek (OpenAI 兼容 HTTP) |
| 图片生成 | 火山即梦 Seedream (volcengine SDK) |
| 视频生成 | 火山即梦 视频生成3.0 (volcengine SDK) |
| 向量数据库 | pymilvus (Milvus Lite) |
| MCP 协议 | mcp (Model Context Protocol) |
| 前端 | 原生 HTML/JS |
| 配置管理 | python-dotenv |

## 已修复的 Bug

| Bug | 文件 | 问题 | 修复方案 |
|-----|------|------|---------|
| Character 缺少 char_id | `skill/drama_make_skill.py` | LLM 返回的角色数据不含 `char_id`，但 Pydantic 模型要求该字段，导致运行时验证失败 | 解析后用 `setdefault` 自动补全 `char_id` |
| HTML 非 ASCII 连字符 | `static/index.html` | `charset`、`Content-Type` 等使用了 Unicode 非断行连字符 (U+2011)，导致编码识别失败和请求头错误 | 替换为标准 ASCII 连字符 |
| 同步调用阻塞事件循环 | `skill/drama_make_skill.py` | 异步方法中直接调用同步的 `requests.post`，阻塞 FastAPI 事件循环 | 使用 `asyncio.to_thread()` 包装同步调用 |
| Milvus 导入路径 | `tools/rag_tool.py` | 使用 `pymilvus_lite` 包导入，兼容性差且缺少目录创建 | 改用 `pymilvus` 标准导入，并自动创建存储目录 |
| 缺少依赖清单 | 项目根目录 | 无 `requirements.txt`，无法安装依赖 | 新建 `requirements.txt` |
| SDK 方法不存在 | `tools/image_tool.py` | 调用 `high_aes_general_v21()` 方法，但 volcengine SDK 中不存在，运行时抛 AttributeError | 改用 SDK 通用方法 `cv_process()`，req_key 改为 `jimeng_high_aes_general_v21_L` |
| SDK 方法不存在 | `tools/video_tool.py` | 调用 `seedance2_video_generation()` / `seedance2_query()` 方法，SDK 中不存在 | 改用 `cv_sync2async_submit_task()` / `cv_sync2async_get_result()`，req_key 改为 `jimeng_t2v_v30` |
| LLM 接口未适配 | `tools/llm_tool.py` | 硬编码 `qwen2-7b-instruct` 模型、无鉴权头、URL 未拼接 `/chat/completions` | 适配 DeepSeek：Bearer token 鉴权 + `deepseek-chat` 模型 + URL 自动拼接 |
| Skill 引用已删除函数 | `skill/drama_make_skill.py` | `step1` 引用不存在的 `self.mcp_client` 和未定义变量；`step3` 引用已改名的 `generate_shot_video()` | 恢复 `parse_script_from_prompt` 调用；`step3` 改为 submit + query 异步任务模式 |
| LLM JSON 解析失败 | `skill/drama_make_skill.py` | DeepSeek 返回的 JSON 被 ```` ```json ```` 代码块包裹，`json.loads` 直接崩溃 | 新增 `_extract_json()`：剥离代码块围栏 + 截取首个 `{` 到末个 `}` |
| id 字段类型错误 | `skill/drama_make_skill.py` | LLM 返回的 `shot_id` 可能是整数，Pydantic 校验失败 | 强制 `str()` 转换所有 id 字段 |
| 图片服务偶发故障 | `tools/image_tool.py` | 火山引擎 t2i 服务端偶发 50500（上游连接失败） | 增加 3 次自动重试，间隔递增 |
