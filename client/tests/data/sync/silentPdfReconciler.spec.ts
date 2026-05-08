import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import { createInMemoryDb, type TestDb } from '../../_helpers/inMemoryDb'
import { setTestDb } from '@/data/sqlite/connection'
import { upsertProject } from '@/data/sqlite/repos/projectRepo'
import { upsertDocument } from '@/data/sqlite/repos/documentRepo'
import { upsertRound, upsertRoundDocument } from '@/data/sqlite/repos/roundRepo'
import { setSetting } from '@/data/sqlite/repos/settingsRepo'
import {
  reconcileSilent,
  filterPending,
  getDailyConsumed,
} from '@/data/sync/silentPdfReconciler'

vi.mock('@/api/client', () => ({
  userDocsApi: {
    listOwned: vi.fn(),
    markOwn: vi.fn(),
    markUnown: vi.fn(),
  },
}))
vi.mock('@/data/sync/documentsSyncService', () => ({
  downloadDocumentPdf: vi.fn(),
}))
// C10: rust 通道在 node 测试环境无 Tauri runtime, 默认禁用让所有 case 走 sp-api
vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn().mockRejectedValue(new Error('not in tauri runtime')),
}))

import { userDocsApi } from '@/api/client'
import { downloadDocumentPdf } from '@/data/sync/documentsSyncService'
import { invoke } from '@tauri-apps/api/core'

// Helper: 插入一篇 doc 到 project p1 + 通过 round1 的 round_documents 关联
// 这样新版 reconcileSilent 的 SQLite 查询能找到它（必需 pdf_url / doi / patenthub source）
async function _seedDocInProject(
  projectId: string,
  documentId: string,
  docOver: Partial<ReturnType<typeof localDoc>> = {},
): Promise<void> {
  await upsertDocument(localDoc({
    id: documentId,
    pdf_url: 'https://example.org/' + documentId + '.pdf',  // 让 SQLite WHERE 命中
    ...docOver,
  }) as any)
  await upsertRoundDocument({
    id: `rd-${documentId}`,
    round_id: 'r1',
    document_id: documentId,
    rank_in_round: 1,
    initial_score: null,
    agent_score: null,
    agent_rationale: null,
    one_line_summary: null,
    below_cutoff: false,
  })
}

// 插入项目 + 一个 round（外键依赖）
async function _seedProjectAndRound(projectId: string): Promise<void> {
  await upsertProject({
    id: projectId,
    title: 'Test',
    description: '',
    domain: 'cs',
    domains: null,
    search_config: null,
    current_round: 1,
    max_rounds: 5,
    status: 'active',
    research_note_md: '',
    research_note_updated_at: null,
    research_note_updated_by: null,
    created_at: 1000,
    updated_at: 1000,
    last_synced_at: null,
  })
  await upsertRound({
    id: 'r1',
    project_id: projectId,
    round_number: 1,
    status: 'complete',
    time_horizon_years: null,
    max_results: 10,
    language_scope: 'chinese',
    sources_used: null,
    search_queries: null,
    total_candidates: 0,
    selected_count: 0,
    source_stats: null,
    progress: 1,
    progress_message: '',
    started_at: null,
    completed_at: null,
    cancelled_reason: null,
    cancelled_at: null,
    partial_answer: null,
    partial_completed_at: null,
    created_at: 1000,
    last_synced_at: null,
  })
}

beforeEach(() => {
  // 默认全局禁用 rust 通道，强制走 sp-api（保持现有 test case 行为）
  ;(globalThis as any).__SP_DISABLE_RUST_PDF__ = true
})

afterEach(() => {
  delete (globalThis as any).__SP_DISABLE_RUST_PDF__
})

const ownedDto = (over: any = {}) => ({
  document_id: 'doc1',
  project_id: 'p1',
  source: 'downloaded',
  format: 'pdf',
  owned_at: '2026-05-01T00:00:00Z',
  last_seen_at: '2026-05-01T00:00:00Z',
  ...over,
})

const localDoc = (over: any = {}) => ({
  id: 'doc1',
  source: 'arxiv',
  external_id: 'ext-1',
  doc_type: 'paper',
  title: 'Test',
  title_zh: null,
  authors: null,
  abstract: null,
  publication_date: null,
  url: null,
  doi: null,
  journal: null,
  citation_count: 0,
  pdf_url: null,
  fulltext_status: 'not_attempted',
  fulltext_path: null,
  fulltext_pdf_path: null,
  fulltext_pdf_status: 'not_attempted',
  fulltext_html_path: null,
  fulltext_html_status: 'not_attempted',
  fulltext_text: null,
  pdf_local_path: null,
  html_local_path: null,
  fulltext_local_path: null,
  ai_summary: null,
  ai_key_points: null,
  ai_relevance_reason: null,
  ai_summary_source: 'not_generated',
  ai_summary_user: null,
  ai_key_points_user: null,
  countries: null,
  quality_score: null,
  one_line_summary: null,
  one_line_summary_user: null,
  concept_tags: null,
  probe_cache: null,
  content_hash: null,
  import_source: 'search',
  imported_at: null,
  created_at: 1000,
  last_synced_at: 1000,
  ...over,
})

