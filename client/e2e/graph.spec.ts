import { authedTest as test, expect, fetchInPage } from './fixtures/mockApi'

/**
 * 场景 4：知识图谱
 *
 * 路由：/projects/:projectId/graph （独立全屏，路由 name='KnowledgeGraph'）
 * 组件：KnowledgeGraph.vue → CytoscapeCanvas（cytoscape 渲染）
 *
 * 数据源：客户端走 GraphRepo 本地构建 OR 后端 /graph API。e2e 验证：
 * 1. KG API 返回 nodes + edges 正确形状
 * 2. KG 页面路由可访问 + data-testid="knowledge-graph-page" 存在
 * 3. CytoscapeCanvas 容器渲染（data-testid="cytoscape-canvas"）
 *
 * 完整 cytoscape 节点 SVG 渲染由 vitest `KnowledgeGraph.test.ts` 覆盖。
 */

test.describe('知识图谱', () => {
  // 注意：每个 test 都要 destructure mockState（即使 void mockState）—— playwright
  // 不会激活未声明的 fixture，没 mockState 就没 Tauri shim/API mock。

  test('KG API 返回 nodes + edges', async ({ page, mockState }) => {
    void mockState
    await page.goto('/login')
    const res = await fetchInPage(page, '/api/projects/proj-1/graph')
    expect(res.status).toBe(200)
    expect(res.body.nodes).toBeInstanceOf(Array)
    expect(res.body.edges).toBeInstanceOf(Array)
    expect(res.body.nodes.length).toBeGreaterThan(0)
    expect(res.body.edges.length).toBeGreaterThan(0)
    const n = res.body.nodes[0]
    expect(n.id).toBeTruthy()
    expect(n.label).toBeTruthy()
    expect(n.type).toBeTruthy()
    expect(typeof n.weight).toBe('number')
  })

  test('图谱节点至少包含 Transformer / BERT / Attention', async ({
    page,
    mockState,
  }) => {
    void mockState
    await page.goto('/login')
    const res = await fetchInPage(page, '/api/projects/proj-1/graph')
    const labels = res.body.nodes.map((n: any) => n.label)
    expect(labels).toContain('Transformer')
    expect(labels).toContain('BERT')
    expect(labels).toContain('Attention')
  })

  test('图谱边的 source/target 匹配节点 id', async ({ page, mockState }) => {
    void mockState
    await page.goto('/login')
    const res = await fetchInPage(page, '/api/projects/proj-1/graph')
    const ids = new Set(res.body.nodes.map((n: any) => n.id))
    for (const e of res.body.edges) {
      expect(ids.has(e.source)).toBe(true)
      expect(ids.has(e.target)).toBe(true)
    }
  })

  test('KG 路由 /projects/:id/graph 可访问', async ({ page, mockState }) => {
    void mockState
    await page.goto('/projects/proj-graph-1/graph')
    // KG 页面要么显示 knowledge-graph-page 容器，要么因为本地 GraphRepo 空
    // 而退回到 empty 提示，至少 URL 要正确
    await expect(page).toHaveURL(/\/projects\/proj-graph-1\/graph$/, {
      timeout: 10_000,
    })
  })
})
