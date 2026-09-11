<template>
  <section class="card compose" v-if="segments.length">
    <header>
      <h3>🎬 合成完整短剧</h3>
      <span class="ready">已就绪片段 {{ readyCount }}/{{ segments.length }}</span>
    </header>

    <div v-if="finalUrl" class="final">
      <video :src="finalUrl" controls preload="metadata"></video>
      <div class="final-actions">
        <a class="btn btn-primary" :href="finalUrl" target="_blank" rel="noopener">在新窗口打开</a>
        <a class="btn btn-ghost" :href="finalUrl" download>下载成片</a>
        <button class="btn" :disabled="epBusy" @click="nextEpisode">➕ 新增下一集</button>
      </div>
      <p class="ep-tip">「新增下一集」会在本系列下创建第 {{ nextNo }} 集：剧情承接本集，已有角色立绘 / 场景图自动沿用，仅新增角色 / 场景需要重新生成。</p>
    </div>

    <div v-else class="compose-bar">
      <p>将全部片段按顺序拼接、混入配音，输出最终成片（ffmpeg 本地合成）。</p>
      <button class="btn btn-primary" :disabled="busy || readyCount === 0" @click="doCompose">
        <span v-if="busy" class="spin">◌</span>
        {{ busy ? '合成中，进度见日志…' : '开始合成完整视频' }}
      </button>
    </div>
  </section>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useTaskStore } from '@/stores/task'
import { taskApi } from '@/api/task'
import { useToastStore } from '@/stores/toast'
import { extractError } from '@/api/request'

const emit = defineEmits(['next-episode'])
const taskStore = useTaskStore()
const toast = useToastStore()
const busy = ref(false)
const epBusy = ref(false)

const segments = computed(() => taskStore.segments)
const readyCount = computed(() => segments.value.filter((s) => s.video_url).length)
const finalUrl = computed(() => taskStore.current?.final_video_url || '')
const nextNo = computed(() => (taskStore.current?.episode_no || 1) + 1)

function nextEpisode() { emit('next-episode') }

async function doCompose() {
  busy.value = true
  try {
    await taskApi.compose(taskStore.currentId)
    toast.ok('已开始合成，完成后自动展示成片')
    setTimeout(() => taskStore.reloadCurrent(), 2000)
  } catch (e) {
    toast.err(extractError(e))
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
h3 { font-size: 15px; }
.ready { font-size: 12.5px; color: var(--text-3); }
.compose-bar { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.compose-bar p { font-size: 12.5px; color: var(--text-2); flex: 1; }
.final video { width: 100%; max-height: 420px; border-radius: 10px; background: #000; }
.final-actions { display: flex; gap: 10px; margin-top: 12px; flex-wrap: wrap; }
.ep-tip { font-size: 12px; color: var(--text-3); margin-top: 10px; line-height: 1.6; }
</style>
