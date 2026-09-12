<template>
  <section class="card log-card" style="flex: none;">
    <header @click="open = !open">
      <span class="title">📟 工程执行日志 <em v-if="taskStore.logs.length">（{{ taskStore.logs.length }}）</em></span>
      <span class="conn" :class="{ on: taskStore.connected }">{{ taskStore.connected ? 'SSE 已连接' : '未连接' }}</span>
      <button class="fold">{{ open ? '收起 ▲' : '展开 ▼' }}</button>
    </header>
    <div v-show="open" class="log-body" ref="bodyRef">
      <div v-for="(line, i) in visibleLogs" :key="i" class="log-line">{{ line }}</div>
      <div v-if="!taskStore.logs.length" class="log-empty">{{ emptyText }}</div>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { useTaskStore } from '@/stores/task'

const taskStore = useTaskStore()
const open = ref(true)
const bodyRef = ref(null)

// P2-9：增量渲染——store 保留全量日志（持久化/导出用），DOM 只渲染末尾窗口，
// 避免数千条日志时 v-for 全量重建导致界面卡顿
const LOG_VISIBLE_WINDOW = 500
const visibleLogs = computed(() => taskStore.logs.slice(-LOG_VISIBLE_WINDOW))

// 空态文案：正在跑的任务等待事件；已推进到后续阶段却没有日志的，多为日志持久化上线前的历史任务
const emptyText = computed(() => {
  const st = taskStore.current?.status
  if (st === 'pending' || st === 'parsing' || st === 'generating_asset' && !taskStore.script) {
    return '正在执行，等待日志事件…'
  }
  return '该任务没有可回显的历史执行日志（日志持久化上线前创建的旧任务未保存）。新任务的执行过程会实时滚动记录在此，刷新页面、重启服务后依然保留。'
})

watch(() => taskStore.logs.length, async (n, old) => {
  // 有新日志时若被手动折叠，自动展开，避免生成图/视频阶段误以为日志“消失”
  if (!open.value && (n || 0) > (old || 0)) open.value = true
  if (!open.value) return
  await nextTick()
  const el = bodyRef.value
  if (el) el.scrollTop = el.scrollHeight
})

// 折叠时窗口上移后仍需保持滚动位置正确
watch(visibleLogs, async () => {
  if (!open.value) return
  await nextTick()
  const el = bodyRef.value
  if (el) el.scrollTop = el.scrollHeight
})
</script>

<style scoped>
.log-card {
  padding: 0; overflow: hidden;
  /* 吸附在执行栏顶部：下方剧本/图片/片段面板再长，滚动时日志卡始终可见 */
  position: sticky; top: -20px; z-index: 30;
  background: var(--bg-card);
  box-shadow: 0 6px 18px rgba(0,0,0,.35);
}
header {
  display: flex; align-items: center; gap: 10px; padding: 11px 16px; cursor: pointer;
  user-select: none;
}
.title { font-size: 13.5px; font-weight: 600; }
.title em { color: var(--text-3); font-style: normal; font-weight: 400; }
.conn { margin-left: auto; font-size: 11.5px; color: var(--text-3); display: inline-flex; align-items: center; gap: 6px; }
.conn::before { content: ''; width: 7px; height: 7px; border-radius: 50%; background: var(--text-3); }
.conn.on { color: var(--success); }
.conn.on::before { background: var(--success); box-shadow: 0 0 0 3px rgba(34,197,94,.18); }
.fold { background: none; border: none; color: var(--text-3); cursor: pointer; font-size: 12px; font-family: inherit; }
.log-body {
  height: 200px; overflow-y: auto; padding: 10px 16px; background: #0b0d13;
  border-top: 1px solid var(--border); font-family: "Cascadia Code", Consolas, monospace;
  font-size: 12px; line-height: 1.7;
}
.log-line { color: #b8c0d0; white-space: pre-wrap; word-break: break-all; }
.log-empty { color: var(--text-3); }
</style>
