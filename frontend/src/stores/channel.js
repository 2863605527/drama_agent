import { defineStore } from 'pinia'
import { channelApi } from '@/api/channel'
import { useToastStore } from './toast'

// 一段通道配置的空模板
function emptyProfile() {
  return {
    channel: 'env',
    // cv
    access_key: '', secret_key: '', req_key: '', resolution: '',
    // ark
    api_url: '', api_key: '', model: '', ratio: '', generate_audio: true,
    // http
    endpoint: '', submit_url: '', poll_url: '', token: '', result_path: '',
    task_id_path: '', status_path: '', success_status: '', video_url_path: '',
    native_audio: '',
    // llm
    temperature: null
  }
}

function emptyConfig() {
  return { llm: emptyProfile(), image: emptyProfile(), video: emptyProfile() }
}

export const useChannelStore = defineStore('channel', {
  state: () => ({
    meta: null,          // 通道/模型预设
    config: emptyConfig(),
    loaded: false,
    dialogVisible: false
  }),
  getters: {
    // 侧栏展示：三段当前通道简称
    summary(state) {
      const name = (kind) => {
        const cur = state.config?.[kind]?.channel || 'env'
        if (cur === 'env') return '系统默认'
        const map = { volc_cv: '火山即梦CV', volc_ark: '火山方舟ARK', generic_http: '通用HTTP', openai: 'OpenAI兼容' }
        return map[cur] || cur
      }
      return { llm: name('llm'), image: name('image'), video: name('video') }
    }
  },
  actions: {
    async loadMeta() {
      if (this.meta) return this.meta
      this.meta = await channelApi.meta()
      return this.meta
    },
    async loadConfig() {
      const data = await channelApi.get()
      const remote = data.config || {}
      const cfg = emptyConfig()
      for (const k of ['llm', 'image', 'video']) {
        if (remote[k]) cfg[k] = { ...emptyProfile(), ...remote[k] }
      }
      this.config = cfg
      this.loaded = true
      return cfg
    },
    async save() {
      // 清掉空字符串段不必要字段由后端容忍；直接整体提交（掩码字段后端保留旧值）
      await channelApi.save(this.config)
      const toast = useToastStore()
      toast.ok('通道配置已保存，新任务将使用该配置')
      await this.loadConfig()
    },
    async test(kind) {
      return await channelApi.test(kind, this.config[kind])
    },
    openDialog() { this.dialogVisible = true },
    closeDialog() { this.dialogVisible = false },
    reset() { this.config = emptyConfig() }
  }
})
