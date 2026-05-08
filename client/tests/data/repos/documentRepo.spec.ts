import { describe, it, expect, beforeEach, afterEach } from 'vitest'

import { createInMemoryDb, type TestDb } from '../../_helpers/inMemoryDb'
import { setTestDb } from '@/data/sqlite/connection'
import {
  upsertDocument,
  upsertManyDocuments,
  getDocument,
  getDocumentsByIds,
  updateDocumentLocalPaths,
} from '@/data/sqlite/repos/documentRepo'
import type { LocalDocument } from '@/types/local'

const make = (id: string, over: Partial<LocalDocument> = {}): LocalDocument => ({
  id, source: 'arxiv', external_id: 'arx-' + id, doc_type: 'paper',
  title: 'Title ' + id, title_zh: null, authors: 'Alice; Bob',
  abstract: 'abs', publication_date: '2025-01-01',
  url: 'https://arxiv.org/abs/' + id, doi: null, journal: 'arxiv', citation_count: 5,
  pdf_url: null,
  fulltext_status: 'not_attempted', fulltext_path: null,
  fulltext_pdf_path: null, fulltext_pdf_status: 'not_attempted',
  fulltext_html_path: null, fulltext_html_status: 'not_attempted',
  fulltext_text: null, pdf_local_path: null, html_local_path: null, fulltext_local_path: null,
  ai_summary: 'sum', ai_key_points: ['a', 'b'], ai_relevance_reason: 'because',
  ai_summary_source: 'from_abstract', ai_summary_user: null, ai_key_points_user: null,
  countries: ['US', 'CN'], quality_score: 0.8,
  one_line_summary: 'one', one_line_summary_user: null,
  concept_tags: ['tag1'], probe_cache: null, content_hash: null,
  import_source: 'search', imported_at: null, created_at: 1, last_synced_at: null,
  ...over,
})

describe('documentRepo', () => {
  let db: TestDb
  beforeEach(() => { db = createInMemoryDb() })
  afterEach(async () => { await db.raw.close(); setTestDb(null) })

  it('upsert + get 字段全往返', async () => {
    await upsertDocument(make('d1'))
    const g = await getDocument('d1')
    expect(g).not.toBeNull()
    expect(g!.ai_key_points).toEqual(['a', 'b'])
    expect(g!.countries).toEqual(['US', 'CN'])
    expect(g!.quality_score).toBe(0.8)
  })

  it('upsertMany 批量插入 + 同 id 更新', async () => {
    await upsertManyDocuments([make('d1'), make('d2'), make('d3')])
    let all = await getDocumentsByIds(['d1', 'd2', 'd3'])
    expect(all).toHaveLength(3)

    await upsertManyDocuments([make('d2', { title: 'updated' })])
    const updated = await getDocument('d2')
    expect(updated!.title).toBe('updated')

    all = await getDocumentsByIds(['d1', 'd2', 'd3'])
    expect(all).toHaveLength(3)
  })

  it('getDocumentsByIds 不存在的 id 静默忽略', async () => {
    await upsertDocument(make('d1'))
    const got = await getDocumentsByIds(['d1', 'nope'])
    expect(got).toHaveLength(1)
    expect(got[0].id).toBe('d1')
  })

  it('updateDocumentLocalPaths 单独更新本地路径不动其它字段', async () => {
    await upsertDocument(make('d1'))
    await updateDocumentLocalPaths('d1', {
      pdf_local_path: 'projects/p1/pdfs/d1.pdf',
      fulltext_status: 'available',
    })
    const got = await getDocument('d1')
    expect(got!.pdf_local_path).toBe('projects/p1/pdfs/d1.pdf')
    expect(got!.fulltext_status).toBe('available')
    expect(got!.title).toBe('Title d1')   // 其它字段不变
  })

  it('user override 字段保留 (ai_summary_user)', async () => {
    await upsertDocument(make('d1', { ai_summary_user: '我改的' }))
    const g = await getDocument('d1')
    expect(g!.ai_summary_user).toBe('我改的')
  })
})
