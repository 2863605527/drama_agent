<template>
  <section class="card" v-if="script">
    <header>
      <h3>🎨 角色形象与场景资产</h3>
      <span class="sub">逐个生成，支持重绘 / 本地上传替换 / 编辑描述</span>
    </header>

    <!-- 角色 -->
    <div class="group-title">角色立绘（{{ characters.length }}）</div>
    <div class="grid char-grid">
      <div class="asset" v-for="c in characters" :key="c.char_id">
        <div class="img-box" :class="{ busy: isBusy('character:' + c.char_id) }">
          <img v-if="c.reference_image" :src="c.reference_image" :alt="c.name"
               class="zoomable" title="点击放大预览" @click="preview(c.reference_image)" />
          <div v-else class="placeholder">未生成</div>
          <div v-if="isBusy('character:' + c.char_id)" class="gen-mask">
            <span class="spinner"></span><span>正在生成…<small v-if="elapsedText('character:' + c.char_id)"> {{ elapsedText('character:' + c.char_id) }}</small></span>
          </div>
          <div class="img-actions">
            <button class="mini" :disabled="isBusy('character:' + c.char_id)" @click="regen('character', c.char_id)">
              {{ isBusy('character:' + c.char_id) ? '生成中…' : (c.reference_image ? '重绘' : '生成') }}
            </button>
            <button class="mini" @click="pickFile('character', c.char_id, $event)">上传</button>
            <button v-if="c.reference_image" class="mini danger" :disabled="isBusy('character:' + c.char_id)"
                    @click="clearImg('character', c.char_id)">清除</button>
          </div>
        </div>
        <div class="meta">
          <div class="name-line">
            <strong>{{ c.name }}</strong>
            <span v-if="c.inherited && c.reference_image" class="inh-tag" title="沿用上一集已有立绘">↪ 沿用</span>
            <button class="edit" @click="editChar(c)">✎</button>
          </div>
          <p class="desc">{{ c.description }}</p>
        </div>
      </div>
    </div>

    <!-- 场景（昼夜双图） -->
    <div class="group-title">场景图（{{ scenes.length }} 个场景 × 昼夜）</div>
    <div class="scene-list">
      <div class="scene-asset" v-for="sc in scenes" :key="sc.scene_key">
        <div class="scene-name">
          <strong>{{ sc.scene_key }}</strong>
          <span v-if="sc.inherited && (sc.day_image_url || sc.night_image_url)" class="inh-tag" title="沿用上一集已有场景图">↪ 沿用</span>
          <button class="edit" @click="editScene(sc)">✎ 描述</button>
        </div>
        <div class="scene-imgs">
          <div class="img-box" v-for="variant in ['day', 'night']" :key="variant"
               :class="{ busy: isBusy('scene_image:' + sc.scene_key + ':' + variant) }">
            <img v-if="sc[variant + '_image_url']" :src="sc[variant + '_image_url']"
                 class="zoomable" title="点击放大预览" @click="preview(sc[variant + '_image_url'])" />
            <div v-else class="placeholder">{{ variant === 'day' ? '白天图' : (sc.day_image_url ? '黑夜图' : '黑夜图·先出白天') }}</div>
            <div v-if="isBusy('scene_image:' + sc.scene_key + ':' + variant)" class="gen-mask">
              <span class="spinner"></span><span>正在生成…<small v-if="elapsedText('scene_image:' + sc.scene_key + ':' + variant)"> {{ elapsedText('scene_image:' + sc.scene_key + ':' + variant) }}</small></span>
            </div>
            <div class="img-actions">
              <button class="mini"
                      :disabled="isBusy('scene_image:' + sc.scene_key + ':' + variant) || nightLocked(sc, variant)"
                      :title="nightLocked(sc, variant) ? '黑夜图需以白天图为参考，请先生成或上传白天图' : ''"
                      @click="regen('scene_image', sc.scene_key + ':' + variant)">
                {{ nightGenText(sc, variant) }}
              </button>
              <button class="mini" @click="pickFile('scene_image', sc.scene_key + ':' + variant, $event)">上传</button>
              <button v-if="sc[variant + '_image_url']" class="mini danger"
                      :disabled="isBusy('scene_image:' + sc.scene_key + ':' + variant)"
                      @click="clearImg('scene_image', sc.scene_key + ':' + variant)">清除</button>
            </div>
            <span class="variant-tag">{{ variant === 'day' ? '白天' : '黑夜' }}</span>
          </div>
        </div>
      </div>
    </div>

    <input ref="fileInput" type="file" accept="image/*" hidden @change="onFile" />

    <!-- 编辑角色 -->
    <div v-if="charForm" class="mask" @click.self="charForm = null">
      <div class="modal">
        <h4>编辑角色</h4>
        <label class="f"><span>姓名</span><input class="input" v-model="charForm.name" /></label>
        <label class="f"><span>外貌 / 性格描述</span><textarea class="textarea" rows="5" v-model="charForm.description"></textarea></label>
        <div class="modal-foot">
          <button class="btn" @click="charForm = null">取消</button>
          <button class="btn btn-primary" @click="saveChar">保存</button>
        </div>
      </div>
    </div>

    <!-- 编辑场景 -->
    <div v-if="sceneForm" class="mask" @click.self="sceneForm = null">
      <div class="modal">
        <h4>编辑场景 · {{ sceneForm.scene_key }}</h4>
        <label class="f"><span>纯环境描述（不含人物）</span><textarea class="textarea" rows="5" v-model="sceneForm.description"></textarea></label>
        <div class="modal-foot">
          <button class="btn" @click="sceneForm = null">取消</button>
          <button class="btn btn-primary" @click="saveScene">保存</button>
        </div>
      </div>
    </div>

    <!-- 点击放大预览 -->
    <div v-if="previewUrl" class="lightbox" @click.self="closePreview">
      <img :src="previewUrl" alt="预览" @click.stop />
      <button class="lb-close" @click="closePreview">✕</button>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useTaskStore } from '@/stores/task'
