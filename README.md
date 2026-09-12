# Drama-Agent · AI 短剧自动生成系统

输入一段创意描述，系统通过 Agent 自动完成「剧本解析 → 角色形象生成 → 人工审核 → 分镜图生成 → 分镜视频生成 → 合成完整短剧」的全流程，前端通过 SSE 实时推送进度。

## 技术栈

| 层 | 技术 |
|---|---|
| Web 框架 | FastAPI + Uvicorn / Gunicorn（多 worker） |
| 业务编排 | Agent + Skill（SOP 流水线） |
| 能力调用 | **全能力统一走 MCP**：LLM / 图片 / 视频 / TTS / ffmpeg 合成均经 MCP Client→Server（stdio 持久连接） |
| 大模型 | DeepSeek（剧本生成与结构化解析，走 LLM MCP，OpenAI 兼容可换通道） |
| 图片/视频 | 火山引擎即梦（cv 通道，可切方舟 ark / 通用 HTTP），经 image/video MCP |
| 多用户通道 | 每个用户可在前端自选 cv/ark/http 通道并配置自己的模型与 Key，Fernet 加密落库，提交任务时快照（详见「用户运行时通道配置」） |
| 前端 | Vue 3 + Vite + Pinia + Vue Router 工程（`frontend/`，构建产物由后端托管） |
| 配音 | edge-tts（免费，无需密钥），经 TTS MCP |
| 数据库 | MySQL 8.0（SQLAlchemy 2.0 async + aiomysql + Alembic 迁移） |
| 异步队列 | Celery + Redis（可选，`USE_CELERY=true` 启用，视频/合成剥离到独立 worker） |
| 鉴权 | JWT（PyJWT）+ pbkdf2_sha256 密码哈希 |
| 可观测 | 健康检查、Prometheus 指标、Sentry 错误上报、文本/JSON 结构化日志（按天轮转） |
| CI/CD | GitHub Actions：测试 + Skill 自测 + 镜像构建并推送 GHCR |
| 部署 | Docker + Docker Compose，版本锁定可复现构建 |

## 架构

```
浏览器  Vue3 前端 frontend/dist（根路径 /，history 路由 SPA 回退）
        │  HTTP / SSE
        ▼
FastAPI (main.py = 应用壳, 端口 8010)
  ├─ api/       路由分类包：system(健康/指标) auth(认证) channels(通道配置) tasks(任务业务) task_stream(SSE)
  │     └─ deps.py  限流工厂 / get_agent 依赖注入（agent 单例由 lifespan 注入，路由不碰全局变量）
  ├─ auth/      JWT 登录鉴权、接口归属校验、登录限流
  ├─ core/      配置 / 安全 / 限流 / Prometheus指标 / Sentry / 结构化日志 / crypto 通道密钥加密（横切层）
  ├─ agent/     DramaAgent 任务编排 + 状态机 + SSE 事件（提交时快照用户通道配置）
  │     └─ skill/  短剧生产 SOP 流水线（bind_profile 绑定任务通道，只依赖 mcp_client）
  ├─ tasks/     长任务调度：本地 asyncio 或 Celery+Redis（USE_CELERY 切换）
  ├─ mcp_client/  统一入口 DramaMcpClient（4 条 stdio 持久通道，ContextVar 任务级注入通道）
  ▼
 mcp_server/  llm_mcp   image_mcp   video_mcp   tts_mcp（stdio 子进程，stdout 只走 JSON-RPC）
        │          │           │            │
        ▼          ▼           ▼            ▼
   DeepSeek    火山图片API   火山视频+ffmpeg  edge-tts
        └──────────► MySQL 8.0（users / user_channel_configs / tasks 持久化）
                    Redis（可选：Celery broker + SSE 跨实例桥接）
```

> **统一 MCP 入口**：skill/agent 层不直接 import 任何 `tools.*` 厂商 SDK，全部能力经
> `mcp_client` 走对应 MCP Server；切换模型渠道只改 `tools/` 与 MCP Server，上层零改动。

## 目录结构

```
drama_agent/
├── main.py                    # FastAPI 应用壳：lifespan、中间件、异常处理器、路由注册、静态托管
├── api/                       # ★ REST 接口分类路由（路径与行为不变，加接口只改对应分类文件）
│   ├── system.py              # /health、/metrics
│   ├── auth.py                # /api/auth/register、/login、/me（登录限流）
│   ├── channels.py            # /api/channels/meta、/api/user/channel-config、/channel-test
│   ├── tasks.py               # /api/task/* 任务业务（创建查询/任务操作/资产图片/剧本编辑）
│   ├── task_stream.py         # /api/task/stream/{task_id} SSE 进度流
│   ├── deps.py                # rate_limit 限流工厂、get_agent 依赖注入
│   └── context.py             # 运行时单例容器（agent 实例由 lifespan init_agent 重建）
├── gunicorn_conf.py           # 生产多 worker 配置
├── core/                      # 横切层
│   ├── config.py              # 统一配置（pydantic-settings）+ 启动校验
│   ├── security.py            # 密码哈希 pbkdf2_sha256
│   ├── ratelimit.py           # 固定窗口限流器（可换 Redis）
│   ├── metrics.py             # Prometheus 指标（未装时自动降级）
│   ├── observability.py       # Sentry 初始化（无 DSN/未装时自动降级）
│   ├── crypto.py              # 用户通道密钥 Fernet 加解密（enc: 前缀，密钥由 JWT secret 派生）
│   └── deps.py                # 任务归属校验（防越权）
├── auth/                      # 注册/登录/JWT/当前用户依赖
├── agent/
│   ├── drama_agent.py         # Agent 核心：任务编排、状态机、DB 兜底加载、长任务分发、通道快照
│   └── progress_hub.py        # SSE 进度事件总线（可选 Redis Pub/Sub 跨实例桥接）
├── tasks/                     # 异步任务层
│   ├── job_runner.py          # 与执行器无关的长任务逻辑（从 DB 重建→恢复通道→跑 skill→落库）
│   ├── dispatcher.py          # 本地 asyncio / Celery 双通道分发（USE_CELERY 开关）
│   ├── celery_app.py          # Celery 实例（仅启用队列时导入）
│   └── celery_jobs.py         # 片段视频 / 合成 Celery 任务
├── skill/drama_make_skill.py  # 短剧生产 SOP（各执行入口 bind_profile，只经 mcp_client 调外部能力）
├── tools/                     # llm/image/video/tts/media_channel/rag 厂商适配（仅 MCP server 调用，profile 覆盖 .env）
├── mcp_server/                # stdio MCP Server：llm / image / video / tts（全部接通）
├── mcp_client/                # MCP Client：4 通道持久连接统一入口 + ContextVar 通道绑定
├── drama_director_skill/      # ★ 可上传的移植技能包（双模式，零 Key 客户端运行）
│   ├── SKILL.md / prompts/ / schemas/ / examples/
│   ├── runtime/               # provider 抽象：client(宿主模型) / project(工程Key)
│   └── platforms/             # Coze / 豆包 / Codex / WorkBuddy 接入指南
├── db/                        # SQLAlchemy 模型（含 UserChannelConfig）、会话、CRUD
├── migrations/                # Alembic 数据库迁移（0001 初始 / 0002 用户通道配置）
├── schema/
│   ├── drama_schema.py        # 短剧 Pydantic 数据模型（DramaTask.channel_profile 通道快照）
│   └── channel_schema.py      # ★ 通道元数据 CHANNEL_META + 校验/掩码/合并（前端动态表单唯一权威）
├── frontend/                  # ★ Vue3+Vite 前端工程（src 源码 + dist 构建产物，详见 frontend/README.md）
├── tests/                     # pytest：单元 + MCP 通道 + 通道配置接口 + 端到端 + 队列分发
├── .github/workflows/ci.yml   # CI/CD：测试 + Skill 自测 + 镜像构建推送 GHCR
├── Dockerfile / docker-compose.yml（含 redis、celery-worker，profile 按需启用）
├── requirements.txt           # 直接依赖（可读下限）
├── requirements.lock          # 精确版本锁（可复现构建）
└── requirements-dev.txt       # 测试/开发额外依赖
```

