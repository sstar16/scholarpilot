/**
 * ScoringAgent 单测 — 7+ 用例覆盖任务规范要求：
 *  1. happy path：30 篇 mock score → above + below 正确分桶
 *  2. LLM JSON malformed → retry → fallback default score
 *  3. LLMQueue resume 行为（mock job state pending → resume() 续跑）
 *  4. onProgress 回调被调用
 *  5. 边界：empty docs 数组 → 返 {above:[], below:[]}
 *  6. 边界：cutoff=0 → 全 above；cutoff=100 → 全 below
 *  7. parseScoringResponse 单元（直接测 helper）
 *  8. 自动分桶映射（80/60/40 阈值）
 *
 * Mock 策略：
 * - LLM 用 vi.fn() 注入到 ScoringAgent 构造参数
 * - LLMQueue 用真实 class + in-memory MockDb（参考 concurrent_queue.test.ts）
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LLMQueue } from '../../llm/concurrent_queue'
import {
  ScoringAgent,
  parseScoringResponse,
  type LLMLike,
  type ScoreInput,
  type ScoreOutput,
} from '../scoringAgent'

// ── In-memory mock SQLite ──────────────────────────────────────────────

interface Row {
  job_id: string
  run_id: string
  doc_id: string | null
  agent_kind: string
  prompt_hash: string
  status: 'pending' | 'running' | 'done' | 'failed'
  result_json: string | null
  error_message: string | null
  retried_count: number
  schema_version: number
  created_at: number
  updated_at: number
}

class MockDb {
  rows = new Map<string, Row>()

  async execute(sql: string, params: unknown[] = []): Promise<unknown> {
    const s = sql.trim().toUpperCase()
    if (s.startsWith('INSERT OR IGNORE INTO LLM_RUN_JOBS')) {
      const [job_id, run_id, doc_id, agent_kind, prompt_hash, created_at, updated_at] =
        params as [string, string, string | null, string, string, number, number]
      if (!this.rows.has(job_id)) {
        this.rows.set(job_id, {
          job_id,
          run_id,
          doc_id,
          agent_kind,
          prompt_hash,
          status: 'pending',
          result_json: null,
          error_message: null,
          retried_count: 0,
          schema_version: 1,
          created_at,
          updated_at,
        })
      }
      return
    }
    if (s.startsWith('UPDATE LLM_RUN_JOBS')) {
      const isBumpRetry = s.includes('RETRIED_COUNT=RETRIED_COUNT+1')
      const [status, result_json, error_message, updated_at, job_id] = params as [
        Row['status'], string | null, string | null, number, string,
      ]
      const r = this.rows.get(job_id)
      if (r) {
        r.status = status
        r.result_json = result_json
        r.error_message = error_message
        r.updated_at = updated_at
        if (isBumpRetry) r.retried_count += 1
      }
      return
    }
    if (s.startsWith('DELETE FROM LLM_RUN_JOBS')) {
      const [run_id] = params as [string]
      for (const [k, v] of this.rows) {
        if (v.run_id === run_id) this.rows.delete(k)
      }
      return
    }
    throw new Error(`MockDb.execute unhandled SQL: ${sql}`)
  }

  async select<T = unknown>(sql: string, params: unknown[] = []): Promise<T[]> {
    const s = sql.trim().toUpperCase()
    if (s.includes('FROM LLM_RUN_JOBS')) {
      const all = Array.from(this.rows.values())
      const filterStatus = s.includes("STATUS IN ('PENDING','RUNNING')")
      const filterByRun = s.includes('RUN_ID=?')
      let out = all
      if (filterByRun) {
        const runId = params[0] as string
        out = out.filter((r) => r.run_id === runId)
      }
      if (filterStatus) {
        out = out.filter((r) => r.status === 'pending' || r.status === 'running')
      }
      return out as unknown as T[]
    }
    throw new Error(`MockDb.select unhandled SQL: ${sql}`)
  }
}

// ── Helpers ────────────────────────────────────────────────────────────

function makeLLM(
  textsOrFn: Array<string | null> | ((prompt: string, idx: number) => string | null),
): LLMLike & { generate: ReturnType<typeof vi.fn> } {
  let callIdx = 0
  const generate = vi.fn(async (prompt: string) => {
    let text: string | null
    if (typeof textsOrFn === 'function') {
      text = textsOrFn(prompt, callIdx)
    } else {
      text = callIdx < textsOrFn.length ? textsOrFn[callIdx] : null
    }
    callIdx++
    if (text === null) return null
    return {
      text,
      usage: { input_tokens: 10, output_tokens: 20 },
      cost_usd: 0.0001,
      latency_ms: 100,
      provider: 'mock',
      model: 'mock-model',
    }
  })
  return { generate } as LLMLike & { generate: ReturnType<typeof vi.fn> }
}

function makeLLMByDocTitle(scoreFn: (title: string) => number): LLMLike {
  // 通过 prompt 文本里的 title 字段决定分数
  return {
    generate: vi.fn(async (prompt: string) => {
      // 在 rendered prompt 里抽取 - **标题**: xxx 行
      const m = prompt.match(/\*\*标题\*\*:\s*([^\n]+)/)
      const title = m ? m[1].trim() : 'unknown'
      const score = scoreFn(title)
      return {
        text: JSON.stringify({
          score,
          rationale: `score=${score} for ${title}`,
          one_line: `summary of ${title}`,
        }),
        usage: { input_tokens: 10, output_tokens: 20 },
        cost_usd: 0.0001,
        latency_ms: 100,
        provider: 'mock',
        model: 'mock-model',
      }
    }),
  }
}

function makeDocs(n: number, titlePrefix = 'doc'): ScoreInput[] {
  return Array.from({ length: n }, (_, i) => ({
    docId: `d-${i}`,
    title: `${titlePrefix}-${i}`,
    abstract: `Abstract for ${i}`,
    authors: 'Alice, Bob',
    year: 2024,
    source: 'arxiv',
  }))
}

function makeQueue(): { db: MockDb; queue: LLMQueue } {
  const db = new MockDb()
  const queue = new LLMQueue({
    concurrency: 8,
    intervalCap: 1000,
    interval: 1,
    _dbForTesting: db,
  })
  return { db, queue }
}

// ── reset ───────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  vi.useRealTimers()
})

// ════════════════════════════════════════════════════════════════════════
// parseScoringResponse 单元
// ════════════════════════════════════════════════════════════════════════

describe('parseScoringResponse', () => {
  it('裸 JSON → 解析 score/rationale/one_line', () => {
    const r = parseScoringResponse('{"score": 8.5, "rationale": "好", "one_line": "总结"}')
    expect(r?.score).toBe(8.5)
    expect(r?.rationale).toBe('好')
    expect(r?.oneLine).toBe('总结')
  })

  it('剥 ```json fence', () => {
    const r = parseScoringResponse('```json\n{"score":7,"rationale":"x"}\n```')
    expect(r?.score).toBe(7)
  })

  it('从前后解释里挑出 JSON', () => {
    const r = parseScoringResponse(
      '我的评分是:\n{"score": 6.5, "rationale": "ok"}\n以上。',
    )
    expect(r?.score).toBe(6.5)
  })

  it('多个对象，优先含 score 字段的', () => {
    const r = parseScoringResponse(
      '{"unrelated":1} {"score": 9, "rationale": "好"}',
    )
    expect(r?.score).toBe(9)
  })

  it('score 越界 → null', () => {
    expect(parseScoringResponse('{"score":11}')).toBeNull()
    expect(parseScoringResponse('{"score":-1}')).toBeNull()
  })

  it('score 缺失 / 非数字 → null', () => {
    expect(parseScoringResponse('{"rationale":"x"}')).toBeNull()
    expect(parseScoringResponse('{"score":"abc"}')).toBeNull()
  })

  it('完全无效 → null', () => {
    expect(parseScoringResponse('not a json at all')).toBeNull()
    expect(parseScoringResponse('')).toBeNull()
    expect(parseScoringResponse(null)).toBeNull()
    expect(parseScoringResponse(undefined)).toBeNull()
  })

  it('rationale / one_line 截断', () => {
    const long = 'x'.repeat(500)
    const r = parseScoringResponse(JSON.stringify({ score: 5, rationale: long, one_line: long }))
    expect(r?.rationale.length).toBe(200)
    expect(r?.oneLine.length).toBe(100)
  })
})

// ════════════════════════════════════════════════════════════════════════
// scoreSingle
// ════════════════════════════════════════════════════════════════════════

describe('ScoringAgent.scoreSingle', () => {
  it('happy path：LLM 返合法 JSON → score×10 + bucket', async () => {
    const llm = makeLLM([JSON.stringify({ score: 8.5, rationale: '相关', one_line: '总结' })])
    const { queue } = makeQueue()
    const agent = new ScoringAgent(llm, queue)
    const out = await agent.scoreSingle({
      doc: { docId: 'a', title: 't', abstract: 'a' },
      projectDescription: 'p',
      memorySnapshot: 'm',
    })
    expect(out.docId).toBe('a')
    expect(out.score).toBe(85)
    expect(out.bucket).toBe('very_relevant')
    expect(out.reasoning).toBe('相关')
    expect(out.oneLine).toBe('总结')
    expect(out.fallbackUsed).toBeUndefined()
  })

  it('LLM 第一次 garbage → retry 第二次成功', async () => {
    const llm = makeLLM([
      'no json garbage',
      JSON.stringify({ score: 7, rationale: 'ok' }),
    ])
    const { queue } = makeQueue()
    const agent = new ScoringAgent(llm, queue)
    const out = await agent.scoreSingle({
      doc: { docId: 'a', title: 't', abstract: 'a' },
      projectDescription: 'p',
      memorySnapshot: '',
    })
    expect(out.score).toBe(70)
    expect(out.bucket).toBe('relevant')
    expect((llm as any).generate).toHaveBeenCalledTimes(2)
  })

  it('LLM 两次都 garbage → fallback 50 + fallbackUsed=true', async () => {
    const llm = makeLLM(['garbage1', 'garbage2'])
    const { queue } = makeQueue()
    const agent = new ScoringAgent(llm, queue)
    const out = await agent.scoreSingle({
      doc: { docId: 'a', title: 't', abstract: 'a' },
      projectDescription: 'p',
      memorySnapshot: '',
    })
    expect(out.score).toBe(50)
    expect(out.fallbackUsed).toBe(true)
    expect(out.reasoning).toBe('LLM unavailable, default mid-score')
    expect(out.bucket).toBe('uncertain')
  })

  it('LLM 返 null → retry → 仍 null → fallback', async () => {
    const llm = makeLLM([null, null])
    const { queue } = makeQueue()
    const agent = new ScoringAgent(llm, queue)
    const out = await agent.scoreSingle({
      doc: { docId: 'a', title: 't', abstract: 'a' },
      projectDescription: 'p',
      memorySnapshot: '',
    })
    expect(out.fallbackUsed).toBe(true)
  })

  it('LLM throws → retry → 仍 throw → fallback', async () => {
    const llm: LLMLike = {
      generate: vi.fn(async () => {
        throw new Error('network down')
      }),
    }
    const { queue } = makeQueue()
    const agent = new ScoringAgent(llm, queue)
    const out = await agent.scoreSingle({
      doc: { docId: 'a', title: 't', abstract: 'a' },
      projectDescription: 'p',
      memorySnapshot: '',
    })
    expect(out.fallbackUsed).toBe(true)
    expect(out.score).toBe(50)
    expect((llm.generate as ReturnType<typeof vi.fn>)).toHaveBeenCalledTimes(2)
  })

  it('prompt 应包含 project_description / memory_snapshot / title / abstract', async () => {
    const llm = makeLLM([JSON.stringify({ score: 5, rationale: '' })])
    const { queue } = makeQueue()
    const agent = new ScoringAgent(llm, queue)
    await agent.scoreSingle({
      doc: { docId: 'a', title: 'MY_TITLE', abstract: 'MY_ABSTRACT' },
      projectDescription: 'MY_PROJECT',
      memorySnapshot: 'MY_MEMORY',
    })
    const prompt = (llm as any).generate.mock.calls[0][0] as string
    expect(prompt).toContain('MY_PROJECT')
    expect(prompt).toContain('MY_MEMORY')
    expect(prompt).toContain('MY_TITLE')
    expect(prompt).toContain('MY_ABSTRACT')
  })
})

// ════════════════════════════════════════════════════════════════════════
// scoreAll
// ════════════════════════════════════════════════════════════════════════

describe('ScoringAgent.scoreAll — happy path 30 docs', () => {
  it('30 篇并发 → 正确分桶 above/below', async () => {
    const docs = makeDocs(30)
    // 偶数 → 9 分，奇数 → 4 分
    const llm = makeLLMByDocTitle((title) => {
      const idx = Number(title.split('-')[1])
      return idx % 2 === 0 ? 9.0 : 4.0
    })
    const { queue } = makeQueue()
    const agent = new ScoringAgent(llm, queue)
    const result = await agent.scoreAll({
      runId: 'run-1',
      docs,
      projectDescription: 'p',
      memorySnapshot: 'm',
      cutoff: 60,
    })
    // 90 >= 60 → above；40 < 60 → below
    expect(result.above).toHaveLength(15)
    expect(result.below).toHaveLength(15)
    expect(result.above.every((s) => s.score === 90)).toBe(true)
    expect(result.below.every((s) => s.score === 40)).toBe(true)
    // bucket 正确
    expect(result.above.every((s) => s.bucket === 'very_relevant')).toBe(true)
    expect(result.below.every((s) => s.bucket === 'uncertain')).toBe(true)
    // 排序：score 降序
    for (let i = 1; i < result.above.length; i++) {
      expect(result.above[i].score).toBeLessThanOrEqual(result.above[i - 1].score)
    }
  })
})

describe('ScoringAgent.scoreAll — fallback path', () => {
  it('LLM 始终 garbage → 30 篇全 fallback 50 → cutoff=60 全进 below', async () => {
    const docs = makeDocs(30)
    const llm = makeLLM(() => 'garbage no json')
    const { queue } = makeQueue()
    const agent = new ScoringAgent(llm, queue)
    const result = await agent.scoreAll({
      runId: 'run-fb',
      docs,
      projectDescription: 'p',
      memorySnapshot: '',
      cutoff: 60,
    })
    expect(result.above).toHaveLength(0)
    expect(result.below).toHaveLength(30)
    expect(result.below.every((s) => s.fallbackUsed === true)).toBe(true)
    expect(result.below.every((s) => s.score === 50)).toBe(true)
  })
})

describe('ScoringAgent.scoreAll — onProgress callback', () => {
  it('onProgress 被调用 N 次，最后一次 done=total', async () => {
    const docs = makeDocs(5)
    const llm = makeLLMByDocTitle(() => 7)
    const { queue } = makeQueue()
    const agent = new ScoringAgent(llm, queue)
    const onProgress = vi.fn()
    const result = await agent.scoreAll({
      runId: 'run-prog',
      docs,
      projectDescription: 'p',
      memorySnapshot: '',
      onProgress,
    })
    expect(result.above).toHaveLength(5)
    expect(onProgress).toHaveBeenCalledTimes(5)
    const lastCall = onProgress.mock.calls[onProgress.mock.calls.length - 1]
    expect(lastCall[0]).toBe(5)
    expect(lastCall[1]).toBe(5)
    // lastResult 应该是 ScoreOutput
    expect(lastCall[2]?.docId).toMatch(/^d-/)
  })
})

describe('ScoringAgent.scoreAll — empty docs', () => {
  it('空数组 → 立即返 {above:[], below:[]}（不调 LLM）', async () => {
    const llm = makeLLM([])
    const { queue } = makeQueue()
    const agent = new ScoringAgent(llm, queue)
    const result = await agent.scoreAll({
      runId: 'run-empty',
      docs: [],
      projectDescription: 'p',
      memorySnapshot: '',
    })
    expect(result.above).toEqual([])
    expect(result.below).toEqual([])
    expect((llm as any).generate).not.toHaveBeenCalled()
  })
})

describe('ScoringAgent.scoreAll — cutoff 边界', () => {
  it('cutoff=0 → 全 above', async () => {
    const docs = makeDocs(5)
    const llm = makeLLMByDocTitle(() => 3)  // score=30
    const { queue } = makeQueue()
    const agent = new ScoringAgent(llm, queue)
    const result = await agent.scoreAll({
      runId: 'run-c0',
      docs,
      projectDescription: 'p',
      memorySnapshot: '',
      cutoff: 0,
    })
    expect(result.above).toHaveLength(5)
    expect(result.below).toHaveLength(0)
  })

  it('cutoff=100 → 全 below（即使 score=10 也是 100<100 假，等号 above 收 ===100）', async () => {
    const docs = makeDocs(5)
    const llm = makeLLMByDocTitle(() => 10) // score=100
    const { queue } = makeQueue()
    const agent = new ScoringAgent(llm, queue)
    const result = await agent.scoreAll({
      runId: 'run-c100',
      docs,
      projectDescription: 'p',
      memorySnapshot: '',
      cutoff: 100,
    })
    // score 100 >= cutoff 100 → above
    expect(result.above).toHaveLength(5)
    expect(result.below).toHaveLength(0)
  })

  it('cutoff=101 → 全 below', async () => {
    const docs = makeDocs(5)
    const llm = makeLLMByDocTitle(() => 10) // score=100
    const { queue } = makeQueue()
    const agent = new ScoringAgent(llm, queue)
    const result = await agent.scoreAll({
      runId: 'run-c101',
      docs,
      projectDescription: 'p',
      memorySnapshot: '',
      cutoff: 101,
    })
    expect(result.above).toHaveLength(0)
    expect(result.below).toHaveLength(5)
  })

  it('默认 cutoff=60', async () => {
    const docs = makeDocs(2)
    const llm = makeLLMByDocTitle((t) => (t === 'doc-0' ? 6 : 5))
    const { queue } = makeQueue()
    const agent = new ScoringAgent(llm, queue)
    const result = await agent.scoreAll({
      runId: 'run-def',
      docs,
      projectDescription: 'p',
      memorySnapshot: '',
    })
    expect(result.above).toHaveLength(1) // 60
    expect(result.below).toHaveLength(1) // 50
  })
})

describe('ScoringAgent.scoreAll — bucket 自动分桶', () => {
  it('80/60/40 阈值切换', async () => {
    // 4 篇 doc，分别期望 90/70/50/30
    const docs: ScoreInput[] = [
      { docId: 'a', title: 'a', abstract: '' },
      { docId: 'b', title: 'b', abstract: '' },
      { docId: 'c', title: 'c', abstract: '' },
      { docId: 'd', title: 'd', abstract: '' },
    ]
    const map: Record<string, number> = { a: 9, b: 7, c: 5, d: 3 }
    const llm = makeLLMByDocTitle((t) => map[t] ?? 5)
    const { queue } = makeQueue()
    const agent = new ScoringAgent(llm, queue)
    const result = await agent.scoreAll({
      runId: 'run-bucket',
      docs,
      projectDescription: 'p',
      memorySnapshot: '',
      cutoff: 0, // 全进 above 看 bucket
    })
    const byId = new Map(result.above.map((s) => [s.docId, s]))
    expect(byId.get('a')?.bucket).toBe('very_relevant')
    expect(byId.get('b')?.bucket).toBe('relevant')
    expect(byId.get('c')?.bucket).toBe('uncertain')
    expect(byId.get('d')?.bucket).toBe('irrelevant')
  })
})

// ════════════════════════════════════════════════════════════════════════
// LLMQueue resume integration
// ════════════════════════════════════════════════════════════════════════

describe('ScoringAgent + LLMQueue.resume — 续跑行为', () => {
  it('mock job state pending → resume() 续跑只跑 pending/running', async () => {
    const db = new MockDb()
    const queue = new LLMQueue({
      concurrency: 4,
      intervalCap: 1000,
      interval: 1,
      _dbForTesting: db,
    })
    const runId = 'run-resume'
    const docs = makeDocs(10)

    // 模拟前次跑了 6 篇（5 done + 1 running 表示崩溃前一刻），剩 4 篇 pending
    const t = Date.now()
    docs.forEach((d, i) => {
      let status: Row['status'] = 'pending'
      if (i < 5) status = 'done'
      else if (i === 5) status = 'running'
      db.rows.set(`old-${d.docId}`, {
        job_id: `old-${d.docId}`,
        run_id: runId,
        doc_id: d.docId,
        agent_kind: 'scoring',
        prompt_hash: 'h',
        status,
        result_json: status === 'done' ? JSON.stringify({ docId: d.docId, score: 80, reasoning: 'old' }) : null,
        error_message: null,
        retried_count: 0,
        schema_version: 1,
        created_at: t,
        updated_at: t,
      })
    })

    // 续跑 handler：直接给 score=70
    const handler = vi.fn(async (job): Promise<ScoreOutput> => {
      return {
        docId: job.docId ?? 'unknown',
        score: 70,
        reasoning: 'resumed',
        bucket: 'relevant',
      }
    })

    const hydrate = (row: Row) => ({
      jobId: row.job_id,
      runId: row.run_id,
      docId: row.doc_id,
      agentKind: row.agent_kind,
      input: { docId: row.doc_id ?? '' },
      promptHash: row.prompt_hash,
    })

    const results = await queue.resume(
      runId,
      hydrate as any,
      handler,
    )

    // 应该续跑 1 running + 4 pending = 5
    expect(results).toHaveLength(5)
    expect(results.every((r) => r.status === 'done')).toBe(true)
    expect(handler).toHaveBeenCalledTimes(5)

    // db 中所有 row 都该是 done
    let doneCount = 0
    for (const r of db.rows.values()) {
      if (r.status === 'done') doneCount++
    }
    expect(doneCount).toBe(10)
  })
})