import { taskApi, uploadReplaceImage } from '@/api/task'
import { useToastStore } from '@/stores/toast'
import { extractError } from '@/api/request'

const taskStore = useTaskStore()
const toast = useToastStore()
const script = computed(() => taskStore.script)
const characters = computed(() => taskStore.characters)
const scenes = computed(() => taskStore.scenes)

const fileInput = ref(null)
let pendingUpload = null
const charForm = ref(null)
const sceneForm = ref(null)

// 当前正在生成的图片集合（支持多张并发，各自显示遮罩/禁用）
const busyCount = computed(() => Object.keys(taskStore.assetBusyMap || {}).length)
function isBusy(key) { return !!(taskStore.assetBusyMap && taskStore.assetBusyMap[key]) }
// 已等待计时：每个生成中的资产记录起始时间，每秒刷新，让用户明确知道在跑而非卡死
const startMap = {}
const nowTick = ref(Date.now())
let tickTimer = null
onMounted(() => { tickTimer = setInterval(() => { nowTick.value = Date.now() }, 1000) })
onUnmounted(() => { if (tickTimer) clearInterval(tickTimer) })
function elapsedText(key) {
  const s = startMap[key]
  if (!s) return ''
  return `已等待 ${Math.max(0, Math.floor((nowTick.value - s) / 1000))}s`
}
// 黑夜图必须以白天图为参考：该场景还没有白天图时，黑夜「生成」按钮锁定
function nightLocked(sc, variant) {
  return variant === 'night' && !sc.day_image_url
}
function nightGenText(sc, variant) {
  const key = 'scene_image:' + sc.scene_key + ':' + variant
  if (isBusy(key)) return '生成中…'
  if (nightLocked(sc, variant)) return '先出白天图'
  return sc[variant + '_image_url'] ? '重绘' : '生成'
}

