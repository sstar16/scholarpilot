/**
 * DispatchSummariesPhase — 给所有保存的文档调度 LLM 摘要生成。
 *
 * 移植自 backend `phases/dispatch_summaries.py:15-80`，差异：
 * - 删除 Celery `chord(group(generate_summary_for_doc.s(...)))` 链路
 * - 删除 `can_interrupt = True`（PRD 决策 10）
 * - 删除 `run_coordinator_async`（QualityAgent / ProfilePreAnalyzer fire-and-forget 是低价值附加）
 * - 改为 `summarizer.summarizeBatch(docs)` 走 Phase B 的 LLMQueue（p-queue + SQLite 中间持久化）
 *
 * 接通策略（C 阶段）：默认 lazy 构造真 LLMSummarizer + LLMQueue + llmManager；
 * `setSummarizer()` 仅供单测注入 mock。
 */
import { LLMSummarizer, type SummarizeInput } from '@/data/agents/summarizer'
import { LLMQueue } from '@/data/llm/concurrent_queue'
import { llmManager } from '@/data/llm/manager'
import { LiteratureWriter, type LibraryDoc as LibWriterDoc } from '@/data/fs/literatureWriter'
import type { LocalRound } from '@/types/local'
import { upsertRound } from '@/data/sqlite/repos/roundRepo'
import { getProject } from '@/data/sqlite/repos/projectRepo'
import { listClassificationsByProject, type ClientBucket } from '@/data/sqlite/repos/bucketRepo'

import type { RoundContext } from '../context'
import type { Phase } from '../runner'

import type { FetchedDoc } from './fetch'
import type { LoadRoundOutput } from './loadRound'
import type { SaveDocsOutput } from './saveDocs'

export interface DispatchSummariesOutput {
  dispatched: boolean
  selected: number
  total: number
  summaryCount: number
}

export interface SummarySpec {
  docId: string
  source: string
  externalId: string
  summary: string
  keyPoints?: string[]
  relevanceReason?: string
}

/**
 * 鸭子接口：Summarizer 注入点（已默认接通真 LLMSummarizer，setter 仅供单测）。
 */
export interface SummarizerLike {
  summarizeBatch(params: {
    docs: FetchedDoc[]
    projectDescription: string
    roundId: string
    llmManager: unknown
    onSummaryReady?: (s: SummarySpec) => void
  }): Promise<SummarySpec[]>
}

const _SUMMARIZER_HOLDER: { current: SummarizerLike | null } = { current: null }

/** 仅供单测注入 mock；传 null 走默认真 summarizer。 */
export function setSummarizer(impl: SummarizerLike | null): void {
  _SUMMARIZER_HOLDER.current = impl
}

// ── 默认真 LLMSummarizer 适配器（懒构造单例） ──────────────────────────

let _defaultSummarizerSingleton: SummarizerLike | null = null

function _toSummarizeInput(d: FetchedDoc): SummarizeInput {
  const anyDoc = d as unknown as Record<string, unknown>
  return {
    docId: String(anyDoc.docId ?? anyDoc.id ?? anyDoc.external_id ?? ''),
    title: String(anyDoc.title ?? ''),
    abstract: String(anyDoc.abstract ?? ''),
    fulltext: typeof anyDoc.fulltext_text === 'string' ? (anyDoc.fulltext_text as string) : undefined,
    authors: typeof anyDoc.authors === 'string' ? (anyDoc.authors as string) : undefined,
    year: typeof anyDoc.year === 'number' ? (anyDoc.year as number) : undefined,
  }
}

