---
name: drama-make-skill
description: 一句话创意 → 完整短剧视频的自动化流水线 Skill。当用户要求"生成短剧/分镜/剧本视频"、"把这段剧本做成视频"、"自动生成角色立绘和场景图"、"给分镜配音/合成完整短剧"时使用。流程：LLM 解析剧本（同时输出场景资产与片段分组，片段由 LLM 像导演一样决定每段含几个分镜，且每段总时长硬性 ≤ SEGMENT_MAX_DURATION=15 秒，超长自动拆段；step1 阶段化进度面板+已用秒数+剩余预估）→ 展示空的角色/场景模块由用户逐个手动生成或上传图片（角色立绘 + 场景昼夜双图，**黑夜图必须在白天图基础上生成、构图/建筑/物件严格一致**，未全部就绪禁止进入视频阶段）→ 人工审核 → 用户逐片段手动生成视频（cv 通道自动剥离即梦不识别的 <node-asset>/<duration-ms> 标签、强制场景一致性指令；ark Seedance 通道原生支持角色参考图）→ 手动合成（支持只合成已生成的 2 个以上片段）。所有错误信息中文（火山 API 业务错误码自动翻译为友好提示：50430 并发限流、50400 权限不足、50501 参数违规等），生成按钮带计时器+预计剩余。LLM/图片/视频供应商全部配置化，**.env 改 3 个变量即可切换 DeepSeek/Kimi/Qwen/GLM/OpenAI/本地 vLLM**，跨通道换 cv→ark Seedance 只改 IMAGE_CHANNEL/VIDEO_CHANNEL。
---

# Drama Make Skill — 短剧自动生成（v2.6.8）

一句话创意 → 完整短剧视频的自动化流水线 Skill。

## 这个 Skill 是干什么的

输入一句创意（如"校园虐恋短剧，女主被误会后伤心离开，男主追悔莫及"），
自动完成以下流程，最终产出一部合成好的完整短剧视频：

1. **剧本解析**（LLM）— 生成剧本、角色设定、分镜脚本（严格 JSON，含场景键 scene_key、口型标注 mouth_open），
   同时输出 `scenes` 场景资产（每场景独立的环境描述，不含人物）与 `segments` 片段分组
  （**片段由 LLM 像导演/剪辑师一样决定**：每段含几个分镜、共切几段，而非代码机械按场景切；短剧本通常 1~2 段，每段 2~4 镜）
2. **展示空模块 + 手动生成图片**（human-in-the-loop）— 剧本解析后展示空的角色卡片与场景卡片（昼夜双图位），
   **不再自动生成任何图**；由用户逐个点击「生成」按钮触发 AI 出图，或点「上传」用本地图片。
   每个角色一张全身立绘（多角色画风强制统一）、每场景白天/黑夜各一张纯背景空镜图（不含人物）
3. **资产齐全门槛校验** — 任一角色立绘或场景昼夜图未生成/未上传时，禁止确认审核进入视频阶段
   （前端禁用审核按钮并提示缺图数量，后端二次校验拒绝）
4. **人工审核断点** — 全部图就绪后，用户确认/修改角色与场景描述，通过后进入视频阶段
5. **片段视频手动生成**（小云雀多分镜模式）— 审核通过后**不自动生成**，
   由用户逐片段点击触发；每段用「场景锚定 + 分镜N<duration-ms> + 完整分镜描述（台词/画外音直接融入）」
   的多分镜 prompt 一次生成一段连续表演视频；失败可逐段重试
6. **手动合成完整短剧**（ffmpeg）— 用户点击「合成视频」触发：全部片段生成则合成完整短剧；
   **已生成 2 个及以上片段也可只合成已生成的部分**（后面片段不想要了直接用现有片段拼接）；
   TTS 配音按各分镜起始毫秒精确对齐混入（音画时间轴同步），原生音频通道则直接保留模型声音

## 触发场景

用户提到以下意图时调用本 Skill：
- "帮我生成短剧 / 分镜 / 剧本视频"
- "把这段剧本做成视频"
- "自动生成角色立绘和场景图"
- "给分镜配音 / 合成完整短剧"