## 快速开始（Docker，推荐）

前置：已安装 Docker Desktop。

```bash
# 1. 准备环境变量
cp .env.example .env
#   编辑 .env：只需改 JWT_SECRET_KEY 为一段随机字符串、MYSQL_* 密码（生产）；
#   模型通道（大模型/图片/视频）已改为【前端登录后手动配置】，无需也不建议在 .env 里配 Key。
#   （注册地址、Key 获取、模型名怎么填：docs/媒体通道配置教程-cv-ark-http.md）

# 2. 一键启动（MySQL + 应用，首次构建约几分钟）
docker compose up -d --build

# 3. 查看状态
docker compose ps
```

启动后访问：

- 前端页面（Vue，根路径）：<http://127.0.0.1:8010/>（history 路由刷新自动回退，如 `/login`）
- 接口文档：<http://127.0.0.1:8010/docs>
- 健康检查：<http://127.0.0.1:8010/health>
- 指标：<http://127.0.0.1:8010/metrics>

> 镜像内已包含 `frontend/dist` 构建产物，由 FastAPI 在根路径托管，无需单独起前端服务。
> 若要改前端，请在 `frontend/` 下 `npm run build` 重新产出（详见 `frontend/README.md`）。

数据持久化：MySQL 数据存于 Docker 卷 `mysql_data`；生成的图片/视频、日志分别挂载到宿主 `assets/`、`logs/`。

## 快速开始（本地开发，无 Docker）

```powershell
# 0) 使用项目解释器（示例为 Windows 上的 F:\python\python.exe，需已装 requirements）
# 1) 配置环境变量（只需基础项；模型通道 Key 登录后在【前端弹窗】配置，不写进 .env）
copy .env.example .env   # 改 JWT_SECRET_KEY；VOLC_*/LLM_* 可留空
# 2) 无 MySQL 时可用 SQLite 跑通（PowerShell）
$env:DRAMA_DB="sqlite"
# 3) 构建前端（首次或前端有改动时）
cd frontend; npm install; npm run build; cd ..
# 4) 启动后端，浏览器打开 http://127.0.0.1:8010/
F:\python\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8010
# 前端热更新开发：另开终端 cd frontend; npm run dev（5173，/api 自动代理到 8010）
```

## 环境变量

完整列表见 `.env.example`，关键项：

| 变量 | 必需 | 说明 |
|---|---|---|
| `JWT_SECRET_KEY` | 是 | **生产必须**改为随机串（`openssl rand -hex 32`），否则 `ENVIRONMENT=production` 时**拒绝启动** |
| `MYSQL_*` | 是 | 数据库连接，compose 已覆盖容器内地址为 `mysql` |
| `DRAMA_DB` | 否 | 设为 `sqlite` 时用本地 SQLite（`./drama_agent.db`），免 MySQL 跑通/测试；不设则走 MySQL |
| `ASSET_SIGN_DISABLED` | 否 | 设为 `1` 关闭 /assets 媒体签名（仅内网调试，生产禁用） |
| `VOLC_ACCESS_KEY` / `VOLC_SECRET_KEY` | 否 | ⚠️ 仅兜底：**模型通道已改为前端手动配置**，.env 不配也能用（登录后弹窗填写） |
| `LLM_API_KEY` / `LLM_MODEL` | 否 | ⚠️ 仅兜底：同上，正式配置入口是前端「模型通道」弹窗 |
| `JWT_EXPIRE_MINUTES` | 否 | token 有效期（分钟），默认 1440 |
| `ENVIRONMENT` | 否 | `development` / `production`（生产强制校验密钥） |
| `CORS_ORIGINS` | 否 | 跨域白名单，`*` 或逗号分隔域名 |
| `LOGIN_RATE_LIMIT` / `API_RATE_LIMIT` | 否 | 限流，格式 `次数/时间窗` |
| `WEB_CONCURRENCY` | 否 | gunicorn worker 数，本地/SSE 建议 1，生产 2~4 |
| `MCP_CALL_TIMEOUT` | 否 | MCP 调用超时秒数，默认 180 |
| `LOG_FORMAT` | 否 | `text`（默认彩色文本）/ `json`（生产结构化单行 JSON，便于 Loki/ELK） |
| `SENTRY_DSN` | 否 | Sentry 错误上报 DSN，留空不启用 |
| `SENTRY_TRACES_SAMPLE` | 否 | Sentry 性能采样率，默认 0.05 |
| `USE_CELERY` | 否 | `false`（默认进程内后台）/ `true`（视频合成走 Celery 队列） |
| `REDIS_URL` | 队列条件 | 启用 Celery 或多实例 SSE 桥接时必填，compose 内为 `redis://redis:6379/0` |
| `CELERY_CONCURRENCY` | 否 | 单 worker 并发视频任务数，默认 2 |

