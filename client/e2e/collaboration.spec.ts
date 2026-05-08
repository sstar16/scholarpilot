import { authedTest as test, expect, fetchInPage } from './fixtures/mockApi'

/**
 * 场景 3：共同研究模式
 *
 * 客户端 collab 路径：项目 + 文献库非空 → ChatPanel 触发 collaboration agent →
 * rich_type=collaboration_started → /collaboration/question 返回 answer + citations。
 *
 * 浏览器 e2e 不走完整 chat → store → SQLite 流程（依赖 Tauri SQL plugin），改测：
 * 1. 协作问答 API 返回 citations 形状
 * 2. 协作启动 API 返回 doc_ids
 * 3. 文献库列表 API 形状
 * 4. ProjectView 路由可访问
 */

test.describe('共同研究模式', () => {
  test('协作问答 API 返回带 citations 的回答', async ({ page, mockState }) => {
    void mockState
    await page.goto('/login')
    const res = await fetchInPage(
      page,
      '/api/conversation/sess-1/collaboration/question',
      {
        method: 'POST',
        body: { question: '这些论文里哪个用了 Transformer？' },
      },
    )
    expect(res.status).toBe(200)
    expect(res.body.answer).toContain('Transformer')
    expect(res.body.citations).toHaveLength(2)
    expect(res.body.citations[0].doc_id).toBe('doc-1')
    expect(res.body.citations[1].doc_id).toBe('doc-2')
  })

  test('协作启动 API 返回 doc_ids 列表', async ({ page, mockState }) => {
    await page.goto('/login')
    const res = await fetchInPage(
      page,
      '/api/conversation/sess-1/collaboration/start',
      {
        method: 'POST',
        body: { doc_ids: mockState.documents.map((d) => d.id) },
      },
    )
    expect(res.status).toBe(200)
    expect(res.body.doc_ids).toHaveLength(mockState.documents.length)
  })

  test('文献库列表 API 返回 mock 文档（协作模式选 docs 用）', async ({
    page,
    mockState,
  }) => {
    await page.goto('/login')
    const res = await fetchInPage(page, '/api/projects/proj-1/library')
    expect(res.status).toBe(200)
    expect(res.body.total).toBe(mockState.documents.length)
    expect(res.body.files[0].title).toContain('Transformer')
  })

  test('ProjectView 协作场景路由可访问（骨架渲染）', async ({ page, mockState }) => {
    void mockState
    await page.goto('/projects/proj-collab-1')
    await expect(page.locator('.project-view')).toBeVisible({ timeout: 10_000 })
  })
})
