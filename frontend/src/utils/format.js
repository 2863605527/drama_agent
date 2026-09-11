// 状态、时间、选项等纯函数工具

export const STATUS_TEXT = {
  pending: '排队中',
  parsing: '解析剧本中',
  generating_asset: '待生成形象',
  human_review: '待人工审核',
  generating_shot: '生成分镜中',
  generating_video: '待生成视频',
  composing: '合成成片中',
  done: '已完成',
  failed: '失败'
}

export function statusText(s) {
  return STATUS_TEXT[s] || s || '未知'
}

export function statusBadge(s) {
  if (s === 'done') return 'badge-done'
  if (s === 'failed') return 'badge-failed'
  if (s === 'human_review') return 'badge-review'
  if (s === 'pending' || s === 'parsing') return 'badge-pending'
  return 'badge-running'
}

export function fmtTime(iso) {
  if (!iso) return ''
  // 后端无 created_at 回显时用 task_id（uuid）无法格式化，做保护
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = Date.now()
  const diff = (now - d.getTime()) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// 画风选项
export const STYLE_OPTIONS = [
  { value: 'anime', label: '日系动漫' },
  { value: 'realistic', label: '写实电影' },
  { value: '3d', label: '3D 渲染' },
  { value: 'q版', label: 'Q 版卡通' },
  { value: '国风', label: '国风水墨' }
]

// 配音方式
export const AUDIO_OPTIONS = [
  { value: 'auto', label: '自动（按通道）' },
  { value: 'native', label: '原生音频' },
  { value: 'tts', label: 'TTS 配音' }
]

// 流水线步骤定义
export const PIPELINE_STEPS = [
  { key: 'parse', label: '剧本解析' },
  { key: 'asset', label: '角色/场景图' },
  { key: 'review', label: '人工审核' },
  { key: 'video', label: '片段视频' },
  { key: 'compose', label: '合成成片' }
]

// 阿拉伯数字转中文（集数，1~20 够用，超出回退阿拉伯数字）
const CN = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
export function episodeCn(n) {
  n = Number(n) || 1
  if (n <= 10) return CN[n]
  if (n < 20) return '十' + CN[n - 10]
  if (n % 10 === 0) return CN[Math.floor(n / 10)] + '十'
  return String(n)
}

export function taskTitle(t) {
  const base = t?.script?.title || (t?.user_prompt || '未命名短剧').slice(0, 24)
  // 系列续作（第 2 集起）：显示「系列名 · 第N集」
  if (t?.parent_id && (t.episode_no || 1) > 1) {
    return `${t.series_title || base} · 第${episodeCn(t.episode_no)}集`
  }
  return base
}

// 系列名（去掉「· 第N集」后缀，书架标题用）
export function seriesName(t) {
  if (!t) return ''
  return (t.series_title || taskTitle(t)).replace(/\s*·\s*第.+集$/, '')
}

// 归组同一系列的所有集：沿 parent_id 链找到根任务，根相同的算一个系列，
// 按 episode_no 升序。找不到的父任务（已删除）按断链各自成组。
export function seriesFamily(tasks, task) {
  if (!task) return []
  const byId = new Map((tasks || []).map((t) => [t.task_id, t]))
  const rootOf = (t) => {
    let cur = t
    const seen = new Set([t.task_id])
    while (cur?.parent_id && byId.has(cur.parent_id) && !seen.has(cur.parent_id)) {
      seen.add(cur.parent_id)
      cur = byId.get(cur.parent_id)
    }
    return cur
  }
  const rootId = rootOf(task)?.task_id
  return (tasks || [])
    .filter((t) => rootOf(t)?.task_id === rootId)
    .sort((a, b) => (a.episode_no || 1) - (b.episode_no || 1))
}