function _ensureDefaultSummarizer(): SummarizerLike {
  if (_defaultSummarizerSingleton) return _defaultSummarizerSingleton

  const llmAdapter = {
    async generate(prompt: string, options?: {
      temperature?: number
      response_format?: { type: 'json_object' | 'text' } | null
    }) {
      return llmManager.generate(prompt, options ?? {})
    },
  }
  const queue = new LLMQueue()
  const real = new LLMSummarizer(llmAdapter, queue)

  _defaultSummarizerSingleton = {
    async summarizeBatch(params: {
      docs: FetchedDoc[]
      projectDescription: string
      roundId: string
      llmManager: unknown
      onSummaryReady?: (s: SummarySpec) => void
    }): Promise<SummarySpec[]> {
      const inputs = params.docs.map(_toSummarizeInput)
      const docMap = new Map<string, FetchedDoc>()
      for (let i = 0; i < params.docs.length; i++) {
        docMap.set(inputs[i].docId, params.docs[i])
      }
      const results = await real.summarizeBatch({
        runId: params.roundId,
        docs: inputs,
        targetLanguage: 'zh',
        onProgress: (_done, _total, lastResult) => {
          if (!lastResult) return
          const orig = docMap.get(lastResult.docId)
          const spec: SummarySpec = {
            docId: lastResult.docId,
            source: typeof (orig as unknown as Record<string, unknown>)?.source === 'string'
              ? String((orig as unknown as Record<string, unknown>).source)
              : '',
            externalId: typeof (orig as unknown as Record<string, unknown>)?.external_id === 'string'
              ? String((orig as unknown as Record<string, unknown>).external_id)
              : '',
            summary: lastResult.summary,
            keyPoints: lastResult.keyPoints,
            relevanceReason: undefined,
          }
          try {
            params.onSummaryReady?.(spec)
          } catch (e) {
            console.warn('[dispatchSummaries] onSummaryReady listener throw (ignored):', e)
          }
        },
      })
      return results.map((r) => {
        const orig = docMap.get(r.docId)
        return {
          docId: r.docId,
          source: typeof (orig as unknown as Record<string, unknown>)?.source === 'string'
            ? String((orig as unknown as Record<string, unknown>).source)
            : '',
          externalId: typeof (orig as unknown as Record<string, unknown>)?.external_id === 'string'
            ? String((orig as unknown as Record<string, unknown>).external_id)
            : '',
          summary: r.summary,
          keyPoints: r.keyPoints,
        } as SummarySpec
      })
    },
  }
  return _defaultSummarizerSingleton
}

export const dispatchSummariesPhase: Phase = {
  name: 'dispatch_summaries',
  deps: ['save_docs'],
  progressRange: [0.60, 0.62] as const,

  async execute(ctx: RoundContext): Promise<DispatchSummariesOutput> {
    const saveOut = ctx.get<SaveDocsOutput>('save_docs')
    const loaded = ctx.get<LoadRoundOutput>('load_round')

    if (saveOut.zeroResults || saveOut.selectedDocs.length === 0) {
      // zero-results 已经在 saveDocs 标了 awaiting_feedback；这里只透传
      return {
        dispatched: false,
        selected: 0,
        total: saveOut.totalCandidates,
        summaryCount: 0,
      }
    }

    // 标 status → 'summarizing'
    const summarizingRound: LocalRound = {
      ...loaded.round,
      status: 'summarizing',
      progress: 0.60,
      progress_message: `正在为 ${saveOut.selectedDocs.length} 篇文献生成 AI 摘要...`,
    }
    await upsertRound(summarizingRound)
    ctx.round = summarizingRound

    ctx.eventBus.publish(`round:${ctx.roundId}`, 'round_status', {
      roundId: ctx.roundId,
      status: 'summarizing',
      progress: 0.62,
      message: `正在为 ${saveOut.selectedDocs.length} 篇文献生成 AI 摘要...`,
    })

    const summarizer = _SUMMARIZER_HOLDER.current ?? _ensureDefaultSummarizer()

    let summaryCount = 0
    let summariesProduced: SummarySpec[] = []
    try {
      const summaries = await summarizer.summarizeBatch({
        docs: saveOut.selectedDocs,
        projectDescription: loaded.project.description,
        roundId: ctx.roundId,
        llmManager: ctx.llmManager,
        onSummaryReady: (s) => {
          summaryCount++
          ctx.eventBus.publish(`round:${ctx.roundId}`, 'summary_ready', {
            roundId: ctx.roundId,
            docId: s.docId,
            summary: s.summary,
          })
        },
      })
      ctx.summaries = summaries
      summariesProduced = summaries
    } catch (e) {
      console.warn('[DispatchSummariesPhase] summarizeBatch failed (non-fatal):', e)
    }

    // C6 hook：把单篇 + 索引写到 library/ markdown workspace
    // 失败仅 log，不影响 round 状态推进（feedback 主流程保活）
    try {
      await _writeLiteratureMarkdown(ctx, loaded, saveOut, summariesProduced)
    } catch (e) {
      console.warn('[DispatchSummariesPhase] LiteratureWriter hook failed (non-fatal):', e)
    }

    // 摘要完成 → awaiting_feedback
    const finalRound: LocalRound = {
      ...summarizingRound,
      status: 'awaiting_feedback',
      progress: 0.62,
      completed_at: Date.now(),
    }
    await upsertRound(finalRound)
    ctx.round = finalRound
    ctx.eventBus.publish(`round:${ctx.roundId}`, 'round_complete', {
      roundId: ctx.roundId,
    })

    return {
      dispatched: true,
      selected: saveOut.selectedDocs.length,
      total: saveOut.totalCandidates,
      summaryCount,
    }
  },
}