## 输入

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| user_prompt | str | 是 | 短剧创意描述 |
| style | str | 否 | 画风：anime / realistic / 3d / q版 / 国风 / cyberpunk，默认 anime |

## 输出

`DramaTask` 对象（Pydantic），核心字段：
- `script.title` — 剧本标题
- `script.characters[]` — 角色（含 reference_image 立绘 URL）
- `script.scenes[]` — 场景资产（含 scene_key、description、day_image_url、night_image_url）
- `script.shots[]` — 分镜（含 scene_key 场景键、mouth_open 口型标注、segment_id 所属片段、duration 时长、lines 台词）
- `script.segments[]` — 片段（多个分镜合成的连续表演视频单元，含 shot_ids、scene_key、duration 总时长、video_url 片段视频）
- `final_video_url` — 合成后的完整视频本地路径

## 环境变量

密钥（不得上传/外泄）：LLM Key、火山 AK/SK、方舟 ARK_API_KEY。全部配置化，
**换 LLM、换图片/视频模型、跨供应商换通道都只改环境变量，不改代码**。

完整配置示例见仓库根 `.env.example`（脱敏模板）。

> **🔥 一致性升级指南（推荐客户阅读）**：`references/seedance_upgrade_guide.md`（同 `docs/方舟Seedance升级指南.md`）
> 如果想让人物/场景一致性大幅增强（多次生成同一角色不换脸不换装），把图片/视频通道切到
> 火山方舟 Seedance 2.0 + Seedream（原生 `role=reference_image` 参考图机制）。
> 该文档包含：效果对比表、注册开通步骤（火山引擎控制台 → 方舟 → 模型广场 → API Key）、
> `.env` 配置修改、验证步骤、常见问题（50400/模型名不匹配/回切 cv 通道）。
>
> **⚠️ 重要：cv 通道（即梦 jimeng 系列）不支持图生图**——`cv_process` 接口实测所有 i2i req_key（`seededit_v2.0_i2i` / `jimeng_image2image_*` / `jimeng_i2i_rec`）均报 50200 not supported。
> 即梦只能文生图，白天→黑夜场景图一致性**靠文字描述**维持，模型不一定强遵守。
> 切到 ark Seedream 后，黑夜图可基于白天图**真正做图生图风格迁移**，一致性大幅提升。


## 如何切换供应商（不改代码）

### 1. 切换大模型 LLM（DeepSeek / Kimi / Qwen / GLM / OpenAI / 本地 vLLM）

所有兼容 OpenAI Chat Completions 协议的供应商都能接入。**改 `.env` 的 3 个变量**：

| 供应商 | LLM_API_URL | LLM_MODEL 示例 |
|--------|-------------|----------------|
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` / `deepseek-reasoner` |
| Moonshot Kimi | `https://api.moonshot.cn` | `moonshot-v1-8k` / `kimi-k2` |
| 阿里百炼 Qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` / `qwen-max` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4/chat/completions` | `glm-4-plus` / `glm-4-flash` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` / `gpt-4o-mini` |
| 本地 vLLM | `http://localhost:8000/v1` | 任意 HuggingFace 模型名 |

设置 `LLM_API_KEY=sk-xxx` + `LLM_TEMPERATURE=0.7`，重启服务即可。`llm_chat()` 内置 3 次指数退避重试，应对网络抖动。

### 2. 切换图片/视频通道（同通道换模型 vs 跨供应商）

**同通道换模型**（推荐，零风险）：只改 `IMAGE_REQ_KEY` / `VIDEO_REQ_KEY`（cv 通道）或 `ARK_IMAGE_MODEL` / `ARK_VIDEO_MODEL`（方舟通道）。例如把即梦视频从 `jimeng_t2v_v30` 切到 `jimeng_t2v_v20`：

```bash
# .env
VIDEO_REQ_KEY=jimeng_t2v_v20
```

**跨通道**（cv → ark）：改 `IMAGE_CHANNEL` / `VIDEO_CHANNEL` + 对应通道凭据：

