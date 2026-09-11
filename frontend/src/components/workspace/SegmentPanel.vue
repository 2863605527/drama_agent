<template>
  <section class="card" v-if="script && segments.length">
    <header>
      <h3>🎞️ 片段视频（一个片段 = 一段连续视频，内含多个分镜）</h3>
      <div class="head-right">
        <button class="btn btn-ghost btn-sm" :disabled="genAllBusy || !canGenVideo || !pendingSegs.length" :title="canGenVideo ? '' : stageHint" @click="genAll">
          <span v-if="genAllBusy" class="spin">◌</span>
          {{ !canGenVideo ? '🔒 完成形象并审核后生成' : (pendingSegs.length ? `▶ 生成全部（剩 ${pendingSegs.length} 段）` : '全部片段已生成') }}
        </button>
        <div class="audio-pick">
          <span>配音</span>
          <select class="input" :value="audioMode" @change="changeAudio($event.target.value)">
            <option v-for="a in AUDIO_OPTIONS" :key="a.value" :value="a.value">{{ a.label }}</option>
          </select>
        </div>
      </div>
    </header>

    <div class="seg" v-for="(seg, si) in segments" :key="seg.segment_id">
      <!-- 片段头：中文名 + 概要 + 状态 + 唯一操作按钮 -->
      <div class="seg-head">
        <strong class="seg-name">片段 {{ pad(si + 1) }}</strong>
        <span class="seg-shots">{{ seg.shot_ids?.length || 0 }} 个分镜 · 共 {{ seg.duration || 0 }} 秒 · 场景：{{ seg.scene_key || '—' }}</span>
        <span class="badge" :class="stateBadge(seg)">{{ stateText(seg) }}</span>
        <div class="seg-ops">
          <template v-if="canGenVideo">
            <button v-if="segState(seg) === 'idle' || segState(seg) === 'failed'"
                    class="btn btn-primary btn-sm" :disabled="busySeg === seg.segment_id" @click="genSeg(seg)">
              <span v-if="busySeg === seg.segment_id" class="spin">◌</span>
              {{ segState(seg) === 'failed' ? '↻ 重新生成' : '▶ 生成片段视频' }}
            </button>
            <button v-if="segState(seg) === 'done'" class="btn btn-ghost btn-sm"
                    :disabled="busySeg === seg.segment_id" @click="genSeg(seg)">↻ 重新生成</button>
            <span v-if="segState(seg) === 'running'" class="running-txt"><span class="spin">◌</span> 视频生成中，进度见顶部日志…</span>
          </template>
          <button v-else class="btn btn-sm btn-locked" disabled :title="stageHint">🔒 完成形象并审核后生成</button>
        </div>
      </div>

      <!-- 分镜明细：仅作为本片段的脚本分镜文字（已合并进同一段视频，不单独出视频） -->
      <div class="shot-list">
        <div class="shot-item" v-for="sh in shotsOf(seg)" :key="sh.shot_id">
          <div class="si-title">
            <b>分镜 {{ globalShotNo(sh) }}</b>
            <span class="si-dur">{{ sh.duration || 0 }}s</span>
            <button class="edit" @click="editShot(sh)">✎ 编辑</button>
          </div>
          <p class="si-line"><em>内容</em>{{ sh.content }}</p>
          <p class="si-line"><em>镜头</em>{{ sh.camera }}</p>
          <p class="si-line"><em>光影</em>{{ sh.lighting }}</p>
          <p class="si-line" v-if="sh.lines"><em>台词</em>{{ sh.lines }}</p>
        </div>
      </div>

      <!-- 片段唯一视频区：整段只此一个，未生成时给单一占位 -->
      <div class="seg-video">
        <video v-if="seg.video_url" :src="seg.video_url" controls preload="metadata"></video>
        <div v-if="seg.video_url && seg.quality_warning" class="quality-warn" :title="seg.quality_warning">
          ⚠️ 质量复核：{{ seg.quality_warning }}，建议点「重新生成」
        </div>
        <div v-else class="sv-empty">
          <span v-if="segState(seg)==='running'" class="pulse">正在把 {{ seg.shot_ids?.length || 0 }} 个分镜合成为一段视频…</span>
          <span v-else-if="!canGenVideo" class="lock-hint">🔒 {{ stageHint }}</span>
          <span v-else>这 {{ seg.shot_ids?.length || 0 }} 个分镜会合并生成「片段 {{ pad(si + 1) }}」一段视频，点击右上角「生成片段视频」</span>
        </div>
      </div>
    </div>

    <!-- 编辑分镜 -->
    <div v-if="shotForm" class="mask" @click.self="shotForm = null">
      <div class="modal">
        <h4>编辑分镜 {{ shotForm._no }}</h4>
        <label class="f"><span>画面内容</span><textarea class="textarea" rows="3" v-model="shotForm.content"></textarea></label>
        <label class="f"><span>镜头语言</span><input class="input" v-model="shotForm.camera" /></label>
        <label class="f"><span>光影氛围</span><input class="input" v-model="shotForm.lighting" /></label>
        <label class="f"><span>视频提示词（可空，空则由内容自动生成）</span><textarea class="textarea" rows="3" v-model="shotForm.prompt"></textarea></label>
        <div class="modal-foot">
          <button class="btn" @click="shotForm = null">取消</button>
          <button class="btn btn-primary" @click="saveShot">保存并重生效</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useTaskStore } from '@/stores/task'
