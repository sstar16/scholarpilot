/**
 * LLM Queue — p-queue + SQLite 持久化的可恢复任务队列。
 *
 * 用途：B5/B8/B9/B11 等检索路径会一次产生几十个 LLM job（per-doc scoring /
 * summary / graph extract）。客户端断网/崩溃/退出时这些 job 可能跑了一半，
 * 我们把每个 job 的中间状态写到 SQLite `llm_run_jobs` 表，重启时 `resume()`
 * 把 status='pending'/'running' 的 job 重新 enqueue（running 视作前次崩溃）。
 *
 * 与 backend Celery 差异：
 * - 客户端单进程 + WebView，没有 broker
 * - 用 p-queue 控并发 + 速率（避免 LLM provider 419/429）
 * - 持久化只为"断网续跑"，不做分布式
 *
 * concurrency / intervalCap 默认值参考 PRD §C11：
 * - 8 路并发（DeepSeek/Moonshot/jiekou 实测稳定）
 * - 30 reqs / 60s（保守 → 留余量给 user 主动触发的 skill）
 */
import PQueue from 'p-queue'
import Database from '@tauri-apps/plugin-sql'

import { nowMs, uuidv4 } from './utils'

// ── 类型定义 ────────────────────────────────────────────────────────────

export type AgentKind =
  | 'scoring'
  | 'summary'
  | 'graph'
  | 'memory'
  | 'query_plan'
  | 'other'

export type JobStatus = 'pending' | 'running' | 'done' | 'failed'

export interface LLMJob<TInput = unknown, _TOutput = unknown> {
  jobId: string
  runId: string
  docId?: string | null
  agentKind: AgentKind | string
  input: TInput
  promptHash: string
}

export interface JobResult<TOutput = unknown> {
  jobId: string
  status: 'done' | 'failed'
  result?: TOutput
  error?: string
}

export interface QueueOptions {
  concurrency?: number
  /** rate-limit window 内最大请求数 */
  intervalCap?: number
  /** rate-limit window 时长 ms */
  interval?: number
  /** 自定义 SQLite path（测试用，默认 sqlite:scholarpilot.db） */
  sqlitePath?: string
  /** 测试钩子：注入 Database（绕过 tauri plugin） */
  _dbForTesting?: Database | unknown
}

interface DbRow {
  job_id: string
  run_id: string
  doc_id: string | null
  agent_kind: string
  prompt_hash: string
  status: JobStatus
  result_json: string | null
  error_message: string | null
  retried_count: number
  schema_version: number
  created_at: number
  updated_at: number
}

// ── 抽象 DB 接口（让测试可以塞 mock） ─────────────────────────────────

interface DbLike {
  execute(query: string, bindValues?: unknown[]): Promise<unknown>
  select<T = unknown>(query: string, bindValues?: unknown[]): Promise<T[]>
}

// ── 主类 ────────────────────────────────────────────────────────────────

export class LLMQueue {
  private queue: PQueue
  private dbPromise: Promise<DbLike>
  private opts: Required<Pick<QueueOptions, 'concurrency' | 'intervalCap' | 'interval' | 'sqlitePath'>>

  constructor(opts: QueueOptions = {}) {
    this.opts = {
      concurrency: opts.concurrency ?? 8,
      intervalCap: opts.intervalCap ?? 30,
      interval: opts.interval ?? 60_000,
      sqlitePath: opts.sqlitePath ?? 'sqlite:scholarpilot.db',
    }
    this.queue = new PQueue({
      concurrency: this.opts.concurrency,
      intervalCap: this.opts.intervalCap,
      interval: this.opts.interval,
      carryoverConcurrencyCount: true,
    })
    if (opts._dbForTesting) {
      this.dbPromise = Promise.resolve(opts._dbForTesting as DbLike)
    } else {
      this.dbPromise = Database.load(this.opts.sqlitePath) as unknown as Promise<DbLike>
    }
  }

  /** 暴露给调用方做暂停/恢复（settings 切换 LLM provider 时需要 pause）。 */
  pause(): void { this.queue.pause() }
  start(): void { this.queue.start() }
  get size(): number { return this.queue.size }
  get pending(): number { return this.queue.pending }

  // ── 持久化操作 ────────────────────────────────────────────────────

  private async insertJobRow(job: LLMJob): Promise<void> {
    const db = await this.dbPromise
    const t = nowMs()
    await db.execute(
      `INSERT OR IGNORE INTO llm_run_jobs (
        job_id, run_id, doc_id, agent_kind, prompt_hash,
        status, retried_count, schema_version, created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, 'pending', 0, 1, ?, ?)`,
      [job.jobId, job.runId, job.docId ?? null, job.agentKind, job.promptHash, t, t],
    )
  }

  private async updateStatus(
    jobId: string,
    status: JobStatus,
    extra: { result?: unknown, error?: string, bumpRetry?: boolean } = {},
  ): Promise<void> {
    const db = await this.dbPromise
    const t = nowMs()
    if (extra.bumpRetry) {
      await db.execute(
        `UPDATE llm_run_jobs SET status=?, result_json=?, error_message=?,
          retried_count=retried_count+1, updated_at=? WHERE job_id=?`,
        [
          status,
          extra.result === undefined ? null : JSON.stringify(extra.result),
          extra.error ?? null,
          t,
          jobId,
        ],
      )
    } else {
      await db.execute(
        `UPDATE llm_run_jobs SET status=?, result_json=?, error_message=?, updated_at=?
          WHERE job_id=?`,
        [
          status,
          extra.result === undefined ? null : JSON.stringify(extra.result),
          extra.error ?? null,
          t,
          jobId,
        ],
      )
    }
  }