> 启动时 `core/config.py` 会自动校验必需变量：缺失只告警（开发）或强提示（生产），避免运行到一半才发现密钥没配。
> **通道配置唯一入口 = 登录后前端「模型通道」弹窗**：每个用户独立配置（LLM/图片/视频，手动填模型名与 Key），
> 加密落库、按任务快照；未配置任何通道时后端才回退 `.env` 兜底。

## 数据库迁移（Alembic）

应用启动时会 `create_all` 自动建表并幂等补列（适合开发）。**生产环境建议用 Alembic 管理表结构变更**：

- `0001_initial`：users + tasks；
- `0002_channel_config`：新增 `user_channel_configs`（用户加密通道配置）与 `tasks.channel_config`（任务通道快照列）；
- `0003_episode_logs_assets`：补齐多集续写列（`parent_id` / `episode_no` / `series_title` / `logs`）与个人资产元数据表 `assets`。

> 0003 之后 `alembic upgrade head` 与启动时 `init_db` 增量补齐得到的 schema 完全一致；
> 老库若已由 init_db 补齐过，0003 的 `add_column` 会因列已存在而报错——老库请直接依赖 init_db 的幂等补齐，
> 不要重复执行 0003（全新库才需要 `alembic upgrade head`）。

```bash
# 应用到最新版本
docker exec drama-agent alembic upgrade head
# 查看迁移历史
docker exec drama-agent alembic history
# 回滚一个版本
docker exec drama-agent alembic downgrade -1
# 表结构模型变更后生成新迁移（开发机执行）
alembic revision --autogenerate -m "describe change"
```

## 测试

后端测试用 SQLite 内存库，**不依赖真实 MySQL / LLM / 火山 / Redis / Celery**（外部能力全部 mock），共 **154** 个用例：

- 安全与基建：密码哈希、JWT、限流器、配置校验、schema、注册登录、**越权拦截**、健康检查、LLM 双模式、**全局异常脱敏**（`test_error_masking.py`）；
- **P0 吊销机制**（`test_token_revocation.py`）：改密/退出所有设备后旧 token 立即失效、新登录 token 有效、payload 版本号；
- **P0 媒体签名**（`test_asset_signature.py`）：签名往返/篡改/过期拒绝、嵌套签名与去签名、`/assets` 路由无签名 403；
- **MySQL 兼容**（`test_mysql_compat.py`，`-m mysql` 标记，本地无 MySQL 自动跳过，CI MySQL 矩阵运行）：建表、`token_version` 幂等补列、用户 CRUD 改密版本自增；
- **用户通道配置接口**（`test_e2e_channel_api.py`）：元数据、空配置、保存加密、掩码回读、掩码沿用旧值、缺必填 400、媒体凭据校验、SPA 托管；MCP 工具 schema 的 profile 可空（`test_smoke_mcp_schema.py`）；
- **MCP 通道**（`test_mcp_client.py`）：持久连接只 initialize 一次、断线自动重建重试、poll JSON 解析与坏 JSON 兜底、参数序列化；
- **图片通道连接池**（`test_channel_pool.py`）：池接口与单通道同构、并发请求分发到不同子进程、超池排队、池大小跟随 `IMAGE_MAX_CONCURRENCY`；
- **SSE 短时 stream token**（`test_stream_token.py`）：签发/校验、任务绑定、篡改/过期/垃圾输入全部拒绝；
- **端到端流水线**（`test_e2e_pipeline.py`）：mock 全部 MCP 能力，完整跑 `step1 解析 → step2 出图 → step3 → 逐片段出片 → compose 合成`，并覆盖 LLM 失败路径；
- **异步队列分发**（`test_task_dispatch.py`）：`USE_CELERY` 开关在本地 asyncio / Celery `.delay` 间正确切换、完成回调被 await。

> 除单测外，另做过两类**真实链路**验证（不入库、用完即清）：① 真实 stdio 拉起 4 个 MCP Server，
> list_tools 齐全且优雅关闭（曾据此抓出「日志写 stdout 污染 JSON-RPC」「ClientSession 未进入异步上下文」两个真实缺陷并修复）；
> ② 真实 uvicorn 启动走通 注册→通道元数据→保存掩码→连通测试→SPA 托管。

```bash
# 容器内运行（生产镜像无 pytest，先装开发依赖）
docker exec drama-agent pip install -q -r requirements-dev.txt aiosqlite
docker exec drama-agent python -m pytest -q

# 本地运行（需 python3.11+）
pip install -r requirements-dev.txt aiosqlite
pytest -q

# Windows PowerShell（指定项目解释器 + SQLite）
$env:DRAMA_DB="sqlite"; F:\python\python.exe -m pytest tests -q -p no:cacheprovider

# 前端单测（Vitest，frontend/ 目录下）
npm test

# E2E 冒烟（Playwright，需后端已启动 + 浏览器已装）
npx playwright install chromium      # 首次
npx playwright test                 # 在 e2e/ 目录执行
```

> 端到端测试曾抓出一个真实并发缺陷：视频并发信号量 `_VIDEO_SLOT` 双重 acquire 泄漏许可，
> 导致第 2 个片段永久排队卡死；已修复为「仅非阻塞未拿到时才阻塞获取」。

## CI/CD（GitHub Actions）

`.github/workflows/ci.yml` 在 push / PR 时运行五个 job：

1. **test**：装依赖 → `compileall` 语法检查 → `pytest`（SQLite 内存，无需外部服务，`-m "not mysql"`）；
2. **test-mysql**（P1-6 矩阵）：起 MySQL 8 service，跑 `pytest -m mysql` 验证建表 / 幂等补列 / CRUD 兼容；
3. **frontend**：`npm ci` → Vitest 单测 → `npm run build`；
4. **e2e**（P1-7）：构建前端 + 起后端（SQLite）→ Playwright 冒烟（注册 → 工作台 → 未配置拦截 → 通道教程）；
5. **docker**：依赖前四个全部通过后，buildx 构建镜像；PR 只构建不推，push 到分支/tag 时登录 GHCR 并推送
   `ghcr.io/<owner>/drama-agent`（标签：分支名 / semver / `sha-短哈希` / 默认分支 `latest`），带 GHA 层缓存。

