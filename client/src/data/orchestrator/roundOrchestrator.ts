/**
 * RoundOrchestrator — 客户端版状态机，替代 backend `workers/search_tasks.py:_execute_round_async`。
 *
 * 设计要点：
 * 1. 单例（getInstance），全 app 一个，避免并发争抢
 * 2. per-roundId mutex（`Map<roundId, Promise>`），确保同一 round_id 串行
 * 3. 11 phase 拓扑顺序跑，phase 间通过 ctx.artifacts 共享数据
 * 4. AbortSignal 控制中途 cancel
 * 5. resumeInterrupted：启动时扫 SQLite 找未完成 round（status ∈ pending/searching/scoring/saving/summarizing）
 *
 * 不做的事（vs backend）：
 * - 不调 chord/Celery（Phase B LLMQueue 替代）
 * - 不发 SSE（事件直接走 ctx.eventBus 进程内 emitter）
 * - 不管 Cloudflare Tunnel / nginx
 */
import type { LLMManagerLike } from '../pipeline/context'
import { createRoundContext } from '../pipeline/context'
import { PhaseAborted, PhaseSkipped } from '../pipeline/context'
import { applySearchModePhase } from '../pipeline/phases/applySearchMode'
import { buildDedupPhase } from '../pipeline/phases/buildDedup'
import { dispatchSummariesPhase } from '../pipeline/phases/dispatchSummaries'
import { fetchPhase } from '../pipeline/phases/fetch'
import { loadConfirmedKeywordsPhase } from '../pipeline/phases/loadConfirmedKeywords'
import { loadMemoryPhase } from '../pipeline/phases/loadMemory'
import { loadRoundPhase } from '../pipeline/phases/loadRound'
import { planQueryPhase } from '../pipeline/phases/planQuery'
import { rerankPhase } from '../pipeline/phases/rerank'
import { saveDocsPhase } from '../pipeline/phases/saveDocs'
import { scorePhase } from '../pipeline/phases/score'
import { PhaseRunner, type Phase } from '../pipeline/runner'
import { getDatabase } from '../sqlite/connection'
import { getRound, upsertRound } from '../sqlite/repos/roundRepo'
import type { LocalRound } from '@/types/local'

import { ClientEventBus, getEventBus } from './eventBus'
import { INTERRUPTIBLE_STATUSES, type RoundStatus, isTerminal } from './runState'

/** 默认 11-phase 链。Caller 可通过 setPhases(...) 注入自定义 phase set（测试用）。 */
const DEFAULT_PHASES: ReadonlyArray<Phase> = [
  loadRoundPhase,
  buildDedupPhase,
  loadMemoryPhase,
  planQueryPhase,
  loadConfirmedKeywordsPhase,
  applySearchModePhase,
  fetchPhase,
  rerankPhase,
  scorePhase,
  saveDocsPhase,
  dispatchSummariesPhase,
]

export interface StartRoundParams {
  projectId: string
  roundId: string
  /** 是否由用户主动触发（false=定时推送）。仅日志用。 */
  userTriggered?: boolean
  /** 注入 LLM manager；不传则等价于 caller 必须先 init() llmManager 单例。 */
  llmManager?: LLMManagerLike
}

export interface InterruptedRoundInfo {
  roundId: string
  projectId: string
  lastPhase: string
  status: RoundStatus
  startedAt: number | null
}

export interface ResumePrompt {
  rounds: InterruptedRoundInfo[]
  /** 调 caller 决定每个 round 怎么处理；caller 必须每个 round 都给出 action。 */
  resolve: (decisions: Record<string, 'resume' | 'abandon'>) => Promise<void>
}

export class RoundOrchestrator {
  private static _instance: RoundOrchestrator | null = null

  /** per-roundId 串行 mutex（最后一个 promise 链尾）。 */
  private readonly _mutex = new Map<string, Promise<void>>()
  /** 每个 round 的 AbortController（cancel 用）。 */
  private readonly _aborts = new Map<string, AbortController>()
  /** 注入的 phase 链，默认 11 phase。 */
  private _phases: ReadonlyArray<Phase> = DEFAULT_PHASES
  private readonly _eventBus: ClientEventBus
  private _llmManager: LLMManagerLike | null = null

  private constructor(eventBus?: ClientEventBus) {
    this._eventBus = eventBus ?? getEventBus()
  }

