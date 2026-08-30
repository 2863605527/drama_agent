# Drama-Agent 配置参考

所有配置都在项目根目录 `.env`，改动后需重启服务生效。密钥（VOLC_ACCESS_KEY / VOLC_SECRET_KEY / LLM_API_KEY / ARK_API_KEY）**不得上传或外泄**。

> **换模型/换供应商原则**：同供应商换模型只改对应 `REQ_KEY`/`MODEL`；跨供应商换通道改 `*_CHANNEL` + 通道凭据。**全部配置化，代码零改动**（通道层在 `tools/media_channel.py`）。

## 大模型 LLM（OpenAI 兼容接口，可切换任意厂商）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LLM_API_URL` | `https://api.deepseek.com` | 基地址。Kimi=`https://api.moonshot.cn`，Qwen=`https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `LLM_API_KEY` | - | API Key（兼容旧变量名 `DEEPSEEK_API_KEY`） |
| `LLM_MODEL` | `deepseek-v4-pro` | 模型名：deepseek-chat / moonshot-v1-8k / qwen-plus… |
| `LLM_TEMPERATURE` | `0.7` | 生成温度 0.0~1.0 |

## 媒体通道（换供应商/换通道只改这里）

通道类型：`volc_cv`（火山即梦视觉服务，默认）/ `volc_ark`（火山方舟 Seedance 2.0 + Seedream）/ `generic_http`（通用 HTTP 第三方）。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `IMAGE_CHANNEL` | `volc_cv` | 图片生成通道 |
| `VIDEO_CHANNEL` | `volc_cv` | 视频生成通道 |

### 方舟通道（IMAGE_CHANNEL 或 VIDEO_CHANNEL = `volc_ark` 时生效）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ARK_API_KEY` | - | **必填**。方舟 API Key（`volc-sk-xxx`），需在方舟控制台开通模型并新建 Key，与即梦 AK/SK 不通用 |
| `ARK_API_URL` | `https://ark.cn-beijing.volces.com/api/v3` | 方舟 API 基地址（一般不用改） |
| `ARK_IMAGE_MODEL` | `doubao-seedream-5-0-260128` | 方舟图片模型（Seedream 系列） |
| `ARK_VIDEO_MODEL` | `doubao-seedance-2-0-260128` | 方舟视频模型：标准版 `doubao-seedance-2-0-260128` / 快速版 `doubao-seedance-2-0-fast-260128` |
| `ARK_VIDEO_RESOLUTION` | `720p` | 480p / 720p / 1080p / 4k |
| `ARK_VIDEO_RATIO` | `9:16` | 宽高比：9:16（竖屏短剧）/ 16:9 / 1:1 / 3:4 / 21:9 / adaptive |
| `ARK_VIDEO_AUDIO` | `true` | Seedance 原生音频：true=视频自带声音（自动跳过 edge-tts 配音）；false=静音视频走 TTS |
| `ARK_VIDEO_DUR_MIN` / `ARK_VIDEO_DUR_MAX` | `4` / `15` | Seedance 平台时长范围 [4,15]s，LLM 分配的秒数自动 clamp 到此区间 |

### 通用 HTTP 通道（IMAGE_CHANNEL 或 VIDEO_CHANNEL = `generic_http` 时生效）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `IMAGE_HTTP_URL` | - | 图片 POST 地址，请求体 `{"prompt","width","height"}` |
| `IMAGE_HTTP_TOKEN` | - | 可选 Bearer Token |
| `IMAGE_HTTP_URL_PATH` | `data[0].url` | 图片 URL 在响应 JSON 中的路径（点号+索引） |
| `VIDEO_HTTP_SUBMIT_URL` | - | 视频提交 POST 地址，请求体 `{"prompt","image_url"?,"duration"}`+附加字段 |
| `VIDEO_HTTP_POLL_URL` | - | 轮询 GET 地址，`{task_id}` 占位符替换为任务 id |
| `VIDEO_HTTP_TOKEN` | - | 可选 Bearer Token |
| `VIDEO_HTTP_TASK_ID_PATH` | `data.task_id` | 提交响应中的任务 id 路径 |
| `VIDEO_HTTP_STATUS_PATH` | `data.status` | 轮询响应中的状态路径 |
| `VIDEO_HTTP_SUCCESS_STATUS` | `succeeded` | 视为成功的状态值 |
| `VIDEO_HTTP_VIDEO_URL_PATH` | `data.content.video_url` | 成功时视频 URL 路径 |
| `VIDEO_HTTP_EXTRA_FIELDS` | - | 附加字段 JSON，合并进提交体（如 `{"ratio":"9:16","resolution":"720p"}`） |

## 图片模型（cv 通道）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `IMAGE_REQ_KEY` | `jimeng_high_aes_general_v21_L` | cv 通道 req_key，换即梦图片模型只改这里 |
| `IMAGE_WIDTH` / `IMAGE_HEIGHT` | `1024` / `1024` | 出图尺寸 |

