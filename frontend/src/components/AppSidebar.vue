<template>
  <aside class="sidebar">
    <!-- 品牌 + 新建 -->
    <div class="top">
      <div class="brand">
        <span class="logo">🎬</span>
        <div class="brand-text">
          <strong>Drama-Agent</strong>
          <small>短剧生成工作台</small>
        </div>
      </div>
      <button class="new-btn" @click="$emit('new-task')">
        <span class="plus">＋</span> 新建短剧
      </button>
    </div>

    <!-- 任务会话列表 -->
    <div class="conv-list">
      <div class="conv-head">
        <span>项目对话</span>
        <button class="refresh" title="刷新列表" @click="taskStore.refreshList()">↻</button>
      </div>

      <div v-if="!roots.length" class="empty">还没有任务，点击上方新建</div>

      <div v-for="root in roots"
           :key="root.task_id"
           class="conv-item"
           :class="{ active: isActive(root) }"
           @click="onSelect(root)">
        <div class="conv-title">{{ titleOf(root) }}</div>
        <div class="conv-meta">
          <span class="badge" :class="statusBadge(latestOf(root).status)">{{ statusText(latestOf(root).status) }}</span>
          <span v-if="episodesOf(root).length > 1" class="seg-count">共 {{ episodesOf(root).length }} 集 · 第{{ episodeCn(latestOf(root).episode_no || 1) }}集</span>
          <span v-else-if="latestOf(root).script?.segments" class="seg-count">{{ latestOf(root).script.segments.length }} 片段</span>
        </div>
        <!-- 悬浮操作：失败可重试、任意任务可删除 -->
        <div class="conv-ops">
          <button v-if="latestOf(root).status === 'failed'" class="op op-retry" title="重新开始"
                  :disabled="busyId === root.task_id" @click.stop="onRetry(root)">↻ 重试</button>
          <button class="op op-del" title="删除该短剧"
                  :disabled="busyId === root.task_id" @click.stop="onDelete(root)">🗑</button>
        </div>
      </div>
    </div>

    <!-- 底部用户区 -->
    <div class="user-zone">
      <button class="channel-entry" @click="openChannel">
        <span class="ci-icon">⚙️</span>
        <div class="ci-text">
          <strong>模型通道</strong>
          <small>LLM {{ channel.summary.llm }} · 图 {{ channel.summary.image }} · 视频 {{ channel.summary.video }}</small>
        </div>
        <span class="ci-arrow">›</span>
      </button>

      <div class="user-line">
        <div class="avatar">{{ (auth.username || 'U').slice(0, 1).toUpperCase() }}</div>
        <div class="user-name">{{ auth.username || '未登录' }}</div>
        <button class="logout" title="退出登录" @click="logout">退出</button>
      </div>
    </div>

    <ChannelConfigDialog />
  </aside>
</template>

<script setup>
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useTaskStore } from '@/stores/task'
import { useAuthStore } from '@/stores/auth'
import { useChannelStore } from '@/stores/channel'
import { useToastStore } from '@/stores/toast'
import { extractError } from '@/api/request'
import { statusText, statusBadge, taskTitle, seriesFamily, seriesName, episodeCn } from '@/utils/format'
import ChannelConfigDialog from './ChannelConfigDialog.vue'

defineEmits(['new-task', 'select'])

const router = useRouter()
const taskStore = useTaskStore()
const auth = useAuthStore()
const channel = useChannelStore()
const toast = useToastStore()

const busyId = ref('')   // 正在删除/重试的任务，防止重复点击

// 左侧只显示「系列根任务」：续写各集归入同一个对话，新建短剧才新增对话条目。
// 父任务已删除（断链）的子任务按独立对话显示。
const roots = computed(() => {
  const tasks = taskStore.tasks
  const ids = new Set(tasks.map((t) => t.task_id))
  return tasks.filter((t) => !t.parent_id || !ids.has(t.parent_id))
})

