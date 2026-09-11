<template>
  <section class="card steps-card">
    <div class="step" v-for="(s, i) in steps" :key="s.key" :class="s.state">
      <div class="dot">
        <span v-if="s.state === 'done'">✓</span>
        <span v-else-if="s.state === 'running'" class="spin">◌</span>
        <span v-else>{{ i + 1 }}</span>
      </div>
      <div class="step-label">{{ s.label }}</div>
      <div class="bar" v-if="i < steps.length - 1"></div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useTaskStore } from '@/stores/task'
import { PIPELINE_STEPS } from '@/utils/format'

const taskStore = useTaskStore()

const steps = computed(() => {
  const t = taskStore.current
  const sc = t?.script
  const status = t?.status
  const stateOf = (key) => {
    const order = ['parse', 'asset', 'review', 'video', 'compose']
    let curIdx = 0
    if (sc) curIdx = 1
    if (sc && allAssetsReady(sc)) curIdx = 2
    if (['generating_video', 'generating_shot', 'composing', 'done'].includes(status)) curIdx = 3
    if (hasAnyVideo(sc)) curIdx = 3
    if (status === 'composing' || t?.final_video_url) curIdx = 4
    if (status === 'done') curIdx = 5
    const idx = order.indexOf(key)
    if (idx < curIdx) return 'done'
    if (idx === curIdx) return 'running'
    return 'waiting'
  }
  return PIPELINE_STEPS.map((s) => ({ ...s, state: stateOf(s.key) }))
})

function allAssetsReady(sc) {
  const charOk = sc.characters.every((c) => c.reference_image)
  const sceneOk = sc.scenes.every((s) => s.day_image_url && s.night_image_url)
  return charOk && sceneOk
}
function hasAnyVideo(sc) {
  return sc?.segments?.some((g) => g.video_url) || sc?.shots?.some((s) => s.video_url)
}
</script>

<style scoped>
.steps-card { display: flex; align-items: center; padding: 16px 20px; gap: 0; }
.step { display: flex; align-items: center; flex: 1; }
.step:last-child { flex: 0; }
.dot {
  width: 30px; height: 30px; border-radius: 50%; flex-shrink: 0;
  display: grid; place-items: center; font-size: 13px; font-weight: 600;
  background: var(--bg-app); border: 1.5px solid var(--border-strong); color: var(--text-3);
}
.step-label { font-size: 12.5px; color: var(--text-3); margin: 0 10px 0 8px; white-space: nowrap; }
.bar { flex: 1; height: 2px; background: var(--border); border-radius: 2px; margin-right: 6px; }
.step.done .dot { background: var(--success); border-color: var(--success); color: #062814; }
.step.done .step-label { color: var(--text); }
.step.done .bar { background: var(--success); }
.step.running .dot { border-color: var(--primary); color: var(--primary); background: var(--primary-soft); }
.step.running .step-label { color: var(--text); font-weight: 600; }
</style>
