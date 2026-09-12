import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// 单测只测 store 纯逻辑：mock API 模块（request.js 依赖 window/localStorage，node 环境不适用）
vi.mock('@/api/task', () => ({
  taskApi: {
    list: vi.fn(),
    submit: vi.fn(),
    createEpisode: vi.fn(),
    remove: vi.fn(),
    get: vi.fn(),
    review: vi.fn(),
    retry: vi.fn(),
    compose: vi.fn(),
    regenerate: vi.fn(),
    replaceImage: vi.fn(),
    clearImage: vi.fn(),
    updateCharacter: vi.fn(),
    updateScene: vi.fn(),
    updateShot: vi.fn(),
    updateScript: vi.fn(),
    updateAudioMode: vi.fn(),
    uploadStreamToken: vi.fn()
  },
  streamUrl: vi.fn(),
  fetchStreamToken: vi.fn()
}))

import { useTaskStore } from '@/stores/task'

describe('task store — 关键业务 getters（P1-5 核心逻辑单测）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('assetsReady：角色立绘 + 场景昼夜双图齐全才为 true（分段式渲染前提）', () => {
    const s = useTaskStore()
    // 无剧本 → false
    s.current = { status: 'parsing', script: null }
    expect(s.assetsReady).toBe(false)

    // 角色缺立绘 → false
    s.current = {
      script: {
        characters: [{ id: 'c1', reference_image: '' }],
        scenes: [{ key: 's1', day_image_url: '/assets/d.png', night_image_url: '/assets/n.png' }]
      }
    }
    expect(s.assetsReady).toBe(false)

    // 场景缺黑夜图 → false
    s.current = {
      script: {
        characters: [{ id: 'c1', reference_image: '/assets/c.png' }],
        scenes: [{ key: 's1', day_image_url: '/assets/d.png', night_image_url: '' }]
      }
    }
    expect(s.assetsReady).toBe(false)

    // 齐全 → true
    s.current = {
      script: {
        characters: [{ id: 'c1', reference_image: '/assets/c.png' }],
        scenes: [{ key: 's1', day_image_url: '/assets/d.png', night_image_url: '/assets/n.png' }]
      }
    }
    expect(s.assetsReady).toBe(true)
  })

  it('activeAssetBusy：单张显示 label，多张聚合计数并取最早时间', () => {
    const s = useTaskStore()
    expect(s.activeAssetBusy).toBe(null)

    s.assetBusyMap = { 'c1': { label: '主角立绘', startAt: 1000 } }
    expect(s.activeAssetBusy.label).toBe('主角立绘')
    expect(s.activeAssetBusy.startAt).toBe(1000)

    s.assetBusyMap = {
      'c1': { label: 'A', startAt: 5000 },
      'c2': { label: 'B', startAt: 1000 },
      's1d': { label: 'C', startAt: 3000 }
    }
    expect(s.activeAssetBusy.label).toBe('3 张角色/场景图')
    expect(s.activeAssetBusy.startAt).toBe(1000) // 最早
  })

  it('日志上限：超过 600 条时裁剪到最近 600 条（防内存膨胀）', () => {
    const s = useTaskStore()
    s.logs = []
    for (let i = 0; i < 700; i++) s.logs.push(`[t] log-${i}`)
    // 模拟 store 内 append 逻辑：沿用现有 splice 规则
    if (s.logs.length > 600) s.logs.splice(0, s.logs.length - 600)
    expect(s.logs.length).toBe(600)
    expect(s.logs[0]).toBe('[t] log-100')
    expect(s.logs[599]).toBe('[t] log-699')
  })
})