function assetLabel(type, id) {
  if (type === 'character') {
    const c = characters.value.find((x) => x.char_id === id)
    return `角色「${c?.name || ''}」立绘`
  }
  const idx = id.lastIndexOf(':')
  const sk = idx >= 0 ? id.slice(0, idx) : id
  const v = idx >= 0 ? id.slice(idx + 1) : 'day'
  return `场景「${sk}」${v === 'day' ? '白天' : '黑夜'}图`
}

async function regen(type, id) {
  const key = `${type}:${id}`
  if (isBusy(key)) return            // 防止重复点击
  const label = assetLabel(type, id)
  // 点击瞬间即给反馈：按钮 loading + 图片遮罩 + 计时动画 + 日志，不再干等接口
  taskStore.setAssetBusy(key, label)
  startMap[key] = Date.now()
  taskStore.appendLog(`🎨 开始生成${label}，图片通道通常需 10~30 秒，请稍候…`)
  try {
    await taskApi.regenerate(taskStore.currentId, type, id)   // 同步接口：返回时图已生成完
    await taskStore.reloadCurrent()            // 立即回刷，把图显示出来
    taskStore.clearAssetBusy(key)
    delete startMap[key]
    toast.ok(`${label}生成完成`)
  } catch (e) {
    taskStore.clearAssetBusy(key)
    delete startMap[key]
    toast.err(extractError(e))
  }
}

function pickFile(type, id, ev) {
  pendingUpload = { type, id }
  fileInput.value.click()
}

async function onFile(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (!file || !pendingUpload) return
  try {
    await uploadReplaceImage(taskStore.currentId, pendingUpload.type, pendingUpload.id, file)
    await taskStore.reloadCurrent()
    toast.ok('图片已替换')
  } catch (e) {
    toast.err(extractError(e))
  } finally {
    pendingUpload = null
  }
}

function editChar(c) { charForm.value = { char_id: c.char_id, name: c.name, description: c.description } }
async function saveChar() {
  try {
    await taskApi.updateCharacter(taskStore.currentId, charForm.value.char_id, charForm.value.name, charForm.value.description)
    await taskStore.reloadCurrent()
    charForm.value = null
    toast.ok('角色已更新')
  } catch (e) { toast.err(extractError(e)) }
}

function editScene(sc) { sceneForm.value = { scene_key: sc.scene_key, description: sc.description } }
async function saveScene() {
  try {
    await taskApi.updateScene(taskStore.currentId, sceneForm.value.scene_key, sceneForm.value.description)
    await taskStore.reloadCurrent()
    sceneForm.value = null
    toast.ok('场景已更新')
  } catch (e) { toast.err(extractError(e)) }
}

// 点击图片放大预览（lightbox）
const previewUrl = ref(null)
function preview(url) { if (url) previewUrl.value = url }
function closePreview() { previewUrl.value = null }

// 清除某张图片（回到未生成，任务状态不回退）
async function clearImg(type, id) {
  const label = assetLabel(type, id)
  if (!window.confirm(`确定清除${label}？清除后可重新生成或上传。`)) return
  try {
    await taskApi.clearImage(taskStore.currentId, type, id)
    await taskStore.reloadCurrent()
    toast.ok('图片已清除')
  } catch (e) { toast.err(extractError(e)) }
}
</script>

