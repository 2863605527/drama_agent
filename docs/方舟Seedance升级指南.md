# 升级指南：切换到火山方舟 Seedance 2.0（人物/场景一致性大幅增强）

> 适用版本：drama-agent v2.6.0+ ｜ 预计耗时：15~30 分钟 ｜ 只需要改 `.env`，**不需要改任何代码**

---

## 一、先说结论：ark 通道的效果到底如何？

| 对比项 | 当前默认 `volc_cv`（火山即梦 jimeng） | 推荐 `volc_ark`（方舟 Seedance 2.0 + Seedream） |
|--------|--------------------------------------|-----------------------------------------------|
| **角色一致性** | 弱——靠"参考图 + prompt 文字描述"双重作用，多次生成可能换脸/换装 | **强**——原生 `role=reference_image` 参考图机制，多次生成同一角色基本一致 |
| **场景一致性** | 弱——prompt 文字描述为主 | **强**——视频以场景图/角色图为参考锚定 |
| **真人写实风格** | 弱——jimeng 通用模型偏插画 | **强**——Seedream 5.0 写实效果好（皮肤毛孔/光影/镜头质感） |
| **原生音频** | 无，靠 edge-tts 后期配音 | **有**——Seedance 2.0 原生生成声音+台词（`ARK_VIDEO_AUDIO=true`） |
| **视频时长** | 只有 5s/10s 两档（超出会被 clamp） | **1~15 秒任意时长**，原生精确，不裁剪不压缩 |
| **失败率** | 较高（50412 内容审核/参数错误较常见） | 较低 |

**重要说明（诚实版）**：
- Seedance 的参考图一致性是**大幅增强**，不是绝对 100%——生成式 AI 模型每次生成仍有随机性，可能出现轻微的光线/表情/细节差异。
- **想最大程度锁定一致性**，请配合以下操作：
  1. 角色立绘描述写详细（发型/发色/瞳色/服装款式/配饰）
  2. 每次生成都用**同一张**角色立绘/场景图（不要换图）
  3. 场景描述写清"构图、建筑、物件、光线方向"
- 视频生成是"参考图 + prompt"共同作用，**参考图越清晰、prompt 越具体，一致性越高**。

### ⚠️ 重要：cv 通道（即梦）的"白天黑夜不一致"是模型能力限制

火山即梦的 `cv_process` 接口**只支持文生图**——测了 5 个图生图 req_key（`seededit_v2.0_i2i` / `jimeng_image2image_*` 等）**全部报 50200 "req_key not supported"**。即梦视觉服务**不提供图生图 API**。

意味着 cv 通道下：
- ✅ 角色立绘 → 片段视频：cv 通道的 jimeng_t2v_v30 **支持** `image_url` 参考图（视频可参考立绘）
- ❌ 白天场景图 → 黑夜场景图：**不支持图生图**，只能靠文字描述"构图与白天一致"，模型不一定强遵守

**根本解决方案**：切到火山方舟 Seedream（`doubao-seedream-5-0-260128`），它**原生支持 image_to_image 能力**——传 day_image_url 作为参考，黑夜图自动基于白天图做风格迁移，建筑/物件/构图严格一致。

切通道后效果：白天生成 = 正常；黑夜生成 = 自动基于白天图改夜晚（不仅文字描述，模型真正参考白天图）。

---

## 二、注册火山方舟（约 10 分钟）

> 前提：你已有火山引擎账号（即梦 cv 通道用的就是同一个火山账号体系）。

### 第 1 步：登录火山引擎控制台
打开 👉 https://console.volcengine.com/ （用你的火山账号登录，和即梦同一账号）

### 第 2 步：开通「方舟」服务
1. 顶部搜索框搜「**方舟**」（火山方舟 Ark）
2. 点击进入「火山方舟」控制台
3. 首次进入会提示开通，点击「**立即开通**」即可（免费开通，按量付费）

### 第 3 步：在模型广场开通 Seedance + Seedream
1. 左侧菜单找到「**模型广场**」/「模型管理」
2. 搜索并「开通」以下两个模型：
   - **Seedance 2.0**（视频生成）：`doubao-seedance-2-0-260128`（标准版）
   - **Seedream**（图片生成）：`doubao-seedream-5-0-260128`
3. 开通后记录模型名称（也叫 Model ID，形如 `doubao-seedance-2-0-260128`）

> 💡 如果搜索不到，检查控制台区域是否为「北京」；模型名称以控制台实际显示为准，填到 `.env` 即可。

