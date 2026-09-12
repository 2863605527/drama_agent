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
        <div class="row channel-row">
          <span class="lbl">通道类型</span>
          <div class="ch-row">
            <select class="input" v-model="form[kind].channel">
              <option v-for="c in channelOptions" :key="c.value" :value="c.value">{{ c.label }}</option>
            </select>
            <button class="tut-btn" title="查看该通道图文配置教程" @click="tutorial.open(kind, form[kind].channel)">
              📖 教程
            </button>
          </div>
        </div>

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
          <span class="env-tut" @click="tutorial.open(kind, cur.channel)">📖 查看配置教程</span>
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
    <ChannelTutorial ref="tutorial" />
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useChannelStore } from '@/stores/channel'
import { channelApi } from '@/api/channel'
import { useToastStore } from '@/stores/toast'
import { extractError } from '@/api/request'
import { FIELD_SCHEMA, SENSITIVE_KEYS, KIND_LABELS } from '@/config/channelFields'
import ChannelTutorial from './ChannelTutorial.vue'

const channel = useChannelStore()
const toast = useToastStore()
const tutorial = ref(null)

const kinds = KIND_LABELS
const kind = ref('llm')
const form = ref({ llm: {}, image: {}, video: {} })
const testing = ref(false)
const saving = ref(false)
const testResult = ref('')

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
  if (SENSITIVE_KEYS.includes(f.key) && String(cur.value[f.key] || '').startsWith('__MASKED__')) {
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
.channel-row .lbl { display: block; font-size: 12.5px; color: var(--text-2); margin-bottom: 6px; }
.ch-row { display: flex; gap: 8px; }
.ch-row .input { flex: 1; }
.tut-btn {
  flex-shrink: 0; padding: 0 12px; border-radius: 9px; font-size: 12.5px; cursor: pointer;
  background: var(--primary-soft); border: 1px dashed var(--border-strong); color: #cfd8ff;
  font-family: inherit; transition: all .15s;
}
.tut-btn:hover { background: #2b3bff33; border-style: solid; color: #fff; }
.env-tut { display: inline-block; margin-top: 6px; color: var(--primary); cursor: pointer; font-size: 12.5px; }
.env-tut:hover { text-decoration: underline; }
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
