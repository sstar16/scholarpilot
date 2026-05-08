/**
 * ScorePhase — LLM-based per-doc relevance scoring with cutoff filtering.
 *
 * 移植自 backend `phases/score.py:12-89`，差异：
 * - 删除 `can_interrupt = True`（PRD 决策 10）
 * - ScoringAgent 走客户端版（B6 已就绪：`client/src/data/agents/scoringAgent.ts`）
 * - LLMQueue（B6 提供 8-concurrent + 中间持久化）已就绪
 *
 * 接通策略（C 阶段）：默认 lazy 构造真 ScoringAgent + LLMQueue + llmManager；
 * `setScoringAgent()` 仅供单测注入 mock。
 */
import { ScoringAgent, type ScoreInput, type ScoreOutput as AgentScoreOutput } from '@/data/agents/scoringAgent'
import { LLMQueue } from '@/data/llm/concurrent_queue'
import { llmManager } from '@/data/llm/manager'

import type { RoundContext } from '../context'
import { PhaseSkipped } from '../context'
import type { Phase } from '../runner'

import type { FetchOutput, FetchedDoc } from './fetch'
import type { LoadMemoryOutput } from './loadMemory'
import type { LoadRoundOutput } from './loadRound'
import type { RerankOutput } from './rerank'

const DEFAULT_CUTOFF = 6.0

export interface ScoreOutput {
  selectedDocs: FetchedDoc[]
  aboveCutoff: FetchedDoc[]
  belowCutoff: FetchedDoc[]
  cutoff: number
  skipped: boolean
  error?: string
}

/**
 * 鸭子接口：ScoringAgent 注入点（已默认接通真 agent，setter 仅供单测）。
 */
export interface ScoringAgentLike {
  scoreAll(params: {
    docs: FetchedDoc[]
    projectDescription: string
    cutoff: number
    userMemory: string
    llmManager: unknown
  }): Promise<{ above: FetchedDoc[]; below: FetchedDoc[] }>
}

const _SCORING_HOLDER: { current: ScoringAgentLike | null } = { current: null }

/** 仅供单测注入 mock；传 null 走默认真 agent。 */
export function setScoringAgent(impl: ScoringAgentLike | null): void {
  _SCORING_HOLDER.current = impl
}

// ── 默认真 ScoringAgent 适配器（懒构造单例） ─────────────────────────────

let _defaultAgentSingleton: ScoringAgentLike | null = null

/**
 * 把 FetchedDoc → ScoreInput（ScoringAgent 期望的形态）。
 * FetchedDoc 字段名已基本对齐 backend ScoreInput，这里做一次显式转换避免漂移。
 */
function _toScoreInput(d: FetchedDoc): ScoreInput {
  const anyDoc = d as unknown as Record<string, unknown>
  return {
    docId: String(anyDoc.docId ?? anyDoc.id ?? anyDoc.external_id ?? ''),
    title: String(anyDoc.title ?? ''),
    abstract: String(anyDoc.abstract ?? ''),
    authors: typeof anyDoc.authors === 'string' ? (anyDoc.authors as string) : undefined,
    year: typeof anyDoc.year === 'number' ? (anyDoc.year as number) : undefined,
    source: typeof anyDoc.source === 'string' ? (anyDoc.source as string) : undefined,
    docType: typeof anyDoc.doc_type === 'string' ? (anyDoc.doc_type as string) : undefined,
    publicationDate: typeof anyDoc.publication_date === 'string' ? (anyDoc.publication_date as string) : undefined,
    citationCount: typeof anyDoc.citation_count === 'number' ? (anyDoc.citation_count as number) : undefined,
    doi: typeof anyDoc.doi === 'string' ? (anyDoc.doi as string) : undefined,
    journal: typeof anyDoc.journal === 'string' ? (anyDoc.journal as string) : undefined,
  }
}