  static getInstance(): RoundOrchestrator {
    if (!RoundOrchestrator._instance) {
      RoundOrchestrator._instance = new RoundOrchestrator()
    }
    return RoundOrchestrator._instance
  }

  /** 测试用：创建一个独立实例，不影响单例。 */
  static _createForTesting(eventBus?: ClientEventBus): RoundOrchestrator {
    return new RoundOrchestrator(eventBus)
  }

  /** 测试用：重置全局单例。 */
  static _resetForTesting(): void {
    RoundOrchestrator._instance = null
  }

  /** 注入 LLM manager（应用 bootstrap 时调一次）。 */
  setLlmManager(llm: LLMManagerLike): void {
    this._llmManager = llm
  }

  /** 测试用：注入自定义 phase 链。 */
  setPhases(phases: ReadonlyArray<Phase>): void {
    this._phases = phases
  }

  /** 重置回默认 11 phase。 */
  resetPhases(): void {
    this._phases = DEFAULT_PHASES
  }

  /**
   * 启动一轮检索（pending → ... → awaiting_feedback）。
   *
   * Mutex：同一 roundId 并发调用 → 第二个 await 第一个完成。
   * 异常：phase 抛 → catch → 标 status='failed'；不 re-throw（让调用方 fire-and-forget 也没事）。
   */
  async startRound(params: StartRoundParams): Promise<void> {
    const { roundId } = params
    if (!roundId) throw new Error('roundId required')

    const previous = this._mutex.get(roundId)
    const next = (previous ?? Promise.resolve()).then(() => this._runRoundOnce(params))
    // 即使失败也更新 mutex 链尾（用 catch+resolve 保 chain 不死锁）
    const guarded = next.catch((e) => {
      console.warn(`[RoundOrchestrator] round ${roundId} run threw:`, e)
    })
    this._mutex.set(roundId, guarded.then(() => {}))
    return guarded
  }

  /** 单次实际跑 phase 链（mutex 内部调用）。 */
  private async _runRoundOnce(params: StartRoundParams): Promise<void> {
    const { roundId, projectId } = params
    const llm = params.llmManager ?? this._llmManager
    if (!llm) {
      throw new Error('llmManager not configured; call setLlmManager() first or pass it in startRound()')
    }

    const ac = new AbortController()
    this._aborts.set(roundId, ac)

    const ctx = createRoundContext({
      roundId,
      projectId,
      llmManager: llm,
      eventBus: this._eventBus,
      abortSignal: ac.signal,
    })

    const runner = new PhaseRunner(this._phases)
    try {
      await runner.run(ctx)
    } catch (e) {
      if (e instanceof PhaseAborted) {
        if (e.reason === 'awaiting_keywords') {
          // Graceful pause: phase already wrote status='awaiting_keywords' to SQLite.
          // Do NOT overwrite with 'cancelled'. Just notify UI to refresh.
          this._eventBus.publish(`round:${roundId}`, 'round_status', {
            roundId,
            status: 'awaiting_keywords',
            progress: 0.20,
            message: '等待用户确认关键词方案',
          })
          return
        }
        await this._markCancelled(roundId, e.reason)
        this._eventBus.publish(`round:${roundId}`, 'round_cancelled', {
          roundId,
          reason: e.reason,
          payload: e.payload,
        })
        return
      }
      if (e instanceof PhaseSkipped) {
        // 极少出现到这里：runner 已经吞 PhaseSkipped；再兜底
        console.warn(`[RoundOrchestrator] PhaseSkipped escaped runner for round ${roundId}`)
        return
      }
      await this._markFailed(roundId, (e as Error).message ?? 'unknown')
      this._eventBus.publish(`round:${roundId}`, 'round_failed', {
        roundId,
        error: (e as Error).message ?? 'unknown',
      })
    } finally {
      this._aborts.delete(roundId)
    }
  }

