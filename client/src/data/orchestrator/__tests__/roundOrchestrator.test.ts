/**
 * RoundOrchestrator 单测 — 验证：
 *   1. happy path：注入 mock phase 链跑通 pending → complete
 *   2. mutex：同 roundId 并发 startRound → 串行执行（第二个等第一个）
 *   3. cancelRound：phase 间检 abortSignal 抛 PhaseAborted → 标 cancelled
 *   4. phase 异常 → 标 status='failed' 写库
 *   5. resumeInterrupted：mock SQLite 返中断 round 列表
 *   6. confirmKeywords：写 search_queries.keyword_plan 并标 status=searching
 *
 * Mock 策略：
 * - SQLite 用 better-sqlite3 in-memory (符合 vitest 环境)
 * - Phase 链通过 setPhases() 注入 mock，不跑真实 11 phase
 * - LLMManager 注入空 mock（phase 不调）
 */
import Database from 'better-sqlite3'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import { ClientEventBus, _resetEventBusForTesting } from '../eventBus'
import { RoundOrchestrator } from '../roundOrchestrator'
import { setTestDb } from '@/data/sqlite/connection'
import type { DbHandle } from '@/data/sqlite/schema'
import type { LocalRound } from '@/types/local'
import type { Phase } from '@/data/pipeline/runner'
import { PhaseAborted } from '@/data/pipeline/context'
import { upsertRound, getRound } from '@/data/sqlite/repos/roundRepo'

// ─────────────── DB Setup ───────────────

const SCHEMA_SQL = `
CREATE TABLE search_rounds (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  round_number INTEGER NOT NULL,
  status TEXT NOT NULL,
  time_horizon_years INTEGER,
  max_results INTEGER NOT NULL DEFAULT 10,
  language_scope TEXT NOT NULL DEFAULT 'international',
  sources_used_json TEXT,
  search_queries_json TEXT,
  total_candidates INTEGER NOT NULL DEFAULT 0,
  selected_count INTEGER NOT NULL DEFAULT 0,
  source_stats_json TEXT,
  progress REAL NOT NULL DEFAULT 0,
  progress_message TEXT NOT NULL DEFAULT '',
  started_at INTEGER,
  completed_at INTEGER,
  cancelled_reason TEXT,
  cancelled_at INTEGER,
  partial_answer_json TEXT,
  partial_completed_at INTEGER,
  created_at INTEGER NOT NULL,
  last_synced_at INTEGER
);
`

function mkBetterSqliteHandle(): DbHandle & { _raw: Database.Database } {
  const raw = new Database(':memory:')
  raw.exec(SCHEMA_SQL)
  return {
    _raw: raw,
    async select<T = unknown>(sql: string, bindings: unknown[] = []): Promise<T[]> {
      const stmt = raw.prepare(sql)
      return stmt.all(...bindings) as T[]
    },
    async execute(sql: string, bindings: unknown[] = []) {
      const stmt = raw.prepare(sql)
      const r = stmt.run(...bindings)
      return { rowsAffected: r.changes, lastInsertId: Number(r.lastInsertRowid) }
    },
    async close() {
      raw.close()
    },
  }
}

function mkRound(id: string, projectId: string, status = 'pending'): LocalRound {
  return {
    id,
    project_id: projectId,
    round_number: 1,
    status,
    time_horizon_years: null,
    max_results: 10,
    language_scope: 'international',
    sources_used: null,
    search_queries: null,
    total_candidates: 0,
    selected_count: 0,
    source_stats: null,
    progress: 0,
    progress_message: '',
    started_at: null,
    completed_at: null,
    cancelled_reason: null,
    cancelled_at: null,
    partial_answer: null,
    partial_completed_at: null,
    created_at: Date.now(),
    last_synced_at: null,
  }
}

let dbHandle: ReturnType<typeof mkBetterSqliteHandle>
let bus: ClientEventBus

beforeEach(async () => {
  dbHandle = mkBetterSqliteHandle()
  setTestDb(dbHandle)
  bus = new ClientEventBus()
  RoundOrchestrator._resetForTesting()
  _resetEventBusForTesting()
})

afterEach(async () => {
  await dbHandle.close()
  setTestDb(null)
  RoundOrchestrator._resetForTesting()
})

// ─────────────── Tests ───────────────

