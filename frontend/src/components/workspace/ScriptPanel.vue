<template>
  <section class="card" v-if="script">
    <header>
      <h3>📖 剧本信息</h3>
      <button class="btn btn-ghost btn-sm" @click="openEdit">编辑剧本</button>
    </header>
    <div class="script-body">
      <h4 class="script-title">{{ script.title }}</h4>
      <pre class="raw">{{ script.raw_content }}</pre>
      <div class="stat">
        {{ script.characters?.length || 0 }} 角色 ·
        {{ script.scenes?.length || 0 }} 场景 ·
        {{ script.shots?.length || 0 }} 分镜 ·
        {{ script.segments?.length || 0 }} 片段
      </div>
    </div>

    <!-- 编辑弹层 -->
    <div v-if="editing" class="mask" @click.self="editing = false">
      <div class="modal">
        <h4>编辑剧本</h4>
        <label class="f"><span>标题</span><input class="input" v-model="form.title" /></label>
        <label class="f"><span>原始剧本</span><textarea class="textarea" rows="10" v-model="form.raw_content"></textarea></label>
        <div class="modal-foot">
          <button class="btn" @click="editing = false">取消</button>
          <button class="btn btn-primary" :disabled="saving" @click="save">保存</button>
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

const taskStore = useTaskStore()
const toast = useToastStore()
const script = computed(() => taskStore.script)
const editing = ref(false)
const saving = ref(false)
const form = ref({ title: '', raw_content: '' })

function openEdit() {
  form.value = { title: script.value.title, raw_content: script.value.raw_content }
  editing.value = true
}

async function save() {
  saving.value = true
  try {
    await taskApi.updateScript(taskStore.currentId, form.value.title, form.value.raw_content)
    await taskStore.reloadCurrent()
    editing.value = false
    toast.ok('剧本已更新')
  } catch (e) {
    toast.err(extractError(e))
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
h3 { font-size: 15px; }
.script-title { font-size: 16px; margin-bottom: 10px; }
.raw {
  white-space: pre-wrap; font-family: inherit; font-size: 13px; color: var(--text-2);
  background: var(--bg-app); border: 1px solid var(--border); border-radius: 8px;
  padding: 12px; max-height: 260px; overflow: auto; line-height: 1.8;
}
.stat { font-size: 12px; color: var(--text-3); margin-top: 10px; }

.mask { position: fixed; inset: 0; background: rgba(6,8,14,.6); z-index: 900; display: grid; place-items: center; }
.modal { width: 560px; max-width: 92vw; background: var(--bg-card); border: 1px solid var(--border-strong); border-radius: 14px; padding: 22px; }
.modal h4 { margin-bottom: 16px; }
.f { display: block; margin-bottom: 14px; }
.f span { display: block; font-size: 12.5px; color: var(--text-2); margin-bottom: 6px; }
.modal-foot { display: flex; justify-content: flex-end; gap: 10px; }
</style>