  /**
   * 用户在 awaiting_keywords 阶段确认/编辑了 keyword plan。
   * 把 plan 写到 round.search_queries_json.keyword_plan，让 LoadConfirmedKeywordsPhase 读到。
   */
  async confirmKeywords(
    roundId: string,
    plan: {
      base_query?: string
      year_from?: number | null
      year_to?: number | null
      language_scope?: string
      exclude_terms?: string[]
      synonyms?: Record<string, string[]>
      source_plans?: Array<{
        source_id: string
        enabled?: boolean
        query?: string
        query_medium?: string
        query_simple?: string
      }>
    },
  ): Promise<void> {
    const round = await getRound(roundId)
    if (!round) throw new Error(`round ${roundId} not found`)
    const sq = (round.search_queries && typeof round.search_queries === 'object'
      ? { ...(round.search_queries as Record<string, unknown>) }
      : {}) as Record<string, unknown>
    sq.keyword_plan = { ...plan, confirmed: true }
    await upsertRound({
      ...round,
      status: 'searching' as RoundStatus,
      search_queries: sq,
    })
    this._eventBus.publish(`round:${roundId}`, 'round_status', {
      roundId,
      status: 'searching',
      progress: 0.21,
      message: '已确认 keywords，开始检索...',
    })
  }

  /** 取消一轮检索：abort 所有 phase，标 status='cancelled'。 */
  async cancelRound(roundId: string, reason = 'user_cancelled'): Promise<void> {
    const ac = this._aborts.get(roundId)
    if (ac) ac.abort()
    await this._markCancelled(roundId, reason)
    this._eventBus.publish(`round:${roundId}`, 'round_cancelled', {
      roundId,
      reason,
    })
  }

  /**
   * 应用启动时调一次：扫 SQLite 找未完成 round，返回 ResumePrompt 让 UI 弹 dialog。
   *
   * UI flow：
   * 1. await orchestrator.resumeInterrupted() → 拿到 InterruptedRoundInfo[]
   * 2. ElDialog 列出每个 round，让用户选 [继续 | 放弃]
   * 3. 调 prompt.resolve({ roundId: 'resume' | 'abandon', ... })
   * 4. orchestrator 内部对每个 round：resume → startRound；abandon → markCancelled('user_resumed_abandoned')
   */
  async resumeInterrupted(): Promise<ResumePrompt> {
    const db = getDatabase()
    const placeholders = [...INTERRUPTIBLE_STATUSES].map(() => '?').join(',')
    const rows = await db.select<{
      id: string
      project_id: string
      status: string
      started_at: number | null
      progress_message: string
    }>(
      `SELECT id, project_id, status, started_at, progress_message
         FROM search_rounds
        WHERE status IN (${placeholders})
        ORDER BY started_at DESC NULLS LAST, id DESC`,
      [...INTERRUPTIBLE_STATUSES],
    )

    const rounds: InterruptedRoundInfo[] = rows.map((r) => ({
      roundId: r.id,
      projectId: r.project_id,
      status: r.status as RoundStatus,
      lastPhase: r.progress_message ?? r.status,
      startedAt: r.started_at,
    }))

    return {
      rounds,
      resolve: async (decisions) => {
        for (const info of rounds) {
          const action = decisions[info.roundId]
          if (action === 'resume') {
            await this.startRound({
              roundId: info.roundId,
              projectId: info.projectId,
              userTriggered: false,
            })
          } else if (action === 'abandon') {
            await this._markCancelled(info.roundId, 'user_resumed_abandoned')
            this._eventBus.publish(`round:${info.roundId}`, 'round_cancelled', {
              roundId: info.roundId,
              reason: 'user_resumed_abandoned',
            })
          }
          // 没决策 → 不动；下次启动还会再问
        }
      },
    }
  }

  // ─────────────── 内部状态写库 ───────────────

  private async _markCancelled(roundId: string, reason: string): Promise<void> {
    const r = await getRound(roundId)
    if (!r || isTerminal(r.status as RoundStatus)) return
    const updated: LocalRound = {
      ...r,
      status: 'cancelled',
      cancelled_reason: reason,
      cancelled_at: Date.now(),
    }
    await upsertRound(updated)
  }

  private async _markFailed(roundId: string, errorMessage: string): Promise<void> {
    const r = await getRound(roundId)
    if (!r || isTerminal(r.status as RoundStatus)) return
    const updated: LocalRound = {
      ...r,
      status: 'failed',
      progress_message: `failed: ${errorMessage.slice(0, 200)}`,
      completed_at: Date.now(),
    }
    await upsertRound(updated)
  }
}

/** 单例便捷入口。 */
export function getRoundOrchestrator(): RoundOrchestrator {
  return RoundOrchestrator.getInstance()
}