同一分支新推送自动取消旧运行（`concurrency`）。Fork/本地无需任何 secret 即可跑前四个 job。

## 生产部署（只配环境，不改代码）

本项目按「一次构建、到处运行」设计，上线步骤：

1. 推代码到 GitHub，CI 自动跑测试并构建镜像推送到 GHCR（`ghcr.io/<owner>/drama-agent`，分支/tag/SHA 多种标签）；也可在服务器 `docker compose build`。
2. 在服务器准备 `.env`：填入生产密钥、强随机 `JWT_SECRET_KEY`、`ENVIRONMENT=production`、收敛 `CORS_ORIGINS` 为真实域名。
3. 设置 `WEB_CONCURRENCY=2~4` 开启多 worker；`LOG_FORMAT=json` 输出结构化日志；按需填 `SENTRY_DSN`。
4. **启用异步队列**（推荐）：`USE_CELERY=true`，用 `docker compose --profile celery up -d` 一并起 Redis 与 Celery worker。
5. 首次用 `alembic upgrade head` 建表/迁移（或依赖启动自动 create_all）。
6. 前置 Nginx/负载均衡做 HTTPS 终止，把 `/health` 配为健康探测、`/metrics` 仅对内网/Prometheus 开放；Prometheus 抓取 `/metrics`，Sentry 收错误。

无需改任何代码，差异全部由环境变量注入。

### 多实例水平扩展

- 任务历史已落 MySQL，任意实例都能通过 `tasks/job_runner.load_task` / `agent.load_task` 从 DB 重建，**实例无状态、可随意扩缩**。
- 长任务下沉到 Celery worker 后，Web 实例只做 HTTP/SSE，可独立于 worker 分别扩容（`CELERY_CONCURRENCY` 控 worker 并发）。
- SSE 跨实例进度：Web 与 worker 启动时按 `REDIS_URL` 自动 `progress_hub.attach_redis`，经 Redis Pub/Sub 桥接，创建任务的实例与建立 SSE 的实例不同也能收到（代码已落地，非预留）。
- 单实例内存限流器在多实例下可替换为 Redis（`core/ratelimit.py` 接口保持不变）。

## 鉴权与安全

- 注册/登录后下发 JWT；除认证接口外所有 `/api/task/*` 都要求登录。
- SSE 因 EventSource 无法自定义请求头，token 通过 `?token=` 传递并在后端校验。
- **所有按 task_id 的操作都做归属校验**：只能访问自己的任务，他人任务返回 403（见 `core/deps.py`，测试 `tests/test_authorization.py` 覆盖）。
- 登录/注册按 IP 限流，防暴力破解与批量注册；上传图片限制 10MB，并按**文件内容魔数**识别真实格式
  （PNG/JPG/GIF/WebP/BMP），伪造扩展名的 SVG/HTML 一律 400 拒绝，防存储型 XSS。
- 密码使用 pbkdf2_sha256（规避 bcrypt 72 字节长度限制）。
- **注册格式白名单**（`auth/validators.py`，前后端同规则）：账号 3~20 位、字母开头、仅字母/数字/下划线（禁中文与特殊字符）；密码 6~20 位、仅英文字母与数字（禁中文、空格、特殊字符）。前端注册实时校验并禁用提交按钮，后端接口兜底返回 400；登录不做此限制以兼容历史账号。
- **用户通道密钥加密存储**：用户自填的 api_key/AK/SK/token 经 Fernet 加密后落库（含任务快照 `tasks.channel_config`），接口只回掩码，日志与任务快照不外泄明文；任务执行时在服务端内部解密使用。
- **安全响应头（P1-5）**：全局中间件注入 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、
  `Referrer-Policy: no-referrer`、CSP（`default-src 'self'` + `frame-ancestors 'none'`，img/media 放行 `blob:`/`https:` 以兼容成片与参考图）。
- **CORS 收敛（P1-6）**：默认仅允许本地开发白名单（127.0.0.1:5173/8010 等），不再接受 `*` 通配；生产在 `.env` 配 `CORS_ORIGINS` 实际域名。
- **Adminer 默认不启动（P1-7）**：`docker-compose.yml` 中 adminer 走 `profiles: ["adminer"]`，需要时 `docker compose --profile adminer up -d`，避免把数据库管理面板暴露在默认端口。
- **指标不再失真（P0-2）**：任务状态指标仅在 DB 状态真实变化时自增（`agent/drama_agent.py::_save_task`）。
- **生产 JWT 密钥强制（P0-3）**：`ENVIRONMENT=production` 下 JWT_SECRET_KEY 为空/占位/过短直接拒绝启动（`core/config.py`），
  docker-compose 的默认值为弱密钥占位（含历史内置串 `4f8a...` 已列入黑名单），**生产必须用 `openssl rand -hex 32` 覆盖**，否则容器拒启——这是刻意设计，防止用公开仓库可查的密钥上线导致 token 可伪造。
- **JWT 吊销（P0-1）**：`users.token_version` 随改密 / `POST /api/auth/logout-all` 自增，旧 token 立即失效（401「登录状态已失效」）；
  新增 `POST /api/auth/change-password`（校验旧密码后全端下线）。
- **媒体访问签名（P0-2）**：后端下发所有 `/assets/...` URL 附加 HMAC 签名（7 天有效），静态路由对无签名/过期/篡改请求返回 403，
  防未授权遍历与盗链；存储与生成链路保持相对路径（参考图转 base64 不受影响）。内网调试可用 `ASSET_SIGN_DISABLED=1` 整体关闭（生产禁用）。
- **审计日志（P2-11）**：`audit_logs` 表记录注册/登录（含失败）/改密/登出全部设备/删除任务/保存通道等关键事件（不含敏感值），
  用 SQL 查询 `SELECT * FROM audit_logs ORDER BY id DESC LIMIT 100;` 追溯。

## MCP 说明

### MCP 接线情况（以代码为准：LLM / 图片 / 视频 / TTS / 合成全部走 MCP）