// ── C6: dispatchSummaries 后把每篇文献 + 索引写到 library/ markdown workspace ──

async function _writeLiteratureMarkdown(
  ctx: RoundContext,
  loaded: LoadRoundOutput,
  saveOut: SaveDocsOutput,
  summaries: SummarySpec[],
): Promise<void> {
  if (!saveOut.selectedDocs || saveOut.selectedDocs.length === 0) return

  const project = await getProject(ctx.projectId)
  const projectTitle = project?.title ?? null
  const writer = new LiteratureWriter(ctx.projectId, projectTitle)

  const summaryByDocId = new Map<string, SummarySpec>()
  for (const s of summaries) {
    const k = s.docId || `${s.source}::${s.externalId}`
    summaryByDocId.set(k, s)
  }

  // 拉本地分类（如有）；新轮多数文献还没分桶，bucket 留 uncategorized
  const classifications = await listClassificationsByProject(ctx.projectId)
  const bucketByDoc = new Map<string, ClientBucket>()
  for (const c of classifications) bucketByDoc.set(c.document_id, c.bucket)

  const writerDocs: LibWriterDoc[] = []
  for (const d of saveOut.selectedDocs) {
    const anyDoc = d as unknown as Record<string, unknown>
    const externalId = typeof anyDoc.external_id === 'string' ? anyDoc.external_id : ''
    const source = typeof anyDoc.source === 'string' ? anyDoc.source : ''
    // SaveDocsPhase 用 `${source}:${external_id}` 当 LocalDocument.id；这里保持一致
    const explicitId = anyDoc.docId ?? anyDoc.id
    const docId = String(explicitId ?? (source && externalId ? `${source}:${externalId}` : ''))
    if (!docId) continue
    const summary = summaryByDocId.get(docId) ?? summaryByDocId.get(`${source}::${externalId}`)
    const wd: LibWriterDoc = {
      docId,
      title: typeof anyDoc.title === 'string' ? anyDoc.title : 'Untitled',
      authors: typeof anyDoc.authors === 'string' ? anyDoc.authors : null,
      year: typeof anyDoc.year === 'number' ? (anyDoc.year as number) : null,
      source,
      doi: typeof anyDoc.doi === 'string' ? anyDoc.doi : null,
      summary: summary?.summary ?? (typeof anyDoc.ai_summary === 'string' ? anyDoc.ai_summary : null),
      keyPoints: summary?.keyPoints ?? null,
      score: typeof anyDoc.quality_score === 'number'
        ? (anyDoc.quality_score as number)
        : (typeof anyDoc.agent_score === 'number' ? (anyDoc.agent_score as number) : null),
      bucket: bucketByDoc.get(docId) ?? 'uncategorized',
      tags: Array.isArray(anyDoc.concept_tags) ? (anyDoc.concept_tags as string[]) : null,
      oneLineSummary: typeof anyDoc.one_line_summary === 'string'
        ? (anyDoc.one_line_summary as string)
        : null,
      roundNumber: typeof loaded.round.round_number === 'number' ? loaded.round.round_number : null,
      journal: typeof anyDoc.journal === 'string' ? anyDoc.journal : null,
      url: typeof anyDoc.url === 'string' ? anyDoc.url : null,
    }
    writerDocs.push(wd)
    try {
      await writer.writeDoc(wd)
    } catch (e) {
      console.warn('[LiteratureWriter] writeDoc failed:', docId, e)
    }
  }

  try {
    await writer.writeIndex(writerDocs)
  } catch (e) {
    console.warn('[LiteratureWriter] writeIndex failed:', e)
  }
}
