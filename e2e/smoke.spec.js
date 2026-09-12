// P1-7 核心用户链路冒烟（Playwright）：
// 1) 注册 → 登录态跳转工作台
// 2) 工作台核心元素渲染（新建短剧 / 开始生成 / 模型通道）
// 3) 未配置大模型时点击「开始生成」→ 弹窗拦截，不进入流程
// 4) 模型通道配置弹窗 → 「📖 教程」按钮 → 图文教程弹窗
import { test, expect } from '@playwright/test'

const uniq = () => `e2e_${Date.now() % 100000000}`

test('注册 → 工作台 → 未配置模型拦截 → 通道教程弹窗', async ({ page }) => {
  const username = uniq()
  const password = 'e2epass123'

  // ---- 1. 注册（登录页切换「注册」tab）----
  await page.goto('/login')
  await expect(page.locator('body')).toContainText(/AI 短剧智能生成工作台/, { timeout: 20_000 })
  await page.getByRole('button', { name: '注册', exact: true }).click()
  await page.locator('input[placeholder*="字母开头"]').fill(username)
  await page.locator('input[placeholder*="6~20位"]').fill(password)
  await page.getByRole('button', { name: /注册并登录/ }).click()

  // ---- 2. 工作台 ----
  await expect(page.locator('body')).toContainText(/新建短剧/, { timeout: 25_000 })
  await expect(page.locator('body')).toContainText(/开始生成/, { timeout: 10_000 })

  // ---- 3. 未配置 LLM → 开始生成按钮禁用（拦截进入流程）----
  const startBtn = page.getByRole('button', { name: /开始生成/ }).first()
  await expect(startBtn).toBeDisabled({ timeout: 8_000 })

  // ---- 4. 模型通道弹窗 → 教程 ----
  await page.getByText('模型通道', { exact: true }).click()
  await expect(page.locator('body')).toContainText(/模型通道配置/, { timeout: 8_000 })
  const tut = page.getByRole('button', { name: /📖 教程/ }).first()
  await expect(tut).toBeVisible({ timeout: 8_000 })
  await tut.click()
  await expect(page.locator('body')).toContainText(/Key|密钥|教程/, { timeout: 8_000 })
})

test('登录页基础渲染与非法输入提示', async ({ page }) => {
  await page.goto('/login')
  await expect(page.locator('body')).toContainText(/用户名/, { timeout: 15_000 })
  await page.getByRole('button', { name: '注册', exact: true }).click()
  // 中文用户名 → 前端即时校验报错
  await page.locator('input[placeholder*="字母开头"]').fill('中文名')
  await expect(page.locator('body')).toContainText(/字母|仅/, { timeout: 8_000 })
})
