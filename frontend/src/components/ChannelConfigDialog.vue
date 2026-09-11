<template>
  <div v-if="channel.dialogVisible" class="mask" @click.self="close">
    <div class="dialog fade-up">
      <header>
        <div>
          <h3>模型通道配置</h3>
          <p>选择通道并填写模型与 Key，配置加密保存；新任务立即生效，已有任务重绘/重生成时也会使用最新图片/视频通道</p>
        </div>
        <button class="icon-btn" @click="close">✕</button>
      </header>

      <div class="kind-tabs">
        <button v-for="k in kinds" :key="k.key" :class="{ active: kind === k.key }" @click="kind = k.key">
          {{ k.label }}
          <span class="dot" :class="customClass(k.key)"></span>
        </button>
      </div>

      <div class="body">
        <!-- 通道选择 -->
        <label class="row">
          <span class="lbl">通道类型</span>
          <select class="input" v-model="form[kind].channel">
            <option v-for="c in channelOptions" :key="c.value" :value="c.value">{{ c.label }}</option>
          </select>
        </label>

        <!-- 动态字段（主字段） -->
        <label class="row" v-for="f in primaryFields" :key="f.key">
          <span class="lbl">
            {{ f.label }}
            <em v-if="f.required" class="req">*</em>
          </span>

          <select v-if="f.type === 'select'" class="input" v-model="form[kind][f.key]">
            <option value="">{{ f.placeholder || '请选择' }}</option>
            <option v-for="o in f.options" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>

          <label v-else-if="f.type === 'switch'" class="switch-line">
            <input type="checkbox" v-model="form[kind][f.key]" />
            <span>开启（视频原生生成音频，可跳过 TTS）</span>
          </label>

          <input v-else
                 class="input"
                 :type="f.type === 'password' ? 'password' : 'text'"
                 :list="f.list || undefined"
                 v-model="form[kind][f.key]"
                 :placeholder="placeholderOf(f)" />
        </label>

        <!-- 高级字段（通用 HTTP 技术参数，平台自动识别，默认折叠） -->
        <details v-if="advancedFields.length" class="adv-box" :open="showAdvanced" @toggle="showAdvanced = $event.target.open">
          <summary>高级设置（平台自动识别，一般无需展开；特殊平台可手动覆盖）</summary>
          <label class="row" v-for="f in advancedFields" :key="f.key">
            <span class="lbl">{{ f.label }}</span>
            <select v-if="f.type === 'select'" class="input" v-model="form[kind][f.key]">
              <option value="">{{ f.placeholder || '默认（自动）' }}</option>
              <option v-for="o in f.options" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
            <input v-else
                   class="input"
                   :type="f.type === 'password' ? 'password' : 'text'"
                   v-model="form[kind][f.key]"
                   :placeholder="placeholderOf(f)" />
          </label>
        </details>

      <datalist id="llm-models">
        <option v-for="m in llmSuggestions" :key="m" :value="m"></option>
      </datalist>
      <datalist v-for="dl in modelDatalists" :key="dl.id" :id="dl.id">
        <option v-for="o in dl.options" :key="o.value" :value="o.value">{{ o.label }}</option>
      </datalist>

        <div v-if="isEnv" class="env-hint">
          ⚠️ 本段当前仍是服务端默认通道（旧版本配置）。新版本已移除「系统默认」选项，
          <b>请在下方选择具体通道并填写模型与 Key</b>，所有能力（剧本 / 图片 / 视频）均需手动配置。
        </div>
      </div>

      <footer>
        <div class="test-state" v-if="testing">测试中…</div>
        <div class="test-state ok" v-else-if="testResult">✅ {{ testResult }}</div>
        <div class="spacer"></div>
        <button class="btn btn-ghost" :disabled="testing || saving" @click="runTest">连通测试</button>
        <button class="btn" :disabled="testing || saving" @click="close">取消</button>
        <button class="btn btn-primary" :disabled="testing || saving" @click="save">
          <span v-if="saving" class="spin">◌</span> 保存配置
        </button>
      </footer>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useChannelStore } from '@/stores/channel'
import { channelApi } from '@/api/channel'
import { useToastStore } from '@/stores/toast'
import { extractError } from '@/api/request'

const channel = useChannelStore()
const toast = useToastStore()

const kinds = [
  { key: 'llm', label: '大模型' },
  { key: 'image', label: '图片' },
  { key: 'video', label: '视频' }
]
const kind = ref('llm')
const form = ref({ llm: {}, image: {}, video: {} })
const testing = ref(false)
const saving = ref(false)
const testResult = ref('')

