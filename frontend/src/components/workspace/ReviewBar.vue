<template>
  <section class="card review" v-if="taskStore.current?.status === 'human_review'">
    <div class="icon">🖐️</div>
    <div class="info">
      <h4>人工审核断点</h4>
      <p>角色立绘与昼夜场景图已生成，请确认形象是否符合预期。确认后进入片段视频阶段，需你在下方逐片段手动点击生成。</p>
    </div>
    <div class="actions">
      <details class="adjust">
        <summary class="btn btn-ghost btn-sm">需要调整</summary>
        <div class="adjust-box">
          <textarea class="textarea" rows="3" v-model="note" placeholder="填写形象调整意见，将回到形象生成阶段"></textarea>
          <button class="btn btn-danger btn-sm" :disabled="busy" @click="submit(false)">提交调整意见</button>
        </div>
      </details>
      <button class="btn btn-primary" :disabled="busy" @click="submit(true)">
        <span v-if="busy" class="spin">◌</span> 形象无误，继续生成
      </button>
    </div>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import { useTaskStore } from '@/stores/task'
import { taskApi } from '@/api/task'
import { useToastStore } from '@/stores/toast'
import { extractError } from '@/api/request'

const taskStore = useTaskStore()
const toast = useToastStore()
const busy = ref(false)
const note = ref('')

async function submit(accept) {
  if (!accept && !note.value.trim()) {
    toast.err('请填写调整意见')
    return
  }
  busy.value = true
  try {
    await taskApi.review(taskStore.currentId, accept, accept ? null : note.value.trim())
    toast.ok(accept ? '已确认，请在下方逐片段手动生成视频' : '已提交调整意见')
    note.value = ''
    setTimeout(() => taskStore.reloadCurrent(), 1200)
  } catch (e) {
    toast.err(extractError(e))
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.review { display: flex; align-items: center; gap: 16px; border-color: rgba(245,158,11,.4); background: linear-gradient(135deg, rgba(245,158,11,.08), var(--bg-card) 60%); }
.icon { font-size: 30px; }
.info { flex: 1; }
.info h4 { font-size: 15px; margin-bottom: 4px; }
.info p { font-size: 12.5px; color: var(--text-2); }
.actions { display: flex; align-items: flex-start; gap: 10px; }
.adjust { position: relative; }
.adjust summary { list-style: none; }
.adjust summary::-webkit-details-marker { display: none; }
.adjust-box {
  position: absolute; right: 0; top: 34px; width: 320px; z-index: 20;
  background: var(--bg-card-2); border: 1px solid var(--border-strong); border-radius: 10px;
  padding: 12px; box-shadow: var(--shadow); display: flex; flex-direction: column; gap: 8px;
}
</style>
