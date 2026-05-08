/**
 * PlanQueryPhase — 用 QueryPlanAgent 生成本轮 QueryPlan，写到 search_rounds.search_queries_json。
 *
 * 移植自 backend `phases/plan_query.py:13-111`，差异：
 * - QueryPlanAgent 走客户端版（B5 已就绪：`client/src/data/agents/queryPlanAgent.ts`）
 * - 不调 ToolRegistry 取 reliability（客户端没那个）
 * - fallback：客户端简化版 `_buildQueryFallback()`（base_query = project.description / domain）
 * - 写库走 roundRepo.upsertRound（不再 SQLAlchemy update）
 *
 * 接通策略（C 阶段）：
 * - 默认走 agenticPlan（C4 fetcherApi 已就绪 → search_preview 自检）
 * - agentic 内部三层兜底：parse 失败重试 → 耗尽 iterations 走 legacy → legacy 也挂 throw
 * - 最外层 catch fallback 到 `_buildQueryFallback`（保最后底）
 * - `setQueryPlanAgent()` 仅供单测注入 mock。
 */
import {
  QueryPlanAgent,
  type QueryPlan as ClientQueryPlan,
} from '@/data/agents/queryPlanAgent'
import { fetcherApi, type SourceMeta } from '@/api/fetcher'
import { llmManager } from '@/data/llm/manager'
import type { LocalRound } from '@/types/local'
import { upsertRound } from '@/data/sqlite/repos/roundRepo'
import {
  getActiveSessionForProject,
  appendMessage,
} from '@/data/sqlite/repos/conversationRepo'

import type { RoundContext } from '../context'
import { PhaseAborted } from '../context'
import type { Phase } from '../runner'

import type { LoadMemoryOutput } from './loadMemory'
import type { LoadRoundOutput } from './loadRound'

export interface PlanQueryOutput {
  queryPlan: ClientQueryPlan
  planSource: 'agent' | 'fallback'
}

/**
 * 客户端默认数据源（fallback 路径用）。完整 14 源在 fetcher.listSources 里维护。
 *
 * 用于：
 * 1. 测试环境（无 fetcherApi.sources() 网络）
 * 2. fetcherApi.sources() 失败时兜底
 */
const _DEFAULT_SOURCES = [
  'openalex',
  'arxiv',
  'crossref',
  'europepmc',
  'dblp',
] as const

/**
 * 鸭子接口：QueryPlanAgent 注入点（已默认接通真 agent，setter 仅供单测）。
 *
 * 暴露 `agenticPlan` 和 `legacyPlan` 两条路径，让单测可以选不同 mock。
 */
export interface QueryPlanAgentLike {
  agenticPlan(params: {
    projectDescription: string
    memorySnapshot?: string
    sources: string[]
    maxIterations?: number
  }): Promise<ClientQueryPlan>
  legacyPlan(params: {
    projectDescription: string
    memorySnapshot?: string
    sources: string[]
    roundNumber?: number
    maxRounds?: number
  }): Promise<ClientQueryPlan>
}

const _AGENT_HOLDER: { current: QueryPlanAgentLike | null } = { current: null }

/** 仅供单测注入 mock；传 null 走默认真 agent。 */
export function setQueryPlanAgent(impl: QueryPlanAgentLike | null): void {
  _AGENT_HOLDER.current = impl
}

// ── 默认真 QueryPlanAgent 适配器（懒构造单例） ─────────────────────────

let _defaultAgentSingleton: QueryPlanAgentLike | null = null

function _ensureDefaultAgent(): QueryPlanAgentLike {
  if (_defaultAgentSingleton) return _defaultAgentSingleton

  const llmAdapter = {
    async generate(prompt: string, options?: {
      temperature?: number
      response_format?: { type: 'json_object' | 'text' } | null
    }) {
      return llmManager.generate(prompt, options ?? {})
    },
  }
  const realAgent = new QueryPlanAgent(llmAdapter, fetcherApi)
  _defaultAgentSingleton = {
    agenticPlan: (p) => realAgent.agenticPlan(p),
    legacyPlan: (p) => realAgent.legacyPlan(p),
  }
  return _defaultAgentSingleton
}

async function _resolveSources(): Promise<{ ids: string[]; metaById: Map<string, SourceMeta> }> {
  const metaById = new Map<string, SourceMeta>()
  try {
    const all = await fetcherApi.sources()
    for (const s of all) metaById.set(s.id, s)
    const enabled = all.filter((s) => s.enabled).map((s) => s.id)
    if (enabled.length > 0) return { ids: enabled, metaById }
  } catch (e) {
    console.warn('[PlanQueryPhase] fetcherApi.sources() failed, fallback to defaults:', e)
  }
  return { ids: [..._DEFAULT_SOURCES], metaById }
}

