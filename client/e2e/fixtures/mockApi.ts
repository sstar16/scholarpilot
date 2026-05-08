/**
 * Playwright fixture：拦截所有 axios HTTP（VITE_API_BASE_URL=https://api.scholarpilot.top）
 * + 注入 init script，把 @tauri-apps/api/core invoke 调用 mock 在 window.__E2E_INVOKE__。
 *
 * 不依赖真后端 / 真 Tauri runtime，让 Vite dev server 也能跑出完整 UI 流程。
 */
import { test as base, type Page, type BrowserContext } from '@playwright/test'

const API_HOST = 'https://api.scholarpilot.top'

/**
 * 内存 mock 状态（每个 test 重置）
 *
 * 真后端的端点都列在 client/src/api/client.ts。最常见的：
 *   POST /api/auth/login → { access_token, refresh_token }
 *   GET  /api/auth/me → user object
 *   GET  /api/projects → []
 *   POST /api/projects → project
 *   POST /api/projects/:id/rounds/prepare → round + plan
 *   POST /api/projects/:id/rounds/:rid/confirm-keywords → round
 *   GET  /api/projects/:id/rounds/:rid/status → status enum
 *   GET  /api/projects/:id/rounds/:rid/results → docs[]
 *   POST /api/projects/:id/rounds/:rid/feedback → { saved, next_round_id }
 *   POST /api/conversation/start → conversation session
 *   POST /api/conversation/:sid/message → state transition
 *   POST /api/conversation/:sid/collaboration/question → answer with citations
 *   GET  /api/projects/:id/graph (推断) → KG nodes/edges
 */

export interface MockState {
  user: { id: string; email: string; name: string; is_admin: boolean }
  projects: Array<{
    id: string
    title: string
    description: string
    domain: string
    domains?: string[] | null
    status: string
    current_round: number
    created_at: string
  }>
  rounds: Record<
    string,
    {
      id: string
      project_id: string
      number: number
      status: string
      keyword_plan?: any
    }
  >
  documents: Array<{
    id: string
    title: string
    abstract: string
    authors: string[]
    score: number
    bucket?: string | null
  }>
  // 推迟计算的状态机：每次 GET status 返回 status[idx++]，模拟 fetcher → scoring → awaiting_feedback
  statusSequence: string[]
  statusIdx: number
}

export function defaultState(): MockState {
  return {
    user: {
      id: 'user-1',
      email: 'tester@scholarpilot.top',
      name: 'Tester',
      is_admin: false,
    },
    projects: [],
    rounds: {},
    documents: [
      {
        id: 'doc-1',
        title: 'Attention Is All You Need (Transformer 原始论文)',
        abstract: 'We propose the Transformer, a novel architecture based solely on attention mechanisms...',
        authors: ['Vaswani', 'Shazeer'],
        score: 0.92,
      },
      {
        id: 'doc-2',
        title: 'BERT: Pre-training of Deep Bidirectional Transformers',
        abstract: 'BERT uses Transformer encoders and masked language modeling...',
        authors: ['Devlin', 'Chang'],
        score: 0.88,
      },
      {
        id: 'doc-3',
        title: 'A Survey on Graph Neural Networks',
        abstract: 'GNNs are an important class of models that operate on graph-structured data...',
        authors: ['Wu', 'Pan'],
        score: 0.65,
      },
    ],
    statusSequence: ['fetching', 'scoring', 'summarizing', 'awaiting_feedback'],
    statusIdx: 0,
  }
}

/**
 * 注册 Tauri invoke 桩：
 * - secure_get / secure_set / secure_delete：内存 Map
 * - fs_*：no-op（true / 空字符串）
 * - log_webview_error：no-op
 * - accounts_*：no-op
 */