// 注入空 sleep 跳过 retry timing
const noopSleep = () => Promise.resolve()

describe('silentPdfReconciler.filterPending', () => {
  let db: TestDb
  beforeEach(() => {
    db = createInMemoryDb()
    vi.clearAllMocks()
  })
  afterEach(async () => { await db.raw.close(); setTestDb(null) })

  it('uploaded_local 跳过', async () => {
    await upsertDocument(localDoc({ id: 'doc1' }))
    const items = [ownedDto({ document_id: 'doc1', source: 'uploaded_local' })]
    const out = await filterPending(items)
    expect(out).toEqual([])
  })

  it('已在本地（pdf_local_path 非空）跳过', async () => {
    await upsertDocument(localDoc({ id: 'doc1', pdf_local_path: 'projects/p1/pdfs/doc1.pdf' }))
    const items = [ownedDto({ document_id: 'doc1' })]
    const out = await filterPending(items)
    expect(out).toEqual([])
  })

  it('本地无 doc 元数据 跳过', async () => {
    const items = [ownedDto({ document_id: 'unknown' })]
    const out = await filterPending(items)
    expect(out).toEqual([])
  })

  it('downloaded + 本地无文件 → 保留', async () => {
    await upsertDocument(localDoc({ id: 'doc1', pdf_local_path: null }))
    const items = [ownedDto({ document_id: 'doc1', source: 'downloaded' })]
    const out = await filterPending(items)
    expect(out).toHaveLength(1)
  })

  it('uploaded_synced + 本地无文件 → 保留', async () => {
    await upsertDocument(localDoc({ id: 'doc1', pdf_local_path: null }))
    const items = [ownedDto({ document_id: 'doc1', source: 'uploaded_synced' })]
    const out = await filterPending(items)
    expect(out).toHaveLength(1)
  })
})

describe('silentPdfReconciler.getDailyConsumed', () => {
  let db: TestDb
  beforeEach(() => {
    db = createInMemoryDb()
    vi.clearAllMocks()
  })
  afterEach(async () => { await db.raw.close(); setTestDb(null) })

  it('从未跑过 → 0', async () => {
    expect(await getDailyConsumed()).toBe(0)
  })

  it('今日已 set → 返回数字', async () => {
    const today = new Date().toISOString().slice(0, 10)
    await setSetting('silent_pdf_daily_date', today)
    await setSetting('silent_pdf_daily_count', '42')
    expect(await getDailyConsumed()).toBe(42)
  })

  it('跨日 → 重置为 0', async () => {
    await setSetting('silent_pdf_daily_date', '2020-01-01')   // 远古日期
    await setSetting('silent_pdf_daily_count', '99')
    expect(await getDailyConsumed()).toBe(0)
  })
})