function _ensureDefaultAgent(): ScoringAgentLike {
  if (_defaultAgentSingleton) return _defaultAgentSingleton

  const llmAdapter = {
    async generate(prompt: string, options?: {
      temperature?: number
      response_format?: { type: 'json_object' | 'text' } | null
    }) {
      // llmManager.generate 返回 LLMResult | null，签名兼容 ScoringAgent.LLMLike
      return llmManager.generate(prompt, options ?? {})
    },
  }
  const queue = new LLMQueue()
  const realAgent = new ScoringAgent(llmAdapter, queue)

  _defaultAgentSingleton = {
    async scoreAll(params: {
      docs: FetchedDoc[]
      projectDescription: string
      cutoff: number
      userMemory: string
      llmManager: unknown
    }): Promise<{ above: FetchedDoc[]; below: FetchedDoc[] }> {
      const scoreInputs = params.docs.map(_toScoreInput)
      const docByDocId = new Map<string, FetchedDoc>()
      for (let i = 0; i < params.docs.length; i++) {
        docByDocId.set(scoreInputs[i].docId, params.docs[i])
      }
      const runId = `score-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
      const result = await realAgent.scoreAll({
        runId,
        docs: scoreInputs,
        projectDescription: params.projectDescription,
        memorySnapshot: params.userMemory,
        cutoff: params.cutoff,
      })
      // 把 ScoreOutput 回填到 FetchedDoc（保留 score / reasoning 元数据，下游 phase 可用）
      const enrich = (so: AgentScoreOutput): FetchedDoc | null => {
        const orig = docByDocId.get(so.docId)
        if (!orig) return null
        // 浅 merge —— 不破坏 FetchedDoc 原结构
        return {
          ...(orig as object),
          agent_score: so.score,
          agent_rationale: so.reasoning,
          one_line_summary: so.oneLine ?? null,
          bucket: so.bucket,
        } as unknown as FetchedDoc
      }
      const above = result.above.map(enrich).filter((d): d is FetchedDoc => d != null)
      const below = result.below.map(enrich).filter((d): d is FetchedDoc => d != null)
      return { above, below }
    },
  }
  return _defaultAgentSingleton
}

export const scorePhase: Phase = {
  name: 'score',
  deps: ['rerank', 'load_memory', 'load_round'],
  progressRange: [0.42, 0.52] as const,

  async execute(ctx: RoundContext): Promise<ScoreOutput> {
    let docs: FetchedDoc[] = []
    if (ctx.has('rerank')) {
      const rerank = ctx.get<RerankOutput | null>('rerank')
      docs = rerank?.selectedDocs ?? []
    }
    if (docs.length === 0 && ctx.has('fetch')) {
      docs = ctx.get<FetchOutput>('fetch').selectedDocs
    }
    if (docs.length === 0) {
      throw new PhaseSkipped('no docs to score')
    }

    const loaded = ctx.get<LoadRoundOutput>('load_round')
    const memory = ctx.get<LoadMemoryOutput>('load_memory')
    const project = loaded.project
    const cutoff = loaded.scoringCutoff ?? DEFAULT_CUTOFF

    ctx.eventBus.publish(`round:${ctx.roundId}`, 'round_status', {
      roundId: ctx.roundId,
      status: 'scoring',
      progress: 0.45,
      message: `AI 正在评估 ${docs.length} 篇文献相关性...`,
    })

    const scoringDesc = project.title
      ? `【${project.title}】${project.description}`
      : project.description

    const agent = _SCORING_HOLDER.current ?? _ensureDefaultAgent()

    try {
      const { above, below } = await agent.scoreAll({
        docs,
        projectDescription: scoringDesc,
        cutoff,
        userMemory: memory.combinedMd,
        llmManager: ctx.llmManager,
      })
      ctx.eventBus.publish(`round:${ctx.roundId}`, 'scoring_complete', {
        roundId: ctx.roundId,
        above_cutoff: above.length,
        below_cutoff: below.length,
        cutoff,
      })
      ctx.scoredDocs = above
      return {
        selectedDocs: [...above, ...below],
        aboveCutoff: above,
        belowCutoff: below,
        cutoff,
        skipped: false,
      }
    } catch (e) {
      console.warn('[ScorePhase] scoringAgent failed, falling back to legacy:', e)
      return {
        selectedDocs: docs,
        aboveCutoff: docs,
        belowCutoff: [],
        cutoff,
        skipped: true,
        error: (e as Error).message,
      }
    }
  },
}
