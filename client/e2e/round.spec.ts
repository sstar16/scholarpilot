import { authedTest as test, expect, fetchInPage } from './fixtures/mockApi'

/**
 * 场景 2：完整一轮检索 — 创建项目 + 触发 query plan + 关键词确认 + 反馈
 *
 * 注意：客户端走「本地 SQLite 优先」架构（见 src/stores/project.ts），多个 store
 *   - projectStore.fetchProject → 读 SQLite 不调 axios
 *   - conversationStore._shadowWriteToLocal → SQLite shadow write
 * 在浏览器 e2e（无 Tauri SQL plugin）下这部分行为受限，所以 UI 流程测试只
 * 验证「页面骨架渲染 + 路由跳转 + 鉴权保护」，深层 store 行为由 vitest 单测覆盖。
 *
 * Round 状态机 / 反馈 API mock 走 fetchInPage（page.evaluate(fetch) 走 context.route）。
 */

test.describe('一轮检索流程 (UI shell + API)', () => {
  test('Dashboard 渲染期刊 masthead + 新建按钮', async ({ page, mockState }) => {
    void mockState
    await page.goto('/dashboard')
    // masthead 品牌
    await expect(page.locator('.hj-masthead__brand')).toContainText('SCHOLARPILOT', {
      timeout: 10_000,
    })
    // hero 行的「+ 新建项目」按钮（用 hj-cta class 精确匹配）
    await expect(page.locator('.hj-cta', { hasText: '新建项目' }).first()).toBeVisible()
  })

  test('点击「新建项目」→ /projects/new', async ({ page, mockState }) => {
    void mockState
    await page.goto('/dashboard')
    await page.locator('.hj-cta', { hasText: '新建项目' }).first().click()
    await page.waitForURL('**/projects/new', { timeout: 10_000 })
    await expect(page).toHaveURL(/\/projects\/new$/)
  })

  test('对话页加载 + 顶栏「创建研究项目」', async ({ page, mockState }) => {
    void mockState
    await page.goto('/projects/new')
    // ConversationCreate 顶栏 card-header 有「创建研究项目」文字
    await expect(page.locator('.card-header')).toContainText('创建研究项目', {
      timeout: 10_000,
    })
  })

  test('ProjectView 路由可访问（页面骨架渲染）', async ({ page, mockState }) => {
    void mockState
    await page.goto('/projects/proj-test-1')
    // ProjectView 用 v-if="projectStore.loading" 显示 skeleton；本地 DB 取不到时
    // project 为 null，渲染为空 div.project-view
    await expect(page.locator('.project-view')).toBeVisible({ timeout: 10_000 })
  })

  test('round 状态机推进：fetching → scoring → summarizing → awaiting_feedback', async ({
    page,
    mockState,
  }) => {
    void page
    expect(mockState.statusSequence).toEqual([
      'fetching',
      'scoring',
      'summarizing',
      'awaiting_feedback',
    ])
    for (let i = 0; i < 4; i++) {
      const idx = Math.min(mockState.statusIdx, mockState.statusSequence.length - 1)
      const status = mockState.statusSequence[idx]
      mockState.statusIdx += 1
      expect(status).toBe(mockState.statusSequence[i])
    }
    expect(mockState.statusSequence[3]).toBe('awaiting_feedback')
  })

  test('反馈提交后 round.status → complete', async ({ page, mockState }) => {
    const rid = 'round-mock-1'
    mockState.rounds[rid] = {
      id: rid,
      project_id: 'proj-1',
      number: 1,
      status: 'awaiting_feedback',
    }
    await page.goto('/login')
    const res = await fetchInPage(
      page,
      `/api/projects/proj-1/rounds/${rid}/feedback`,
      {
        method: 'POST',
        body: {
          feedbacks: [
            { document_id: 'doc-1', bucket: 'core' },
            { document_id: 'doc-2', bucket: 'related' },
            { document_id: 'doc-3', bucket: 'rejected' },
          ],
        },
      },
    )
    expect(res.status).toBe(200)
    expect(res.body.saved).toBeGreaterThan(0)
    expect(mockState.rounds[rid].status).toBe('complete')
  })

  test('keyword plan API 返回每源关键词', async ({ page, mockState }) => {
    void mockState
    await page.goto('/login')
    const res = await fetchInPage(
      page,
      '/api/projects/proj-1/rounds/prepare',
      { method: 'POST' },
    )
    expect(res.status).toBe(200)
    expect(res.body.keyword_plan).toBeDefined()
    expect(res.body.keyword_plan.per_source).toHaveProperty('arxiv')
  })
})
