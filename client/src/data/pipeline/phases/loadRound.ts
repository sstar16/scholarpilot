/**
 * LoadRoundPhase — 客户端版，移植自 backend `phases/load_round.py:13-96`。
 *
 * 差异：
 * - 删除 `set_llm_context()`（LLMContext 是 backend BYOK ContextVar，客户端 LLMManager 单例）
 * - 删除 ConversationSession 查询（C5.7 collaboration store 自管 session）
 * - 删除 `mark_round_searching()` —— 直接 roundRepo.upsert
 * - 数据来源：SQLite roundRepo / projectRepo
 *
 * 行为：
 * 1. 从 roundRepo 读 round（roundId 即 ctx.roundId）
 * 2. 从 projectRepo 读 project
 * 3. 标记 round.status = 'searching'（向状态机推进）
 * 4. 解析 search_config 里的 scoring_weights / scoring_cutoff / search_mode
 * 5. emit `round_status` 给 UI
 */
import type { LocalProject, LocalRound } from '@/types/local'
import { getProject } from '@/data/sqlite/repos/projectRepo'
import { getRound, upsertRound } from '@/data/sqlite/repos/roundRepo'

import type { RoundContext } from '../context'
import { PhaseAborted } from '../context'
import type { Phase } from '../runner'

export interface LoadRoundOutput {
  round: LocalRound
  project: LocalProject
  scoringWeights: Record<string, number> | null
  scoringCutoff: number | null
  searchMode: string | null
}

export const loadRoundPhase: Phase = {
  name: 'load_round',
  deps: [],
  progressRange: [0.04, 0.08] as const,

  async execute(ctx: RoundContext): Promise<LoadRoundOutput> {
    const round = await getRound(ctx.roundId)
    if (!round) {
      throw new PhaseAborted('round_not_found', { roundId: ctx.roundId })
    }
    if (round.project_id !== ctx.projectId) {
      throw new PhaseAborted('round_project_mismatch', {
        expected: ctx.projectId,
        actual: round.project_id,
      })
    }

    const project = await getProject(round.project_id)
    if (!project) {
      throw new PhaseAborted('project_not_found', { projectId: round.project_id })
    }

    // 写入第一象限 ctx 字段，便于下游 phase 直接 ctx.project / ctx.round
    ctx.round = round
    ctx.project = project

    // 推 status → 'searching'
    const updated: LocalRound = {
      ...round,
      status: 'searching',
      started_at: round.started_at ?? Date.now(),
      progress: 0.08,
      progress_message: '正在加载用户画像与项目记忆...',
    }
    await upsertRound(updated)
    ctx.round = updated

    // 解析 search_config
    let scoringWeights: Record<string, number> | null = null
    let scoringCutoff: number | null = null
    let searchMode: string | null = null
    if (project.search_config && typeof project.search_config === 'object') {
      const cfg = project.search_config as Record<string, unknown>
      if (cfg.scoring_weights && typeof cfg.scoring_weights === 'object') {
        scoringWeights = cfg.scoring_weights as Record<string, number>
      }
      if (cfg.scoring_cutoff !== undefined) {
        const v = Number(cfg.scoring_cutoff)
        scoringCutoff = Number.isFinite(v) ? v : null
      }
      if (typeof cfg.search_mode === 'string') {
        searchMode = cfg.search_mode
      }
    }

    ctx.eventBus.publish(`round:${ctx.roundId}`, 'round_status', {
      roundId: ctx.roundId,
      status: 'searching',
      progress: 0.08,
      message: '正在加载用户画像与项目记忆...',
    })

    return {
      round: updated,
      project,
      scoringWeights,
      scoringCutoff,
      searchMode,
    }
  },
}