import { taskApi } from '@/api/task'
import { useToastStore } from '@/stores/toast'
import { extractError } from '@/api/request'
import { AUDIO_OPTIONS } from '@/utils/format'

const taskStore = useTaskStore()
const toast = useToastStore()
const script = computed(() => taskStore.script)
const segments = computed(() => taskStore.segments)
const shots = computed(() => taskStore.shots)
const audioMode = computed(() => taskStore.current?.audio_mode || 'auto')

const shotForm = ref(null)
const busySeg = ref('')
const genAllBusy = ref(false)

const pad = (n) => String(n).padStart(2, '0')

// 只有进入「片段视频」阶段（人工审核通过后）才允许生成；done 后可重生成
const taskStatus = computed(() => taskStore.current?.status || '')
const canGenVideo = computed(() => ['generating_video', 'done'].includes(taskStatus.value))
const stageHint = computed(() => {
  if (taskStatus.value === 'generating_asset') return '请先在上方生成全部角色立绘与场景昼夜图，完成后会进入人工审核'
  if (taskStatus.value === 'human_review') return '请先在上方「人工审核断点」点击“形象无误，继续生成”'
  if (taskStatus.value === 'pending' || taskStatus.value === 'parsing') return '剧本仍在解析，请稍候'
  return ''
})

function shotsOf(seg) {
  const ids = seg.shot_ids || []
  return shots.value.filter((s) => ids.includes(s.shot_id))
}
function globalShotNo(sh) {
  const i = shots.value.findIndex((x) => x.shot_id === sh.shot_id)
  return i >= 0 ? i + 1 : '?'
}
// 片段状态：done（已出片）/ running / failed / idle（待生成）
function segState(seg) {
  if (seg.video_url) return 'done'
  return taskStore.segRuntime[seg.segment_id] || 'idle'
}
function stateText(seg) {
  return { idle: '待生成', running: '生成中…', failed: '生成失败', done: '已出片' }[segState(seg)]
}
function stateBadge(seg) {
  return { idle: 'badge-pending', running: 'badge-running', failed: 'badge-failed', done: 'badge-done' }[segState(seg)]
}
const pendingSegs = computed(() => segments.value.filter((s) => !s.video_url && taskStore.segRuntime[s.segment_id] !== 'running'))

async function genSeg(seg) {
  if (busySeg.value) return
  if (!canGenVideo.value) { toast.err(stageHint.value || '当前阶段还不能生成片段视频'); return }
  busySeg.value = seg.segment_id
  // 立即进入“生成中”动画，不等待接口往返
  taskStore.segRuntime[seg.segment_id] = 'running'
  seg.quality_warning = null
  taskStore.appendLog(`🎞️ 提交「片段 ${seg.segment_id.slice(0, 4)}」视频生成，视频通道通常需 30~90 秒…`)
  try {
    await taskApi.regenerate(taskStore.currentId, 'segment_video', seg.segment_id)
    toast.ok('已开始生成该片段视频，进度见顶部执行日志')
  } catch (e) {
    taskStore.segRuntime[seg.segment_id] = 'failed'
    toast.err(extractError(e))
  } finally {
    busySeg.value = ''
  }
}