describe('RoundOrchestrator.startRound — phase pipeline', () => {
  it('happy path: 跑通注入的 mock 3-phase 链', async () => {
    const orch = RoundOrchestrator._createForTesting(bus)
    orch.setLlmManager({ generate: async () => null } as never)

    const order: string[] = []
    const phaseA: Phase = {
      name: 'a', deps: [], progressRange: [0, 0.5],
      execute: async () => { order.push('a'); return { ok: 1 } },
    }
    const phaseB: Phase = {
      name: 'b', deps: ['a'], progressRange: [0.5, 1],
      execute: async () => { order.push('b'); return { ok: 2 } },
    }
    orch.setPhases([phaseA, phaseB])

    await upsertRound(mkRound('r1', 'p1'))
    await orch.startRound({ roundId: 'r1', projectId: 'p1' })

    expect(order).toEqual(['a', 'b'])
  })

  it('phase 异常 → status=failed 写库 + emit round_failed', async () => {
    const orch = RoundOrchestrator._createForTesting(bus)
    orch.setLlmManager({ generate: async () => null } as never)
    const failPhase: Phase = {
      name: 'fail', deps: [], progressRange: [0, 1],
      execute: async () => { throw new Error('boom') },
    }
    orch.setPhases([failPhase])
    await upsertRound(mkRound('r1', 'p1'))

    const events: string[] = []
    bus.subscribe('round:r1', (e) => events.push(e.event))

    await orch.startRound({ roundId: 'r1', projectId: 'p1' })
    const r = await getRound('r1')
    expect(r?.status).toBe('failed')
    expect(r?.progress_message).toMatch(/boom/)
    expect(events).toContain('round_failed')
  })

  it('PhaseAborted → status=cancelled', async () => {
    const orch = RoundOrchestrator._createForTesting(bus)
    orch.setLlmManager({ generate: async () => null } as never)
    const abortPhase: Phase = {
      name: 'abort', deps: [], progressRange: [0, 1],
      execute: async () => { throw new PhaseAborted('user_request', { x: 1 }) },
    }
    orch.setPhases([abortPhase])
    await upsertRound(mkRound('r1', 'p1'))

    const events: string[] = []
    bus.subscribe('round:r1', (e) => events.push(e.event))

    await orch.startRound({ roundId: 'r1', projectId: 'p1' })
    const r = await getRound('r1')
    expect(r?.status).toBe('cancelled')
    expect(r?.cancelled_reason).toBe('user_request')
    expect(events).toContain('round_cancelled')
  })

  it('llmManager 缺失抛错', async () => {
    const orch = RoundOrchestrator._createForTesting(bus)
    orch.setPhases([])
    await upsertRound(mkRound('r1', 'p1'))
    // startRound 内部 catch 错误并 log，不再 reject；通过 status 验证
    await orch.startRound({ roundId: 'r1', projectId: 'p1' })
    // round 还是 pending，因为 _runRoundOnce 抛在进 runner 之前
    const r = await getRound('r1')
    expect(r?.status).toBe('pending')
  })
})

describe('RoundOrchestrator mutex', () => {
  it('同 roundId 并发 startRound → 第二个等第一个完成', async () => {
    const orch = RoundOrchestrator._createForTesting(bus)
    orch.setLlmManager({ generate: async () => null } as never)

    let inflight = 0
    let maxInflight = 0
    const slowPhase: Phase = {
      name: 's', deps: [], progressRange: [0, 1],
      execute: async () => {
        inflight++
        maxInflight = Math.max(maxInflight, inflight)
        await new Promise((r) => setTimeout(r, 30))
        inflight--
        return null
      },
    }
    orch.setPhases([slowPhase])
    await upsertRound(mkRound('r1', 'p1'))

    // 并发触发 3 次同 roundId
    const p1 = orch.startRound({ roundId: 'r1', projectId: 'p1' })
    const p2 = orch.startRound({ roundId: 'r1', projectId: 'p1' })
    const p3 = orch.startRound({ roundId: 'r1', projectId: 'p1' })
    await Promise.all([p1, p2, p3])

    // 串行 → 任意时刻最多 1 个 phase 在跑
    expect(maxInflight).toBe(1)
  })

  it('不同 roundId 不互相阻塞', async () => {
    const orch = RoundOrchestrator._createForTesting(bus)
    orch.setLlmManager({ generate: async () => null } as never)

    let inflight = 0
    let maxInflight = 0
    const slowPhase: Phase = {
      name: 's', deps: [], progressRange: [0, 1],
      execute: async () => {
        inflight++
        maxInflight = Math.max(maxInflight, inflight)
        await new Promise((r) => setTimeout(r, 30))
        inflight--
        return null
      },
    }
    orch.setPhases([slowPhase])
    await upsertRound(mkRound('r1', 'p1'))
    await upsertRound(mkRound('r2', 'p1'))

    await Promise.all([
      orch.startRound({ roundId: 'r1', projectId: 'p1' }),
      orch.startRound({ roundId: 'r2', projectId: 'p1' }),
    ])
    expect(maxInflight).toBeGreaterThanOrEqual(2)
  })
})