### 第 4 步：创建 API Key
1. 左侧菜单「**API Key 管理**」→「创建 API Key」
2. 密钥以 `volc-sk-` 开头，**复制保存**（只显示一次！）
3. 注意：方舟 Key（volc-sk-xxx）和即梦的 AK/SK **不通用**，是两个独立凭据

---

## 三、修改 `.env`（约 3 分钟）

打开项目根目录的 `.env`，把**图片通道和视频通道都切到方舟**：

```bash
# ====== 媒体通道切换（核心：cv → ark）======
IMAGE_CHANNEL=volc_ark
VIDEO_CHANNEL=volc_ark

# ====== 填入你的方舟 Key ======
ARK_API_KEY=volc-sk-你刚复制的密钥

# ====== 方舟模型（一般不用改，控制台开通的模型名一致即可）======
ARK_IMAGE_MODEL=doubao-seedream-5-0-260128
ARK_VIDEO_MODEL=doubao-seedance-2-0-260128

# ====== 视频参数（竖屏短剧推荐）======
ARK_VIDEO_RESOLUTION=720p
ARK_VIDEO_RATIO=9:16
# Seedance 原生音频：true=视频自带声音+台词（跳过 edge-tts 配音）
ARK_VIDEO_AUDIO=true
# Seedance 时长范围（秒）：1~15 秒任意值，LLM 分配多少就生成多少
ARK_VIDEO_DUR_MIN=4
ARK_VIDEO_DUR_MAX=15

# ====== 视频时长策略：切到"任意时长制"（不再 clamp 到 5/10s 档位）======
VIDEO_DURATION_SLOTS=any
VIDEO_TRIM=false
VIDEO_DURATION_RANGE=1,15
```

保存 `.env` 后，**重启服务**：

```bash
# 先停掉旧服务（Ctrl+C 或杀进程），再重新启动
python -m uvicorn main:app --host 0.0.0.0 --port 8010
```

---

## 四、验证是否生效（2 分钟）

1. 浏览器打开 `http://127.0.0.1:8010/static/index.html`（Ctrl+F5 强刷）
2. 提交一个新剧本（或继续旧任务），选 **realistic（真人写实）** 风格
3. 生成角色立绘 → 应该明显是真人写实（皮肤纹理、电影感、非插画）
4. 生成场景图（白天→黑夜）→ 黑夜基于白天，构图一致
5. 生成片段视频 → 人物外貌与立绘一致、场景与场景图一致，且**视频自带声音**
6. 检查服务端日志应出现：
   ```
   ark image ok | model=doubao-seedream-5-0-260128
   ark video submit ok | model=doubao-seedance-2-0-260128 | audio=True
   ```

---

## 五、效果对比（同一剧本，两种通道实测参考）

| | volc_cv（即梦） | volc_ark（Seedance+Seedream） |
|---|---|---|
| 角色立绘 | 偏插画/2.5D | 真人写实照片质感 |
| 视频角色 | 偶尔换脸/换装 | 与立绘高度一致 |
| 场景 | 与场景图有出入 | 构图/光线跟随参考图 |
| 配音 | edge-tts 合成（机械感） | Seedance 原生人声（自然） |
| 最长片段 | 10 秒 | 15 秒 |

---

## 六、常见问题

**Q1：ark 通道报错 50400 / Access Denied？**
A：方舟 Key 未开通对应模型，或 Key 过期。回到「模型广场」确认 Seedance/Seedream 已开通，重新创建 Key。

**Q2：报错"模型不存在"（model not found）？**
A：`ARK_IMAGE_MODEL` / `ARK_VIDEO_MODEL` 的模型名和控制台不一致。打开控制台「模型广场」复制实际 Model ID 填回 `.env`。

**Q3：切回即梦 cv 通道？**
A：把 `.env` 的 `IMAGE_CHANNEL=volc_cv`、`VIDEO_CHANNEL=volc_cv`，并恢复 `VIDEO_DURATION_SLOTS=5,10` + `VIDEO_TRIM=true` + `VIDEO_DURATION_RANGE=2,10`。两份配置可随时互切。

**Q4：ark 通道更贵吗？**
A：火山按量付费，Seedance 2.0 比 jimeng 略贵，但一致性和质量显著提升。建议先用 5~10 条视频试跑评估。

**Q5：能同时用即梦出图 + Seedance 出视频吗？**
A：可以。`IMAGE_CHANNEL=volc_cv` + `VIDEO_CHANNEL=volc_ark`——图片走即梦、视频走方舟（反之亦然），互不干扰。