```bash
# .env：把图片/视频切到火山方舟 Seedance + Seedream（推荐用于真人写实/角色一致性要求高的场景）
IMAGE_CHANNEL=volc_ark
VIDEO_CHANNEL=volc_ark
ARK_API_KEY=volc-sk-xxx
ARK_VIDEO_MODEL=doubao-seedance-2-0-260128   # Seedance 2.0 标准版，支持原生参考图 + 原生音频
ARK_IMAGE_MODEL=doubao-seedream-5-0-260128  # Seedream 5.0 写实效果强
```

切到 **volc_ark** 后**所有一致性自动增强**：
- 视频通道自动启用 `role=reference_image`（角色参考图），prompt 中的 `<node-asset>` 占位标签方舟原生支持
- Seedance 2.0 原生生成音频（`ARK_VIDEO_AUDIO=true`），无需 edge-tts 配音
- 视频时长档位可放宽到 1~15 秒任意值（`VIDEO_DURATION_SLOTS=any` + `VIDEO_DURATION_RANGE=1,15` + `VIDEO_TRIM=false`）

**第三方通用 HTTP 通道**：见 `.env.example` 的 `IMAGE_HTTP_*` / `VIDEO_HTTP_*` 配置（任何 OpenAI 风格协议都能接）。

### 3. 切换视频时长策略（任意时长 / 档位制）

```bash
# 档位制（即梦 frames=121/241）：生成 5/10s 后 ffmpeg 裁剪到 LLM 分配的精确秒数
VIDEO_DURATION_SLOTS=5,10
VIDEO_SLOT_FRAMES=121,241
VIDEO_TRIM=true
VIDEO_DURATION_RANGE=2,10

# 任意时长制（Seedance）：直接传 duration 秒数，无裁剪
VIDEO_DURATION_SLOTS=any
VIDEO_TRIM=false
VIDEO_DURATION_RANGE=1,15
```

## 一致性最佳实践（角色立绘 ↔ 场景图 ↔ 视频）

根据实际验证（火山即梦 cv 通道 vs 方舟 Seedance）：

| 场景 | 推荐配置 | 原因 |
|------|----------|------|
| **anime 风格** + 场景一致性 | `volc_cv` 够用 | cv 通道已剥离即梦不识别的 `<node-asset>` 标签，强化场景一致性指令 |
| **realistic 风格** | **强烈推荐 `volc_ark`（Seedance + Seedream）** | cv 通道的 jimeng_* 通用模型对"真人写实"风格响应弱，易出插画；Seedream 写实效果稳定 |
| 角色/场景强一致性（短剧发布级） | **`volc_ark`（Seedance 2.0）** | Seedance 原生支持 `role=reference_image`，角色外貌与参考图一致性强；cv 通道 jimeng_t2v_v30 支持图生视频但一致性较弱 |
| 单条视频 > 10 秒 | `volc_ark` | cv 通道最大 10s/档，ark 通道 1~15s 任意时长 |

**风格不匹配排查清单**（选 realistic 却出卡通）：
1. 检查 `.env` 的 `IMAGE_CHANNEL`——cv 通道的 `jimeng_*` 通用模型写实响应弱，切到 `volc_ark` + `Seedream` 立竿见影
2. 升级 `IMAGE_REQ_KEY` 到更高质量的写实专用模型（如 `jimeng_high_aes_general_v30`）
3. 检查 `character.description` 描述是否含"白色/可爱/二次元"等卡通化关键词，改为"写真皮肤毛孔、85mm 镜头定妆照"
4. Skill 已自动注入"佳能 EOS R5 + 85mm 镜头"等摄影器材关键词强化写实

**视频人物/背景不一致排查清单**：
1. `VIDEO_CHANNEL=volc_cv` 时：jimeng_t2v_v30 对长 prompt 的一致性遵循有限——升级到 `volc_ark` Seedance（`role=reference_image` 原生支持）
2. 确认场景图已先生成（视频参考图优先用场景图，非角色立绘）
3. Skill 已自动：cv 通道 prompt 去掉 `<node-asset>` / `<duration-ms>` 标签（即梦不识别），改用自然语言一致性指令

**白天黑夜场景图不一致**：
- Skill v2.5.5+ 已强化：黑夜生成时若白天图已存在，prompt 自动追加"构图与白天版本完全一致（相同建筑/物件/景别/机位/角度），仅将日光替换为月光/夜色、整体改为冷暗色调"
- 前端：白天图未生成时，黑夜"生成"按钮自动禁用 + 黄色提示"请先生成白天图"