describe('silentPdfReconciler.reconcileSilent', () => {
  let db: TestDb
  beforeEach(async () => {
    db = createInMemoryDb()
    vi.clearAllMocks()
    await _seedProjectAndRound('p1')
  })
  afterEach(async () => { await db.raw.close(); setTestDb(null) })

  it('所有 ownership 都成功下载 → succeeded=N', async () => {
    await _seedDocInProject('p1', 'doc1')
    await _seedDocInProject('p1', 'doc2')
    ;(downloadDocumentPdf as any).mockResolvedValue({ status: 'available', size: 100 })

    const r = await reconcileSilent('p1', { sleep: noopSleep })
    expect(r.attempted).toBe(2)
    expect(r.succeeded).toBe(2)
    expect(r.failed).toBe(0)
    expect(r.capped).toBe(0)
    expect(r.skipped).toBe(0)
  })

  it('配额已用完 → 全部 capped', async () => {
    await _seedDocInProject('p1', 'doc1')
    const today = new Date().toISOString().slice(0, 10)
    await setSetting('silent_pdf_daily_date', today)
    await setSetting('silent_pdf_daily_count', '100')   // 已用完默认 100/天

    const r = await reconcileSilent('p1', { sleep: noopSleep })
    expect(r.attempted).toBe(0)
    expect(r.capped).toBe(1)
    expect(downloadDocumentPdf).not.toHaveBeenCalled()
  })

  it('配额剩 1 + 待下 3 → attempted 1, capped 2', async () => {
    await _seedDocInProject('p1', 'd1')
    await _seedDocInProject('p1', 'd2')
    await _seedDocInProject('p1', 'd3')
    const today = new Date().toISOString().slice(0, 10)
    await setSetting('silent_pdf_daily_date', today)
    await setSetting('silent_pdf_daily_count', '99')
    ;(downloadDocumentPdf as any).mockResolvedValue({ status: 'available' })

    const r = await reconcileSilent('p1', { sleep: noopSleep })
    expect(r.attempted).toBe(1)
    expect(r.succeeded).toBe(1)
    expect(r.capped).toBe(2)
  })

  it('已在本地的跳过 + 缺元数据的跳过 → skipped 计数', async () => {
    // d1: 已在本地（pdf_local_path 非空）→ filterPending 跳过
    // d2: 缺 pdf_url/doi → SQLite WHERE 不命中 → 不会进入 items
    // 所以仅 d1 计入 skipped
    await _seedDocInProject('p1', 'd1', { pdf_local_path: 'projects/p1/pdfs/d1.pdf' } as any)

    const r = await reconcileSilent('p1', { sleep: noopSleep })
    expect(r.attempted).toBe(0)
    expect(r.skipped).toBe(1)
    expect(downloadDocumentPdf).not.toHaveBeenCalled()
  })

  it('单篇 download 返 failed → failed++ 不扣配额', async () => {
    await _seedDocInProject('p1', 'doc1')
    ;(downloadDocumentPdf as any).mockResolvedValue({ status: 'failed' })

    const r = await reconcileSilent('p1', { sleep: noopSleep, retryDelaysMs: [0, 0, 0] })
    expect(r.attempted).toBe(1)
    expect(r.succeeded).toBe(0)
    expect(r.failed).toBe(1)
    // 新版 _downloadWithRetry 不再 retry, 单次调用
    expect(downloadDocumentPdf).toHaveBeenCalledTimes(1)
    expect(await getDailyConsumed()).toBe(0)   // 失败不扣配额
  })

  it('SQLite 查询失败 → 返回 0 stats，不抛', async () => {
    // 销毁 db 让 SELECT 抛错
    db.raw.close()
    setTestDb(null)
    const r = await reconcileSilent('p1', { sleep: noopSleep })
    expect(r).toEqual({ attempted: 0, succeeded: 0, failed: 0, capped: 0, skipped: 0 })
    // 重新建一个空 db 让 afterEach 清理不抛错
    db = createInMemoryDb()
  })

  it('queued 状态算 failed (不算成功)', async () => {
    await _seedDocInProject('p1', 'doc1')
    ;(downloadDocumentPdf as any).mockResolvedValue({ status: 'queued' })

    const r = await reconcileSilent('p1', { sleep: noopSleep, retryDelaysMs: [0] })
    expect(r.attempted).toBe(1)
    expect(r.failed).toBe(1)   // queued 不算成功
    // 单次调用 (不再 retry)
    expect(downloadDocumentPdf).toHaveBeenCalledTimes(1)
  })

  // 2026-05-08：rust 三通道路由（pdf_fetch_direct / via_resolve_url / via_proxy）
  // 已搬到 documentsSyncService.downloadDocumentPdf 内部。reconciler 这里只看
  // downloadDocumentPdf 的 status 决定 succeeded/failed/queued。
  // C 类付费源由 reconciler 主动跳过（不消耗付费配额做静默批量）。
  describe('三通道路由（行为约定）', () => {
    it('付费源（patenthub）reconciler 主动跳过，不调 downloadDocumentPdf', async () => {
      await _seedDocInProject('p1', 'doc1', { source: 'patenthub' } as any)

      const r = await reconcileSilent('p1', { sleep: noopSleep })
      // 付费源在 _downloadOnce 里 return false，stats.failed=1, attempted=1
      expect(r.attempted).toBe(1)
      expect(r.failed).toBe(1)
      expect(r.succeeded).toBe(0)
      expect(downloadDocumentPdf).not.toHaveBeenCalled()
    })

    it('downloadDocumentPdf 内部 invoke 抛错 → 优雅 false（reconciler 不抛）', async () => {
      await _seedDocInProject('p1', 'doc1', { source: 'arxiv' } as any)
      // mock 把内部异常 surface 成 status='failed'（实际 service 已经 try/catch）
      ;(downloadDocumentPdf as any).mockRejectedValue(new Error('IPC failure'))

      const r = await reconcileSilent('p1', { sleep: noopSleep })
      expect(r.failed).toBe(1)
    })
  })

  it('成功扣配额累计', async () => {
    await _seedDocInProject('p1', 'd1')
    await _seedDocInProject('p1', 'd2')
    ;(downloadDocumentPdf as any).mockResolvedValue({ status: 'available' })

    expect(await getDailyConsumed()).toBe(0)
    const r = await reconcileSilent('p1', { sleep: noopSleep })
    expect(r.succeeded).toBe(2)
    expect(await getDailyConsumed()).toBe(2)
  })
})