export const planQueryPhase: Phase = {
  name: 'plan_query',
  deps: ['load_round', 'build_dedup', 'load_memory'],
  progressRange: [0.13, 0.20] as const,

  async execute(ctx: RoundContext): Promise<PlanQueryOutput> {
    const loaded = ctx.get<LoadRoundOutput>('load_round')
    const memory = ctx.get<LoadMemoryOutput>('load_memory')
    const project = loaded.project

    const { ids: sources, metaById } = await _resolveSources()

    let queryPlan: ClientQueryPlan
    let planSource: PlanQueryOutput['planSource']

    const agent = _AGENT_HOLDER.current ?? _ensureDefaultAgent()

    try {
      // 2026-05-08 改默认走 legacy：单次 LLM 调用直出 plan，**不依赖 sp-api search_preview**
      // 试探。agenticPlan 会在 LLM ↔ sp-api 之间循环试探（多轮 LLM + 网络），任一环节
      // 不稳就死磕到 maxIterations，整个 round 在 plan_query 卡死。
      // 用户视角：生成关键词应该完全 client BYOK 自洽，不该被 sp-api 卡。
      queryPlan = await agent.legacyPlan({
        projectDescription: project.description,
        memorySnapshot: memory.combinedMd,
        sources,
      })
      planSource = 'agent'
    } catch (e) {
      console.warn('[PlanQueryPhase] legacyPlan failed, falling back to keyword split:', e)
      queryPlan = _buildQueryFallback(project, memory)
      planSource = 'fallback'
    }

    ctx.queryPlan = queryPlan

    const planInfo = {
      base_query: queryPlan.meta.baseQuery,
      year_from: queryPlan.meta.yearFrom,
      year_to: queryPlan.meta.yearTo,
      language_scope: queryPlan.meta.languageScope,
      sources_selected: Object.keys(queryPlan.perSource),
      plan_source: planSource,
      reasoning: queryPlan.reasoning,
    }

    ctx.eventBus.publish(`round:${ctx.roundId}`, 'agent_plan', {
      roundId: ctx.roundId,
      plan_source: planSource,
      base_query: queryPlan.meta.baseQuery.slice(0, 100),
      sources: Object.keys(queryPlan.perSource),
    })

    const session = await getActiveSessionForProject(project.id)
    if (!session) {
      console.warn('[PlanQueryPhase] no active session for project; keyword confirm bubble will not render')
    }
    const appendPromise = session
      ? appendMessage({
          session_id: session.id,
          role: 'assistant',
          content_md: '请确认或编辑下面的检索关键词方案：',
          rich_data: _buildKeywordConfirmRichData({
            ctx, loaded, queryPlan, metaById, planSource,
          }),
          created_at: Date.now(),
        })
      : Promise.resolve()

    const updated: LocalRound = {
      ...loaded.round,
      status: 'awaiting_keywords',
      search_queries: planInfo,
      progress: 0.20,
      progress_message: '等待关键词确认',
    }
    await Promise.all([appendPromise, upsertRound(updated)])

    ctx.eventBus.publish(`round:${ctx.roundId}`, 'message_appended', {
      roundId: ctx.roundId,
    })

    throw new PhaseAborted('awaiting_keywords', { message: '等待用户确认关键词方案' })
  },
}

function _buildKeywordConfirmRichData(args: {
  ctx: RoundContext
  loaded: LoadRoundOutput
  queryPlan: ClientQueryPlan
  metaById: Map<string, SourceMeta>
  planSource: PlanQueryOutput['planSource']
}): Record<string, unknown> {
  const { ctx, loaded, queryPlan, metaById, planSource } = args
  return {
    type: 'keyword_confirmation',
    round_id: ctx.roundId,
    round_number: loaded.round.round_number,
    base_query: queryPlan.meta.baseQuery,
    year_from: queryPlan.meta.yearFrom,
    year_to: queryPlan.meta.yearTo,
    language_scope: queryPlan.meta.languageScope,
    exclude_terms: queryPlan.meta.excludeTerms,
    source_plans: Object.entries(queryPlan.perSource).map(([sid, sp]) => {
      const meta = metaById.get(sid)
      return {
        source_id: sid,
        display_name: meta?.name ?? sid,
        // 复杂层用 base_query（QueryPlanAgent 已生成含 (A OR B) AND (C OR D) 结构）
        query: queryPlan.meta.baseQuery,
        query_medium: sp.keywords.slice(0, 5).join(' AND '),
        query_simple: sp.keywords.slice(0, 2).join(' AND '),
        query_format: 'plain',
        language: meta?.language ?? 'en',
        enabled: true,
        generation_method: planSource === 'agent' ? 'llm' : 'heuristic',
        notes: '',
        category: meta?.category ?? '',
      }
    }),
    max_per_source: 25,
    plan_source: planSource,
    reasoning: queryPlan.reasoning,
  }
}

/** 客户端简化版 fallback：拿 project.description 切词当 base_query，分发到默认 5 个源。 */
function _buildQueryFallback(
  project: { description: string; domain: string; domains: string[] | null },
  memory: LoadMemoryOutput,
): ClientQueryPlan {
  const base = (project.description || project.domain || 'research').trim()
  const keywords = base
    .split(/\s+/)
    .filter((w) => w.length >= 2)
    .slice(0, 8)
  if (keywords.length === 0) keywords.push(project.domain || 'research')

  const filters: Record<string, unknown> = {
    year_from: null,
    year_to: new Date().getFullYear(),
    language_scope: 'international',
    exclude_terms: memory.excludedKeywords ?? [],
  }
  const perSource: ClientQueryPlan['perSource'] = {}
  for (const s of _DEFAULT_SOURCES) {
    perSource[s] = { keywords: [...keywords], filters: { ...filters } }
  }

  return {
    perSource,
    reasoning: 'fallback: built from project.description tokens',
    iterations: 0,
    meta: {
      baseQuery: base,
      chineseQuery: null,
      yearFrom: null,
      yearTo: new Date().getFullYear(),
      languageScope: 'international',
      excludeTerms: memory.excludedKeywords ?? [],
      clarificationNeeded: false,
      clarificationMessage: '',
      mode: 'legacy',
    },
  }
}