```
# LLM（OpenAI 兼容，可切换任意厂商）
LLM_API_URL=https://api.deepseek.com   # Kimi=https://api.moonshot.cn、Qwen=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=sk-xxx                     # 兼容旧变量名 DEEPSEEK_API_KEY
LLM_MODEL=deepseek-chat                # 或 moonshot-v1-8k / qwen-plus …

# 媒体通道（volc_cv 即梦 / volc_ark 方舟 / generic_http 通用 HTTP）
IMAGE_CHANNEL=volc_cv
VIDEO_CHANNEL=volc_cv
VOLC_ACCESS_KEY=xxx                    # cv 通道（即梦）密钥
VOLC_SECRET_KEY=xxx
# ARK_API_KEY=volc-sk-xxx              # 方舟通道（Seedance 2.0 / Seedream）密钥

# 视频时长策略（核心：剧本决定，模型仅执行适配）
VIDEO_DURATION_SLOTS=5,10              # 平台档位；any=任意时长
VIDEO_DURATION_RANGE=2,10              # LLM 可分配范围（技术上限）
VIDEO_TRIM=true                        # 档位制=true（生成后裁剪）；任意制=false

# TTS 配音（edge-tts，模型原生音频时自动跳过）
ENABLE_TTS=1
TTS_VOICE=zh-CN-XiaoxiaoNeural

# 并发控制（角色图+分镜图并行生成；片段视频逐段生成）
IMAGE_MAX_CONCURRENCY=3             # 同时生成的图片数（建议 2~3）
VIDEO_MAX_CONCURRENCY=2             # 同时生成的视频数（建议 1~2，防 50430）
```

## 时长策略（核心：剧本决定，模型仅执行适配）

- 时长**唯一来源是大模型解析剧本时按叙事节奏的分配结果**（台词字数÷语速 + 动作余量 + 叙事定档），
  代码里没有任何"固定 5 秒"之类的写死
- 模型能力只影响执行层：`tools/video_tool.py` 的 `resolve_duration_params()` 自动适配
  - 档位制模型（如即梦 frames=121/241 只支持 5s/10s）→ 选「≥目标秒数的最小档位」生成，再裁剪到 LLM 分配的秒数
  - 任意时长模型（如 Seedance 1~15s 原生带音频）→ 直接传 LLM 分配的秒数，不裁剪
- 换模型只改 `.env`，不改代码

## 片段视频模式（小云雀多分镜模式）

视频不是逐镜生成，而是按片段生成（更接近真实短剧生产的分镜密度与连续表演）：

1. **分组（由 LLM 决定 + 时长硬校验）**：step1 解析时 LLM 直接输出 `segments[]`（每段含 segment_id/scene_key/shot_ids），
   像 导演/剪辑师一样决定每段含几个分镜、共切几段——同场景连续分镜合为一段、每段 2~4 镜、场景切换才切新片段、
   **片段总时长（所有分镜 duration 之和）硬性 ≤ `SEGMENT_MAX_DURATION`（默认 15 秒）**、短剧本通常只切 1~2 段（禁止每镜单独成段）。
   LLM 分组后 `_enforce_segment_duration()` 强制校验：超 15 秒的片段自动在分镜边界拆成多段（例：6 镜 30s → 3 段 12s/12s/6s）。
   LLM 未输出 segments 时回退到 `_assign_segments()` 代码贪心分组（同样按 15s 上限切）。
2. **多分镜 prompt**（`_build_segment_video_prompt()`，对齐小云雀）：
   ```
   本片段场景设定在: <node-asset>scene_{scene_key}_day</node-asset>。生成一个由以下N个分镜组成的视频。
   分镜1<duration-ms>4000</duration-ms>: <完整分镜描述，含景别/动作/台词/画外音，角色用<node-asset>char_{char_id}</node-asset>占位>
   分镜2<duration-ms>3000</duration-ms>: …
   画风：… 角色外貌锁定：… 角色设定：… Negative prompt: …
   ```
   台词/画外音/内心独白直接写进分镜描述（如"他嘴唇哆嗦着说：'你……你怎么知道？！'"），
   不再单独标注"张嘴/不张嘴"括号注释；口型由 mouth_open 字段控制 TTS 配音方式，不写进 prompt 文本。
