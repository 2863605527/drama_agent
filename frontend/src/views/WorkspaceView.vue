<template>
  <div class="workspace">
    <!-- 无任务：欢迎 + 创意输入 -->
    <div v-if="!taskStore.current" class="welcome">
      <div class="welcome-inner fade-up">
        <div class="hero-logo">🎬</div>
        <h1>AI 短剧自动生成工作台</h1>
        <p class="slogan">一句创意 → 剧本拆解 → 角色场景立绘 → 分镜视频 → 合成成片，全流程可视化、可干预</p>
        <div class="welcome-composer">
          <ComposerCard hero />
        </div>
        <div class="features">
          <div class="feat"><span>🧩</span>多 Agent 流水线</div>
          <div class="feat"><span>🖐️</span>人工审核断点</div>
          <div class="feat"><span>⚙️</span>多通道可切换</div>
          <div class="feat"><span>🔁</span>任意环节重生成</div>
        </div>
      </div>
    </div>

    <!-- 有任务：工程执行栏 -->
    <template v-else>
      <div class="ws-header">
        <div class="ws-title">
          <h2>{{ taskTitle(taskStore.current) }}</h2>
          <span class="badge" :class="statusBadge(taskStore.current.status)">
            {{ statusText(taskStore.current.status) }}
          </span>
        </div>
        <div class="ws-actions">
          <span class="task-id">ID: {{ taskStore.currentId.slice(0, 8) }}</span>
          <button v-if="showShelfBack" class="btn btn-ghost btn-sm" @click="viewMode = 'shelf'">📚 返回书架</button>
          <button class="btn btn-ghost btn-sm" @click="taskStore.reloadCurrent()">刷新详情</button>
        </div>
      </div>

      <div class="ws-body">
        <!-- 已完成：书架视图，点书翻开该集详情 -->
        <BookShelf v-if="viewMode === 'shelf'"
          @open="openBook" @new-episode="showEpisode = true" />

        <template v-else>
          <PipelineSteps />
          <GenerationTimer />
          <LogStream />

          <!-- 剧本尚未解析出时，允许再次输入/查看提交态 -->
          <ComposerCard v-if="!taskStore.script && ['pending', 'parsing'].includes(taskStore.current.status)" />

          <ScriptPanel />
          <AssetPanel />
          <ReviewBar />
          <!-- 分段式渲染：角色立绘 + 场景昼夜图全部就绪后，才渲染片段视频与合成组件 -->
          <SegmentPanel v-if="taskStore.assetsReady" />
          <ComposePanel v-if="taskStore.assetsReady" @next-episode="showEpisode = true" />

          <div v-if="taskStore.current.status === 'failed'" class="card failed-box">
            <div class="failed-head">
              <h4>❌ 任务失败</h4>
              <button class="btn btn-primary btn-sm" :disabled="retrying" @click="retryCurrent">↻ 重新开始</button>
            </div>
            <p>可在执行日志中查看原因；点「重新开始」可直接重跑本任务，或调整通道配置后新建任务。</p>
          </div>
        </template>

        <!-- 续写下一集输入框：书架或合成面板点击后展开（挂在最新一集下） -->
        <ComposerCard v-if="showEpisode" episode
          :parent-id="nextParentId"
          :next-no="nextNo"
          :series-title="seriesTitle"
          @done="showEpisode = false" @cancel="showEpisode = false" />
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { useTaskStore } from '@/stores/task'
import { useToastStore } from '@/stores/toast'
import { extractError } from '@/api/request'
import { statusText, statusBadge, taskTitle, seriesFamily, seriesName } from '@/utils/format'
import ComposerCard from '@/components/workspace/ComposerCard.vue'
import PipelineSteps from '@/components/workspace/PipelineSteps.vue'
import GenerationTimer from '@/components/workspace/GenerationTimer.vue'
import LogStream from '@/components/workspace/LogStream.vue'
import ScriptPanel from '@/components/workspace/ScriptPanel.vue'
import AssetPanel from '@/components/workspace/AssetPanel.vue'
import ReviewBar from '@/components/workspace/ReviewBar.vue'
import SegmentPanel from '@/components/workspace/SegmentPanel.vue'
import ComposePanel from '@/components/workspace/ComposePanel.vue'
import BookShelf from '@/components/workspace/BookShelf.vue'

const taskStore = useTaskStore()
const toast = useToastStore()
const retrying = ref(false)
const showEpisode = ref(false)
// 'shelf'：书架视图（流程完成后默认）；'detail'：某集流程详情
const viewMode = ref('detail')

