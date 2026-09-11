import { defineStore } from 'pinia'
import { taskApi, streamUrl, fetchStreamToken } from '@/api/task'

let es = null

export const useTaskStore = defineStore('task', {
  state: () => ({
    tasks: [],            // 任务列表（摘要）
    current: null,        // 当前选中任务（完整 DramaTask）
    currentId: '',
    logs: [],             // 当前任务实时日志
    maxSeq: 0,            // 已接收日志的最大自增序号（用于和详情基线去重）
    maxTs: 0,             // 已接收日志的最大服务器时间戳（跨重启单调，重启后 seq 归零也不误判重复）
    segRuntime: {},       // 片段运行态：{ [segment_id]: 'running' | 'ok' | 'failed' }
    assetBusyMap: {},     // 多张图片并发生成忙碌态：{ [key]: { label, startAt } }
    loadingList: false,
    connected: false,
    navTick: 0,           // 侧边栏点击信号（每次从列表点任务都自增，同任务重复点击也能触发视图切换）
    _autoReloading: false // 阶段跃迁自动拉详情的防抖标记
  }),
  getters: {
    script: (s) => s.current?.script || null,
    characters: (s) => s.current?.script?.characters || [],
    scenes: (s) => s.current?.script?.scenes || [],
    shots: (s) => s.current?.script?.shots || [],
    segments: (s) => s.current?.script?.segments || [],
    // 当前并发生成的图片（单张精确到名称，多张聚合计数，取最早开始时间驱动计时）
    activeAssetBusy(s) {
      const keys = Object.keys(s.assetBusyMap || {})
      if (!keys.length) return null
      if (keys.length === 1) {
        const v = s.assetBusyMap[keys[0]]
        return { label: v.label, startAt: v.startAt }
      }
      let earliest = Date.now()
      keys.forEach((k) => { earliest = Math.min(earliest, s.assetBusyMap[k].startAt) })
      return { label: `${keys.length} 张角色/场景图`, startAt: earliest }
    },
    // 形象资产是否全部就绪：每个角色有立绘、每个场景昼夜双图齐全（含续写继承）。
    // 用于分段式渲染：图没出齐/传齐之前，不渲染片段视频与合成组件。
    assetsReady(s) {
      const script = s.current?.script
      if (!script) return false
      const chars = script.characters || []
      const scenes = script.scenes || []
      if (!chars.length || !scenes.length) return false
      if (!chars.every((c) => c.reference_image)) return false
      return scenes.every((sc) => sc.day_image_url && sc.night_image_url)
    }
  },
  actions: {
    // ---------------- 任务列表 ----------------
    async refreshList(selectId = null) {
      this.loadingList = true
      try {
        this.tasks = await taskApi.list()
        if (selectId) await this.selectTask(selectId)
      } finally {
        this.loadingList = false
      }
    },

    async createTask(prompt, style) {
      const task = await taskApi.submit(prompt, style)
      await this.refreshList()
      await this.selectTask(task.task_id)
      return task
    },

    // 续写下一集：继承父集角色/场景资产，创建后切到新一集
    async createEpisode(parentId, prompt, style) {
      const task = await taskApi.createEpisode(parentId, prompt, style)
      await this.refreshList()
      await this.selectTask(task.task_id)
      return task
    },

    // 删除任务：后端级联删除整个系列（根+子集），本地同样移除整个系列；
    // 若删的是当前任务（或当前是系列某一集）则回到空白态
    async deleteTask(id) {
      await taskApi.remove(id)
      const familyIds = new Set()
      const byId = new Map(this.tasks.map((t) => [t.task_id, t]))
      const collect = (tid) => {
        familyIds.add(tid)
        this.tasks.filter((t) => t.parent_id === tid).forEach((t) => collect(t.task_id))
      }
      collect(id)
      this.tasks = this.tasks.filter((t) => !familyIds.has(t.task_id))
      if (familyIds.has(this.currentId)) this.newBlank()
    },

    // 失败/完成任务整体重新开始：原地重跑并重新订阅进度流
    async retryTask(id) {
      const task = await taskApi.retry(id)
      await this.refreshList()
      if (id === this.currentId) {
        await this.selectTask(id)   // 关闭旧 SSE、清空旧日志、拉取重置后的任务并重连
      }
      return task
    },

    // 回到「新建空白」态：右侧显示创意输入
    newBlank() {
      this.closeStream()
      this.current = null
      this.currentId = ''
      this.logs = []
      this.maxSeq = 0
      this.segRuntime = {}
      this.assetBusyMap = {}
    },

    // ---------------- 选中任务 + SSE ----------------
    async selectTask(id) {
      this.closeStream()
      this.currentId = id
      const detail = await taskApi.detail(id)
      this.current = detail
      // 用后端持久化的历史日志作为基线（刷新/重启后仍可回显），SSE 只补增量
      const baseLogs = detail?.logs || []
      this.logs = baseLogs.map((l) => l.message || '').filter(Boolean)
      this.maxSeq = baseLogs.reduce((m, l) => Math.max(m, l.seq || 0), 0)
      this.maxTs = baseLogs.reduce((m, l) => Math.max(m, l.ts || 0), 0)
      this.segRuntime = {}
      this.assetBusyMap = {}
      this.openStream(id)
      this._startWatchdog()
      return this.current
    },

    // 从左侧列表点任务：无论是否已是当前任务都发信号，
    // 工作台据此决定开书架（已完成）还是流程详情（进行中/失败）
    async selectFromSidebar(id) {
      await this.selectTask(id)
      this.navTick++
    },

    async reloadCurrent() {
      if (!this.currentId) return
      const t = await taskApi.detail(this.currentId)
      if (t) {
        // 合并保护：本地已回填视频 URL、但回拉数据暂缺时（落库/广播时序差），保留本地值，避免把视频覆盖没
        const old = this.current
        if (old?.script?.segments && t.script?.segments) {
          t.script.segments.forEach((ns) => {
            const os = old.script.segments.find((x) => x.segment_id === ns.segment_id)
            if (os?.video_url && !ns.video_url) ns.video_url = os.video_url
          })
        }
        this.current = t
      }
    },

    openStream(id) {
      this.closeStream()
      this._connectCount = 0
      this._connectStream(id)
    },

    // P1-5：SSE 用短时 stream token（60s）。建立/重建连接前先取 token，
    // onerror 时按防抖+上限自动重新签发重建，避免「token 过期→自动重连永远 401」。
    async _connectStream(id) {
      if (this._connectCount >= 5) { this.connected = false; return } // 连续失败上限，交给看门狗兜底
      this._connectCount++
      let token = ''
      try {
        token = await fetchStreamToken(id)
      } catch { this.connected = false; return }
      if (!token || this.currentId !== id) return
      this._streamToken = token
      if (es) { es.close(); es = null }
      es = new EventSource(streamUrl(id, token))
      this.connected = true
      const events = ['status', 'log', 'char', 'scene_img', 'shot', 'segment',
        'compose', 'final', 'fail', 'script_update', 'char_update',
        'scene_update', 'shot_update']
      events.forEach((evt) => {
        es.addEventListener(evt, (e) => {
          try { this.applyEvent(evt, JSON.parse(e.data)) } catch (err) { /* ignore */ }
        })
      })
      es.onerror = () => {
        // EventSource 自动重连同一 URL；token 过期（60s）后重连会 401。
        // 主动关闭并重新签发 token 重建，15s 防抖避免风暴。
        this.connected = false
        const now = Date.now()
        if (!this._lastReconnectAt || now - this._lastReconnectAt > 15000) {
          this._lastReconnectAt = now
          if (es) { es.close(); es = null }
          this._connectStream(id)
        }
      }
      es.onopen = () => { this.connected = true }
    },

    closeStream() {
      if (es) { es.close(); es = null }
      this.connected = false
      this._stopWatchdog()
    },

    // ---------------- 兜底轮询看门狗 ----------------
    // 任务处于进行态时每 8 秒回拉一次详情：即使 SSE 断连/事件丢失（容器重启、
    // 令牌过期、代理断流…），UI 也保证在有限时间内收敛到数据库真实状态，
    // 不会永远卡在「生成中/合成中」（2026-09-04 合成完成但页面无反应事故的兜底）
    _startWatchdog() {
      this._stopWatchdog()
      this._wdTimer = setInterval(async () => {
        const st = this.current?.status
        const running = ['parsing', 'generating_asset', 'generating_shot', 'generating_video', 'composing'].includes(st)
        if (running && !this._wdBusy) {
          this._wdBusy = true
          try { await this.reloadCurrent() } catch { /* 忽略，下轮再试 */ } finally { this._wdBusy = false }
        }
      }, 8000)
    },
    _stopWatchdog() {
      if (this._wdTimer) { clearInterval(this._wdTimer); this._wdTimer = null }
    },

    appendLog(message) {
      const time = new Date().toLocaleTimeString('zh-CN', { hour12: false })
      this.logs.push(`[${time}] ${message}`)
      if (this.logs.length > 600) this.logs.splice(0, this.logs.length - 600)
    },

    // 标记某张图（character:char_id / scene_image:scene_key:variant）开始生成，支持多张并发各自显示
    setAssetBusy(key, label) {
      this.assetBusyMap = { ...this.assetBusyMap, [key]: { label, startAt: Date.now() } }
    },
    clearAssetBusy(key) {
      if (!key || !(key in this.assetBusyMap)) return
      const next = { ...this.assetBusyMap }
      delete next[key]
      this.assetBusyMap = next
    },

    // ---------------- SSE 事件 → 当前任务状态合并 ----------------
    // 阶段跃迁后若本地还没有剧本（SSE 只推状态不推全量剧本），自动拉一次详情让各面板渲染
    _maybeAutoReload(status) {
      const SCRIPT_READY = ['generating_asset', 'human_review', 'generating_shot', 'generating_video', 'composing', 'done']
      if (SCRIPT_READY.includes(status) && this.current && !this.current.script && !this._autoReloading) {
        this._autoReloading = true
        this.reloadCurrent().finally(() => {
          this._autoReloading = false
          // 拉取后基线日志可能更新，同步 seq/ts 水位避免重复
          const base = this.current?.logs || []
          this.maxSeq = Math.max(this.maxSeq, base.reduce((m, l) => Math.max(m, l.seq || 0), 0))
          this.maxTs = Math.max(this.maxTs, base.reduce((m, l) => Math.max(m, l.ts || 0), 0))
        })
      }
    },

    applyEvent(evt, d) {
      // 日志去重：优先用服务器时间戳 ts（跨进程重启单调，不会把新事件误判为重复）；
      // 旧事件无 ts 时退回 seq 水位比较（SSE 历史回放不会和基线重复）
      if (d.message && (evt === 'status' || evt === 'log' || evt === 'compose' || evt === 'final' || evt === 'fail')) {
        const ts = typeof d.ts === 'number' ? d.ts : null
        let fresh = false
        if (ts != null) {
          if (ts > (this.maxTs || 0)) { fresh = true; this.maxTs = ts }
        } else if (d.seq == null || d.seq > this.maxSeq) {
          fresh = true
        }
        if (fresh) {
          this.appendLog(d.message)
          if (d.seq != null) this.maxSeq = Math.max(this.maxSeq, d.seq)
        }
      }
      if (!this.current) return
      const t = this.current

      if (evt === 'status') {
        t.status = d.status
        this._maybeAutoReload(d.status)
      } else if (evt === 'log') {
        // 已在上面记录
      } else if (evt === 'fail') {
        t.status = 'failed'
      } else if (evt === 'final') {
        t.final_video_url = d.final_video_url
        t.status = 'done'
        this.reloadCurrent()
      } else if (evt === 'compose') {
        if (d.status === 'ok') { t.status = 'done'; this.reloadCurrent() }
      } else if (evt === 'char') {
        const c = t.script?.characters?.[d.index]
        if (c) {
          if (d.status === 'clear') c.reference_image = null
          else if (d.image_url) c.reference_image = d.image_url
        }
        if (['ok', 'failed', 'clear'].includes(d.status)) this.clearAssetBusy(`character:${d.char_id}`)
      } else if (evt === 'scene_img') {
        const sc = t.script?.scenes?.[d.index]
        if (sc) {
          if (d.status === 'clear' || d.status === 'reset') {
            // 用户主动清除 / 白天图更换后连带清空
            if (d.variant === 'day') sc.day_image_url = null
            else sc.night_image_url = null
          } else if (d.image_url) {
            if (d.variant === 'day') sc.day_image_url = d.image_url
            else sc.night_image_url = d.image_url
          }
        }
        if (['ok', 'failed', 'reset', 'clear'].includes(d.status)) this.clearAssetBusy(`scene_image:${d.scene_key}:${d.variant}`)
      } else if (evt === 'shot') {
        const sh = t.script?.shots?.find((x) => x.shot_id === d.shot_id)
        if (sh && d.video_url) sh.video_url = d.video_url
      } else if (evt === 'segment') {
        if (d.status && d.segment_id) this.segRuntime[d.segment_id] = d.status
        const seg = t.script?.segments?.find((x) => x.segment_id === d.segment_id)
        if (seg && d.quality_warning !== undefined) seg.quality_warning = d.quality_warning
        if (seg && d.video_url) {
          seg.video_url = d.video_url
          t.script.shots.forEach((sh) => {
            if (seg.shot_ids.includes(sh.shot_id)) sh.video_url = d.video_url
          })
        }
        // 片段视频落库后回刷一次，保证刷新前后状态一致
        if (d.status === 'ok' || d.status === 'failed') this.reloadCurrent()
      } else if (evt === 'script_update') {
        if (t.script) {
          if (d.title) t.script.title = d.title
          if (d.raw_content) t.script.raw_content = d.raw_content
        }
      } else if (evt === 'char_update') {
        const c = t.script?.characters?.find((x) => x.char_id === d.char_id)
        if (c) { c.name = d.name; c.description = d.description }
      } else if (evt === 'scene_update') {
        const sc = t.script?.scenes?.find((x) => x.scene_key === d.scene_key)
        if (sc) sc.description = d.description
      } else if (evt === 'shot_update') {
        const sh = t.script?.shots?.find((x) => x.shot_id === d.shot_id)
        if (sh) Object.assign(sh, {
          content: d.content ?? sh.content,
          camera: d.camera ?? sh.camera,
          lighting: d.lighting ?? sh.lighting,
          prompt: d.prompt ?? sh.prompt
        })
      }
    }
  }
})
