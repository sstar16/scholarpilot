/**
 * Round 状态机定义 + 合法 transition 表。
 *
 * 与 backend `app/models/search_round.py` 的 status 枚举大体对齐，但删除了 `partial_complete`
 * （Answer Now 在 Phase C 决策 10 中删除）。
 *
 * 状态：
 *  - pending             : orchestrator 刚 INSERT，准备 pickup
 *  - awaiting_keywords   : PlanQueryPhase 出 query_plan，等用户确认
 *  - searching           : LoadConfirmedKeywords 后开始 fetch
 *  - scoring             : Rerank/Score phase
 *  - saving              : SaveDocs phase（短暂中间态）
 *  - summarizing         : DispatchSummaries phase
 *  - awaiting_feedback   : 摘要全部 ready，等用户 4-bucket 反馈
 *  - complete            : 用户 feedback 提交完毕（终态）
 *  - failed              : 任何 phase 异常未恢复（终态）
 *  - cancelled           : 用户主动取消 / 启动恢复时弃疗（终态）
 */

export type RoundStatus =
  | 'pending'
  | 'awaiting_keywords'
  | 'searching'
  | 'scoring'
  | 'saving'
  | 'summarizing'
  | 'awaiting_feedback'
  | 'complete'
  | 'failed'
  | 'cancelled'

/** 终态：进入后 round 不再变化。 */
export const TERMINAL_STATUSES: ReadonlySet<RoundStatus> = new Set<RoundStatus>([
  'complete',
  'failed',
  'cancelled',
])

/** 中断恢复时被认为「未完成」的状态（启动 dialog 用）。 */
export const INTERRUPTIBLE_STATUSES: ReadonlySet<RoundStatus> = new Set<RoundStatus>([
  'pending',
  'awaiting_keywords',
  'searching',
  'scoring',
  'saving',
  'summarizing',
])

/** 允许的状态 transition 表。
 *
 *  对应 plan §3.1 transition 表（删除了 `partial_complete` 行）。
 */
const ALLOWED: Record<RoundStatus, ReadonlyArray<RoundStatus>> = {
  pending: ['awaiting_keywords', 'searching', 'failed', 'cancelled'],
  awaiting_keywords: ['searching', 'failed', 'cancelled'],
  searching: ['scoring', 'awaiting_feedback', 'failed', 'cancelled'],
  scoring: ['saving', 'awaiting_feedback', 'failed', 'cancelled'],
  saving: ['summarizing', 'awaiting_feedback', 'failed', 'cancelled'],
  summarizing: ['awaiting_feedback', 'failed', 'cancelled'],
  awaiting_feedback: ['complete', 'failed', 'cancelled'],
  complete: [],
  failed: [],
  cancelled: [],
}

export function isTransitionAllowed(from: RoundStatus, to: RoundStatus): boolean {
  if (from === to) return true // idempotent
  return (ALLOWED[from] ?? []).includes(to)
}

/** Throws if transition not allowed. */
export function assertTransition(from: RoundStatus, to: RoundStatus): void {
  if (!isTransitionAllowed(from, to)) {
    throw new Error(`illegal round transition: ${from} → ${to}`)
  }
}

export function isTerminal(status: RoundStatus): boolean {
  return TERMINAL_STATUSES.has(status)
}

export function isInterruptible(status: RoundStatus): boolean {
  return INTERRUPTIBLE_STATUSES.has(status)
}
