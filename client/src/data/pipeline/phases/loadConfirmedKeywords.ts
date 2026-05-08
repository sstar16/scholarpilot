/**
 * LoadConfirmedKeywordsPhase — 读用户在 awaiting_keywords 阶段确认/编辑过的 keyword plan
 * 并 merge 进 ctx.queryPlan。
 *
 * 移植自 backend `phases/load_confirmed_keywords.py:17-95`，差异：
 * - 删除 redis 依赖；keyword plan 直接存 round.search_queries_json 的 `keyword_plan` 子字段
 *   （由 RoundOrchestrator.confirmKeywords() 写入）
 * - 走 SQLite roundRepo 读
 * - 用户没确认时（status 不是 awaiting_keywords→searching），返回 null（视同 PRD agentic 输出）
 */
import { getRound } from '@/data/sqlite/repos/roundRepo'

import type { RoundContext } from '../context'
import type { Phase } from '../runner'

import type { PlanQueryOutput } from './planQuery'

export interface LoadConfirmedKeywordsOutput {
  /** key=source, val={complex/medium/simple 三档 query 字符串} */
  perSourceQueries: Record<string, { complex: string; medium: string; simple: string }> | null
  dynamicSynonyms: Record<string, string[]> | null
}

export const loadConfirmedKeywordsPhase: Phase = {
  name: 'load_confirmed_keywords',
  deps: ['plan_query'],
  progressRange: [0.20, 0.21] as const,

  async execute(ctx: RoundContext): Promise<LoadConfirmedKeywordsOutput> {
    const round = await getRound(ctx.roundId)
    const plan = ctx.get<PlanQueryOutput>('plan_query')

    const sq = round?.search_queries
    if (!sq || typeof sq !== 'object') {
      return { perSourceQueries: null, dynamicSynonyms: null }
    }
    const planRecord = sq as Record<string, unknown>
    const kp = planRecord.keyword_plan as Record<string, unknown> | undefined
    if (!kp || !kp.confirmed) {
      return { perSourceQueries: null, dynamicSynonyms: null }
    }

    let perSourceQueries: LoadConfirmedKeywordsOutput['perSourceQueries'] = null
    const sourcePlans = Array.isArray(kp.source_plans) ? (kp.source_plans as Array<Record<string, unknown>>) : []
    if (sourcePlans.length > 0) {
      perSourceQueries = {}
      for (const p of sourcePlans) {
        if (p?.enabled === false) continue
        const sid = String(p.source_id ?? '')
        if (!sid) continue
        perSourceQueries[sid] = {
          complex: String(p.query ?? '').trim(),
          medium: String(p.query_medium ?? '').trim(),
          simple: String(p.query_simple ?? '').trim(),
        }
      }
      if (Object.keys(perSourceQueries).length > 0) {
        // 替换 plan.perSource keys 为用户的 enabled set（verbatim，不做 intersection）
        const replaced: typeof plan.queryPlan.perSource = {}
        for (const sid of Object.keys(perSourceQueries)) {
          replaced[sid] = plan.queryPlan.perSource[sid]
            ?? {
              keywords: perSourceQueries[sid].complex.split(/\s+/).filter((w) => w.length >= 2),
              filters: { ...plan.queryPlan.meta },
            }
        }
        plan.queryPlan.perSource = replaced
      } else {
        perSourceQueries = null
      }
    }

    if (typeof kp.base_query === 'string') {
      plan.queryPlan.meta.baseQuery = kp.base_query
    }
    for (const k of ['year_from', 'year_to', 'language_scope', 'exclude_terms'] as const) {
      if (k in kp) {
        ;(plan.queryPlan.meta as Record<string, unknown>)[
          k === 'language_scope'
            ? 'languageScope'
            : k === 'year_from'
              ? 'yearFrom'
              : k === 'year_to'
                ? 'yearTo'
                : 'excludeTerms'
        ] = kp[k]
      }
    }

    const dynamicSynonyms = kp.synonyms && typeof kp.synonyms === 'object'
      ? (kp.synonyms as Record<string, string[]>)
      : null

    return { perSourceQueries, dynamicSynonyms }
  },
}