| 能力 | 走 MCP | Client 方法 → Server 工具 → 底层 |
|---|---|---|
| LLM（剧本/分镜） | ✅ | `call_llm` → `llm_mcp` → OpenAI 兼容接口 |
| 图片（角色立绘/场景昼夜图） | ✅ | `gen_image` → `image_mcp.gen_image` → 火山即梦/方舟（带退避重试） |
| 视频提交/轮询/下载 | ✅ | `submit_video/poll_video/download_video` → `video_mcp` → 火山即梦 |
| 视频裁剪/混音/合成/探测 | ✅ | `finalize_video/mix_segment_audio/compose_videos/probe_resolution` → `video_mcp` → ffmpeg |
| 配音 TTS | ✅ | `tts_synthesize/tts_enabled` → `tts_mcp` → edge-tts（独立线程避免事件循环冲突） |

- **统一入口**：`skill/`、`agent/` 只依赖 `mcp_client/agent_mcp_client.py` 的全局单例 `mcp_client`，
  不再直接 import 任何 `tools.*` 厂商适配；替换/新增模型渠道只改 MCP Server，上层 SOP 零改动。
- **持久通道 + 并发复用**：每条通道一个专属常驻 worker task，stdio 建连/调用/关闭都在同一 task 内
  （规避 anyio 跨 task 退出 cancel scope 的问题），并在 worker 内对 JSON-RPC 做多路复用；
  通道异常自动重建并重试一次，应用关闭时统一 `mcp_client.close()` 优雅退出。
- **指标**：每次调用按通道埋 `drama_media_calls_total` / `drama_media_latency_seconds`，LLM 另有独立指标。
- MCP Server 日志禁止写 stdout（会污染 stdio 协议），错误走 stderr 并在 Client 侧抑制。
- **大响应文件旁路（重要稳定性设计）**：MCP stdio 在单条 JSON-RPC 消息较大、且叠加网络返回等场景时
  可能出现「上游已 200 但 `call_tool` 迟迟不回包」的假死（剧本结构化解析 JSON 最易触发，表现为解析偶发卡死）。
  因此 `mcp_server/_mcp_io.py` 约定：工具返回文本超过 `MCP_INLINE_MAX`（默认 8000 字符）时落盘到
  父子进程共享的临时目录，stdio 只回一个短信封 `{__mcp_large_file__: 路径}`，Client 收到后读文件还原并删除；
  小响应原样直传、零开销。新增会返回大文本的 MCP 工具时，用 `wrap_large()` 包裹返回值即可。
- `DramaMakeSkill(llm_provider=...)` 仍支持注入自定义 LLM 来源（可移植 Skill 包的客户端模式使用），
  不传则走上述 MCP（项目模式，默认）。
- `rag_mcp` / Milvus 为独立预留能力，不在短剧主流程链路。

## 用户运行时通道配置（多用户自选 cv / ark / http + 模型 + Key）

> **新版已移除「系统默认(.env)」选项**：前端「模型通道」弹窗中，大模型 / 图片 / 视频三段的通道下拉
> 只提供真实通道（OpenAI 兼容 / 火山即梦 CV / 火山方舟 ARK / 通用 HTTP），**不再有 `env` 选项**，
> 所有能力均需在弹窗内手动选择通道并填写模型与 Key。
> 旧版本里保存过 `env` 的用户，弹窗会给出警示提示引导重新手动配置；`.env` 仅在用户完全未配置任何
> 通道时作为最后兜底，保证升级后仍能跑通，不是主配置入口。

### 通道类型（以 `schema/channel_schema.py` 的 `CHANNEL_META` 为唯一权威）

| 能力 | 可选通道 | 关键凭据/参数 |
|---|---|---|
| 大模型 LLM | `openai`（OpenAI 兼容自定义 base_url+key+model） | api_key、base_url、model |
| 图片 | `volc_cv`（火山即梦视觉，AK/SK+req_key）/ `volc_ark`（方舟，Bearer Key+模型）/ `generic_http`（通用 HTTP） | access_key/secret_key/req_key 或 api_key/model |
| 视频 | `volc_cv` / `volc_ark` / `generic_http`，另含分辨率、宽高比、原生音频开关 | 同上 + model/resolution/ratio |

### 数据流与安全

1. 前端表单字段、分辨率、宽高比等固定枚举由 `GET /api/channels/meta` 动态下发，前端不硬编码；**图片/视频/大模型的"模型名"一律为手动填写输入框**（配 datalist 常用模型候选，可自由输入任意最新模型而不受下拉限制），每个通道在 placeholder 里给出示例与填写提示。
2. 保存走 `PUT /api/user/channel-config`：后端做必填校验，敏感字段（api_key/access_key/secret_key/token）
   用 **Fernet 加密**后写入 `user_channel_configs` 表（一人一条）；读取只回 `__MASKED__xxxx` 掩码，
   前端留空不改时后端自动沿用旧值（`merge_profiles`）。
3. **提交任务时把该用户配置解密后快照进 `tasks.channel_config`，快照以加密形式落库**（`enc:` 前缀，P1-3），
   运行时解密为内存明文使用；启动时自动检测历史明文快照并一次性迁移加密。
   整条流水线（含重启恢复）都用这份快照，事后再改通道配置不影响在跑任务，保证可复现。
4. 运行时通过 **ContextVar 任务级绑定**下发：Skill 每个执行入口 `mcp_client.bind_profile(task.channel_profile)`，
   门面方法签名保持稳定，asyncio 并发任务天然隔离；profile 为空（未配置）时 MCP Server / tools 100% 回退 `.env` 兜底。
5. **重试与续写自动跟随最新通道（401 修复）**：任务点「重新开始」或续写下一集时，会先
   `_refresh_media_profile` 用用户「当前最新」的 LLM/图片/视频配置覆盖任务旧快照——旧快照 llm 段为 null
   （创建时未配置）的任务不再永远走 `.env` 兜底，避免因 `.env` Key 失效/过期导致 LLM 401。
6. **续写归入同一对话**：左侧对话列表只显示系列根任务（续写各集按 `parent_id` 归并，显示「共 N 集」与最新一集状态）；
   点击进入系列最新一集；删除根任务时后端级联删除同系列所有子任务（`crud.delete_task`），本地列表同步移除整个系列。

### 相关接口（均需 Bearer JWT）

| 方法/路径 | 作用 |
|---|---|
| `GET /api/channels/meta` | 返回三类能力的通道、必填字段、模型预设、分辨率/宽高比元数据 |
| `GET /api/user/channel-config` | 读取当前用户的脱敏（掩码）配置，未配置返回 null |
| `PUT /api/user/channel-config` | 校验 + 掩码合并 + 加密保存，返回脱敏配置 |
| `POST /api/user/channel-test` | 连通测试：LLM 发极简真实 ping；图片/视频只校验凭据完整性（不烧额度） |