  // ── 主入口：批量 enqueue ─────────────────────────────────────────

  async enqueue<TInput, TOutput>(
    jobs: LLMJob<TInput, TOutput>[],
    handler: (job: LLMJob<TInput, TOutput>) => Promise<TOutput>,
    onProgress?: (done: number, total: number, lastResult?: TOutput) => void,
  ): Promise<JobResult<TOutput>[]> {
    // 先把所有 job 写到 SQLite（pending）
    for (const j of jobs) {
      await this.insertJobRow(j)
    }

    const total = jobs.length
    let done = 0
    const results: JobResult<TOutput>[] = []

    const runOne = async (job: LLMJob<TInput, TOutput>): Promise<JobResult<TOutput>> => {
      await this.updateStatus(job.jobId, 'running')
      try {
        const out = await handler(job)
        await this.updateStatus(job.jobId, 'done', { result: out })
        done++
        onProgress?.(done, total, out)
        return { jobId: job.jobId, status: 'done', result: out }
      } catch (e: unknown) {
        const errMsg = e instanceof Error ? e.message : String(e)
        await this.updateStatus(job.jobId, 'failed', { error: errMsg, bumpRetry: true })
        done++
        onProgress?.(done, total, undefined)
        return { jobId: job.jobId, status: 'failed', error: errMsg }
      }
    }

    const tasks = jobs.map((j) => this.queue.add(() => runOne(j)) as Promise<JobResult<TOutput>>)
    const settled = await Promise.all(tasks)
    results.push(...settled)
    return results
  }

  // ── 续跑 ──────────────────────────────────────────────────────────

  /**
   * 启动时调用：扫 status IN ('pending','running') 的 job，重新 enqueue。
   * `running` 表示前次进程崩溃在该 job 中间，与 pending 同等处理（再跑一次）。
   *
   * @param runId 只续跑该 run 的 job；不传则续跑所有
   * @param hydrate 把 DB row 反序列化成 LLMJob（caller 决定 input 怎么还原 — 通常 input 自己也要
   *                序列化进 result_json 或外部 payload 表，这里默认给空 input；也可以让 hydrate 抛
   *                "找不到 input" 跳过）
   */
  async resume<TInput, TOutput>(
    runId: string | undefined,
    hydrate: (row: DbRow) => LLMJob<TInput, TOutput> | null,
    handler: (job: LLMJob<TInput, TOutput>) => Promise<TOutput>,
    onProgress?: (done: number, total: number, lastResult?: TOutput) => void,
  ): Promise<JobResult<TOutput>[]> {
    const db = await this.dbPromise
    const sql = runId
      ? `SELECT * FROM llm_run_jobs WHERE run_id=? AND status IN ('pending','running')`
      : `SELECT * FROM llm_run_jobs WHERE status IN ('pending','running')`
    const params = runId ? [runId] : []
    const rows = (await db.select<DbRow>(sql, params)) ?? []
    const jobs: LLMJob<TInput, TOutput>[] = []
    for (const r of rows) {
      const j = hydrate(r)
      if (j) jobs.push(j)
    }
    if (!jobs.length) return []

    const total = jobs.length
    let done = 0
    const results: JobResult<TOutput>[] = []

    const runOne = async (job: LLMJob<TInput, TOutput>): Promise<JobResult<TOutput>> => {
      await this.updateStatus(job.jobId, 'running', { bumpRetry: true })
      try {
        const out = await handler(job)
        await this.updateStatus(job.jobId, 'done', { result: out })
        done++
        onProgress?.(done, total, out)
        return { jobId: job.jobId, status: 'done', result: out }
      } catch (e: unknown) {
        const errMsg = e instanceof Error ? e.message : String(e)
        await this.updateStatus(job.jobId, 'failed', { error: errMsg, bumpRetry: true })
        done++
        onProgress?.(done, total, undefined)
        return { jobId: job.jobId, status: 'failed', error: errMsg }
      }
    }

    const tasks = jobs.map((j) => this.queue.add(() => runOne(j)) as Promise<JobResult<TOutput>>)
    const settled = await Promise.all(tasks)
    results.push(...settled)
    return results
  }

  // ── 查询 ──────────────────────────────────────────────────────────

  async getJobsByRun(runId: string): Promise<DbRow[]> {
    const db = await this.dbPromise
    return (await db.select<DbRow>(`SELECT * FROM llm_run_jobs WHERE run_id=?`, [runId])) ?? []
  }

  async deleteJobsByRun(runId: string): Promise<void> {
    const db = await this.dbPromise
    await db.execute(`DELETE FROM llm_run_jobs WHERE run_id=?`, [runId])
  }
}

// ── 工具：构造 jobId（uuid） ─────────────────────────────────────────

export function makeJobId(): string {
  return uuidv4()
}