> 换方舟图片模型：`IMAGE_CHANNEL=volc_ark` + `ARK_API_KEY` + `ARK_IMAGE_MODEL`。

## 视频模型（cv 通道）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `VIDEO_REQ_KEY` | `jimeng_t2v_v30` | cv 通道 req_key：jimeng_t2v_v30 / jimeng_t2v_v20 / jimeng_i2v_v21… |
| `VIDEO_DURATION` | `4` | 兜底秒数（大模型未分配时用；正常会被剧本分配的时长覆盖） |
| `VIDEO_RESOLUTION` | `720p` | 720p / 1080p |
| `VIDEO_MAX_CONCURRENCY` | `2` | 同时生成的分镜视频数（进程级排队）。调大可提速但易触发 50430 |

> 换方舟视频模型（Seedance 2.0）：`VIDEO_CHANNEL=volc_ark` + `ARK_API_KEY` + `ARK_VIDEO_MODEL` + 时长策略改任意制（见下）。

## 视频时长策略（核心：剧本决定，模型仅执行适配）

**时长唯一来源是大模型解析剧本时按叙事节奏的分配结果**，代码零写死。以下配置只是「当前视频平台的技术能力声明」，换模型时调整：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `VIDEO_DURATION_SLOTS` | `5,10` | 平台支持的时长档位（秒），逗号分隔；`any` = 支持任意时长（如 Seedance 1~15s，直接传 duration、无需裁剪） |
| `VIDEO_SLOT_FRAMES` | `121,241` | 档位模式下各档位对应的请求参数字段值（与档位一一对应）；`any` 模式忽略 |
| `VIDEO_SLOT_PARAM` | `frames` | 档位模式的请求参数字段名（即梦用 frames；其他模型若用 duration_seconds 等，改这里） |
| `VIDEO_ANY_PARAM` | `duration` | 任意时长模式的请求参数字段名 |
| `VIDEO_DURATION_RANGE` | `2,10` | 大模型可分配的单镜时长范围 min,max（**只是技术上限**，不是固定档位；换支持任意时长的模型放宽即可，如 `1,15`） |
| `VIDEO_TRIM` | `true` | 生成后是否裁剪到 LLM 分配的精确秒数。档位制=true；任意时长模型=false（原生精确，避免二次压缩） |

### 换模型/换通道示例（.env 改动）

| 目标 | `.env` 改动 |
|---|---|
| 即梦通道内换图片模型 | `IMAGE_REQ_KEY`（如 `jimeng_high_aes_general_v21`） |
| 即梦通道内换视频模型 | `VIDEO_REQ_KEY`（如 `jimeng_t2v_v20`），必要时同步档位四项 |
| **换方舟 Seedance 2.0 视频**（任意时长+原生音频） | `VIDEO_CHANNEL=volc_ark`、`ARK_API_KEY=volc-sk-xxx`、`ARK_VIDEO_MODEL=doubao-seedance-2-0-260128`、`VIDEO_DURATION_SLOTS=any`、`VIDEO_TRIM=false`、`VIDEO_DURATION_RANGE=1,15`、`ARK_VIDEO_AUDIO=true` |
| 换方舟 Seedream 图片 | `IMAGE_CHANNEL=volc_ark`、`ARK_API_KEY=volc-sk-xxx`、`ARK_IMAGE_MODEL=doubao-seedream-5-0-260128` |
| 换任意 HTTP 供应商 | `IMAGE_CHANNEL`/`VIDEO_CHANNEL=generic_http` + 对应 URL/TOKEN/JSON 路径 |

### 档位选择逻辑（`tools/video_tool.py` 的 `resolve_duration_params`）

- 档位制：选「≥目标秒数的最小档位」提交；目标超过最大档位时用最大档位并打 warning
- 任意制：直接传目标秒数
- 大模型分配 12s 而模型只有 10s 档时，按 10s 生成并告警——这是模型能力上限，不是写死

## TTS 配音（edge-tts，本地免费）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ENABLE_TTS` | `1` | 1 开 / 0 关 |
| `TTS_VOICE` | `zh-CN-XiaoxiaoNeural` | 音色：Xiaoxiao 女温柔 / Yunxi 男阳光 / Yunyang 男播音 / Xiaoyi 女活泼 |
| `TTS_RATE` | `+8%` | 语速 -50% ~ +100% |

> 视频通道为方舟 Seedance 且 `ARK_VIDEO_AUDIO=true` 时，流水线自动跳过 TTS（模型原生音频优先）。

## 火山引擎密钥

| 变量 | 说明 |
|---|---|
| `VOLC_ACCESS_KEY` / `VOLC_SECRET_KEY` | 火山引擎密钥（即梦 cv 通道图片+视频共用） |
| `VOLC_REGION` | `cn-beijing` |
| `ARK_API_KEY` | 火山方舟密钥（`volc-sk-xxx`，方舟通道专用，与上面 AK/SK 不通用） |