> 加密密钥默认由 `JWT_SECRET_KEY` 经 SHA256 派生；生产建议改为独立环境变量/KMS 托管并支持轮换。

### 通用 HTTP 通道怎么填（以硅基流动 SiliconFlow 为例）

> 📖 **三通道注册/Key 获取/模型名填写图文教程**见 [`docs/媒体通道配置教程-cv-ark-http.md`](docs/媒体通道配置教程-cv-ark-http.md)（含火山即梦 cv、方舟 ark、硅基流动 HTTP 的注册地址、Key 位置截图与模型名对照表）。

选「通用 HTTP」后，**前端只需填 3 项：服务地址 BaseURL、Bearer Token、模型名（手填）**，
后端 `tools/http_presets.py` 会按**域名自动识别平台**并补全提交/轮询地址、结果路径、状态枚举、参考图字段等全部技术细节，
本地参考图自动转 base64 上传。已内置硅基流动、智谱 BigModel、OpenAI 官方三套预设，未识别的平台按 OpenAI 兼容默认兜底；
特殊平台可展开「高级设置」逐项覆盖（用户值优先）。连通测试会真实请求只读的 `/v1/models` 验证地址与 Token，
不再只做表单完整性校验。

**最简填法（以硅基流动为例，图片/视频都是这 3 项）**

| 表单项 | 图片 | 视频 |
|---|---|---|
| 服务地址 BaseURL | `https://api.siliconflow.cn` | `https://api.siliconflow.cn` |
| Bearer Token | 硅基 `sk-...` | 同一个 `sk-...` |
| 模型名 | `Kwai-Kolors/Kolors` | 图生 `Wan-AI/Wan2.2-I2V-A14B` / 文生 `Wan-AI/Wan2.2-T2V-A14B` |

后端据此自动补全（无需手填）：图片 POST `/v1/images/generations`、取 `images[0].url`、尺寸字段 `image_size`；
视频 POST `/v1/video/submit`（剔除其不收的 `duration`），POST `/v1/video/status` 轮询、body `{"requestId":"{task_id}"}`、
成功枚举 `Succeed`、取 `results.videos[0].url`。智谱/OpenAI 同理自动切换为各自路径与枚举。

> 换任何新平台：先只填根地址 + Key + 模型试一次；若该平台返回结构特殊，再展开「高级设置」覆盖对应路径即可，无需改代码。
> 结果/状态路径支持 `a[0].b` 下标语法。**已有任务改了通道也立即生效**：在任务里点重绘/重生成时会用你当前最新的图片/视频通道（LLM 剧本段仍用创建时快照）。

### 图片预览与清除
- 角色立绘、场景昼夜图**点击即可放大全屏预览**（点空白或右上角关闭）；
- 每张图提供「清除」按钮，回到未生成状态可重新生成/上传（清除白天图会连带清除依赖它的黑夜图，任务状态只进不退）。

## 健壮性与资产生命周期

- **低成本剧本自检断点**：step1 解析、片段确定性分组之后、烧钱出图/出视频之前，`DramaMakeSkill._self_check_script`
  先校验角色/场景/分镜/片段引用完整性与时长，悬空角色引用自动剔除，结构性硬错误（空结构、引用不存在分镜、
  片段时长 0 等）直接拦下任务，不产生图片/视频费用，并在日志提示重新开始。
- **片段视频崩溃点修复（P0-1）**：片段执行处不再读取空 refs 数组下标（原 `refs[0]` 在无引用片段上会抛
  IndexError 直接打崩流水线），改为空引用时记 warning 并跳过，任务其余片段照常执行。
- **出片后 ffprobe 复核**：片段视频落盘后用 ffmpeg 解析实际时长与音轨（`probe_video_quality`），
  实际时长与脚本时长偏差过大、或含台词却检测不到音轨时，在该片段上标记 `quality_warning`（前端橙色提示，建议重生成）。
- **启动 reconcile**：进程/容器重启后 `tasks/reconcile.py` 扫描任务——卡在 `pending`（解析中、无法续跑）的标记
  failed 并写日志；资产/审核/视频等人工断点阶段任务保持原状态可继续操作，不再永久卡 PENDING。
- **个人资产元数据表（assets）**：图片/视频/音频的文件本体存磁盘 `assets/`（未来可平滑切换 MinIO/OSS 对象存储），
  MySQL `assets` 表只登记元数据——归属用户、类型（角色/场景昼夜/片段视频/配音/成片/上传）、来源（ai/upload）、
  体积、sha256、引用次数。任务每次落库（`crud.update_task`）幂等登记其引用的本地资产，启动时 `backfill_all_assets`
  全量回填存量（不移动文件），`rebuild_ref_counts` 重算引用数。用户上传按用户分目录 `assets/u{user_id}/uploads/`，
  历史扁平目录（images/videos/audio/final/uploads）继续兼容。
- **安全孤儿资产回收**：`tasks/asset_gc.py` 四重判定后才删除——① 数据库引用集合为空时整体跳过（空库/连接失败
  绝不等于"全部是孤儿"）；② 只回收**已在 assets 表登记**、③ 现场扫描确认**不被任何任务引用**、④ **非用户上传**的文件；
  未登记的磁盘文件一律保留（只计数），表中磁盘已不存在的悬空记录一并清理。删除任务会同步清理其前缀专属的视频/音频/成片。
- **图片统一落盘**：所有生成图（角色/白天/黑夜，任意通道）成功后下载到 `assets/images`，前端用本地 URL，
  避免供应商签名链接过期（硅基约 1h、火山约 24h）导致裂图；图生图/图生视频的本地参考图自动转 base64。
- **MCP 错误不再伪装成图片 URL**：MCP 工具返回 `isError`（如火山 50400 限流）时按失败重试/抛错处理，
  图片门面再校验返回必须是合法图片地址，杜绝「错误文本被当 URL 回填导致前端裂图」。
- **图片通道连接池（P1-3）**：图片 MCP 从单条串行通道改为 `_ChannelPool`（默认 3 条，跟随
  `IMAGE_MAX_CONCURRENCY`），多张角色/场景图**真正并行出图**而非排队串行；池惰性建连、按队列最短分发、
  并发超池自动排队，接口与单通道同构（调用方零改动）。