async function genAll() {
  if (genAllBusy.value) return
  if (!canGenVideo.value) { toast.err(stageHint.value || '当前阶段还不能生成片段视频'); return }
  const list = pendingSegs.value
  if (!list.length) return
  genAllBusy.value = true
  try {
    for (const seg of list) {
      taskStore.segRuntime[seg.segment_id] = 'running'   // 立即动画
      seg.quality_warning = null
      await taskApi.regenerate(taskStore.currentId, 'segment_video', seg.segment_id)
    }
    toast.ok(`已提交 ${list.length} 个片段，按通道并发依次生成，进度见顶部执行日志`)
  } catch (e) {
    toast.err(extractError(e))
  } finally {
    genAllBusy.value = false
  }
}

async function changeAudio(mode) {
  try {
    await taskApi.updateAudioMode(taskStore.currentId, mode)
    await taskStore.reloadCurrent()
    toast.ok('配音方式已更新')
  } catch (e) { toast.err(extractError(e)) }
}

function editShot(sh) {
  shotForm.value = {
    _no: globalShotNo(sh), shot_id: sh.shot_id, content: sh.content,
    camera: sh.camera, lighting: sh.lighting, prompt: sh.prompt || ''
  }
}
async function saveShot() {
  try {
    await taskApi.updateShot(taskStore.currentId, shotForm.value.shot_id, {
      content: shotForm.value.content, camera: shotForm.value.camera,
      lighting: shotForm.value.lighting, prompt: shotForm.value.prompt
    })
    await taskStore.reloadCurrent()
    shotForm.value = null
    toast.ok('分镜已更新')
  } catch (e) { toast.err(extractError(e)) }
}
</script>

<style scoped>
header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; gap: 12px; flex-wrap: wrap; }
h3 { font-size: 15px; }
.head-right { display: flex; align-items: center; gap: 12px; }
.audio-pick { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-2); }
.audio-pick .input { width: auto; padding: 6px 10px; }
.seg { border: 1px solid var(--border); border-radius: 12px; padding: 14px; margin-bottom: 14px; background: var(--bg-app); }
.seg-head { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
.seg-name { font-size: 14px; }
.seg-shots { font-size: 12px; color: var(--text-3); }
.seg-ops { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.running-txt { font-size: 12.5px; color: #fbbf24; display: inline-flex; align-items: center; gap: 6px; }
.btn-locked { opacity: .6; cursor: not-allowed; color: var(--text-3); }
.lock-hint { color: #fbbf24; }

/* 分镜明细：紧凑文字列表，不再各带视频框 */
.shot-list { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
.shot-item { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.si-title { display: flex; align-items: center; gap: 10px; font-size: 13px; margin-bottom: 4px; }
.si-title b { font-weight: 600; }
.si-dur { font-size: 11.5px; color: var(--text-3); background: var(--bg-app); border-radius: 6px; padding: 1px 7px; }
.edit { margin-left: auto; background: none; border: none; color: var(--text-3); cursor: pointer; font-size: 12px; font-family: inherit; }
.edit:hover { color: var(--primary); }
.si-line { font-size: 12.5px; color: var(--text-2); line-height: 1.65; margin-top: 2px; }
.si-line em { font-style: normal; color: var(--text-3); display: inline-block; width: 38px; }

/* 片段唯一视频区 */
.seg-video video { width: 100%; max-height: 380px; border-radius: 10px; background: #000; display: block; }
.quality-warn {
  margin-top: 6px; padding: 6px 10px; border-radius: 8px; font-size: 12.5px; line-height: 1.5;
  color: #b25e09; background: #fdf3e3; border: 1px solid #f0c98a;
}
.sv-empty {
  width: 100%; min-height: 96px; display: grid; place-items: center; padding: 16px;
  background: #0b0d13; border: 1px dashed var(--border-strong); border-radius: 10px;
  color: var(--text-3); font-size: 12.5px; text-align: center; line-height: 1.7;
}
.mask { position: fixed; inset: 0; background: rgba(6,8,14,.6); z-index: 900; display: grid; place-items: center; }
.modal { width: 540px; max-width: 92vw; background: var(--bg-card); border: 1px solid var(--border-strong); border-radius: 14px; padding: 22px; max-height: 88vh; overflow-y: auto; }
.modal h4 { margin-bottom: 16px; }
.f { display: block; margin-bottom: 13px; }
.f span { display: block; font-size: 12.5px; color: var(--text-2); margin-bottom: 6px; }
.modal-foot { display: flex; justify-content: flex-end; gap: 10px; }
</style>
