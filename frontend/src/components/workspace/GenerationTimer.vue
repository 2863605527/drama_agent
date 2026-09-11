<template>
  <section v-if="running" class="card gen-timer" aria-live="polite">
    <div class="gt-row">
      <span class="gt-pulse"></span>
      <span class="gt-stage">{{ view.label }}中</span>
      <span class="gt-time">
        已耗时 <b class="num">{{ fmt(elapsed) }}</b>
        <template v-if="!over">
          <span class="gt-sep">·</span>预计还需约 <b class="num ok">{{ fmt(remain) }}</b>
        </template>
        <b v-else class="warn">已超参考时长，仍在生成中，请勿重复点击 / 提交</b>
      </span>
      <span class="gt-est">该阶段参考约 {{ fmt(view.est) }}</span>
    </div>
    <!-- 不确定进度条：来回滑动，表示任务仍在推进而非卡死 -->
    <div class="gt-track"><span class="gt-slide"></span></div>
  </section>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { useTaskStore } from '@/stores/task'

const taskStore = useTaskStore()

// 各自动阶段的参考时长（秒，经验值，仅用于缓解等待焦虑，不是精确倒计时）
// 剧本解析需串行两次大模型（起草 + 超大结构化 JSON），实测约 1~3 分钟
const PHASE = {
  pending: { label: '剧本解析', est: 180 },
  parsing: { label: '剧本解析', est: 180 },
  // 注：generating_asset / generating_video 都是「等待用户手动逐张/逐段生成」的空闲态，
  // 不随状态自动计时；前者由 assetBusy、后者由 segRunning（确有片段在生成）驱动。
  generating_shot: { label: '生成分镜', est: 120 },
  composing: { label: '合成成片', est: 60 }
}
const RUN_STATUS = Object.keys(PHASE)
// 单张图片（手动点生成/重绘）的参考耗时
const ASSET_EST = 25
// 单个片段视频（手动点生成）的参考耗时
const SEG_EST = 120

const startAt = ref(0)
const segStartAt = ref(0)
const now = ref(Date.now())
let timer = null

const statusRunning = computed(() => RUN_STATUS.includes(taskStore.current?.status))
const busy = computed(() => taskStore.activeAssetBusy || null)
// 是否确有片段在生成（而不是刚进入视频阶段空等用户点击）
const segRunning = computed(() => Object.values(taskStore.segRuntime || {}).includes('running'))
const running = computed(() => statusRunning.value || !!busy.value || segRunning.value)

// 当前应展示的阶段：单张出图 / 单段视频优先（精确到正在做什么），否则取任务状态阶段
const view = computed(() => {
  if (busy.value) return { label: `生成图片 · ${busy.value.label}`, est: ASSET_EST, base: busy.value.startAt }
  if (segRunning.value) return { label: '生成片段视频', est: SEG_EST, base: segStartAt.value }
  const p = PHASE[taskStore.current?.status] || PHASE.pending
  return { label: p.label, est: p.est, base: startAt.value }
})
const elapsed = computed(() => (view.value.base ? Math.floor((now.value - view.value.base) / 1000) : 0))
const remain = computed(() => Math.max(0, view.value.est - elapsed.value))
const over = computed(() => elapsed.value >= view.value.est)

function fmt(sec) {
  sec = Math.max(0, Math.floor(sec))
  const m = String(Math.floor(sec / 60)).padStart(2, '0')
  const s = String(sec % 60).padStart(2, '0')
  return `${m}:${s}`
}
function startTicker() {
  if (timer) return
  now.value = Date.now()
  timer = setInterval(() => { now.value = Date.now() }, 1000)
}
function stopTicker() {
  if (timer) { clearInterval(timer); timer = null }
}

watch(segRunning, (on, off) => {
  if (on && !off) segStartAt.value = Date.now()   // 首个片段开始生成时起表
  if (!on && off) segStartAt.value = 0           // 全部片段结束时清零
})

watch([running, () => taskStore.currentId], (cur, old) => {
  const idChanged = old && cur[1] !== old[1]
  if (idChanged) { startAt.value = 0; segStartAt.value = 0 }
  if (cur[0]) {
    // 状态阶段（非手动出图/片段）进入运行态时起表；手动任务用各自 startAt
    if (statusRunning.value && !busy.value && !segRunning.value && !startAt.value) startAt.value = Date.now()
    startTicker()
  } else {
    stopTicker(); startAt.value = 0
  }
}, { immediate: true })

onBeforeUnmount(stopTicker)
</script>

<style scoped>
.gen-timer { padding: 12px 16px 14px; }
.gt-row { display: flex; align-items: center; gap: 10px; font-size: 12.5px; color: var(--text-2); }
.gt-stage { font-weight: 600; color: var(--text); display: flex; align-items: center; gap: 7px; }
.gt-pulse {
  width: 9px; height: 9px; border-radius: 50%; background: var(--primary);
  box-shadow: 0 0 0 0 rgba(99,102,241,.5); animation: gt-pulse 1.2s ease-out infinite;
}
@keyframes gt-pulse {
  0% { box-shadow: 0 0 0 0 rgba(99,102,241,.45); }
  70% { box-shadow: 0 0 0 7px rgba(99,102,241,0); }
  100% { box-shadow: 0 0 0 0 rgba(99,102,241,0); }
}
.gt-time { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.num { font-family: "Cascadia Code", Consolas, monospace; font-variant-numeric: tabular-nums; color: var(--text); }
.num.ok { color: var(--success); }
.gt-sep { color: var(--text-3); }
.warn { color: #fbbf24; font-weight: 600; }
.gt-est { margin-left: auto; font-size: 11px; color: var(--text-3); white-space: nowrap; }
.gt-track {
  margin-top: 10px; height: 5px; border-radius: 3px; overflow: hidden;
  background: var(--bg-app); position: relative;
}
.gt-slide {
  position: absolute; top: 0; left: -35%; width: 35%; height: 100%;
  border-radius: 3px; background: var(--gradient);
  animation: gt-slide 1.4s ease-in-out infinite;
}
@keyframes gt-slide {
  0% { left: -35%; }
  100% { left: 100%; }
}
</style>