- **SSE 短时 stream token（P1-5）**：JWT 不再出现在 SSE URL query（避免进访问/代理/历史日志）。
  前端先 `POST /api/task/{task_id}/stream_token` 用 Authorization 头换取 60s 有效、绑定
  task_id+user_id、HMAC 签名的短时 token，EventSource 只带该 token；连接断开/过期时前端自动重新签发重建。
- **全局异常脱敏（P1-4）**：未处理异常不再把内部细节（SQL/路径/表名）回传前端，统一返回
  「服务器内部错误，请稍后重试（错误码 xxxxxxxx）」，完整堆栈仅落日志并按 trace id 定位。
- **静态资源分级缓存（P2-7）**：`/assets` 下 `images/`、`uploads/`（uuid 文件名，内容变则 URL 变）
  长缓存 `immutable`；`videos/`、`audio/`、`final/` 任务重跑会覆盖同名文件，保持 no-cache 防旧成片。

## 异步任务队列（Celery + Redis，可选）


视频生成（数分钟）与 ffmpeg 合成是长任务。系统提供两条执行通道，由 `USE_CELERY` 切换，**执行体完全相同**（`tasks/job_runner.py`，只认 task_id、从 DB 重建任务、结果落库）：

- `USE_CELERY=false`（**默认，本地零依赖**）：Web 进程内 `asyncio.create_task` 后台执行，请求立即返回，SSE 推进度；
- `USE_CELERY=true`（生产）：投递到 Redis 队列，由独立 `celery-worker` 容器消费，Web 进程不阻塞、可水平扩展；worker 进度经 Redis Pub/Sub 桥接回 Web 的 SSE。

```bash
# 本地/单机：默认即可（MySQL + Web + Adminer）
docker compose up -d --build

# 生产启用队列（额外起 Redis + Celery worker）
USE_CELERY=true docker compose --profile celery up -d --build
docker compose logs -f celery-worker        # 看 worker 消费
```

设计要点：`task_acks_late`（worker 崩溃任务重投，不丢）、`worker_prefetch_multiplier=1`（长任务公平分发）、
软/硬超时 1800s/2100s、失败自动重试 1 次；Web 与 worker 挂载同一 `assets/` 卷共享片段与成片。

## 可观测性

- **Prometheus 指标**：`GET /metrics`（Prometheus 拉取）。含任务计数/状态、进行中 gauge、LLM 与媒体
  调用次数与耗时直方图、HTTP 请求数与耗时（路径自动归一化为路由模板，避免 task_id 造成高基数标签）。
- **Sentry**：配置 `SENTRY_DSN` 即启用错误与异常上报（FastAPI/asyncio 集成，`send_default_pii=False` 不上报隐私）；
  未配置或未装 `sentry-sdk` 时静默降级，不影响启动。
- **结构化日志**：`LOG_FORMAT=text` 为彩色文本（本地），`LOG_FORMAT=json` 为单行 JSON（生产，可直接被
  Loki/ELK 采集）；后台任务自动通过 contextvars 携带 `task_id`/`job` 字段，可按任务串联全链路日志。

## 备份与恢复

一键全量备份，Windows 与 Linux 各一个脚本（逻辑一致）：

**Windows + Docker**：`scripts/backup.ps1`

```bash
powershell -ExecutionPolicy Bypass -File scripts\backup.ps1            # 默认保留最近 7 天
powershell -ExecutionPolicy Bypass -File scripts\backup.ps1 -DaysToKeep 14
```

**Linux 服务器 + Docker**：`scripts/backup.sh`

```bash
bash scripts/backup.sh                          # 默认保留最近 7 天
DAYS_TO_KEEP=14 bash scripts/backup.sh
DRAMA_MYSQL_PWD=xxx bash scripts/backup.sh      # 密码走环境变量，不写死
# crontab -e 每天 03:00：
# 0 3 * * * cd /opt/drama_agent && bash scripts/backup.sh >> logs/backup.log 2>&1
```

- 备份内容：① MySQL `drama_agent` 库（容器内 mysqldump+gzip 后 `docker cp` 出来，避免管道损坏二进制）
  → `backups/mysql/drama_<时间戳>.sql.gz`；② 全部媒体素材 `assets/` → `backups/assets/assets_<时间戳>.tar.gz`；
- 恢复：`gunzip -c drama_*.sql.gz | docker exec -i drama-mysql mysql -udrama -p drama_agent`；
  `tar -xzf assets_*.tar.gz -C <项目根>`；
- Windows 定时备份示例：`schtasks /Create /TN "DramaAgentBackup" /SC DAILY /ST 03:00 /TR "powershell -ExecutionPolicy Bypass -File F:\AI学习\drama_agent\scripts\backup.ps1" /F`；
- `backups/` 已加入 `.gitignore`，不入库。

## 文档索引（docs/）

| 文档 | 内容 |
|---|---|
| [`媒体通道配置教程-cv-ark-http.md`](docs/媒体通道配置教程-cv-ark-http.md) | ★ 三通道图文教程：注册地址、Key 获取位置（含截图）、模型名对照、常见问题 |
| [`方舟Seedance升级指南.md`](docs/方舟Seedance升级指南.md) | 前端弹窗切换方舟（ark）通道的完整步骤、效果对比与常见问题 |
| [`硅基流动视频通道配置指南.md`](docs/硅基流动视频通道配置指南.md) | 通用 HTTP 通道对接硅基流动的逐字段填法与踩坑记录 |

## 常用运维命令

```bash
docker compose logs -f drama-agent     # 跟踪日志
docker compose restart drama-agent     # 重启
docker compose down                    # 停止（数据卷保留）
docker exec drama-mysql mysql -u drama -p drama_agent   # 进数据库
powershell -File scripts\backup.ps1    # 全量备份（MySQL + assets，见「备份与恢复」）
```

## 核心生产流水线

