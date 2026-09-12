// P1-7 E2E 冒烟测试（Playwright）
// 前置：后端已启动（默认 http://127.0.0.1:8010，可用 BASE_URL 覆盖）
// 本地：PW_CHANNEL=msedge PW_HEADLESS=false npx playwright test   （用系统 Edge，免下载浏览器）
// CI  ：npx playwright install --with-deps chromium && npx playwright test（chromium headless）
import { defineConfig } from '@playwright/test'

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8010'

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.js',
  timeout: 60_000,
  retries: 1,
  use: {
    baseURL: BASE_URL,
    // CI 默认 headless；本地可 PW_HEADLESS=false 用窗口观察
    headless: process.env.PW_HEADLESS !== 'false',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure'
  },
  projects: [{
    name: 'chromium',
    use: {
      browserName: 'chromium',
      // 本地无 Playwright 自带浏览器时可用系统 Edge/Chrome：PW_CHANNEL=msedge / chrome
      channel: process.env.PW_CHANNEL || undefined
    }
  }]
})
