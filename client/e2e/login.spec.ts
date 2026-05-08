import { test, expect } from './fixtures/mockApi'

/**
 * 场景 1：登录 + 注册流程
 *
 * 客户端 Login.vue 模式：
 * - default：登录态
 * - ?mode=register：注册态（包含邀请码字段）
 *
 * AuthForm.vue 字段：email / password / name / pwd2 / invitation_code
 * 提交按钮文字「登 录」/「注 册」/「发送重置链接」
 */

test.describe('登录 / 注册', () => {
  test('登录页正确渲染品牌 + tagline', async ({ page, mockState }) => {
    void mockState
    await page.goto('/login')
    // 品牌行
    await expect(page.locator('.scene-mark')).toContainText(/S.*P/)
    // 标题包含「思考」
    await expect(page.locator('.scene-title')).toContainText('思考')
    await expect(page.locator('.scene-title')).toContainText('科研')
  })

  test('邮箱登录 → /dashboard', async ({ page, mockState }) => {
    void mockState
    await page.goto('/login')

    // 填邮箱 + 密码
    await page.locator('input[type="email"]').fill('tester@scholarpilot.top')
    await page.locator('input[type="password"]').first().fill('test1234')

    // 点击「登 录」按钮
    await page.locator('.af-cta', { hasText: /登\s*录/ }).click()

    // 等成功 transition + 跳转
    await page.waitForURL('**/dashboard', { timeout: 15_000 })
    await expect(page).toHaveURL(/\/dashboard$/)

    // dashboard masthead 出现
    await expect(page.locator('.hj-masthead__brand')).toContainText('SCHOLARPILOT')
  })

  test('注册流程（含邀请码）→ /dashboard', async ({ page, mockState }) => {
    void mockState
    await page.goto('/login?mode=register')

    // 注册标题
    await expect(page.locator('.af-title')).toContainText('创建账号')

    // 填字段
    await page.locator('input[type="email"]').fill('newuser@scholarpilot.top')
    await page.locator('input[autocomplete="name"]').fill('新用户')
    const pwdInputs = page.locator('input[type="password"]')
    await pwdInputs.first().fill('test1234')
    await pwdInputs.nth(1).fill('test1234')
    // 邀请码输入框
    await page.locator('input[autocomplete="off"]').first().fill('beta-invite-code')

    // 提交
    await page.locator('.af-cta', { hasText: /注\s*册/ }).click()

    await page.waitForURL('**/dashboard', { timeout: 15_000 })
    await expect(page).toHaveURL(/\/dashboard$/)
  })

  test('邮箱格式错误时本地校验拦截', async ({ page, mockState }) => {
    void mockState
    await page.goto('/login')
    await page.locator('input[type="email"]').fill('bad-email')
    await page.locator('input[type="password"]').first().fill('test1234')
    await page.locator('.af-cta').click()
    await expect(page.locator('.af-err')).toContainText('有效邮箱')
  })

  test('未登录访问受保护路由 → 跳 /login', async ({ page, mockState }) => {
    void mockState
    await page.goto('/dashboard')
    await page.waitForURL('**/login', { timeout: 5_000 })
    await expect(page).toHaveURL(/\/login/)
  })
})
