/**
 * documentsSyncService.downloadDocumentPdf — 三通道路由测试（2026-05-08 改造后）。
 *
 * 旧版 GET /file → POST /download-fulltext 路由已废弃（sp-api 上不存在那两条路由），
 * 现在 ``downloadDocumentPdf`` 内部 ``invoke()`` Tauri rust：
 *   A 类 OA: pdf_fetch_direct（成功立刻 available；失败 → failed）
 *   B 类 landing-meta: 直抓失败回退 pdf_fetch_via_resolve_url
 *   C 类 付费: pdf_fetch_via_proxy（402 → 'queued' + budgetExceeded 字段）
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import { createInMemoryDb, type TestDb } from '../../_helpers/inMemoryDb'
import { setTestDb } from '@/data/sqlite/connection'
import { upsertProject } from '@/data/sqlite/repos/projectRepo'
import { upsertDocument, getDocument } from '@/data/sqlite/repos/documentRepo'
import {
  downloadDocumentPdf,
  uploadDocumentPdf,
} from '@/data/sync/documentsSyncService'

vi.mock('@/data/fs/files', () => ({
  writeBytes: vi.fn(),
  fileExists: vi.fn(),
  removePath: vi.fn(),
  PATHS: {
    pdfFile: (p: string, d: string) => `projects/${p}/pdfs/${d}.pdf`,
    pdfFileLegacy: (p: string, d: string) => `projects/${p}/pdfs/${d}.pdf`,
  },
  assertSafeId: () => {},
}))
vi.mock('@/api/secure_storage', () => ({
  SECURE_KEYS: { ACCESS_TOKEN: 'access_token' },
  secureGet: vi.fn().mockResolvedValue('fake-token'),
}))
vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}))

import { writeBytes, fileExists } from '@/data/fs/files'
import { invoke } from '@tauri-apps/api/core'

const proj = {
  id: 'p1', title: 't', description: '', domain: 'cs', domains: null, search_config: null,
  current_round: 0, max_rounds: 0, status: 'active' as const,
  research_note_md: '', research_note_updated_at: null, research_note_updated_by: null,
  created_at: 1, updated_at: 1, last_synced_at: null,
}
const baseDoc = (id: string, over: any = {}) => ({
  id, source: 'arxiv', external_id: 'a' + id, doc_type: 'paper', title: 'P', title_zh: null,
  authors: null, abstract: null, publication_date: null, url: null, doi: null, journal: null,
  citation_count: 0, pdf_url: 'https://arxiv.org/pdf/' + id,
  fulltext_status: 'not_attempted', fulltext_path: null,
  fulltext_pdf_path: null, fulltext_pdf_status: 'not_attempted',
  fulltext_html_path: null, fulltext_html_status: 'not_attempted',
  fulltext_text: null, pdf_local_path: null, html_local_path: null, fulltext_local_path: null,
  ai_summary: null, ai_key_points: null, ai_relevance_reason: null,
  ai_summary_source: 'not_generated', ai_summary_user: null, ai_key_points_user: null,
  countries: null, quality_score: null, one_line_summary: null, one_line_summary_user: null,
  concept_tags: null, probe_cache: null, content_hash: null,
  import_source: 'search', imported_at: null, created_at: 1, last_synced_at: null,
  ...over,
})

describe('downloadDocumentPdf', () => {
  let db: TestDb
  beforeEach(async () => {
    db = createInMemoryDb()
    await upsertProject(proj)
    vi.clearAllMocks()
  })
  afterEach(async () => { await db.raw.close(); setTestDb(null) })

  it('A 类 OA：rust pdf_fetch_direct 成功 → available + 写 SQLite 路径', async () => {
    await upsertDocument(baseDoc('d1', { source: 'arxiv' }))
    ;(fileExists as any).mockResolvedValue(false)
    ;(invoke as any).mockResolvedValueOnce({
      success: true,
      local_path: 'projects/p1/pdfs/d1.pdf',
      size_bytes: 1024,
      layer_used: 'direct',
    })

    const res = await downloadDocumentPdf('p1', 'd1')

    expect(res.status).toBe('available')
    expect(res.size).toBe(1024)
    expect(res.layer).toBe('direct')
    expect(invoke).toHaveBeenCalledWith('pdf_fetch_direct', expect.any(Object))
    const d = await getDocument('d1')
    expect(d!.pdf_local_path).toBe('projects/p1/pdfs/d1.pdf')
    expect(d!.fulltext_pdf_status).toBe('available')
  })

  it('已有本地副本 → 跳过 invoke，修复 SQLite 字段', async () => {
    await upsertDocument(baseDoc('d1', { pdf_local_path: null }))
    ;(fileExists as any).mockResolvedValue(true)

    const res = await downloadDocumentPdf('p1', 'd1')

    expect(res.status).toBe('skipped')
    expect(invoke).not.toHaveBeenCalled()
    expect(writeBytes).not.toHaveBeenCalled()
    const d = await getDocument('d1')
    expect(d!.pdf_local_path).toBe('projects/p1/pdfs/d1.pdf')
    expect(d!.fulltext_pdf_status).toBe('available')
  })

  it('B 类 landing-meta：direct 失败 → 回退 pdf_fetch_via_resolve_url', async () => {
    await upsertDocument(baseDoc('d1', { source: 'pubmed', pdf_url: null, doi: '10.1/x' }))
    ;(fileExists as any).mockResolvedValue(false)
    ;(invoke as any)
      .mockResolvedValueOnce({ success: false, error: 'all 3 layers failed', layer_used: 'failed' })
      .mockResolvedValueOnce({
        success: true,
        local_path: 'projects/p1/pdfs/d1.pdf',
        size_bytes: 2048,
        layer_used: 'doi-meta',
      })

    const res = await downloadDocumentPdf('p1', 'd1')

    expect(res.status).toBe('available')
    expect(res.size).toBe(2048)
    expect(invoke).toHaveBeenCalledTimes(2)
    expect((invoke as any).mock.calls[0][0]).toBe('pdf_fetch_direct')
    expect((invoke as any).mock.calls[1][0]).toBe('pdf_fetch_via_resolve_url')
  })

  it('C 类 付费：直接 invoke pdf_fetch_via_proxy（不试 direct）', async () => {
    await upsertDocument(baseDoc('d1', { source: 'patenthub', external_id: 'CN123' }))
    ;(fileExists as any).mockResolvedValue(false)
    ;(invoke as any).mockResolvedValueOnce({
      success: true,
      local_path: 'projects/p1/pdfs/d1.pdf',
      size_bytes: 4096,
      layer_used: 'paid-stream',
    })

    const res = await downloadDocumentPdf('p1', 'd1', { clientRunId: 'run-1' })

    expect(res.status).toBe('available')
    expect(invoke).toHaveBeenCalledTimes(1)
    expect((invoke as any).mock.calls[0][0]).toBe('pdf_fetch_via_proxy')
    expect((invoke as any).mock.calls[0][1].req).toMatchObject({
      source: 'patenthub',
      external_id: 'CN123',
      client_run_id: 'run-1',
      force: false,
    })
  })

  it('C 类 付费：402 软超额 → status=queued + budgetExceeded 字段', async () => {
    await upsertDocument(baseDoc('d1', { source: 'patenthub', external_id: 'CN9' }))
    ;(fileExists as any).mockResolvedValue(false)
    const detail = JSON.stringify({
      detail: { used: 5, max: 5, cost_per_pdf: 1.1, message: 'budget', client_run_id: 'r' },
    })
    ;(invoke as any).mockResolvedValueOnce({
      success: false,
      error: 'BUDGET_EXCEEDED:' + detail,
      layer_used: 'budget',
    })

    const res = await downloadDocumentPdf('p1', 'd1')

    expect(res.status).toBe('queued')
    expect(res.budgetExceeded).toEqual({
      used: 5,
      max: 5,
      costPerPdf: 1.1,
      clientRunId: 'r',
    })
  })

  it('A 类 direct 失败（非 landing-meta 源） → status=failed，不进 resolve-url', async () => {
    await upsertDocument(baseDoc('d1', { source: 'arxiv' }))
    ;(fileExists as any).mockResolvedValue(false)
    ;(invoke as any).mockResolvedValueOnce({ success: false, error: 'rust direct fail' })

    const res = await downloadDocumentPdf('p1', 'd1')

    expect(res.status).toBe('failed')
    expect(res.reason).toContain('rust direct fail')
    expect(invoke).toHaveBeenCalledTimes(1)
    const d = await getDocument('d1')
    expect(d!.fulltext_pdf_status).toBe('failed')
  })

  it('invoke 抛错（不在 Tauri runtime） → 优雅 failed，不抛', async () => {
    await upsertDocument(baseDoc('d1', { source: 'arxiv' }))
    ;(fileExists as any).mockResolvedValue(false)
    ;(invoke as any).mockRejectedValue(new Error('Network broken'))

    const res = await downloadDocumentPdf('p1', 'd1')

    expect(res.status).toBe('failed')
    expect(res.reason).toContain('Network broken')
  })
})

describe('uploadDocumentPdf', () => {
  let db: TestDb
  beforeEach(async () => {
    db = createInMemoryDb()
    await upsertProject(proj)
    vi.clearAllMocks()
  })
  afterEach(async () => { await db.raw.close(); setTestDb(null) })

  it('用户上传本地 PDF → 写客户端 fs + SQLite 标记 pdf_local_path（不调任何 invoke）', async () => {
    await upsertDocument(baseDoc('d1'))
    const bytes = new Uint8Array([0x25, 0x50, 0x44, 0x46])  // %PDF magic
    const result = await uploadDocumentPdf('p1', 'd1', bytes)

    expect(result.relPath).toBe('projects/p1/pdfs/d1.pdf')
    expect(result.size).toBe(4)
    expect(writeBytes).toHaveBeenCalledWith('projects/p1/pdfs/d1.pdf', bytes)
    expect(invoke).not.toHaveBeenCalled()
    const d = await getDocument('d1')
    expect(d!.pdf_local_path).toBe('projects/p1/pdfs/d1.pdf')
    expect(d!.fulltext_pdf_status).toBe('available')
  })
})