async function injectTauriShim(context: BrowserContext) {
  await context.addInitScript(() => {
    const _kv = new Map<string, string>()
    // preauth 模式：预填 token，让 ensureInit 拿到登录态
    if ((window as any).__E2E_PREAUTH__) {
      _kv.set('access_token', 'fake-access-token')
      _kv.set('refresh_token', 'fake-refresh-token')
    }
    const invokeImpl = async (cmd: string, args?: any) => {
      switch (cmd) {
        case 'secure_set':
          _kv.set(args.key, args.value)
          return null
        case 'secure_get':
          return _kv.get(args.key) ?? null
        case 'secure_delete':
          _kv.delete(args.key)
          return null
        case 'fs_exists':
          return false
        case 'fs_remove':
        case 'fs_ensure_app_dirs':
        case 'fs_write_bytes_b64':
        case 'log_webview_error':
        case 'accounts_remember_user':
        case 'accounts_clear_active':
          return null
        case 'accounts_list':
          return { users: [], active_user_email: null }
        default:
          return null
      }
    }

    // window 全局便于测试 spy
    ;(window as any).__E2E_INVOKE__ = invokeImpl

    // 拦截 ESM 动态 import('@tauri-apps/api/core') —— Vite 在浏览器里加载真模块
    // 本来会找 __TAURI_INTERNALS__ 报错。我们提供完整接口（invoke + transformCallback +
    // convertFileSrc + unregisterCallback + ipc.postMessage）。
    let _cbId = 0
    const _cbs = new Map<number, any>()
    const fullInvokeImpl = async (cmd: string, args?: any) => {
      // plugin-sql 命令：plugin:sql|load / plugin:sql|select / plugin:sql|execute / plugin:sql|close
      if (cmd && cmd.startsWith('plugin:sql')) {
        if (cmd.endsWith('|select')) return []
        return null
      }
      return invokeImpl(cmd, args)
    }
    ;(window as any).__TAURI_INTERNALS__ = {
      invoke: fullInvokeImpl,
      transformCallback: (cb: any, _once?: boolean) => {
        const id = ++_cbId
        _cbs.set(id, cb)
        return id
      },
      unregisterCallback: (id: number) => {
        _cbs.delete(id)
      },
      convertFileSrc: (path: string, _protocol?: string) => path,
      ipc: { postMessage: () => {} },
      runCallback: (id: number, ...args: any[]) => {
        const cb = _cbs.get(id)
        if (cb) cb(...args)
      },
    }

    // 部分 Tauri plugin（plugin-shell / plugin-fs）走 invoke('plugin:xxx|yyy')。
    // 全部都已被 fullInvokeImpl 兜底返回 null。
  })
}

/**
 * 在 BrowserContext level 注册 axios route：所有 https://api.scholarpilot.top 走 mock。
 * 用 context.route 而不是 page.route，确保：
 * 1. 同 context 多 page 共享 mock
 * 2. context.request（playwright 自带 fetch API）也走 mock —— 但实际上 APIRequest
 *    与 Browser 网络栈是隔离的，需要用 page.evaluate(fetch) 或专门的 helper。
 */
