/**
 * PhaseRunner — 客户端版，移植自 backend `app/harness/pipeline/runner.py`。
 *
 * 差异：
 * - 删除 Answer Now `can_interrupt` 检查（PRD 决策 10）
 * - 删除 HookEngine fire（hook_engine 是 backend 概念）
 * - 删除 SSE EventBus.publish_sync；progress 事件通过 ctx.eventBus 发到客户端 in-memory bus
 * - 用 AbortSignal 替代 Answer Now：phase 间检查 abortSignal.aborted 决定是否中断
 *
 * 行为：
 * 1. 构造时拓扑排序（Kahn 算法 + cycle detection）
 * 2. 依次执行每个 phase
 * 3. phase.skipIf(ctx) → true 直接跳过（不抛异常更声明式）
 * 4. PhaseSkipped 异常等价于 skipIf=true
 * 5. PhaseAborted 异常 → re-throw 让 caller 决定是否标 failed
 * 6. 其它异常 → re-throw 让 caller 标 failed
 * 7. 每个 phase 开始/结束 emit `round_status` 事件（progress 取自 progressRange）
 */
import {
  PhaseAborted,
  PhaseSkipped,
  type RoundContext,
} from './context'

export interface Phase {
  readonly name: string
  readonly deps: readonly string[]
  /** [start, end] ∈ [0, 1]，phase 开始/结束时分别 publish progress。 */
  readonly progressRange: readonly [number, number]
  /** 可选：声明式跳过条件，runner 在 execute 前调（同步或异步皆可）。 */
  skipIf?: (ctx: RoundContext) => boolean | Promise<boolean>
  /** 主逻辑。返回值会被 runner 写到 `ctx.artifacts[name]`。 */
  execute: (ctx: RoundContext) => Promise<unknown>
}

export class PhaseRunner {
  private readonly _phases: ReadonlyArray<Phase>

  constructor(phases: ReadonlyArray<Phase>) {
    this._phases = PhaseRunner._topoSort(phases)
  }

  get phases(): ReadonlyArray<Phase> {
    return this._phases
  }

  /** Kahn 拓扑排序，含 cycle / unknown-dep / duplicate-name 检测。 */
  private static _topoSort(phases: ReadonlyArray<Phase>): ReadonlyArray<Phase> {
    if (phases.length === 0) return []

    const byName = new Map<string, Phase>()
    for (const p of phases) {
      if (byName.has(p.name)) {
        throw new Error(`duplicate phase name: '${p.name}'`)
      }
      byName.set(p.name, p)
    }

    const indeg = new Map<string, number>()
    const graph = new Map<string, string[]>()
    for (const p of phases) {
      indeg.set(p.name, 0)
      graph.set(p.name, [])
    }
    for (const p of phases) {
      for (const d of p.deps) {
        if (!byName.has(d)) {
          throw new Error(`phase '${p.name}' depends on unknown phase '${d}'`)
        }
        graph.get(d)!.push(p.name)
        indeg.set(p.name, (indeg.get(p.name) ?? 0) + 1)
      }
    }

    const ready: string[] = []
    for (const [n, k] of indeg.entries()) if (k === 0) ready.push(n)

    const order: Phase[] = []
    while (ready.length > 0) {
      const n = ready.shift()!
      order.push(byName.get(n)!)
      for (const m of graph.get(n) ?? []) {
        const next = (indeg.get(m) ?? 0) - 1
        indeg.set(m, next)
        if (next === 0) ready.push(m)
      }
    }
    if (order.length !== phases.length) {
      const unresolved = [...indeg.entries()]
        .filter(([, k]) => k > 0)
        .map(([n]) => n)
      throw new Error(`cycle detected involving phases: [${unresolved.join(', ')}]`)
    }
    return order
  }

  /**
   * 顺序执行所有 phase。
   *
   * @throws PhaseAborted — runner 不吞，caller 决定是否标 failed
   * @throws Error — 任何 phase 抛非 PhaseSkipped 异常
   */
  async run(ctx: RoundContext): Promise<RoundContext> {
    for (const p of this._phases) {
      if (ctx.abortSignal.aborted) {
        throw new PhaseAborted('user_cancelled', { stage: p.name })
      }

      // 声明式跳过
      if (await PhaseRunner._shouldSkip(p, ctx)) {
        ctx.set(p.name, null)
        this._publishProgress(ctx, p, 'start')
        this._publishProgress(ctx, p, 'end')
        continue
      }

      this._publishProgress(ctx, p, 'start')

      let output: unknown
      try {
        output = await p.execute(ctx)
      } catch (e) {
        if (e instanceof PhaseSkipped) {
          ctx.set(p.name, null)
          this._publishProgress(ctx, p, 'end')
          continue
        }
        // PhaseAborted / 其它异常 → re-throw
        throw e
      }

      ctx.set(p.name, output)
      this._publishProgress(ctx, p, 'end')
    }
    return ctx
  }

  private static async _shouldSkip(phase: Phase, ctx: RoundContext): Promise<boolean> {
    if (!phase.skipIf) return false
    try {
      const r = phase.skipIf(ctx)
      if (r && typeof (r as Promise<boolean>).then === 'function') {
        return Boolean(await r)
      }
      return Boolean(r)
    } catch (e) {
      console.warn(
        `[PhaseRunner] ${phase.name}.skipIf() raised ${(e as Error).message}; running phase as fallback`,
      )
      return false
    }
  }

  private _publishProgress(ctx: RoundContext, phase: Phase, edge: 'start' | 'end'): void {
    const [start, end] = phase.progressRange
    const progress = edge === 'start' ? start : end
    try {
      ctx.eventBus.publish(`round:${ctx.roundId}`, 'round_status', {
        roundId: ctx.roundId,
        status: phase.name,
        progress: Math.round(progress * 1000) / 1000,
        message: `${phase.name} ${edge}`,
      })
    } catch (e) {
      // event 发不出来不能挂主流程
      console.warn('[PhaseRunner] eventBus.publish failed:', e)
    }
  }
}