1. **剧本解析（S1/S2）**：LLM 先写剧本 → 再调 LLM 解析为结构化 JSON（标题/角色/场景/分镜），约束角色外貌一致性与导演式时长分配；**片段不再由 LLM 自由切分**，而是解析后由代码 `_assign_segments` 做确定性分组（同一连续场景、每段 ≤`SEGMENT_MAX_SHOTS` 镜才合并，场景切换才切段），并做**合并优先的时长再平衡**：同场景分镜总时长仅略微超 `SEGMENT_MAX_DURATION`（默认 15s，视频通道单次硬上限）时，等比压缩组内各镜（每镜不低于下限、最多压缩约 1/3，避免快进感）仍保持一段，明显过长才拆段，从而尽量让「同场景多个分镜 = 一个片段 = 一段视频」。
2. **形象资产（S3/S4）**：并发生成角色立绘（1:1）与每个场景的昼夜环境图（16:9，画面不含人物），完成进入**人工审核断点**，支持改角色、替换图、单项失败重试。**场景黑夜图硬性依赖白天图**：每个场景先生成/上传白天图（文生图，白天图可生成也可本地上传），黑夜图再以白天图为**参考底图做图生图**（火山即梦图生图3.0，`req_key=jimeng_i2i_v30`，经 `IMAGE_I2I_REQ_KEY` 配置，`media_channel._edit_image_cv` 异步提交+轮询，prompt 强制保持同一构图只把日光改为夜色）；白天图缺失时前端黑夜「生成」按钮锁定为"先出白天图"、后端也会直接报错拒绝。重新生成/上传白天图后，与之配套的旧黑夜图会被自动清空（SSE `scene_img` 的 `reset` 事件），需基于新白天图重出黑夜，避免昼夜不匹配。**分段式渲染**：前端按就绪度逐级渲染组件——剧本解析完才显示资产面板，`assetsReady`（全部角色立绘 + 每场景昼夜双图齐全，含续写继承）为真之前**不渲染片段视频组件与合成组件**，图补齐后才出现。**状态只进不退**：一旦进入人工审核及之后的阶段，重绘/上传只更新图片本身、不再回退状态（是否继续由用户自己决定）；重绘导致图暂时不齐时，片段/合成组件随之隐藏、补齐后重新出现。**上传始终自由**：角色与场景（含黑夜）的「上传」按钮在任意时刻都可用，不受其他图片生成中影响；黑夜即使白天为空也允许直接上传（用户自备图无需再改），仅「生成」黑夜要求先有白天图。此外结构化解析对 LLM 偶发漏返回 `characters/shots` 做了一次自动重试，两次都失败才给出可读报错（不再抛裸 `KeyError`）。**跨通道参考图**：黑夜以白天图为参考的图生图在三个图片通道均可用——cv 走即梦图生图3.0（`_edit_image_cv`），方舟 Seedream 在同一 `images/generations` 请求体带 `image` 参考图，generic_http 透传参考图字段（`IMAGE_HTTP_REF_FIELD`，默认 `image`）。场景文生图 prompt 额外强制"只画描述到的环境、不得添加飞机/车辆等描述之外的物体"，避免模型凭空添物。
3. **片段视频（S5）**：一个片段包含同场景的多个分镜，片段 prompt 逐镜标注时长、参考资产、台词与是否张嘴（内心独白不张嘴、对白口型同步）；前端在每个片段卡片上**手动点「生成片段视频」**（也可一键生成全部），以场景图+角色立绘做图生视频，逐片段独立、失败不断流；片段成功后**先 persist 落库再广播 `segment ok`**（`job_runner`），前端回拉详情不会因时序差把视频 URL 覆盖为空，并在 store 层对已回填视频做合并保护；**审核确认只把任务推进到视频阶段、不自动生成任何视频**，全部由用户逐片段手动点击，顶部计时动画也仅在确有片段生成时才出现；TTS 配音或模型原生音频，ffmpeg 精确裁剪/混音。
4. **合成全剧（S6）**：下载全部片段，ffmpeg 按序无损拼接为完整短剧，进度经 SSE 推送。
5. **进度日志持久化与前端自愈**：每条 SSE 事件带自增 `seq`，同时经 sink 防抖落库到 `tasks.logs`；前端打开任务时以库内日志为基线、按 `seq` 去重只补增量，**刷新页面 / 容器重启后历史执行日志不丢**；剧本解析完成的状态跃迁会自动回拉详情，无需手动 F5 即可渲染角色/场景/片段组件。SSE 事件总线为**每个连接维护独立队列并扇出广播**（非多连接共享单队列），连接关闭即注销，因此多标签页、EventSource 自动重连、容器重建后重连都不会出现"事件被断开的旧连接抢走、当前页面收不到实时日志"的问题。手动逐张生成角色/场景图时，按钮即时进入 loading、图片框显示旋转遮罩、顶部计时条显示"正在生成哪张 + 已耗时/预计时长"，出图完成自动恢复，避免"点了没反应"；多张图可并发点，各自独立显示遮罩/禁用，计时条聚合显示"正在生成 N 张"。**手动逐张出图补齐最后一张后，后端自动把任务从「待生成形象」跃迁到「人工审核」**（`DramaAgent._maybe_advance_to_review`，判定 `_all_assets_ready`：全部角色立绘 + 每场景昼夜图齐全，含续写继承图），无需依赖自动批量分支，审核栏会自动弹出。前端「工程执行日志」卡片为 `position: sticky` 吸附在执行栏顶部，下方剧本/图片/片段面板展开、整页滚动时日志始终可见，且新日志到来时若被折叠会自动展开；片段视频按钮在未通过人工审核（未进入 `generating_video`）前为锁定态并给出引导，进入后点击**立即**显示"视频生成中"动画与日志（不等待接口往返）。
6. **多集续写（新增下一集）**：成片后可「新增下一集」，后端新建独立子任务（`parent_id` 指向系列首集、`episode_no` 自增、共享 `series_title`），step1 携带上一集剧情与已有角色/场景清单做续写，并按角色名 / 场景键把上一集已生成的立绘与场景图**原样继承**（标记 `inherited`，前端显示「↪ 沿用」），仅新角色、新场景需要生成形象；通道配置一并继承。接口：`POST /api/task/{parent_id}/episode`。
7. **书架视图（工程收进口）**：某集流程走完（done）后，工作台自动切换为**书架视图**——同系列每一集是一册竖排书脊样式的书（红棕渐变，已完成红棕/进行中暗金呼吸闪烁/失败灰紫，按 `episode_no` 从左到右排列），点书体直接弹出该集成片播放器、点「翻开」进入该集流程详情；书架末尾有虚线「＋ 续写第 N 集」占位书直达续写输入框。系列归组沿 `parent_id` 链找根任务，同一系列所有集共用一个书架，续写完成后书架自动多一本。
