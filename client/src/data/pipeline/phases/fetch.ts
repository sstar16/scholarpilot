/**
 * FetchPhase — 调 sp-api fetcher 14 源并行，merge 结果，做 dedup。
 *
 * 移植自 backend `phases/fetch.py:13-114`，差异：
 * - 客户端没有 AgentSearchLoop；直接走 `fetcherApi.search`
 * - asyncio.gather → 自实现 concurrency-bounded queue（per-source 错误不阻塞 loop）
 * - 14 源并发上限 8（sp-api 压力控制）
 *
 * **C4 已接通**：默认走 `client/src/api/fetcher.ts` 的 `fetcherApi`；单测可通过
 * `setFetcherApi()` 注入 mock。
 */
import { fetcherApi } from '@/api/fetcher'

import type { RoundContext } from '../context'
import type { Phase } from '../runner'

import type { ApplySearchModeOutput } from './applySearchMode'
import type { BuildDedupOutput } from './buildDedup'
import type { LoadConfirmedKeywordsOutput } from './loadConfirmedKeywords'
import type { LoadRoundOutput } from './loadRound'
import type { PlanQueryOutput } from './planQuery'

/** Raw doc 形态（客户端口径，对齐 backend fetcher 返回 dict）。 */
export interface FetchedDoc {
  source: string
  external_id: string
  title: string
  abstract?: string
  authors?: string
  publication_date?: string
  url?: string
  doi?: string
  journal?: string
  citation_count?: number
  pdf_url?: string
  doc_type?: string
  metadata?: Record<string, unknown>
}

export interface SourceStat {
  status: 'ok' | 'error' | 'empty'
  count: number
  error?: string
  latency_ms?: number
}

export interface FetchOutput {
  selectedDocs: FetchedDoc[]
  totalCandidates: number
  sourceStats: Record<string, SourceStat>
  iterations: number
}

/**
 * 鸭子接口：caller 可注入实际的 fetcher 实现（默认走 `@/api/fetcher`）。
 *
 * C4 已接通真 `fetcherApi`；`setFetcherApi()` 仅给单测注入 mock 用。
 */
export interface FetcherApiLike {
  search(body: {
    source: string
    query: string
    max_results: number
    year_from?: number | null
    year_to?: number | null
    query_medium?: string
    query_simple?: string
  }): Promise<{ docs: FetchedDoc[]; latency_ms?: number }>
}

const _FETCH_API_HOLDER: { current: FetcherApiLike | null } = { current: null }

/** 仅单测用：注入 mock fetcherApi；传 null 复位为生产实现。 */
export function setFetcherApi(api: FetcherApiLike | null): void {
  _FETCH_API_HOLDER.current = api
}

export const fetchPhase: Phase = {
  name: 'fetch',
  deps: ['apply_search_mode', 'build_dedup', 'load_round'],
  progressRange: [0.22, 0.40] as const,

  async execute(ctx: RoundContext): Promise<FetchOutput> {
    const planOut = ctx.get<PlanQueryOutput>('plan_query')
    const dedup = ctx.get<BuildDedupOutput>('build_dedup')
    const confirmed = ctx.get<LoadConfirmedKeywordsOutput>('load_confirmed_keywords')
    const finalSources = ctx.get<ApplySearchModeOutput>('apply_search_mode').finalSources
    void ctx.get<LoadRoundOutput>('load_round') // ensure load_round visible

    ctx.eventBus.publish(`round:${ctx.roundId}`, 'round_status', {
      roundId: ctx.roundId,
      status: 'searching',
      progress: 0.22,
      message: `开始检索 ${finalSources.length} 个数据源...`,
    })

    const fetcher: FetcherApiLike = _FETCH_API_HOLDER.current ?? fetcherApi
    const sourceStats: Record<string, SourceStat> = {}
    const allDocs: FetchedDoc[] = []
    const seen = new Set<string>()

    const queryPlan = planOut.queryPlan
    const yearFrom = queryPlan.meta.yearFrom
    const yearTo = queryPlan.meta.yearTo
    const baseQuery = queryPlan.meta.baseQuery

    // p-queue concurrency=8 风控（避免 14 源同时打 sp-api）
    const concurrency = 8
    let inflight = 0
    const queue: Array<() => Promise<void>> = []
    let totalScheduled = 0
    let totalCompleted = 0
    // 用 holder 对象避免 TS 在闭包中将 let 推断为 never
    const finishHolder: { resolve: () => void } = { resolve: () => {} }
    const allDone = new Promise<void>((res) => { finishHolder.resolve = res })

    const runNext = () => {
      while (inflight < concurrency && queue.length > 0) {
        const fn = queue.shift()!
        inflight++
        fn().finally(() => {
          inflight--
          totalCompleted++
          if (totalCompleted >= totalScheduled && queue.length === 0 && inflight === 0) {
            finishHolder.resolve()
          } else {
            runNext()
          }
        })
      }
      if (totalCompleted >= totalScheduled && inflight === 0) finishHolder.resolve()
    }

    for (const sid of finalSources) {
      if (ctx.abortSignal.aborted) break
      const sp = queryPlan.perSource[sid]
      const queryText = (confirmed.perSourceQueries?.[sid]?.complex || sp?.keywords?.join(' ') || baseQuery).trim()
      const queryMedium = confirmed.perSourceQueries?.[sid]?.medium
      const querySimple = confirmed.perSourceQueries?.[sid]?.simple

      totalScheduled++
      queue.push(async () => {
        const t0 = Date.now()
        try {
          ctx.eventBus.publish(`round:${ctx.roundId}`, 'source_started', {
            roundId: ctx.roundId,
            source: sid,
          })
          const r = await fetcher.search({
            source: sid,
            query: queryText || baseQuery || ' ',
            max_results: 25,
            year_from: yearFrom ?? null,
            year_to: yearTo ?? null,
            query_medium: queryMedium,
            query_simple: querySimple,
          })
          const docs = (r.docs ?? []).filter((d) => {
            const key = `${d.source ?? sid}:${d.external_id}`
            if (dedup.excludeKeys.has(key)) return false
            if (seen.has(key)) return false
            seen.add(key)
            return true
          })
          allDocs.push(...docs)
          sourceStats[sid] = {
            status: docs.length > 0 ? 'ok' : 'empty',
            count: docs.length,
            latency_ms: Date.now() - t0,
          }
          for (const d of docs) {
            ctx.eventBus.publish(`round:${ctx.roundId}`, 'doc_arrived', {
              roundId: ctx.roundId,
              source: sid,
              external_id: d.external_id,
              title: d.title,
            })
          }
        } catch (e) {
          sourceStats[sid] = {
            status: 'error',
            count: 0,
            error: (e as Error).message?.slice(0, 200) ?? 'unknown',
            latency_ms: Date.now() - t0,
          }
          console.warn(`[FetchPhase] source ${sid} failed:`, e)
        }
      })
    }
    runNext()
    if (totalScheduled === 0) finishHolder.resolve()
    await allDone

    ctx.fetchedDocs = allDocs
    ctx.eventBus.publish(`round:${ctx.roundId}`, 'round_status', {
      roundId: ctx.roundId,
      status: 'searching',
      progress: 0.38,
      message: `检索完成 · 候选 ${allDocs.length} 篇`,
    })

    return {
      selectedDocs: allDocs,
      totalCandidates: allDocs.length,
      sourceStats,
      iterations: 1,
    }
  },
}
