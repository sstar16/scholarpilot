/**
 * SaveDocsPhase — 持久化 documents + round_documents 到本地 SQLite。
 *
 * 移植自 backend `phases/save_docs.py:11-69`，差异：
 * - 删除 `can_interrupt = True`（PRD 决策 10）
 * - 走 documentRepo.upsertManyDocuments + roundDocumentRepo.upsertRoundDocument
 * - zero-results 路径：不再抛 PhaseAborted，直接 update round status='awaiting_feedback' 让流程优雅终止
 */
import type { LocalDocument, LocalRound, LocalRoundDocument } from '@/types/local'
import { upsertManyDocuments } from '@/data/sqlite/repos/documentRepo'
import { upsertRound, upsertRoundDocument } from '@/data/sqlite/repos/roundRepo'

import type { RoundContext } from '../context'
import type { Phase } from '../runner'

import type { FetchOutput, FetchedDoc } from './fetch'
import type { LoadRoundOutput } from './loadRound'
import type { ScoreOutput } from './score'

export interface SaveDocsOutput {
  selectedDocs: FetchedDoc[]
  selectedCount: number
  totalCandidates: number
  zeroResults: boolean
}

/** 把 FetchedDoc → LocalDocument（最小映射，缺省字段兜底）。 */
function _toLocalDocument(d: FetchedDoc, nowMs: number): LocalDocument {
  return {
    id: `${d.source}:${d.external_id}`,
    source: d.source,
    external_id: d.external_id,
    doc_type: d.doc_type ?? 'paper',
    title: d.title ?? '',
    title_zh: null,
    authors: d.authors ?? null,
    abstract: d.abstract ?? null,
    publication_date: d.publication_date ?? null,
    url: d.url ?? null,
    doi: d.doi ?? null,
    journal: d.journal ?? null,
    citation_count: d.citation_count ?? 0,
    pdf_url: d.pdf_url ?? null,
    fulltext_status: 'unknown',
    fulltext_path: null,
    fulltext_pdf_path: null,
    fulltext_pdf_status: 'unknown',
    fulltext_html_path: null,
    fulltext_html_status: 'unknown',
    fulltext_text: null,
    pdf_local_path: null,
    html_local_path: null,
    fulltext_local_path: null,
    ai_summary: null,
    ai_key_points: null,
    ai_relevance_reason: null,
    ai_summary_source: 'pending',
    ai_summary_user: null,
    ai_key_points_user: null,
    countries: null,
    quality_score: null,
    one_line_summary: null,
    one_line_summary_user: null,
    concept_tags: null,
    probe_cache: null,
    content_hash: null,
    import_source: 'fetch',
    imported_at: nowMs,
    created_at: nowMs,
    last_synced_at: null,
  }
}

export const saveDocsPhase: Phase = {
  name: 'save_docs',
  deps: ['score', 'fetch'],
  progressRange: [0.52, 0.60] as const,

  async execute(ctx: RoundContext): Promise<SaveDocsOutput> {
    const fetchOut = ctx.get<FetchOutput>('fetch')
    const scoreOut = ctx.has('score') ? ctx.get<ScoreOutput | null>('score') : null
    const docs = scoreOut?.selectedDocs ?? fetchOut.selectedDocs
    const loaded = ctx.get<LoadRoundOutput>('load_round')

    ctx.eventBus.publish(`round:${ctx.roundId}`, 'round_status', {
      roundId: ctx.roundId,
      status: 'saving',
      progress: 0.52,
      message: `AI 评分完成，${docs.length} 篇通过筛选`,
    })

    if (docs.length === 0) {
      // zero-results：直接进 awaiting_feedback，不抛
      const updated: LocalRound = {
        ...loaded.round,
        status: 'awaiting_feedback',
        total_candidates: fetchOut.totalCandidates,
        selected_count: 0,
        source_stats: fetchOut.sourceStats as unknown as Record<string, unknown>,
        progress: 0.60,
        progress_message: '本轮未找到符合条件的文献',
      }
      await upsertRound(updated)
      ctx.round = updated
      return {
        selectedDocs: [],
        selectedCount: 0,
        totalCandidates: fetchOut.totalCandidates,
        zeroResults: true,
      }
    }

    const now = Date.now()
    const localDocs = docs.map((d) => _toLocalDocument(d, now))
    await upsertManyDocuments(localDocs)

    // round_documents 链接
    const above = scoreOut?.aboveCutoff ?? docs
    const aboveSet = new Set(above.map((d) => `${d.source}:${d.external_id}`))
    let rank = 1
    for (const d of docs) {
      const docId = `${d.source}:${d.external_id}`
      const link: LocalRoundDocument = {
        id: `${ctx.roundId}:${docId}`,
        round_id: ctx.roundId,
        document_id: docId,
        rank_in_round: rank++,
        initial_score: null,
        agent_score: null,
        agent_rationale: null,
        one_line_summary: null,
        below_cutoff: !aboveSet.has(docId),
      }
      await upsertRoundDocument(link)
    }

    // 更新 round 元数据
    const updated: LocalRound = {
      ...loaded.round,
      status: 'saving',
      total_candidates: fetchOut.totalCandidates,
      selected_count: docs.length,
      source_stats: fetchOut.sourceStats as unknown as Record<string, unknown>,
      progress: 0.58,
      progress_message: `已保存 ${docs.length} 篇文献到本轮`,
    }
    await upsertRound(updated)
    ctx.round = updated

    ctx.eventBus.publish(`round:${ctx.roundId}`, 'round_status', {
      roundId: ctx.roundId,
      status: 'saving',
      progress: 0.58,
      message: `已保存 ${docs.length} 篇文献到本轮`,
    })

    return {
      selectedDocs: docs,
      selectedCount: docs.length,
      totalCandidates: fetchOut.totalCandidates,
      zeroResults: false,
    }
  },
}