3. **配音对齐**：非原生音频通道时逐镜 TTS，再按各分镜起始毫秒 `adelay`+`amix` 混入片段视频
   （`tools/video_tool.py` 的 `mix_segment_audio()`，音画时间轴精确同步）；
   原生音频通道（方舟 Seedance + ARK_VIDEO_AUDIO=true）台词直接写进 prompt 由模型配音
4. **手动合成（支持部分合成）**：用户点击「合成视频」触发 ffmpeg 按片段顺序拼接——
   已生成片段 ≥ 2 个即可合成（未生成的片段自动跳过，适合"后面片段不想要了"的场景）；
   全部生成则合成完整短剧；仅 0~1 个片段时拒绝并提示
5. **旧数据兼容**：无 segments 的旧任务自动退回单镜生成模式（同样支持 ≥2 部分合成）

## 媒体通道与供应商切换（换供应商不改代码）

所有图片/视频生成都经过 `tools/media_channel.py` 通道抽象层：

| 通道 | `*_CHANNEL` | 适用 | 关键配置 |
|---|---|---|---|
| 火山即梦视觉服务 | `volc_cv`（默认） | 即梦 req_key 制模型 | `VOLC_ACCESS_KEY`/`VOLC_SECRET_KEY`、`IMAGE_REQ_KEY`/`VIDEO_REQ_KEY` |
| 火山方舟 | `volc_ark` | **Seedance 2.0 视频**（原生音频+参考图）、Seedream 图片 | `ARK_API_KEY`、`ARK_VIDEO_MODEL`、`ARK_IMAGE_MODEL`、`ARK_VIDEO_AUDIO` |
| 通用 HTTP | `generic_http` | 任意第三方供应商 | `IMAGE_HTTP_URL`、`VIDEO_HTTP_SUBMIT_URL`/`VIDEO_HTTP_POLL_URL` 等 |

换到方舟 Seedance 2.0 视频（任意时长 + 原生音频）示例：
```
VIDEO_CHANNEL=volc_ark
ARK_API_KEY=volc-sk-你的Key
VIDEO_DURATION_SLOTS=any
VIDEO_TRIM=false
VIDEO_DURATION_RANGE=1,15
ARK_VIDEO_AUDIO=true
```

自动适配细节：方舟提交体自动含文本提示词 + 角色参考图（role=reference_image）+
generate_audio + 竖屏 9:16；Seedance 时长 clamp 到 [4,15]s；原生音频视频自动跳过
edge-tts 配音、合成时保留原音轨不二次重编码。

## 使用案例：从创意到完整短剧视频的完整步骤

> **场景**：你想做一段 30~60 秒的校园短剧，天台上少女质问少年为何转学，少年沉默后转身离去。

### 1. 准备环境
- 安装依赖：`pip install -r requirements.txt`（含 pydantic / requests / imageio-ffmpeg / edge-tts / volcengine-python-sdk）
- 复制 `.env.example` 为 `.env`，填入 LLM/火山 KEY（其他走默认值）
- 启动：`python -m uvicorn main:app --host 0.0.0.0 --port 8010`（**不要 reload**，否则多 worker 抢任务）
- 浏览器打开 `http://127.0.0.1:8010/static/index.html`

### 2. 输入创意
在首页文本框输入（**明确指定分镜数和场景数**，避免 LLM 扩写）：
> 校园短剧：黄昏天台上少女质问少年为何转学，少年沉默后转身离去，少女追了两步停下望向远方。2个角色，3个分镜，都在天台这一个场景。

画风下拉选 `anime`（日式动漫），点「提交任务」。

### 3. 等候剧本解析（30 秒 ~ 2 分钟）
前端步骤条「解析剧本」高亮，显示**两阶段进度**：
- 阶段 1：`正在起草剧本大纲…`（DeepSeek 起草完整剧本）
- 阶段 2：`正在结构化拆解角色与分镜…`（提取角色/场景/分镜/片段分组 JSON）
- 面板同步显示**已用秒数**与**预计剩余时间**（30 秒后提示"预计还需 20~50 秒"；80 秒后提示"复杂剧本可能需要 1~2 分钟"）