const SENSITIVE = ['api_key', 'access_key', 'secret_key', 'token']

watch(() => channel.dialogVisible, async (v) => {
  if (v) {
    testResult.value = ''
    await channel.loadMeta()
    await channel.loadConfig()
    form.value = JSON.parse(JSON.stringify(channel.config))
  }
})

const cur = computed(() => form.value[kind.value])
// 已删除「系统默认(.env)」选项：所有通道必须手动配置（存量 env 配置仅兼容展示，引导改为手动通道）
const isEnv = computed(() => !cur.value.channel || cur.value.channel === 'env')
const channelOptions = computed(() =>
  (channel.meta?.[kind.value]?.channels || []).filter((c) => c.value !== 'env')
)
const llmSuggestions = computed(() => channel.meta?.llm?.model_suggestions || [])
// 图片/视频模型改为手动输入，以下拉候选 datalist 提供常用模型建议（可自由输入任意最新模型）
const modelDatalists = computed(() => {
  const out = []
  for (const k of ['image', 'video']) {
    const models = channel.meta?.[k]?.models || {}
    for (const ch of Object.keys(models)) {
      out.push({ id: `dl-${k}-${ch}`, options: models[ch] || [] })
    }
  }
  return out
})

function customClass(k) {
  const ch = form.value[k]?.channel
  return ch && ch !== 'env' ? 'on' : ''
}

