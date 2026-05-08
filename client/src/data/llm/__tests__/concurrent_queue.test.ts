/**
 * LLM Queue 单测：30 个 mock job + 中途崩溃 + resume() 续跑。
 *
 * 不真的连 SQLite —— 用一个 in-memory `DbLike` 实现塞进 `_dbForTesting`。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LLMQueue, makeJobId, type LLMJob } from '../concurrent_queue'

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
      const [job_id, run_id, doc_id, agent_kind, prompt_hash, created_at, updated_at] = params as [
        string, string, string | null, string, string, number, number,
      ]
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
      // 区分两种 update（带/不带 retry++）
      const isBumpRetry = s.includes('RETRIED_COUNT=RETRIED_COUNT+1')
      if (isBumpRetry) {
        const [status, result_json, error_message, updated_at, job_id] = params as [
          Row['status'], string | null, string | null, number, string,
        ]
        const r = this.rows.get(job_id)
        if (r) {
          r.status = status
          r.result_json = result_json
          r.error_message = error_message
          r.retried_count += 1
          r.updated_at = updated_at
        }
      } else {
        const [status, result_json, error_message, updated_at, job_id] = params as [
          Row['status'], string | null, string | null, number, string,
        ]
        const r = this.rows.get(job_id)
        if (r) {
          r.status = status
          r.result_json = result_json
          r.error_message = error_message
          r.updated_at = updated_at
        }
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
      // 简化解析：检查是否带 run_id 过滤 + 是否过滤 status IN ('pending','running')
      const filterStatus = s.includes("STATUS IN ('PENDING','RUNNING')")
      const filterByRun = s.includes('RUN_ID=?')
      let out = all
      if (filterByRun) {
        const runId = params[0] as string
        out = out.filter((r) => r.run_id === runId)
      } else if (params.length === 1 && !filterStatus) {
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

// ── helper ─────────────────────────────────────────────────────────────

function makeJobs(runId: string, n: number): LLMJob<{ idx: number }, string>[] {
  return Array.from({ length: n }, (_, i) => ({
    jobId: `${runId}-${i}-${makeJobId()}`,
    runId,
    docId: `doc-${i}`,
    agentKind: 'scoring',
    input: { idx: i },
    promptHash: `hash-${i}`,
  }))
}

// ── tests ──────────────────────────────────────────────────────────────

describe('LLMQueue.enqueue', () => {
  let mockDb: MockDb
  let queue: LLMQueue

  beforeEach(() => {
    mockDb = new MockDb()
    queue = new LLMQueue({
      concurrency: 4,
      intervalCap: 1000,  // 测试不要 rate-limit
      interval: 1,
      _dbForTesting: mockDb,
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('runs all jobs and persists status=done', async () => {
    const jobs = makeJobs('run-A', 30)
    const handler = vi.fn(async (job: LLMJob<{ idx: number }, string>) => {
      return `out-${job.input.idx}`
    })

    const results = await queue.enqueue(jobs, handler)

    expect(results).toHaveLength(30)
    expect(results.every((r) => r.status === 'done')).toBe(true)
    expect(handler).toHaveBeenCalledTimes(30)

    // SQL 中所有 job 都标记为 done
    for (const j of jobs) {
      const row = mockDb.rows.get(j.jobId)
      expect(row?.status).toBe('done')
      expect(row?.result_json).toBeTruthy()
    }
  })

  it('captures failures without throwing', async () => {
    const jobs = makeJobs('run-fail', 4)
    const handler = vi.fn(async (job: LLMJob<{ idx: number }, string>) => {
      if (job.input.idx === 1 || job.input.idx === 3) {
        throw new Error(`boom-${job.input.idx}`)
      }
      return `ok-${job.input.idx}`
    })

    const results = await queue.enqueue(jobs, handler)
    const fails = results.filter((r) => r.status === 'failed')
    expect(fails).toHaveLength(2)
    expect(fails.map((f) => f.error).sort()).toEqual(['boom-1', 'boom-3'])
  })

  it('progress callback fires for each job', async () => {
    const jobs = makeJobs('run-prog', 5)
    const onProgress = vi.fn()
    await queue.enqueue(
      jobs,
      async (j) => `r-${j.input.idx}`,
      onProgress,
    )
    expect(onProgress).toHaveBeenCalledTimes(5)
    // 最后一次 done 必须是 5/5
    const lastCall = onProgress.mock.calls[onProgress.mock.calls.length - 1]
    expect(lastCall[0]).toBe(5)
    expect(lastCall[1]).toBe(5)
  })
})

describe('LLMQueue.resume (mid-run crash recovery)', () => {
  it('runs only pending/running jobs after a simulated crash', async () => {
    const mockDb = new MockDb()
    const runId = 'run-crash'
    const totalJobs = 30

    // 模拟前次 run：跑了 30 个，前 15 个完成（done），15-19 处于 running（崩溃前），剩下 20-29 还是 pending
    const jobs = makeJobs(runId, totalJobs)
    const t = Date.now()
    for (let i = 0; i < totalJobs; i++) {
      const j = jobs[i]
      let status: Row['status'] = 'pending'
      if (i < 15) status = 'done'
      else if (i < 20) status = 'running'
      mockDb.rows.set(j.jobId, {
        job_id: j.jobId,
        run_id: runId,
        doc_id: j.docId ?? null,
        agent_kind: j.agentKind,
        prompt_hash: j.promptHash,
        status,
        result_json: status === 'done' ? JSON.stringify(`old-${i}`) : null,
        error_message: null,
        retried_count: 0,
        schema_version: 1,
        created_at: t,
        updated_at: t,
      })
    }

    // 重启：建新 queue，调 resume
    const queue = new LLMQueue({
      concurrency: 4,
      intervalCap: 1000,
      interval: 1,
      _dbForTesting: mockDb,
    })

    const handler = vi.fn(async (job: LLMJob<{ idx: number }, string>) => {
      return `new-${job.input.idx}`
    })

    // hydrate：DB row 还原成 LLMJob — 测试里我们 input 直接从 doc_id 解出 idx
    const hydrate = (row: Row): LLMJob<{ idx: number }, string> => {
      const idx = parseInt((row.doc_id ?? 'doc-0').replace('doc-', ''), 10)
      return {
        jobId: row.job_id,
        runId: row.run_id,
        docId: row.doc_id,
        agentKind: row.agent_kind,
        input: { idx },
        promptHash: row.prompt_hash,
      }
    }

    const results = await queue.resume<{ idx: number }, string>(
      runId,
      hydrate as unknown as (row: any) => LLMJob<{ idx: number }, string> | null,
      handler,
    )

    // 应该只续跑 15 + 10 = 15 个 ('running' 5 个 + 'pending' 10 个)
    expect(results).toHaveLength(15)
    expect(results.every((r) => r.status === 'done')).toBe(true)
    // handler 只被调用 15 次（不重跑已 done 的前 15 个）
    expect(handler).toHaveBeenCalledTimes(15)

    // SQL 状态校验
    let doneCount = 0
    for (const r of mockDb.rows.values()) {
      if (r.status === 'done') doneCount++
    }
    expect(doneCount).toBe(30) // 旧 15 + 续跑 15
  })

  it('returns empty array when no pending/running jobs left', async () => {
    const mockDb = new MockDb()
    const queue = new LLMQueue({
      concurrency: 4,
      intervalCap: 1000,
      interval: 1,
      _dbForTesting: mockDb,
    })

    const handler = vi.fn()
    const hydrate = vi.fn()

    const results = await queue.resume('no-such-run', hydrate as any, handler)
    expect(results).toEqual([])
    expect(handler).not.toHaveBeenCalled()
  })
})

describe('LLMQueue rate limiting', () => {
  it('honours intervalCap (smoke test — does not assert timing)', async () => {
    const mockDb = new MockDb()
    const queue = new LLMQueue({
      concurrency: 8,
      intervalCap: 5,
      interval: 100,
      _dbForTesting: mockDb,
    })
    const jobs = makeJobs('rate-run', 10)
    const results = await queue.enqueue(jobs, async (j) => `ok-${j.input.idx}`)
    expect(results).toHaveLength(10)
    expect(results.every((r) => r.status === 'done')).toBe(true)
  })
})
