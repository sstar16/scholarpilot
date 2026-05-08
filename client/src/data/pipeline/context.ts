/**
 * Pipeline RoundContext + control-flow exceptions.
 *
 * 移植自 backend `app/harness/pipeline/types.py`，差异：
 * - 删除 `db: AsyncSession` / `redis` 字段（客户端 repos 直调，不持有 session）
 * - 删除 LLMContext / hook_engine 相关字段
 * - 加入 `eventBus: ClientEventBus`（in-memory）
 * - 加入 `abortSignal: AbortSignal`（用户 cancel 触发）
 * - artifacts 改为 `Map<string, any>`，配合 strict get/set
 */
import type { ClientEventBus } from '../orchestrator/eventBus'

/** 客户端 LLM manager 子集（鸭子类型，方便测试 mock）。 */
export interface LLMManagerLike {
  generate: (
    prompt: string,
    options?: {
      temperature?: number
      max_tokens?: number | null
      response_format?: { type: 'json_object' | 'text' } | null
    },
  ) => Promise<unknown>
  generateStream?: (...args: unknown[]) => unknown
}

/**
 * Mutable context passed to every phase.
 *
 * 第一象限字段（roundId/projectId/llmManager/eventBus/abortSignal）由 orchestrator
 * 在创建 ctx 时填好；其余字段（round/project/...）由 LoadRoundPhase 写入；phase-specific
 * 输出存 `artifacts`，按 `phase.name` 索引。
 */
export interface RoundContext {
  readonly roundId: string
  readonly projectId: string
  readonly llmManager: LLMManagerLike
  readonly eventBus: ClientEventBus
  readonly abortSignal: AbortSignal

  /** Phase 输出缓存（key=phase.name）。 */
  readonly artifacts: Map<string, unknown>

  /** 严格读取上一 phase 的输出。
   *
   *  Throws:
   *    Error — phase 还没跑过（caller 没声明 deps 或运行顺序错乱）
   */
  get<T = unknown>(phaseName: string): T

  /** Soft 检查 phase 是否已产出。 */
  has(phaseName: string): boolean

  /** Phase 内部直接 set（runner 也会在 execute 返回后 set）。 */
  set(phaseName: string, value: unknown): void

  // 由 LoadRoundPhase 写入的常用对象（避免 phase 内部反复 ctx.get('load_round')）
  round?: unknown
  project?: unknown
  /** 项目记忆 markdown 快照（loadMemory 写）。 */
  memorySnapshot?: string
  /** Plan 阶段的最终 query plan（planQuery / loadConfirmedKeywords / applySearchMode 各自更新）。 */
  queryPlan?: unknown
  /** Fetch 阶段返回的 raw docs。 */
  fetchedDocs?: unknown[]
  /** Score 阶段过滤后的 above-cutoff docs。 */
  scoredDocs?: unknown[]
  /** Summary 阶段陆续产出的 summaries。 */
  summaries?: unknown[]
}

export class PhaseSkipped extends Error {
  constructor(message?: string) {
    super(message ?? 'phase skipped')
    this.name = 'PhaseSkipped'
  }
}

export class PhaseAborted extends Error {
  constructor(
    public readonly reason: string,
    public readonly payload: Record<string, unknown> = {},
  ) {
    super(reason)
    this.name = 'PhaseAborted'
  }
}

/** 工厂：构造一个标准 RoundContext。 */
export function createRoundContext(params: {
  roundId: string
  projectId: string
  llmManager: LLMManagerLike
  eventBus: ClientEventBus
  abortSignal: AbortSignal
}): RoundContext {
  const artifacts = new Map<string, unknown>()
  const ctx: RoundContext = {
    roundId: params.roundId,
    projectId: params.projectId,
    llmManager: params.llmManager,
    eventBus: params.eventBus,
    abortSignal: params.abortSignal,
    artifacts,
    get<T = unknown>(phaseName: string): T {
      if (!artifacts.has(phaseName)) {
        throw new Error(
          `phase '${phaseName}' has not produced output yet — `
            + `declare it in deps or check execution order`,
        )
      }
      return artifacts.get(phaseName) as T
    },
    has(phaseName: string): boolean {
      return artifacts.has(phaseName)
    },
    set(phaseName: string, value: unknown): void {
      artifacts.set(phaseName, value)
    },
  }
  return ctx
}