async function registerApiMocks(context: BrowserContext, state: MockState) {
  await context.route(`${API_HOST}/api/**`, async (route, request) => {
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()

    // ─── auth ───
    if (method === 'POST' && path === '/api/auth/login') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: 'fake-access-token',
          refresh_token: 'fake-refresh-token',
        }),
      })
      return
    }
    if (method === 'POST' && path === '/api/auth/register') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: 'fake-access-token',
          refresh_token: 'fake-refresh-token',
        }),
      })
      return
    }
    if (method === 'GET' && path === '/api/auth/me') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(state.user),
      })
      return
    }
    if (method === 'POST' && path === '/api/auth/logout') {
      await route.fulfill({ status: 200, body: '{}' })
      return
    }
    if (method === 'POST' && path === '/api/auth/refresh') {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          access_token: 'fake-access-token-2',
          refresh_token: 'fake-refresh-token-2',
        }),
      })
      return
    }

    // ─── projects ───
    if (method === 'GET' && path === '/api/projects') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(state.projects),
      })
      return
    }
    if (method === 'POST' && path === '/api/projects') {
      const data = JSON.parse(request.postData() || '{}')
      const proj = {
        id: `proj-${state.projects.length + 1}`,
        title: data.title || '新项目',
        description: data.description || '',
        domain: data.domain || 'cs',
        domains: data.domains || ['cs'],
        status: 'active',
        current_round: 0,
        created_at: new Date().toISOString(),
      }
      state.projects.push(proj)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(proj),
      })
      return
    }
    const projGetMatch = path.match(/^\/api\/projects\/(proj-[^/]+)$/)
    if (method === 'GET' && projGetMatch) {
      const id = projGetMatch[1]
      const proj = state.projects.find((p) => p.id === id) || {
        id,
        title: '示例项目',
        description: 'e2e mock',
        domain: 'cs',
        domains: ['cs'],
        status: 'active',
        current_round: 1,
        created_at: new Date().toISOString(),
      }
      await route.fulfill({ status: 200, body: JSON.stringify(proj) })
      return
    }
    if (path.match(/^\/api\/projects\/[^/]+\/stale-check$/)) {
      await route.fulfill({ status: 200, body: '{}' })
      return
    }

    // ─── rounds ───
    const prepMatch = path.match(/^\/api\/projects\/([^/]+)\/rounds\/prepare$/)
    if (method === 'POST' && prepMatch) {
      const projId = prepMatch[1]
      const rid = `round-${Date.now()}`
      state.rounds[rid] = {
        id: rid,
        project_id: projId,
        number: 1,
        status: 'awaiting_keywords',
        keyword_plan: {
          per_source: {
            arxiv: { keywords: ['transformer', 'attention'] },
            openalex: { keywords: ['large language model'] },
          },
        },
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          round_id: rid,
          status: 'awaiting_keywords',
          keyword_plan: state.rounds[rid].keyword_plan,
        }),
      })
      return
    }
    const confirmMatch = path.match(
      /^\/api\/projects\/[^/]+\/rounds\/([^/]+)\/confirm-keywords$/,
    )
    if (method === 'POST' && confirmMatch) {
      const rid = confirmMatch[1]
      if (state.rounds[rid]) state.rounds[rid].status = 'fetching'
      state.statusIdx = 0
      await route.fulfill({
        status: 200,
        body: JSON.stringify({ round_id: rid, status: 'fetching' }),
      })
      return
    }
    const statusMatch = path.match(
      /^\/api\/projects\/[^/]+\/rounds\/([^/]+)\/status$/,
    )
    if (method === 'GET' && statusMatch) {
      const idx = Math.min(state.statusIdx, state.statusSequence.length - 1)
      const status = state.statusSequence[idx]
      state.statusIdx += 1
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          round_id: statusMatch[1],
          status,
          progress: { fetched: 12, scored: 10, summarized: 8 },
        }),
      })
      return
    }
    const resultsMatch = path.match(
      /^\/api\/projects\/[^/]+\/rounds\/([^/]+)\/results$/,
    )
    if (method === 'GET' && resultsMatch) {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          round_id: resultsMatch[1],
          documents: state.documents,
        }),
      })
      return
    }
    const fbMatch = path.match(
      /^\/api\/projects\/[^/]+\/rounds\/([^/]+)\/feedback$/,
    )
    if (method === 'POST' && fbMatch) {
      const rid = fbMatch[1]
      if (state.rounds[rid]) state.rounds[rid].status = 'complete'
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          saved: 4,
          next_round_id: null,
          next_round_number: null,
          monitoring_activated: false,
          message: 'feedback saved',
          memory_update: null,
        }),
      })
      return
    }
    const finalizeMatch = path.match(
      /^\/api\/projects\/[^/]+\/rounds\/([^/]+)\/finalize$/,
    )
    if (method === 'POST' && finalizeMatch) {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({ round_id: finalizeMatch[1], status: 'complete' }),
      })
      return
    }
    if (path.match(/^\/api\/projects\/[^/]+\/rounds$/) && method === 'GET') {
      await route.fulfill({
        status: 200,
        body: JSON.stringify(Object.values(state.rounds)),
      })
      return
    }

    // ─── conversation ───
    if (method === 'POST' && path === '/api/conversation/start') {
      const body = JSON.parse(request.postData() || '{}')
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          id: 'sess-1',
          project_id: body.project_id || null,
          current_state: 'idle',
          search_mode: null,
          messages: [
            {
              id: 'msg-welcome',
              role: 'assistant',
              content: '你好！请用一两句话描述你的研究方向。',
              timestamp: new Date().toISOString(),
            },
          ],
        }),
      })
      return
    }
    const msgMatch = path.match(/^\/api\/conversation\/([^/]+)\/message$/)
    if (method === 'POST' && msgMatch) {
      const body = JSON.parse(request.postData() || '{}')
      const userText: string = body.content || ''
      // 触发关键字流程：state → keyword_confirmation
      const isResearchTopic = userText.length > 5
      // 模拟创建项目（真后端会在意图确认后才创建；这里简化）
      let projId = state.projects[state.projects.length - 1]?.id
      if (!projId) {
        projId = 'proj-conv-1'
        state.projects.push({
          id: projId,
          title: userText.slice(0, 24) || '对话项目',
          description: userText,
          domain: 'cs',
          domains: ['cs'],
          status: 'active',
          current_round: 0,
          created_at: new Date().toISOString(),
        })
      }
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          state: isResearchTopic ? 'keyword_confirmation' : 'idle',
          project_id: projId,
          assistant_message: {
            id: `msg-${Date.now()}`,
            role: 'assistant',
            content: '已记录你的研究方向。',
            timestamp: new Date().toISOString(),
          },
          confirmation: null,
        }),
      })
      return
    }
    const sessGetMatch = path.match(/^\/api\/conversation\/([^/]+)$/)
    if (method === 'GET' && sessGetMatch) {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          id: sessGetMatch[1],
          project_id: state.projects[0]?.id ?? null,
          current_state: 'idle',
          search_mode: null,
          messages: [],
        }),
      })
      return
    }

    // ─── collaboration ───
    const collabQuesMatch = path.match(
      /^\/api\/conversation\/([^/]+)\/collaboration\/question$/,
    )
    if (method === 'POST' && collabQuesMatch) {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          answer:
            'Attention Is All You Need (doc-1) 用了 Transformer，BERT (doc-2) 也基于 Transformer encoder。',
          citations: [
            { doc_id: 'doc-1', title: state.documents[0].title, snippet: 'We propose the Transformer' },
            { doc_id: 'doc-2', title: state.documents[1].title, snippet: 'BERT uses Transformer encoders' },
          ],
        }),
      })
      return
    }
    if (path.match(/^\/api\/conversation\/[^/]+\/collaboration\/start$/)) {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({ session_id: 'sess-1', doc_ids: state.documents.map((d) => d.id) }),
      })
      return
    }

    // ─── library / buckets / others ───
    if (path.match(/^\/api\/projects\/[^/]+\/library$/)) {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          total: state.documents.length,
          by_bucket: {},
          files: state.documents.map((d, i) => ({
            slug: `doc-${i + 1}`,
            title: d.title,
            authors_short: d.authors.join(', '),
            year: 2023,
          })),
        }),
      })
      return
    }
    if (path.match(/^\/api\/projects\/[^/]+\/buckets$/)) {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({ buckets: { core: [], related: [], background: [], rejected: [] } }),
      })
      return
    }
    const classifyMatch = path.match(
      /^\/api\/projects\/[^/]+\/documents\/([^/]+)\/classify$/,
    )
    if ((method === 'PUT' || method === 'DELETE') && classifyMatch) {
      await route.fulfill({ status: 200, body: '{}' })
      return
    }

    // ─── knowledge graph ───
    if (path.match(/^\/api\/projects\/[^/]+\/graph$/)) {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          nodes: [
            { id: 'n1', label: 'Transformer', type: 'method', weight: 0.9, source_doc_ids: ['doc-1'] },
            { id: 'n2', label: 'BERT', type: 'method', weight: 0.85, source_doc_ids: ['doc-2'] },
            { id: 'n3', label: 'Attention', type: 'concept', weight: 0.95, source_doc_ids: ['doc-1', 'doc-2'] },
            { id: 'n4', label: 'NLP', type: 'domain', weight: 0.7, source_doc_ids: ['doc-1', 'doc-2'] },
          ],
          edges: [
            { source: 'n1', target: 'n3', label: 'uses', weight: 0.9 },
            { source: 'n2', target: 'n1', label: 'extends', weight: 0.8 },
            { source: 'n2', target: 'n4', label: 'applied_to', weight: 0.7 },
          ],
        }),
      })
      return
    }

    // ─── monitoring / telemetry / skills ───
    if (path === '/api/telemetry') {
      await route.fulfill({ status: 200, body: '{}' })
      return
    }
    if (path === '/api/skills') {
      await route.fulfill({ status: 200, body: JSON.stringify({ skills: [] }) })
      return
    }

    // 兜底：未知端点 → 200 空 JSON（避免 console.error 干扰测试）
    console.warn(`[mock] unhandled ${method} ${path}`)
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })
}