// 各通道下需要渲染的字段
const FIELD_SCHEMA = {
  llm: {
    openai: [
      { key: 'api_url', label: '接口地址 BaseURL', type: 'text', required: true, placeholder: '如 https://api.deepseek.com（无需 /chat/completions）' },
      { key: 'api_key', label: 'API Key', type: 'password', required: true },
      { key: 'model', label: '模型名', type: 'text', required: true, placeholder: '如 deepseek-chat', list: 'llm-models' },
      { key: 'temperature', label: '采样温度（可空）', type: 'text', placeholder: '0~1，留空用默认 0.7' }
    ]
  },
  image: {
    volc_cv: [
      { key: 'access_key', label: 'AccessKey', type: 'password', required: true },
      { key: 'secret_key', label: 'SecretKey', type: 'password', required: true },
      { key: 'req_key', label: '图片模型 req_key（手动填写）', type: 'text', required: true, optionsKey: 'volc_cv', list: 'dl-image-volc_cv', placeholder: '即梦文生图模型，如 jimeng_t2i_v40 / jimeng_high_aes_general_v21_L；可手填最新模型' }
    ],
    volc_ark: [
      { key: 'api_key', label: 'API Key（volc-sk-）', type: 'password', required: true },
      { key: 'model', label: '图片模型（手动填写）', type: 'text', required: true, optionsKey: 'volc_ark', list: 'dl-image-volc_ark', placeholder: '方舟 Seedream 模型，如 doubao-seedream-4-0-250828；可手填最新版本' },
      { key: 'api_url', label: '接口地址（可空用官方）', type: 'text', placeholder: '默认 https://ark.cn-beijing.volces.com/api/v3' }
    ],
    generic_http: [
      { key: 'base_url', label: '服务地址 BaseURL', type: 'text', required: true, placeholder: '只填根地址即可，如 https://api.siliconflow.cn（后端按域名自动识别平台、补全路径）' },
      { key: 'token', label: 'Bearer Token', type: 'password', required: true, placeholder: '第三方平台的 API Key（sk-...）' },
      { key: 'model', label: '图片模型名（手动填写）', type: 'text', required: true, placeholder: '硅基如 Kwai-Kolors/Kolors；按供应商文档填写，可填任意最新模型' },
      { key: 'endpoint', label: '图片生成接口 URL（高级）', type: 'text', advanced: true, placeholder: '留空自动拼；特殊平台才需手填完整 URL' },
      { key: 'size_field', label: '尺寸字段名（高级）', type: 'text', advanced: true, placeholder: '留空自动识别（硅基 image_size、OpenAI 兼容 size）' },
      { key: 'image_field', label: '图生图参考字段名（高级）', type: 'text', advanced: true, placeholder: '留空自动识别，默认 image' },
      { key: 'result_path', label: '结果图片 URL 路径（高级）', type: 'text', advanced: true, placeholder: '留空自动识别（硅基 images[0].url、兼容 data[0].url）' },
      { key: 'extra_fields', label: '附加请求字段 JSON（高级）', type: 'text', advanced: true, placeholder: '如 {"batch_size": 1}，不需要留空' }
    ]
  },
  video: {
    volc_cv: [
      { key: 'access_key', label: 'AccessKey', type: 'password', required: true },
      { key: 'secret_key', label: 'SecretKey', type: 'password', required: true },
      { key: 'req_key', label: '视频模型 req_key（手动填写）', type: 'text', required: true, optionsKey: 'volc_cv', list: 'dl-video-volc_cv', placeholder: '即梦图生视频模型，如 jimeng_i2v_first_v30_1080；可手填最新模型' },
      { key: 'resolution', label: '分辨率', type: 'select', optionsKey: '__resolution__' }
    ],
    volc_ark: [
      { key: 'api_key', label: 'API Key（volc-sk-）', type: 'password', required: true },
      { key: 'model', label: '视频模型（手动填写）', type: 'text', required: true, optionsKey: 'volc_ark', list: 'dl-video-volc_ark', placeholder: '方舟 Seedance 模型，如 doubao-seedance-1-0-pro-250528；可手填最新版本' },
      { key: 'resolution', label: '分辨率', type: 'select', optionsKey: '__resolution__' },
      { key: 'ratio', label: '宽高比', type: 'select', optionsKey: '__ratio__' },
      { key: 'generate_audio', label: '原生音频', type: 'switch' },
      { key: 'api_url', label: '接口地址（可空用官方）', type: 'text' }
    ],
    generic_http: [
      { key: 'base_url', label: '服务地址 BaseURL', type: 'text', required: true, placeholder: '只填根地址即可，如 https://api.siliconflow.cn（提交/轮询地址自动补全）' },
      { key: 'token', label: 'Bearer Token', type: 'password', required: true, placeholder: '第三方平台的 API Key（sk-...）' },
      { key: 'model', label: '视频模型名（手动填写）', type: 'text', required: true, placeholder: '硅基图生视频 Wan-AI/Wan2.2-I2V-A14B、文生 Wan-AI/Wan2.2-T2V-A14B' },
      { key: 'submit_url', label: '提交任务 URL（高级）', type: 'text', advanced: true, placeholder: '留空自动拼；特殊平台才手填' },
      { key: 'poll_url', label: '轮询 URL（高级，支持 {task_id}）', type: 'text', advanced: true, placeholder: '留空自动拼' },
      { key: 'poll_method', label: '轮询方式（高级）', type: 'select', advanced: true, options: [{ value: 'get', label: 'GET（默认）' }, { value: 'post', label: 'POST' }] },
      { key: 'poll_body', label: 'POST 轮询请求体 JSON（高级）', type: 'text', advanced: true, placeholder: '留空自动识别；如 {"requestId": "{task_id}"}' },
      { key: 'extra_fields', label: '提交附加字段 JSON（高级）', type: 'text', advanced: true, placeholder: '如 {"image_size": "1280x720"}，不需要留空' },
      { key: 'image_field', label: '参考图字段名（高级）', type: 'text', advanced: true, placeholder: '留空自动识别，默认 image' },
      { key: 'omit_fields', label: '剔除默认字段（高级，逗号分隔）', type: 'text', advanced: true, placeholder: '如 duration（硅基不收该字段，已自动剔除）' },
      { key: 'task_id_path', label: '任务ID路径（高级）', type: 'text', advanced: true, placeholder: '留空自动识别（硅基 requestId）' },
      { key: 'status_path', label: '状态路径（高级）', type: 'text', advanced: true, placeholder: '留空自动识别' },
      { key: 'success_status', label: '成功状态值（高级）', type: 'text', advanced: true, placeholder: '留空自动识别（硅基 Succeed）' },
      { key: 'video_url_path', label: '视频URL路径（高级）', type: 'text', advanced: true, placeholder: '留空自动识别（硅基 results.videos[0].url）' },
      { key: 'native_audio', label: '平台原生带音频（高级）', type: 'text', advanced: true, placeholder: '该平台生成的视频自带音轨填 1/true；留空=默认无音轨，走 TTS 配音' }
    ]
  }
}

