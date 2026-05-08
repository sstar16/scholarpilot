import { describe, it, expect, beforeEach, afterEach } from 'vitest'

import { createInMemoryDb, type TestDb } from '../../_helpers/inMemoryDb'
import { setTestDb } from '@/data/sqlite/connection'
import { upsertProject } from '@/data/sqlite/repos/projectRepo'
import {
  upsertRound,
  getRound,
  listRoundsByProject,
  deleteRound,
  upsertRoundDocument,
  getRoundDocuments,
} from '@/data/sqlite/repos/roundRepo'
import type { LocalProject, LocalRound, LocalRoundDocument } from '@/types/local'

// 故意不依赖 documentRepo（在 Task 6 才实现）。round_documents.document_id
// 有 FK 约束指向 documents 表，这里用 raw SQL 直接 seed 一个最小行即可。
function _seedDocument(rawDb: import('better-sqlite3').Database, id: string): void {
  rawDb
    .prepare(
      `INSERT OR REPLACE INTO documents (
         id, source, external_id, doc_type, title, citation_count,
         fulltext_status, fulltext_pdf_status, fulltext_html_status,
         ai_summary_source, import_source, created_at
       ) VALUES (?, 'arxiv', ?, 'paper', ?, 0,
         'not_attempted', 'not_attempted', 'not_attempted',
         'not_generated', 'search', 1)`,
    )
    .run(id, 'ext-' + id, 'paper ' + id)
}

const proj = (id = 'p1'): LocalProject => ({
  id, title: 't', description: '', domain: 'cs', domains: null, search_config: null,
  current_round: 0, max_rounds: 0, status: 'active',
  research_note_md: '', research_note_updated_at: null, research_note_updated_by: null,
  created_at: 1, updated_at: 1, last_synced_at: null,
})

const round = (over: Partial<LocalRound> = {}): LocalRound => ({
  id: 'r1', project_id: 'p1', round_number: 1, status: 'pending',
  time_horizon_years: null, max_results: 10, language_scope: 'chinese',
  sources_used: ['arxiv', 'openalex'], search_queries: { arxiv: 'q1' },
  total_candidates: 0, selected_count: 0, source_stats: null,
  progress: 0, progress_message: '', started_at: null, completed_at: null,
  cancelled_reason: null, cancelled_at: null,
  partial_answer: null, partial_completed_at: null,
  created_at: 1, last_synced_at: null,
  ...over,
})

describe('roundRepo', () => {
  let db: TestDb
  beforeEach(async () => {
    db = createInMemoryDb()
    await upsertProject(proj())
  })
  afterEach(async () => {
    await db.raw.close()
    setTestDb(null)
  })

  it('upsert round + get', async () => {
    await upsertRound(round())
    const got = await getRound('r1')
    expect(got).not.toBeNull()
    expect(got!.sources_used).toEqual(['arxiv', 'openalex'])
    expect(got!.search_queries).toEqual({ arxiv: 'q1' })
  })

  it('list by project 按 round_number desc', async () => {
    await upsertRound(round({ id: 'r1', round_number: 1 }))
    await upsertRound(round({ id: 'r2', round_number: 2 }))
    await upsertRound(round({ id: 'r3', round_number: 3 }))
    const list = await listRoundsByProject('p1')
    expect(list.map((r) => r.id)).toEqual(['r3', 'r2', 'r1'])
  })

  it('delete round 级联删 round_documents', async () => {
    _seedDocument(db.raw, 'd1')
    await upsertRound(round())
    await upsertRoundDocument({
      id: 'rd1', round_id: 'r1', document_id: 'd1',
      rank_in_round: 0, initial_score: 0.5, agent_score: null, agent_rationale: null,
      one_line_summary: null, below_cutoff: false,
    })

    await deleteRound('r1')
    const links = await getRoundDocuments('r1')
    expect(links).toEqual([])
  })

  it('upsert round_document 同 (round_id, document_id) 更新而不重复', async () => {
    _seedDocument(db.raw, 'd1')
    await upsertRound(round())
    const link: LocalRoundDocument = {
      id: 'rd1', round_id: 'r1', document_id: 'd1',
      rank_in_round: 0, initial_score: 0.5, agent_score: null, agent_rationale: null,
      one_line_summary: 'first', below_cutoff: false,
    }
    await upsertRoundDocument(link)
    await upsertRoundDocument({ ...link, one_line_summary: 'updated', agent_score: 0.9 })
    const links = await getRoundDocuments('r1')
    expect(links).toHaveLength(1)
    expect(links[0].one_line_summary).toBe('updated')
    expect(links[0].agent_score).toBe(0.9)
  })

  it('below_cutoff TRUE/FALSE 正确往返', async () => {
    _seedDocument(db.raw, 'd1')
    await upsertRound(round())
    await upsertRoundDocument({
      id: 'rd1', round_id: 'r1', document_id: 'd1', rank_in_round: 0,
      initial_score: 0.1, agent_score: 0.2, agent_rationale: null,
      one_line_summary: null, below_cutoff: true,
    })
    const links = await getRoundDocuments('r1')
    expect(links[0].below_cutoff).toBe(true)
  })
})