// 同系列所有集（含当前），按集数排序；续写挂在最新一集下
const family = computed(() => seriesFamily(taskStore.tasks, taskStore.current))
const latestEp = computed(() => family.value[family.value.length - 1] || taskStore.current)
const nextParentId = computed(() => latestEp.value?.task_id || taskStore.currentId)
const nextNo = computed(() => (latestEp.value?.episode_no || 1) + 1)
const seriesTitle = computed(() => seriesName(taskStore.current) || taskTitle(taskStore.current))
// 系列里只要有任一集流程走完，进入对话时就优先显示书架
const hasDone = computed(() => family.value.some((f) => f.status === 'done'))

// 详情页的「返回书架」：当前任务已完成时展示
const showShelfBack = computed(() =>
  viewMode.value === 'detail' && taskStore.current?.status === 'done')

function openBook(id) {
  if (id === taskStore.currentId) { viewMode.value = 'detail'; return }
  taskStore.selectTask(id).then(() => { viewMode.value = 'detail' }).catch(() => {})
}

// 内部切任务（书架翻开某集 / 续写创建新集 / 重试）→ 直接进流程详情。
// 注意：本 watch 必须定义在 navTick watch 之前——侧边栏进入时 currentId 与 navTick
// 同帧变化，先执行本逻辑（进详情），再由下方 navTick 覆盖为书架（系列有已完成集时）。
watch(() => taskStore.currentId, () => {
  showEpisode.value = false
  viewMode.value = 'detail'
})

// 从侧边栏点任务（进入对话）：系列有已完成集 → 书架；否则 → 流程详情
watch(() => taskStore.navTick, () => {
  showEpisode.value = false
  viewMode.value = hasDone.value ? 'shelf' : 'detail'
})

// 某集流程走完（→ done）：刷新列表让书架上出新书，并切到书架视图
watch(() => taskStore.current?.status, (s, old) => {
  if (s === 'done' && old && old !== 'done') {
    taskStore.refreshList()
    viewMode.value = 'shelf'
  }
})

async function retryCurrent() {
  if (retrying.value) return
  retrying.value = true
  try {
    await taskStore.retryTask(taskStore.currentId)
    toast.ok('已重新开始')
  } catch (e) {
    toast.err(extractError(e))
  } finally {
    retrying.value = false
  }
}

onBeforeUnmount(() => taskStore.closeStream())
</script>

<style scoped>
.workspace { height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

/* 欢迎页 */
.welcome { flex: 1; overflow-y: auto; display: grid; place-items: center; padding: 40px 20px; }
.welcome-inner { width: 720px; max-width: 100%; }
.hero-logo {
  width: 76px; height: 76px; border-radius: 22px; background: var(--gradient);
  display: grid; place-items: center; font-size: 42px; margin: 0 auto 18px;
  box-shadow: 0 12px 32px rgba(99,102,241,.42), inset 0 1px 0 rgba(255,255,255,.22);
  animation: hero-float 4s ease-in-out infinite;
}
@keyframes hero-float { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-7px); } }
.welcome-inner h1 {
  text-align: center; font-size: 30px; margin-bottom: 10px; letter-spacing: .5px;
  background: linear-gradient(120deg, #fff 30%, #c7d2fe 70%, #ddd6fe);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}
.slogan { text-align: center; color: var(--text-2); font-size: 14px; margin-bottom: 28px; }
.welcome-composer { margin-bottom: 26px; }
.features { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.feat {
  text-align: center; padding: 16px 8px; font-size: 12.5px; color: var(--text-2);
  background: var(--bg-card); border: 1px solid var(--border); border-radius: 12px;
  transition: all .2s var(--ease, ease);
}
.feat:hover { transform: translateY(-3px); border-color: rgba(99,102,241,.45); background: var(--bg-card-2); box-shadow: var(--shadow); }
.feat span { display: block; font-size: 20px; margin-bottom: 6px; }

/* 执行栏 */
.ws-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 24px; border-bottom: 1px solid var(--border);
  background: rgba(20,23,31,.82); backdrop-filter: blur(10px);
  position: sticky; top: 0; z-index: 20;
}
.ws-title { display: flex; align-items: center; gap: 12px; }
.ws-title h2 { font-size: 17px; font-weight: 600; max-width: 520px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; letter-spacing: .3px; }
.ws-actions { display: flex; align-items: center; gap: 12px; }
.task-id { font-size: 11.5px; color: var(--text-3); font-family: Consolas, monospace; }
.ws-body { flex: 1; overflow-y: auto; padding: 20px 24px 60px; display: flex; flex-direction: column; gap: 16px; max-width: 1080px; width: 100%; margin: 0 auto; }
.failed-box { border-color: rgba(239,68,68,.5); }
.failed-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 6px; }
.failed-head h4 { margin: 0; }
.failed-box p { font-size: 12.5px; color: var(--text-2); }
</style>