const visibleFields = computed(() => {
  const ch = cur.value.channel
  const list = FIELD_SCHEMA[kind.value]?.[ch] || []
  // 注入模型/分辨率/比例选项
  return list.map((f) => {
    if (f.optionsKey === '__resolution__') return { ...f, options: channel.meta?.video?.resolutions?.map((v) => ({ value: v, label: v })) }
    if (f.optionsKey === '__ratio__') return { ...f, options: channel.meta?.video?.ratios?.map((v) => ({ value: v, label: v })) }
    if (f.optionsKey) return { ...f, options: channel.meta?.[kind.value]?.models?.[f.optionsKey] || [] }
    return f
  })
})
// 通用 HTTP：主字段只留 地址/Key/模型，技术字段折叠进「高级设置」
const primaryFields = computed(() => visibleFields.value.filter((f) => !f.advanced))
const advancedFields = computed(() => visibleFields.value.filter((f) => f.advanced))
const showAdvanced = ref(false)
watch(kind, () => { showAdvanced.value = false })
watch(() => cur.value.channel, () => { showAdvanced.value = false })

function placeholderOf(f) {
  if (SENSITIVE.includes(f.key) && String(cur.value[f.key] || '').startsWith('__MASKED__')) {
    return '已配置（掩码显示，不修改请留空）'
  }
  return f.placeholder || ''
}

function close() {
  channel.closeDialog()
}

async function runTest() {
  testResult.value = ''
  testing.value = true
  try {
    const r = await channelApi.test(kind.value, cur.value)
    testResult.value = r.reply || '通过'
    toast.ok('连通测试通过')
  } catch (e) {
    testResult.value = ''
    toast.err(extractError(e))
  } finally {
    testing.value = false
  }
}

async function save() {
  saving.value = true
  try {
    channel.config = JSON.parse(JSON.stringify(form.value))
    await channel.save()
    channel.closeDialog()
  } catch (e) {
    toast.err(extractError(e))
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.mask {
  position: fixed; inset: 0; background: rgba(6, 8, 14, .62); z-index: 1000;
  display: grid; place-items: center; backdrop-filter: blur(3px);
}
.dialog {
  width: 560px; max-width: 94vw; max-height: 88vh; display: flex; flex-direction: column;
  background: var(--bg-card); border: 1px solid var(--border-strong);
  border-radius: 16px; box-shadow: var(--shadow); overflow: hidden;
}
header {
  display: flex; justify-content: space-between; align-items: flex-start;
  padding: 20px 22px 14px; border-bottom: 1px solid var(--border);
}
header h3 { font-size: 17px; }
header p { font-size: 12.5px; color: var(--text-3); margin-top: 3px; }
.icon-btn { background: none; border: none; color: var(--text-3); font-size: 16px; cursor: pointer; padding: 4px 8px; border-radius: 6px; }
.icon-btn:hover { background: var(--bg-hover); color: var(--text); }

.kind-tabs { display: flex; gap: 6px; padding: 14px 22px 0; }
.kind-tabs button {
  position: relative; padding: 8px 18px; border-radius: 8px 8px 0 0; border: 1px solid transparent;
  background: transparent; color: var(--text-2); cursor: pointer; font-size: 13.5px; font-family: inherit;
  border-bottom: none;
}
.kind-tabs button.active { background: var(--bg-card-2); color: var(--text); font-weight: 600; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: transparent; display: inline-block; margin-left: 5px; }
.dot.on { background: var(--success); box-shadow: 0 0 6px var(--success); }

.body { padding: 16px 22px; overflow-y: auto; background: var(--bg-card-2); flex: 1; }
.row { display: block; margin-bottom: 14px; }
.lbl { display: block; font-size: 12.5px; color: var(--text-2); margin-bottom: 6px; }
.req { color: var(--danger); font-style: normal; margin-left: 2px; }
.switch-line { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-2); cursor: pointer; }
.switch-line input { width: 16px; height: 16px; accent-color: var(--primary); }
.env-hint {
  padding: 14px; border-radius: 10px; background: var(--primary-soft);
  color: #c7d2fe; font-size: 12.5px; line-height: 1.7; border: 1px dashed var(--border-strong);
}
.adv-box {
  margin: 4px 0 14px; padding: 10px 12px; border: 1px dashed var(--border);
  border-radius: 10px; background: rgba(255,255,255,0.02);
}
.adv-box summary {
  cursor: pointer; font-size: 12.5px; color: var(--text-3); user-select: none; outline: none;
}
.adv-box summary:hover { color: var(--text-2); }
.adv-box[open] summary { margin-bottom: 10px; }
.adv-box .row { margin-bottom: 10px; }

footer { display: flex; align-items: center; gap: 10px; padding: 14px 22px; border-top: 1px solid var(--border); }
.spacer { flex: 1; }
.test-state { font-size: 12.5px; color: var(--text-3); }
.test-state.ok { color: var(--success); }
</style>