describe('RoundOrchestrator.cancelRound', () => {
  it('运行中 cancel 标 cancelled', async () => {
    const orch = RoundOrchestrator._createForTesting(bus)
    orch.setLlmManager({ generate: async () => null } as never)

    let started = false
    const slowPhase: Phase = {
      name: 's', deps: [], progressRange: [0, 0.5],
      execute: async () => {
        started = true
        await new Promise((r) => setTimeout(r, 100))
        return null
      },
    }
    const followPhase: Phase = {
      name: 'f', deps: ['s'], progressRange: [0.5, 1],
      execute: async () => null,
    }
    orch.setPhases([slowPhase, followPhase])
    await upsertRound(mkRound('r1', 'p1'))

    const runP = orch.startRound({ roundId: 'r1', projectId: 'p1' })
    // wait until slow phase starts
    await vi.waitFor(() => expect(started).toBe(true), { timeout: 500, interval: 5 })
    await orch.cancelRound('r1', 'mid_flight')
    await runP
    const r = await getRound('r1')
    expect(r?.status).toBe('cancelled')
    expect(r?.cancelled_reason).toMatch(/mid_flight|user_cancelled/)
  })
})

describe('RoundOrchestrator.confirmKeywords', () => {
  it('写 search_queries.keyword_plan 并标 status=searching', async () => {
    const orch = RoundOrchestrator._createForTesting(bus)
    await upsertRound({ ...mkRound('r1', 'p1', 'awaiting_keywords') })

    await orch.confirmKeywords('r1', {
      base_query: 'AI healthcare',
      year_from: 2020,
      year_to: 2026,
      source_plans: [{ source_id: 'arxiv', enabled: true, query: 'AI healthcare' }],
    })
    const r = await getRound('r1')
    expect(r?.status).toBe('searching')
    expect((r?.search_queries as Record<string, unknown>)?.keyword_plan).toMatchObject({
      base_query: 'AI healthcare',
      year_from: 2020,
      confirmed: true,
    })
  })

  it('round 不存在抛错', async () => {
    const orch = RoundOrchestrator._createForTesting(bus)
    await expect(orch.confirmKeywords('ghost', {})).rejects.toThrowError(/not found/)
  })
})

describe('RoundOrchestrator.resumeInterrupted', () => {
  it('扫到 pending/searching/scoring 等中断 round', async () => {
    const orch = RoundOrchestrator._createForTesting(bus)
    await upsertRound({ ...mkRound('r1', 'p1', 'searching'), started_at: 1000 })
    await upsertRound({ ...mkRound('r2', 'p1', 'scoring'), started_at: 2000 })
    await upsertRound({ ...mkRound('r3', 'p1', 'complete') })
    await upsertRound({ ...mkRound('r4', 'p1', 'awaiting_feedback') }) // 不算 interrupted

    const prompt = await orch.resumeInterrupted()
    const ids = prompt.rounds.map((r) => r.roundId).sort()
    expect(ids).toEqual(['r1', 'r2'])
  })

  it('resolve abandon → status=cancelled, reason=user_resumed_abandoned', async () => {
    const orch = RoundOrchestrator._createForTesting(bus)
    await upsertRound({ ...mkRound('r1', 'p1', 'searching') })

    const prompt = await orch.resumeInterrupted()
    expect(prompt.rounds.length).toBe(1)
    await prompt.resolve({ r1: 'abandon' })

    const r = await getRound('r1')
    expect(r?.status).toBe('cancelled')
    expect(r?.cancelled_reason).toBe('user_resumed_abandoned')
  })
})
