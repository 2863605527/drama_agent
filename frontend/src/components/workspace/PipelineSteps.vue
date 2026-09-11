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
.steps-card { display: flex; align-items: center; padding: 18px 22px; gap: 0; }
.step { display: flex; align-items: center; flex: 1; }
.step:last-child { flex: 0; }
.dot {
  width: 32px; height: 32px; border-radius: 50%; flex-shrink: 0;
  display: grid; place-items: center; font-size: 13px; font-weight: 600;
  background: var(--bg-app); border: 1.5px solid var(--border-strong); color: var(--text-3);
  transition: all .3s var(--ease, ease);
}
.step-label { font-size: 12.5px; color: var(--text-3); margin: 0 10px 0 8px; white-space: nowrap; transition: color .3s; }
.bar {
  flex: 1; height: 2px; border-radius: 2px; margin-right: 6px;
  background: var(--border); position: relative; overflow: hidden;
}
.step.done .dot {
  background: linear-gradient(135deg, #22c55e, #16a34a); border-color: transparent;
  color: #052e16; box-shadow: 0 3px 10px rgba(34,197,94,.32);
}
.step.done .dot span { animation: check-pop .3s var(--ease, ease) both; }
@keyframes check-pop { from { transform: scale(.3); opacity: 0; } to { transform: scale(1); opacity: 1; } }
.step.done .step-label { color: var(--text); }
.step.done .bar { background: linear-gradient(90deg, #22c55e, rgba(34,197,94,.55)); }
.step.running .dot {
  border-color: var(--primary); color: #c7d2fe;
  background: var(--primary-soft);
  box-shadow: 0 0 0 0 rgba(99,102,241,.4);
  animation: dot-ring 1.6s ease-out infinite;
}
@keyframes dot-ring {
  0% { box-shadow: 0 0 0 0 rgba(99,102,241,.4); }
  70% { box-shadow: 0 0 0 9px rgba(99,102,241,0); }
  100% { box-shadow: 0 0 0 0 rgba(99,102,241,0); }
}
.step.running .step-label { color: var(--text); font-weight: 600; }
.step.waiting .dot { opacity: .75; }
</style>