function familyOf(root) { return seriesFamily(taskStore.tasks, root) }
function episodesOf(root) { return familyOf(root) }
function latestOf(root) {
  const f = familyOf(root)
  return f[f.length - 1] || root
}
function titleOf(root) { return seriesName(root) || taskTitle(root) }
function isActive(root) {
  return familyOf(root).some((f) => f.task_id === taskStore.currentId)
}
// 点击对话 → 进入该系列「最新一集」（最近进展）；已在其中则仍发信号刷新视图
function onSelect(root) {
  const latest = latestOf(root)
  if (latest.task_id === taskStore.currentId) taskStore.navTick++
  else taskStore.selectFromSidebar(latest.task_id)
}

async function onDelete(root) {
  if (busyId.value) return
  const n = episodesOf(root).length
  const tip = n > 1 ? `（共 ${n} 集，将全部删除）` : ''
  if (!window.confirm(`确定删除短剧「${titleOf(root)}」${tip}吗？\n删除后不可恢复。`)) return
  busyId.value = root.task_id
  try {
    await taskStore.deleteTask(root.task_id)
    toast.ok('已删除')
  } catch (e) {
    toast.err(extractError(e))
  } finally {
    busyId.value = ''
  }
}

async function onRetry(root) {
  if (busyId.value) return
  const latest = latestOf(root)
  busyId.value = root.task_id
  try {
    // 先切到该任务，保证重跑后能直接看到执行进度
    if (taskStore.currentId !== latest.task_id) await taskStore.selectTask(latest.task_id)
    await taskStore.retryTask(latest.task_id)
    toast.ok('已重新开始')
  } catch (e) {
    toast.err(extractError(e))
  } finally {
    busyId.value = ''
  }
}

function openChannel() {
  channel.openDialog()
}

function logout() {
  // reset 会关 SSE 并清空任务/日志；App.vue 的 isLogin watch 再兜底清一次
  taskStore.reset()
  auth.logout()
  toast.ok('已退出登录')
  router.replace({ name: 'login' })
}

onMounted(async () => {
  try {
    await Promise.all([taskStore.refreshList(), channel.loadMeta().catch(() => null), channel.loadConfig().catch(() => null)])
  } catch (e) { /* 拦截器已处理 */ }
})
</script>

