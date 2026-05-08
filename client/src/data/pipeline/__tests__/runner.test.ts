/**
 * PhaseRunner 单测 — 验证：
 *   1. 拓扑排序：按 deps 顺序执行
 *   2. cycle 检测抛错
 *   3. unknown dep 抛错
 *   4. duplicate name 抛错
 *   5. skipIf=true 跳过 phase
 *   6. PhaseSkipped 异常等价于 skipIf
 *   7. PhaseAborted re-throw
 *   8. 普通异常 re-throw
 *   9. abortSignal.aborted=true → 下一 phase 抛 PhaseAborted
 *   10. 每个 phase 开始/结束 emit round_status 事件
 */
import { describe, it, expect, vi } from 'vitest'

import {
  PhaseAborted,
  PhaseSkipped,
  createRoundContext,
} from '../context'
import { ClientEventBus } from '../../orchestrator/eventBus'
import { PhaseRunner, type Phase } from '../runner'

function mkCtx(opts?: { aborted?: boolean }) {
  const ac = new AbortController()
  if (opts?.aborted) ac.abort()
  const bus = new ClientEventBus()
  const ctx = createRoundContext({
    roundId: 'r1',
    projectId: 'p1',
    llmManager: { generate: async () => null } as never,
    eventBus: bus,
    abortSignal: ac.signal,
  })
  return { ctx, ac, bus }
}

function mkPhase(name: string, deps: string[], execute: Phase['execute'], opts?: Partial<Phase>): Phase {
  return {
    name,
    deps,
    progressRange: opts?.progressRange ?? [0, 1],
    skipIf: opts?.skipIf,
    execute,
  }
}

describe('PhaseRunner topology', () => {
  it('按 deps 顺序执行', async () => {
    const order: string[] = []
    const a = mkPhase('a', [], async () => { order.push('a'); return { v: 1 } })
    const b = mkPhase('b', ['a'], async () => { order.push('b'); return { v: 2 } })
    const c = mkPhase('c', ['a', 'b'], async () => { order.push('c'); return { v: 3 } })

    const runner = new PhaseRunner([c, b, a])
    const { ctx } = mkCtx()
    await runner.run(ctx)
    expect(order).toEqual(['a', 'b', 'c'])
    expect(ctx.get('c')).toEqual({ v: 3 })
  })

  it('cycle 检测抛错', () => {
    const a = mkPhase('a', ['b'], async () => null)
    const b = mkPhase('b', ['a'], async () => null)
    expect(() => new PhaseRunner([a, b])).toThrowError(/cycle detected/)
  })

  it('unknown dep 抛错', () => {
    const a = mkPhase('a', ['ghost'], async () => null)
    expect(() => new PhaseRunner([a])).toThrowError(/depends on unknown phase/)
  })

  it('duplicate name 抛错', () => {
    const a = mkPhase('a', [], async () => null)
    const a2 = mkPhase('a', [], async () => null)
    expect(() => new PhaseRunner([a, a2])).toThrowError(/duplicate phase name/)
  })

  it('空 phase 数组 → run() 直接 resolve', async () => {
    const runner = new PhaseRunner([])
    const { ctx } = mkCtx()
    await expect(runner.run(ctx)).resolves.toBeDefined()
  })
})

describe('PhaseRunner skip / abort', () => {
  it('skipIf=true 跳过 phase（artifact 设为 null）', async () => {
    const exec = vi.fn(async () => ({ ran: true }))
    const a = mkPhase('a', [], exec, { skipIf: () => true })
    const runner = new PhaseRunner([a])
    const { ctx } = mkCtx()
    await runner.run(ctx)
    expect(exec).not.toHaveBeenCalled()
    expect(ctx.get('a')).toBeNull()
  })

  it('PhaseSkipped 异常等价于 skipIf=true', async () => {
    const a = mkPhase('a', [], async () => { throw new PhaseSkipped('not needed') })
    const runner = new PhaseRunner([a])
    const { ctx } = mkCtx()
    await runner.run(ctx)
    expect(ctx.get('a')).toBeNull()
  })

  it('skipIf 异步返 true', async () => {
    const exec = vi.fn(async () => ({ ran: true }))
    const a = mkPhase('a', [], exec, { skipIf: async () => true })
    const runner = new PhaseRunner([a])
    const { ctx } = mkCtx()
    await runner.run(ctx)
    expect(exec).not.toHaveBeenCalled()
  })

  it('PhaseAborted re-throw', async () => {
    const a = mkPhase('a', [], async () => { throw new PhaseAborted('bad', { x: 1 }) })
    const runner = new PhaseRunner([a])
    const { ctx } = mkCtx()
    await expect(runner.run(ctx)).rejects.toBeInstanceOf(PhaseAborted)
  })

  it('普通异常 re-throw', async () => {
    const a = mkPhase('a', [], async () => { throw new Error('oops') })
    const runner = new PhaseRunner([a])
    const { ctx } = mkCtx()
    await expect(runner.run(ctx)).rejects.toThrowError('oops')
  })

  it('abortSignal.aborted=true → 抛 PhaseAborted user_cancelled', async () => {
    const a = mkPhase('a', [], async () => null)
    const runner = new PhaseRunner([a])
    const { ctx } = mkCtx({ aborted: true })
    await expect(runner.run(ctx)).rejects.toBeInstanceOf(PhaseAborted)
  })
})

describe('PhaseRunner events', () => {
  it('每个 phase 开始/结束 emit round_status', async () => {
    const a = mkPhase('a', [], async () => ({ v: 1 }), { progressRange: [0, 0.5] })
    const b = mkPhase('b', ['a'], async () => ({ v: 2 }), { progressRange: [0.5, 1] })
    const runner = new PhaseRunner([a, b])
    const { ctx, bus } = mkCtx()
    const fn = vi.fn()
    bus.subscribe(`round:${ctx.roundId}`, fn)
    await runner.run(ctx)
    // 4 events: start-a, end-a, start-b, end-b
    expect(fn).toHaveBeenCalledTimes(4)
    const progresses = fn.mock.calls.map((c) => c[0].data.progress)
    expect(progresses).toEqual([0, 0.5, 0.5, 1])
  })
})

describe('RoundContext', () => {
  it('get 缺失 phase 抛错', () => {
    const { ctx } = mkCtx()
    expect(() => ctx.get('missing')).toThrowError(/has not produced output yet/)
  })

  it('has / set / get 互通', () => {
    const { ctx } = mkCtx()
    expect(ctx.has('a')).toBe(false)
    ctx.set('a', { x: 1 })
    expect(ctx.has('a')).toBe(true)
    expect(ctx.get('a')).toEqual({ x: 1 })
  })
})
