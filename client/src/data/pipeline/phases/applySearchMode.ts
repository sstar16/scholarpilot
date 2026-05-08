/**
 * ApplySearchModePhase — 根据 project.search_config.search_mode 缩窄 query_plan.perSource：
 *   - static_db : 客户端没有 local_kb，直接 fail
 *   - api       : 过滤掉 local_kb 源
 *   - hybrid    : 保留全部（local_kb 由 caller verbatim 决定）
 *
 * 移植自 backend `phases/apply_search_mode.py:12-44`，差异：
 * - local_kb 在客户端不可用，static_db 模式直接抛 PhaseAborted
 */
import type { RoundContext } from '../context'
import { PhaseAborted } from '../context'
import type { Phase } from '../runner'

import type { LoadConfirmedKeywordsOutput } from './loadConfirmedKeywords'
import type { LoadRoundOutput } from './loadRound'
import type { PlanQueryOutput } from './planQuery'

export interface ApplySearchModeOutput {
  finalSources: string[]
}

export const applySearchModePhase: Phase = {
  name: 'apply_search_mode',
  deps: ['plan_query', 'load_confirmed_keywords'],
  progressRange: [0.21, 0.22] as const,

  async execute(ctx: RoundContext): Promise<ApplySearchModeOutput> {
    const planOut = ctx.get<PlanQueryOutput>('plan_query')
    const loaded = ctx.get<LoadRoundOutput>('load_round')
    const confirmed = ctx.get<LoadConfirmedKeywordsOutput>('load_confirmed_keywords')
    const queryPlan = planOut.queryPlan
    const searchMode = loaded.searchMode

    const sources = Object.keys(queryPlan.perSource)

    let final: string[]
    if (searchMode === 'static_db') {
      throw new PhaseAborted('static_db_unavailable_in_client', {
        message: 'static_db 模式依赖 local_kb，客户端不支持。请改用 api 或 hybrid。',
      })
    } else if (searchMode === 'api') {
      final = sources.filter((s) => s !== 'local_kb')
    } else {
      // hybrid / null
      // hybrid: 客户端通常无 local_kb，verbatim 用户选择即可
      final = [...sources]
      if (!confirmed.perSourceQueries && searchMode === 'hybrid' && !final.includes('local_kb')) {
        // 仅 legacy 路径自动注入 local_kb（客户端跳过，保留行为对齐）
        // do nothing — client 没 local_kb
      }
    }

    // 写回 perSource：仅保留 final 里的 keys
    const filtered: typeof queryPlan.perSource = {}
    for (const s of final) {
      if (queryPlan.perSource[s]) filtered[s] = queryPlan.perSource[s]
    }
    queryPlan.perSource = filtered
    ctx.queryPlan = queryPlan

    return { finalSources: final }
  },
}