解析完成后，**「角色形象与场景」栏自动展示空模块**：
- 角色卡片：「林栀」「陈屿」，含「🎨 生成立绘」与「🖼️ 上传图片」按钮
- 场景卡片：「校园天台黄昏」，含「☀️ 白天」+「🌙 黑夜」两个空位
- 审核按钮**被禁用**，提示「还有 4 张图未生成」

### 4. 手动生成图片（1 ~ 3 分钟）
依次点击每张卡的「🎨 生成」按钮（火山即梦按角色立绘 / 场景昼夜 prompt 出图），或点「🖼️ 上传」用本地图。
每生成一张，审核按钮的提示数 -1（4 → 3 → 2 → 1 → 0）。
全部就绪后审核按钮亮起，提示「🧑‍⚖️ 角色立绘与场景图已全部就绪」。

### 5. 人工审核
点击「✅ 确认通过 · 生成视频」。后端 `human_review_handle` 二次校验：任一图为空则拒绝（前端提示「❌ 还有 N 张图未生成」），全部就绪则进入视频阶段。

### 6. 逐片段生成视频（每段 1 ~ 3 分钟）
**「片段序列」栏**展示 LLM 决定好的片段（例：2 个片段，每片段 1~2 个分镜）。
每个片段卡片包含：
- 左侧：视频播放器（初始等待生成）
- 右侧顶部：片段标题 + 配音方式下拉（**自动 / 原生音频 / TTS 配音**）
- 右侧中部：**「片段 prompt」大文本框**（小云雀格式，可整体编辑后点「📥 应用到分镜」反向拆回各分镜）
- 右侧底部：「分镜摘要」只读 + 「🎥 生成片段视频」按钮

点击「🎥 生成片段视频」，后端用 `_build_segment_video_prompt` 构造 prompt（场景锚定 + 角色 `<node-asset>` 占位 + duration-ms 分镜脚本 + 角色外貌锁定 + 画风 + Negative prompt），提交到火山即梦/方舟。生成完成后下载到 `assets/videos/{tid}_{seg_id}.mp4`。

### 7. 合成完整视频
已生成片段 ≥2 即可点击「🎬 合成视频」（跳过未生成段，至少 2 段拼接）；全部生成则合成完整短剧。
合成器 `compose_final_video` 用 ffmpeg concat demuxer 拼接片段，音频按分镜起始毫秒 `adelay`+`amix` 精确对齐。

### 8. 导出与分享
合成完成后右下角出现「✅ 完整短剧视频」播放器；视频文件落盘到 `assets/final/{tid}_final.mp4`，可本地分享。

### 关键产物
- 角色立绘：`assets/uploads/{uuid}.png`
- 场景图：火山即梦返回 URL
- 片段视频：`assets/videos/{tid}_{seg_id}.mp4`
- 完整短剧：`assets/final/{tid}_final.mp4`
- 配音：`assets/audio/{tid}_{shot_id}.mp3`（TTS 模式时）

### 常见调整
- **想换画风？** 改 `STYLE_DESC_MAP`（`static/index.html`）+ `parse_prompt` 的风格描述。提交时选 `realistic` / `3d` / `q版` / `国风` / `cyberpunk`。
- **想换视频模型？** 改 `.env` 的 `VIDEO_CHANNEL` 与 `VIDEO_REQ_KEY`（即梦/方舟/通用 HTTP 通道均支持，详见 `references/config.md`）。
- **想用方�的原生音频？** `VIDEO_CHANNEL=volc_ark` + `ARK_VIDEO_AUDIO=true`，或前端把配音方式切到「原生音频」。
- **想加 BGM？** 在 `compose_final_video` 的 ffmpeg 链中追加 `-i bgm.mp3 -filter_complex amix`。

## 运行步骤（Agent 调用 SOP）

包根目录加入 `PYTHONPATH` 后：