/**
 * Helper：打开 page 前先把 access token 写到 secure storage（mock 模拟"已登录"状态）。
 *
 * 实现：用一个全局 _e2e_preauth 标志，在 Tauri shim 注入时同步写入 _kv Map。
 * 这样无论 secure_get 何时被调用，都能拿到 fake token。
 */
export async function preauth(page: Page) {
  await page.addInitScript(() => {
    // 标记位 → injectTauriShim 内部读这个标志后会预填 _kv map
    ;(window as any).__E2E_PREAUTH__ = true
  })
}

/**
 * Helper：在浏览器 page context 里发 fetch（这样会走 page.route mock）。
 * Playwright 的 `request` fixture 不走 context.route，所以测试里要测 API
 * 形状的话用这个 helper。
 */
export async function fetchInPage(
  page: Page,
  path: string,
  init: { method?: string; body?: any; headers?: Record<string, string> } = {},
) {
  return page.evaluate(
    async ({ url, init }) => {
      const res = await fetch(url, {
        method: init.method || 'GET',
        headers: {
          'Content-Type': 'application/json',
          Authorization: 'Bearer fake-access-token',
          ...(init.headers || {}),
        },
        body: init.body ? JSON.stringify(init.body) : undefined,
      })
      const text = await res.text()
      let json: any = null
      try {
        json = JSON.parse(text)
      } catch {
        // not json
      }
      return { status: res.status, body: json, text }
    },
    { url: `${API_HOST}${path}`, init },
  )
}

/**
 * 默认 fixture：注入 Tauri shim + API mock，但不自动 preauth。
 * 大部分 test 需要登录态 → 用 `authedTest` （下方）。
 * 测「跳登录页」类型的 test 用 `test`（无 preauth）。
 */
export const test = base.extend<{ mockState: MockState }>({
  mockState: async ({ context }, use) => {
    const state = defaultState()
    await injectTauriShim(context)
    await registerApiMocks(context, state)
    await use(state)
  },
})

/**
 * 已登录态 fixture：context 上预先注入 __E2E_PREAUTH__，让 Tauri shim 把 fake
 * token 预填进 secure storage。注意必须在 fixture 注册顺序里早于 mockState
 * 才能让 init script 顺序对（context.addInitScript 按注册顺序执行）。
 */
export const authedTest = base.extend<{ mockState: MockState }>({
  mockState: async ({ context, page }, use) => {
    // 先标记 preauth（context-level）
    await context.addInitScript(() => {
      ;(window as any).__E2E_PREAUTH__ = true
    })
    // 然后 shim + mock
    const state = defaultState()
    await injectTauriShim(context)
    await registerApiMocks(context, state)
    void page
    await use(state)
  },
})

export { expect } from '@playwright/test'