<style scoped>
header { display: flex; align-items: baseline; gap: 12px; margin-bottom: 14px; }
h3 { font-size: 15px; }
.sub { font-size: 12px; color: var(--text-3); }
.group-title { font-size: 13px; font-weight: 600; color: var(--text-2); margin: 16px 0 10px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }
.asset { background: var(--bg-app); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }
.img-box { position: relative; aspect-ratio: 3/4; background: #0b0d13; }
.img-box img { width: 100%; height: 100%; object-fit: cover; }
.placeholder { width: 100%; height: 100%; display: grid; place-items: center; color: var(--text-3); font-size: 12.5px; }
.img-actions {
  position: absolute; inset: auto 0 0 0; display: flex; gap: 6px; padding: 8px;
  background: linear-gradient(transparent, rgba(0,0,0,.75)); opacity: 0; transition: opacity .15s;
}
.img-box:hover .img-actions { opacity: 1; }
.mini:disabled { opacity: .65; cursor: not-allowed; color: #c7d2fe; }
/* 生成中遮罩：点击后立刻在图片框内反馈，避免“点了没反应” */
.img-box.busy .img-actions { opacity: 1; }
.gen-mask {
  position: absolute; inset: 0; z-index: 3; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 10px;
  background: rgba(8,10,16,.72); color: #dbe2ff; font-size: 12.5px; letter-spacing: .5px;
}
.gen-mask small { opacity: .75; font-size: 11px; font-variant-numeric: tabular-nums; }
.spinner {
  width: 30px; height: 30px; border-radius: 50%;
  border: 3px solid rgba(148,163,255,.25); border-top-color: var(--primary);
  animation: asset-spin .8s linear infinite;
}
@keyframes asset-spin { to { transform: rotate(360deg); } }
.mini {
  flex: 1; padding: 5px 0; font-size: 12px; border-radius: 6px; border: 1px solid var(--border-strong);
  background: rgba(30,34,45,.9); color: var(--text); cursor: pointer; font-family: inherit;
}
.mini:hover { border-color: var(--primary); color: #c7d2fe; }
.mini.danger:hover { border-color: #f87171; color: #fca5a5; }
.zoomable { cursor: zoom-in; }
.lightbox {
  position: fixed; inset: 0; z-index: 2000; background: rgba(0,0,0,.82);
  display: flex; align-items: center; justify-content: center; padding: 40px;
}
.lightbox img {
  max-width: 92vw; max-height: 90vh; object-fit: contain; border-radius: 8px;
  box-shadow: 0 12px 48px rgba(0,0,0,.6); cursor: default;
}
.lb-close {
  position: absolute; top: 22px; right: 28px; width: 40px; height: 40px; border-radius: 50%;
  border: 1px solid rgba(255,255,255,.3); background: rgba(255,255,255,.08); color: #fff;
  font-size: 18px; cursor: pointer;
}
.lb-close:hover { background: rgba(255,255,255,.2); }
.meta { padding: 10px; }
.name-line { display: flex; align-items: center; gap: 8px; }
.name-line strong { font-size: 13.5px; }
.inh-tag { font-size: 10.5px; color: #34d399; border: 1px solid rgba(52,211,153,.4); background: rgba(52,211,153,.1); border-radius: 6px; padding: 1px 6px; white-space: nowrap; }
.edit { background: none; border: none; color: var(--text-3); cursor: pointer; font-size: 13px; }
.edit:hover { color: var(--primary); }
.desc {
  font-size: 12px; color: var(--text-3); margin-top: 5px; line-height: 1.6;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
}
.scene-list { display: flex; flex-direction: column; gap: 12px; }
.scene-asset { background: var(--bg-app); border: 1px solid var(--border); border-radius: 10px; padding: 12px; }
.scene-name { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.scene-imgs { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.scene-imgs .img-box { aspect-ratio: 16/9; border-radius: 8px; overflow: hidden; }
.variant-tag {
  position: absolute; top: 6px; left: 6px; font-size: 11px; padding: 2px 8px;
  background: rgba(0,0,0,.65); border-radius: 6px;
}
.mask { position: fixed; inset: 0; background: rgba(6,8,14,.6); z-index: 900; display: grid; place-items: center; }
.modal { width: 520px; max-width: 92vw; background: var(--bg-card); border: 1px solid var(--border-strong); border-radius: 14px; padding: 22px; }
.modal h4 { margin-bottom: 16px; }
.f { display: block; margin-bottom: 14px; }
.f span { display: block; font-size: 12.5px; color: var(--text-2); margin-bottom: 6px; }
.modal-foot { display: flex; justify-content: flex-end; gap: 10px; }
</style>