<style scoped>
.sidebar {
  width: var(--sidebar-w); flex-shrink: 0; height: 100vh;
  background: linear-gradient(180deg, var(--bg-sidebar), #11141c);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column;
}
.top { padding: 16px 14px 10px; }
.brand { display: flex; align-items: center; gap: 10px; padding: 2px 4px 14px; }
.logo {
  width: 38px; height: 38px; border-radius: 11px; display: grid; place-items: center;
  font-size: 20px; background: var(--gradient);
  box-shadow: 0 4px 12px rgba(99,102,241,.35), inset 0 1px 0 rgba(255,255,255,.2);
}
.brand-text strong { font-size: 15px; display: block; line-height: 1.3; letter-spacing: .3px; }
.brand-text small { font-size: 11px; color: var(--text-3); }
.new-btn {
  width: 100%; padding: 10px; border-radius: 10px; border: 1px dashed var(--border-strong);
  background: var(--primary-soft); color: #c7d2fe; cursor: pointer; font-size: 13.5px;
  transition: all .18s var(--ease, ease); font-family: inherit; font-weight: 500;
}
.new-btn:hover { background: rgba(99,102,241,.24); border-color: var(--primary); transform: translateY(-1px); }
.new-btn:active { transform: translateY(0) scale(.98); }
.new-btn .plus { font-size: 15px; margin-right: 4px; }

.conv-list { flex: 1; overflow-y: auto; padding: 6px 10px; }
.conv-head {
  display: flex; justify-content: space-between; align-items: center;
  font-size: 11.5px; color: var(--text-3); padding: 6px 8px; text-transform: uppercase; letter-spacing: .5px;
}
.refresh { background: none; border: none; color: var(--text-3); cursor: pointer; font-size: 14px; }
.refresh:hover { color: var(--text); }
.empty { font-size: 12.5px; color: var(--text-3); padding: 18px 10px; text-align: center; }
.conv-item {
  position: relative;
  padding: 10px 12px; border-radius: 10px; cursor: pointer; margin-bottom: 4px;
  border: 1px solid transparent; transition: all .16s var(--ease, ease);
}
.conv-item:hover { background: var(--bg-hover); transform: translateX(2px); }
.conv-item.active { background: var(--bg-active); border-color: rgba(99,102,241,.4); }
/* 选中项左侧紫色指示条 */
.conv-item.active::before {
  content: ''; position: absolute; left: -10px; top: 50%; transform: translateY(-50%);
  width: 3px; height: 60%; border-radius: 0 3px 3px 0; background: var(--gradient);
}
.conv-title {
  font-size: 13.5px; color: var(--text); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; margin-bottom: 6px; padding-right: 58px;
}
.conv-meta { display: flex; align-items: center; gap: 8px; }
.seg-count { font-size: 11px; color: var(--text-3); }

/* 悬浮操作按钮组 */
.conv-ops {
  position: absolute; top: 7px; right: 8px; display: flex; gap: 4px;
  opacity: 0; transition: opacity .15s;
}
.conv-item:hover .conv-ops, .conv-item.active .conv-ops { opacity: 1; }
.op {
  border: 1px solid var(--border-strong); background: var(--bg-card); color: var(--text-2);
  border-radius: 6px; font-size: 11px; padding: 2px 6px; cursor: pointer;
  font-family: inherit; line-height: 1.5; white-space: nowrap;
}
.op:hover { border-color: var(--primary); color: var(--text); }
.op:disabled { opacity: .5; cursor: not-allowed; }
.op-retry { color: #fbbf24; border-color: rgba(251,191,36,.45); }
.op-retry:hover:not(:disabled) { background: rgba(251,191,36,.14); color: #fcd34d; }
.op-del:hover:not(:disabled) { color: #fca5a5; border-color: var(--danger); background: rgba(239,68,68,.14); }

.user-zone { border-top: 1px solid var(--border); padding: 10px; }
.channel-entry {
  width: 100%; display: flex; align-items: center; gap: 9px; text-align: left;
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px;
  padding: 9px 11px; cursor: pointer; margin-bottom: 8px; color: var(--text); font-family: inherit;
  transition: all .18s var(--ease, ease);
}
.channel-entry:hover { border-color: rgba(99,102,241,.5); background: var(--bg-hover); }
.ci-icon { font-size: 16px; }
.ci-text { flex: 1; min-width: 0; }
.ci-text strong { font-size: 12.5px; display: block; }
.ci-text small {
  font-size: 10.5px; color: var(--text-3); display: block; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; margin-top: 1px;
}
.ci-arrow { color: var(--text-3); font-size: 16px; transition: transform .18s; }
.channel-entry:hover .ci-arrow { transform: translateX(2px); color: var(--primary); }
.user-line { display: flex; align-items: center; gap: 9px; padding: 4px 6px; }
.avatar {
  width: 32px; height: 32px; border-radius: 50%; background: var(--gradient);
  display: grid; place-items: center; font-weight: 700; font-size: 14px; color: #fff;
  box-shadow: 0 3px 9px rgba(99,102,241,.35), inset 0 1px 0 rgba(255,255,255,.22);
}
.user-name { flex: 1; font-size: 13.5px; }
.logout {
  background: none; border: 1px solid var(--border-strong); color: var(--text-2);
  border-radius: 7px; padding: 4px 10px; font-size: 12px; cursor: pointer; font-family: inherit;
}
.logout:hover { color: #fca5a5; border-color: var(--danger); }
</style>
