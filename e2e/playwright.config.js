// P1-7 E2E 冒烟测试（Playwright）
// 前置：后端已启动（默认 http://127.0.0.1:8010，可用 BASE_URL 覆盖）
// 本地执行：先 `uvicorn main:app --port 8010`，再 `npx playwright test`
// CI 执行：见 .github/workflows/ci.yml 的 e2e job（自动起后端 + 构建前端 dist）
import { defineConfig } from '@playwright/test'

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:8010'

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.js',
  timeout: 60_000,
  retries: 1,
  use: {
    baseURL: BASE_URL,
    headless: true,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure'
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }]
})
