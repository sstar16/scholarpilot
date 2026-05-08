import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

import { createInMemoryDb, type TestDb } from '../../_helpers/inMemoryDb'
import { setTestDb } from '@/data/sqlite/connection'
import { upsertDocument, getDocument } from '@/data/sqlite/repos/documentRepo'
import {
  syncOwnedDocuments,
  markUploaded,
  markUnowned,
  OwnershipSyncError,
} from '@/data/sync/userDocumentsSyncService'

vi.mock('@/api/client', () => ({
  userDocsApi: {
    listOwned: vi.fn(),
    markOwn: vi.fn(),
    markUnown: vi.fn(),
  },
}))

import { userDocsApi } from '@/api/client'

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

describe('userDocumentsSyncService.syncOwnedDocuments', () => {
  let db: TestDb
  beforeEach(() => {
    db = createInMemoryDb()
    vi.clearAllMocks()
  })
  afterEach(async () => { await db.raw.close(); setTestDb(null) })

  it('云端 owned + 本地无 PDF → 标 downloading + pendingDownload++', async () => {
    await upsertDocument(localDoc({ id: 'doc1', pdf_local_path: null }))
    ;(userDocsApi.listOwned as any).mockResolvedValue({
      data: { items: [ownedDto({ document_id: 'doc1', source: 'downloaded' })] },
    })

    const r = await syncOwnedDocuments('p1')
    expect(r.pulled).toBe(1)
    expect(r.pendingDownload).toBe(1)
    expect(r.skipped).toBe(0)

    const local = await getDocument('doc1')
    expect(local!.fulltext_pdf_status).toBe('downloading')
  })

  it('本地已有 pdf_local_path → 跳过，不动 status', async () => {
    await upsertDocument(localDoc({
      id: 'doc1',
      pdf_local_path: 'projects/p1/pdfs/doc1.pdf',
      fulltext_pdf_status: 'available',
    }))
    ;(userDocsApi.listOwned as any).mockResolvedValue({
      data: { items: [ownedDto({ document_id: 'doc1' })] },
    })

    const r = await syncOwnedDocuments('p1')
    expect(r.pendingDownload).toBe(0)
    expect(r.skipped).toBe(1)

    const local = await getDocument('doc1')
    expect(local!.fulltext_pdf_status).toBe('available')   // 没被覆盖
  })

  it('uploaded_local 源 → 跳过（backend 没 binary 拉不到）', async () => {
    await upsertDocument(localDoc({ id: 'doc1', pdf_local_path: null }))
    ;(userDocsApi.listOwned as any).mockResolvedValue({
      data: { items: [ownedDto({ document_id: 'doc1', source: 'uploaded_local' })] },
    })

    const r = await syncOwnedDocuments('p1')
    expect(r.pendingDownload).toBe(0)
    expect(r.skipped).toBe(1)

    const local = await getDocument('doc1')
    expect(local!.fulltext_pdf_status).toBe('not_attempted')   // 没动
  })

  it('uploaded_synced 源 → 标 downloading（backend 有 binary 可拉）', async () => {
    await upsertDocument(localDoc({ id: 'doc1', pdf_local_path: null }))
    ;(userDocsApi.listOwned as any).mockResolvedValue({
      data: { items: [ownedDto({ document_id: 'doc1', source: 'uploaded_synced' })] },
    })

    const r = await syncOwnedDocuments('p1')
    expect(r.pendingDownload).toBe(1)
    const local = await getDocument('doc1')
    expect(local!.fulltext_pdf_status).toBe('downloading')
  })

  it('本地无该 doc 元数据 → skipped 但不报错', async () => {
    ;(userDocsApi.listOwned as any).mockResolvedValue({
      data: { items: [ownedDto({ document_id: 'unknown-doc' })] },
    })

    const r = await syncOwnedDocuments('p1')
    expect(r.pulled).toBe(1)
    expect(r.skipped).toBe(1)
    expect(r.pendingDownload).toBe(0)
  })

  it('网络错误抛 OwnershipSyncError', async () => {
    ;(userDocsApi.listOwned as any).mockRejectedValue(new Error('Network down'))

    await expect(syncOwnedDocuments('p1')).rejects.toThrow(OwnershipSyncError)
  })

  it('不传 projectId → 调 listOwned 也不传', async () => {
    ;(userDocsApi.listOwned as any).mockResolvedValue({ data: { items: [] } })
    await syncOwnedDocuments()
    expect(userDocsApi.listOwned).toHaveBeenCalledWith(undefined, 'pdf')
  })
})

describe('userDocumentsSyncService.markUploaded', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('syncToCloud=false → POST source=uploaded_local', async () => {
    ;(userDocsApi.markOwn as any).mockResolvedValue({ data: {} })
    await markUploaded('p1', 'doc1', 'pdf', false)
    expect(userDocsApi.markOwn).toHaveBeenCalledWith('p1', 'doc1', {
      source: 'uploaded_local',
      format: 'pdf',
    })
  })

  it('syncToCloud=true → POST source=uploaded_synced', async () => {
    ;(userDocsApi.markOwn as any).mockResolvedValue({ data: {} })
    await markUploaded('p1', 'doc1', 'pdf', true)
    expect(userDocsApi.markOwn).toHaveBeenCalledWith('p1', 'doc1', {
      source: 'uploaded_synced',
      format: 'pdf',
    })
  })

  it('default syncToCloud=false（不传第 4 参数）', async () => {
    ;(userDocsApi.markOwn as any).mockResolvedValue({ data: {} })
    await markUploaded('p1', 'doc1')
    expect(userDocsApi.markOwn).toHaveBeenCalledWith('p1', 'doc1', {
      source: 'uploaded_local',
      format: 'pdf',
    })
  })
})

describe('userDocumentsSyncService.markUnowned', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('调 DELETE /own?format=pdf', async () => {
    ;(userDocsApi.markUnown as any).mockResolvedValue({ data: { removed: true } })
    await markUnowned('p1', 'doc1', 'pdf')
    expect(userDocsApi.markUnown).toHaveBeenCalledWith('p1', 'doc1', 'pdf')
  })

  it('default format=pdf', async () => {
    ;(userDocsApi.markUnown as any).mockResolvedValue({ data: { removed: true } })
    await markUnowned('p1', 'doc1')
    expect(userDocsApi.markUnown).toHaveBeenCalledWith('p1', 'doc1', 'pdf')
  })
})
