<template>
  <section class="card composer" :class="{ hero: hero, episode }">
    <div class="composer-head">
      <h3>{{ title }}</h3>
      <div class="style-pick" v-if="!episode">
        <span>画风</span>
        <select class="input" v-model="style">
          <option v-for="s in STYLE_OPTIONS" :key="s.value" :value="s.value">{{ s.label }}</option>
        </select>
      </div>
      <button v-if="episode" class="btn btn-ghost btn-sm" @click="$emit('cancel')">取消</button>
    </div>
    <textarea class="textarea" v-model="prompt" rows="4" :placeholder="placeholder"></textarea>
    <div class="composer-foot">
      <span class="hint">{{ hint }}</span>
      <button class="btn btn-primary" :disabled="submitting || !prompt.trim()" @click="submit">
        <span v-if="submitting" class="spin">◌</span>
        {{ submitting ? '正在提交…' : (episode ? `续写第${episodeCn(nextNo)}集` : '开始生成') }}
      </button>
    </div>
  </section>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useTaskStore } from '@/stores/task'
import { useToastStore } from '@/stores/toast'
import { STYLE_OPTIONS, episodeCn } from '@/utils/format'
import { extractError } from '@/api/request'

const props = defineProps({
  hero: { type: Boolean, default: false },
  // 续写模式
  episode: { type: Boolean, default: false },
  parentId: { type: String, default: '' },
  nextNo: { type: Number, default: 2 },
  seriesTitle: { type: String, default: '' }
})
const emit = defineEmits(['done', 'cancel'])

const taskStore = useTaskStore()
const toast = useToastStore()
const prompt = ref('')
const style = ref('anime')
const submitting = ref(false)

const title = computed(() => props.episode
  ? `📚 续写《${props.seriesTitle || '本系列'}》第 ${episodeCn(props.nextNo)} 集`
  : '描述你的短剧创意')
const placeholder = computed(() => props.episode
  ? '描述这一集的剧情走向（例如：矛盾升级、新角色登场）。已有角色/场景会自动沿用，新出现的才需要生成形象…'
  : '例如：落魄少年偶得上古神剑，在宗门大比上一鸣惊人。要求 3 个角色、2 个场景、4 个分镜……')
const hint = computed(() => props.episode
  ? '剧情承接上一集，已有角色立绘/场景图自动继承，仅新角色、新场景需生成'
  : '大模型将自动拆解角色、场景、分镜与片段，全程可人工干预')

async function submit() {
  if (!prompt.value.trim()) return
  submitting.value = true
  try {
    if (props.episode) {
      await taskStore.createEpisode(props.parentId, prompt.value.trim(), null)
      toast.ok(`第${episodeCn(props.nextNo)}集已创建，正在续写解析…`)
    } else {
      await taskStore.createTask(prompt.value.trim(), style.value)
      toast.ok('任务已创建，剧本解析中…')
    }
    prompt.value = ''
    emit('done')
  } catch (e) {
    toast.err(extractError(e))
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.composer.hero { padding: 26px; }
.composer.episode { border-color: rgba(99,102,241,.45); background: linear-gradient(135deg, rgba(99,102,241,.08), var(--bg-card) 60%); }
.composer-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 10px; }
.composer-head h3 { font-size: 15px; }
.style-pick { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-2); }
.style-pick .input { width: auto; padding: 6px 10px; }
.composer-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 12px; gap: 12px; }
.hint { font-size: 12px; color: var(--text-3); }
</style>