```python
from scripts.drama_make_skill import DramaMakeSkill

skill = DramaMakeSkill()

# 1. 创建任务并解析剧本（LLM 输出角色/场景/分镜/片段分组，并分配每镜时长与台词）
task = await skill.create_task(user_prompt="...", style="anime")
task = await skill.step1_parse_script(task)
# step1 完成后状态停在 GENERATE_ASSET，不再自动生成图

# 2. 用户手动逐个生成图片（角色立绘 + 场景昼夜双图），或上传本地图片
#    每张图就绪后通过 char / scene_img 事件回填前端
task = await skill.regenerate_character_image(task, char_id)        # 单个角色
task = await skill.regenerate_scene_image(task, "scene_key:day")   # 单张场景图

# 3. 资产齐全门槛校验 + 人工审核：所有角色立绘与场景昼夜图就绪后，用户确认通过
#    （任一图为空则后端 human_review_handle 拒绝进入视频阶段）
task = await skill.step3_after_human_review(task)

# 4. 逐片段生成视频（用户手动触发；分镜会自动转发为所属片段）
for seg in task.script.segments:
    task = await skill.regenerate_segment_video(task, seg.segment_id)

# 5. 手动合成（已生成片段 ≥2 即可；全部生成则合成完整短剧）
task = await skill.compose_final_video(task)
```

进度通过 `agent/progress_hub.py` 事件流推送（event: status / log / char / scene_img / scene_update / segment / shot / compose / final），
宿主环境可订阅这些事件实现实时 UI 反馈。

## 目录结构

```
drama-make-skill/
├── SKILL.md                     ← 本文件
├── manifest.json                ← 元数据（版本/依赖/触发词）
├── scripts/
│   └── drama_make_skill.py      ← Skill 主入口（4 步 SOP）
├── tools/
│   ├── media_channel.py         ← 通道抽象层（volc_cv / volc_ark / generic_http）
│   ├── llm_tool.py              ← LLM 调用 + 剧本解析
│   ├── image_tool.py            ← 出图（按 IMAGE_CHANNEL 分发）
│   ├── video_tool.py            ← 视频提交/轮询/下载/裁剪/合成 + 时长策略
│   ├── tts_tool.py              ← edge-tts 配音
│   └── logger_tool.py           ← 日志
├── schema/
│   └── drama_schema.py          ← Pydantic 数据模型
├── agent/
│   └── progress_hub.py          ← SSE 进度事件流
├── references/
│   ├── config.md                ← 全部环境变量（换模型/换通道必读）
│   ├── architecture.md          ← 架构 + API 端点
│   └── api_reference.md         ← 外部 API 依赖说明
└── assets/
    └── logo.svg                 ← Skill 图标
```

## 设计要点（为什么这么拆）

- **角色与场景分离**：角色立绘单独生成并注入视频 prompt；场景图只出空镜（不含人物），
  片段视频以 `<node-asset>scene_{key}_day</node-asset>` 锚定场景，人物一致性由角色描述/标签保证。
- **视频立即落盘**：模型返回的 video_url 是临时签名链接（约 24h 失效），
  生成成功后立刻下载到 `assets/videos/`，前端永远用本地 URL，杜绝 403。
- **JSON 容错解析**：`_extract_json()` 用 `strict=False` + 控制字符转义兜底，
  兼容 LLM 在字符串里输出真实换行的情况。
- **单点失败不中断**：任何一个角色图/场景图失败只标记 failed，不阻塞流水线，
  事后可单独调用 regenerate_* 重试。
- **50430 并发防护**：进程级信号量排队（IMAGE_MAX_CONCURRENCY / VIDEO_MAX_CONCURRENCY）+ 提交层退避重试双保险。
- **原生音频优先**：Seedance 等带原生音频的模型自动跳过 TTS、保留原音轨。

## 已知限制

- 即梦/方舟等视频生成有账号权限门槛（需在控制台开通对应服务）
- 昼夜双图使同阶段图片并发量翻倍，可能触发火山 50430 并发限流；失败项可单独重试
- ffmpeg 合成依赖 `imageio-ffmpeg`（pip 安装即自带二进制，无需系统级安装）
- LLM 输出 JSON 偶发格式漂移，已有双层容错，极端情况仍可能要求重试
- 方舟 Seedance 只支持 4~15s，LLM 分配的秒数自动 clamp 到此区间
