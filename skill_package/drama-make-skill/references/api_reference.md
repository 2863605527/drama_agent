# 外部 API 依赖说明

本 Skill 依赖以下外部服务，使用前必须配置环境变量并开通对应服务。
所有供应商/通道均配置化（`tools/media_channel.py` 分发），**换模型/换通道不改代码**。

## 1. LLM（OpenAI 兼容接口，可切换任意厂商）

| 项 | 值 |
|---|---|
| 环境变量 | `LLM_API_URL` / `LLM_API_KEY` / `LLM_MODEL`（兼容旧变量名 `DEEPSEEK_API_KEY`） |
| 默认 | DeepSeek：`https://api.deepseek.com` + `deepseek-chat` |
| 可选厂商 | Kimi=`https://api.moonshot.cn`+`moonshot-v1-8k`；Qwen=`https://dashscope.aliyuncs.com/compatible-mode/v1`+`qwen-plus`；本地 vLLM=`http://127.0.0.1:8000/v1` |
| 协议 | OpenAI 兼容 `/chat/completions` |
| 用途 | ① 剧本草稿生成 ② 剧本结构化解析（角色 + 分镜 JSON + 每镜时长分配） |
| 获取 | 各厂商控制台创建 API Key |

计费按 token，一次短剧解析约消耗 2k~5k token。

## 2. 媒体通道（图片 / 视频，由 `IMAGE_CHANNEL` / `VIDEO_CHANNEL` 选择）

### 2.1 火山即梦视觉服务（`volc_cv`，默认）

| 项 | 值 |
|---|---|
| 环境变量 | `VOLC_ACCESS_KEY` / `VOLC_SECRET_KEY` |
| SDK | `volcengine-python-sdk`（pip 安装） |
| 图片接口 | `VisualService.cv_process`，req_key=`jimeng_high_aes_general_v21_L`（`IMAGE_REQ_KEY` 可改） |
| 视频接口 | `cv_sync2async_submit_task` / `cv_sync2async_get_result`，req_key=`jimeng_t2v_v30`（`VIDEO_REQ_KEY` 可改） |
| 视频时长 | frames 档位制（121=5s / 241=10s），生成后 ffmpeg 裁剪到 LLM 分配秒数 |
| 注意 | 视频服务需控制台单独开通「即梦AI-视频生成」，否则 code=50400；并发超限报 50430，内置退避重试 + 进程级排队 |

### 2.2 火山方舟（`volc_ark`）

| 项 | 值 |
|---|---|
| 环境变量 | `ARK_API_KEY`（`volc-sk-xxx`，与即梦 AK/SK 不通用） |
| API 基地址 | `https://ark.cn-beijing.volces.com/api/v3`（`ARK_API_URL`） |
| 图片 | `POST /api/v3/images/generations`，模型 `doubao-seedream-5-0-260128`（`ARK_IMAGE_MODEL`） |
| 视频 | `POST /api/v3/contents/generations/tasks` + `GET /tasks/{id}`，模型 `doubao-seedance-2-0-260128`（`ARK_VIDEO_MODEL`） |
| 视频特性 | 原生音频（`ARK_VIDEO_AUDIO=true` 自动跳过 TTS）、角色参考图（role=reference_image）、任意时长 4~15s（LLM 分配自动 clamp） |
| 宽高比 | `ARK_VIDEO_RATIO` 默认 9:16 竖屏 |
| 开通 | 方舟控制台开通模型 + 新建 API Key |

### 2.3 通用 HTTP（`generic_http`）

| 项 | 值 |
|---|---|
| 图片 | `IMAGE_HTTP_URL`，请求体 `{"prompt","width","height"}`，URL 路径 `IMAGE_HTTP_URL_PATH`（默认 `data[0].url`） |
| 视频 | `VIDEO_HTTP_SUBMIT_URL`（POST）+ `VIDEO_HTTP_POLL_URL`（GET，`{task_id}` 占位）+ 状态/URL JSON 路径全可配 |
| 鉴权 | `*_HTTP_TOKEN` 可选 Bearer Token |
| 附加字段 | `VIDEO_HTTP_EXTRA_FIELDS` JSON 合并进提交体 |

## 3. TTS 配音（edge-tts，本地免费）

| 项 | 值 |
|---|---|
| 环境变量 | `ENABLE_TTS`（默认 1）/ `TTS_VOICE`（默认 zh-CN-XiaoxiaoNeural）/ `TTS_RATE`（默认 +8%） |
| 用途 | 分镜台词/旁白合成语音混入视频 |
| 自动跳过 | 视频通道为方舟 Seedance 且 `ARK_VIDEO_AUDIO=true` 时（模型原生音频优先） |
| 安装 | `pip install edge-tts`（联网合成） |

## 4. ffmpeg（视频合成）

不依赖系统安装：`pip install imageio-ffmpeg` 自带二进制。
如系统已有 ffmpeg 则优先使用系统版本。

## 安全声明

- 本 Skill 不收集、不上传任何用户数据
- 所有 API Key 仅从环境变量读取，不落盘、不打印（打包 zip 不含 .env）
- 生成产物（图片/视频）保存在运行目录 `assets/` 下，归用户所有
