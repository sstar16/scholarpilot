/**
 * Scoring Agent — 客户端版（移植自 backend `app/harness/agents/scoring_agent.py`）。
 *
 * 责任：
 *   30 篇文献并发 LLM 评分（0-100）→ above/below 斩杀线分桶。
 *
 * 与 backend 差异：
 * - 用 `LLMQueue`（p-queue + SQLite 持久化）替代 `asyncio.Semaphore`，支持断网/崩溃续跑
 * - **删除 Answer Now 早结束逻辑**（2026-05-07 决策）：不再有 partial_complete /
 *   interrupt_signal / can_interrupt，所有 30 篇必须跑完才返回
 * - 评分单位 0-100（前端 spec），backend 是 0-10；prompt 给的也是 0-10，
 *   解析后 ×10 转成 0-100
 * - 自动分桶：score >= 80 → very_relevant；60-79 → relevant；40-59 → uncertain；< 40 → irrelevant
 *
 * 三层兜底：
 * 1. parse 成功 → 直接返回 LLM 给的 score
 * 2. parse 失败 → retry 一次（temperature 不变）
 * 3. retry 也失败 → 默认 mid-score 50，reasoning 标 "LLM unavailable, default mid-score"
 */
import type { LLMResult } from '../llm/types'

import { LLMQueue, makeJobId, type LLMJob } from '../llm/concurrent_queue'

import { loadPrompt } from './promptLoader'

// ── 类型 ────────────────────────────────────────────────────────────────

export interface ScoreInput {
  docId: string
  title: string
  abstract: string
  authors?: string
  year?: number
  source?: string
  /** 可选：文档类型（paper/patent/etc），默认 paper */
  docType?: string
  /** 可选：发表日期（YYYY-MM-DD），优先于 year */
  publicationDate?: string
  /** 可选：引用量 */
  citationCount?: number
  /** 可选：DOI / 期刊 / AI 提取关键点（拼到 extra_info） */
  doi?: string
  journal?: string
  aiKeyPoints?: string[] | string
}

export type ScoreBucket = 'very_relevant' | 'relevant' | 'uncertain' | 'irrelevant'

export interface ScoreOutput {
  docId: string
  /** 0-100（prompt 出 0-10 后 ×10 标准化） */
  score: number
  reasoning: string
  /** 自动分桶（cutoff 之外的额外语义标签） */
  bucket?: ScoreBucket
  /** 一句话总结（prompt 也输出，前端可选展示） */
  oneLine?: string
  /** True 表示走了 fallback（解析失败 / LLM 不可用） */
  fallbackUsed?: boolean
}

export interface ScoringResult {
  /** score >= cutoff，按 score 降序 */
  above: ScoreOutput[]
  /** score < cutoff，按 score 降序 */
  below: ScoreOutput[]
}

// ── LLM 接口（duck-typed，方便 vi.mock 注入） ────────────────────────────

export interface LLMLike {
  generate(
    prompt: string,
    options?: {
      temperature?: number
      response_format?: { type: 'json_object' | 'text' } | null
    },
  ): Promise<LLMResult | null>
}

// ── 常量 ────────────────────────────────────────────────────────────────

/** prompt 出 0-10 → score 0-100 的倍率 */
const SCORE_SCALE = 10
const DEFAULT_CUTOFF = 60
const DEFAULT_MID_SCORE = 50
const FALLBACK_REASON = 'LLM unavailable, default mid-score'

/** 分桶阈值（基于 0-100 score） */
function classifyBucket(score: number): ScoreBucket {
  if (score >= 80) return 'very_relevant'
  if (score >= 60) return 'relevant'
  if (score >= 40) return 'uncertain'
  return 'irrelevant'
}

// ── JSON 解析（对齐 backend `_parse_scoring_response`） ────────────────────

interface ParsedScore {
  score: number // 0-10 from LLM
  rationale: string
  oneLine: string
}

export function parseScoringResponse(text: string | null | undefined): ParsedScore | null {
  if (!text) return null
  let body = text.trim()
  if (body.startsWith('```')) {
    body = body.replace(/^```(?:json)?\s*\n?/, '')
    body = body.replace(/\n?\s*```\s*$/, '')
  }

  // 平衡扫描所有顶层 {...}
  const candidates: string[] = []
  let depth = 0
  let start = -1
  for (let i = 0; i < body.length; i++) {
    const ch = body[i]
    if (ch === '{') {
      if (depth === 0) start = i
      depth++
    } else if (ch === '}') {
      depth--
      if (depth === 0 && start >= 0) {
        candidates.push(body.slice(start, i + 1))
        start = -1
      }
    }
  }

  // 优先含 "score" 字段的对象
  const ordered = [
    ...candidates.filter((c) => c.includes('"score"')),
    ...candidates.filter((c) => !c.includes('"score"')),
  ]

  for (const cand of ordered) {
    try {
      const obj = JSON.parse(cand) as Record<string, unknown>
      const rawScore = obj.score
      if (rawScore === undefined || rawScore === null) continue
      const score = typeof rawScore === 'number' ? rawScore : Number(rawScore)
      if (!Number.isFinite(score)) continue
      if (score < 0 || score > 10) continue
      return {
        score: Math.round(score * 10) / 10,
        rationale: String(obj.rationale ?? '').slice(0, 200),
        oneLine: String(obj.one_line ?? '').slice(0, 100),
      }
    } catch {
      continue
    }
  }
  return null
}

// ── extra_info / memory_section 拼装（对齐 backend prompts/scoring.py） ──

function buildMemorySection(memorySnapshot: string, bucketExamples: string): string {
  let s = ''
  if (memorySnapshot && memorySnapshot.trim()) {
    s = `## 用户研究偏好记忆\n${memorySnapshot.slice(0, 800)}`
  }
  if (bucketExamples && bucketExamples.trim()) {
    if (s) s += '\n\n'
    s += `## 用户已分类的高相关文献（参考）\n${bucketExamples.slice(0, 600)}`
  }
  return s
}

function buildExtraInfo(doc: ScoreInput): string {
  const parts: string[] = []
  if (doc.aiKeyPoints) {
    let pts: string
    if (Array.isArray(doc.aiKeyPoints)) {
      pts = doc.aiKeyPoints.slice(0, 5).map((p) => String(p)).join('; ')
    } else {
      pts = String(doc.aiKeyPoints)
    }
    if (pts) parts.push(`- **AI 提取关键点**: ${pts}`)
  }
  if (doc.journal) parts.push(`- **期刊/会议**: ${doc.journal}`)
  if (doc.doi) parts.push(`- **DOI**: ${doc.doi}`)
  return parts.join('\n')
}

function pickPublicationDate(doc: ScoreInput): string {
  if (doc.publicationDate) return doc.publicationDate
  if (doc.year !== undefined && doc.year !== null) return String(doc.year)
  return '未知'
}

// ── ScoringAgent ────────────────────────────────────────────────────────

export interface ScoreAllParams {
  /** 用于 LLMQueue 中间状态持久化 */
  runId: string
  docs: ScoreInput[]
  projectDescription: string
  /** 用户记忆作为 context（可空） */
  memorySnapshot: string
  /** 已分类的高相关文献参考（可空，喂给 prompt 的 bucket_examples 区） */
  bucketExamples?: string
  /** 斩杀线（默认 60，above 进入 summarization） */
  cutoff?: number
  onProgress?: (done: number, total: number, lastResult?: ScoreOutput) => void
}

export interface ScoreSingleParams {
  doc: ScoreInput
  projectDescription: string
  memorySnapshot: string
  bucketExamples?: string
}

export class ScoringAgent {
  constructor(
    private readonly llm: LLMLike,
    private readonly queue: LLMQueue,
  ) {}

  /**
   * 30 篇并发评分（LLMQueue concurrency=8）。
   *
   * 全部 done 后按 cutoff 切 above/below；空数组 → 直接返回。
   */
  async scoreAll(params: ScoreAllParams): Promise<ScoringResult> {
    const {
      runId,
      docs,
      projectDescription,
      memorySnapshot,
      bucketExamples = '',
      cutoff = DEFAULT_CUTOFF,
      onProgress,
    } = params

    if (!docs || docs.length === 0) {
      return { above: [], below: [] }
    }

    type JobInput = { docId: string }
    type JobOutput = ScoreOutput

    const jobs: LLMJob<JobInput, JobOutput>[] = docs.map((d) => ({
      jobId: `${runId}-${d.docId}-${makeJobId()}`,
      runId,
      docId: d.docId,
      agentKind: 'scoring',
      input: { docId: d.docId },
      // 简易 promptHash：title 长度 + docId 截 16；测试不依赖 hash 真实性
      promptHash: `${d.docId}:${(d.title ?? '').length}`,
    }))

    // docId → ScoreInput map（handler 里要回查）
    const docMap = new Map<string, ScoreInput>(docs.map((d) => [d.docId, d]))

    const handler = async (job: LLMJob<JobInput, JobOutput>): Promise<JobOutput> => {
      const doc = docMap.get(job.input.docId)
      if (!doc) {
        // 不会发生（jobs 由 docs 派生），降级 fallback
        return {
          docId: job.input.docId,
          score: DEFAULT_MID_SCORE,
          reasoning: FALLBACK_REASON,
          bucket: classifyBucket(DEFAULT_MID_SCORE),
          fallbackUsed: true,
        }
      }
      return this.scoreSingle({
        doc,
        projectDescription,
        memorySnapshot,
        bucketExamples,
      })
    }

    // LLMQueue.enqueue 的 onProgress 回调签名是 (done, total, lastResult)
    const queueProgress = onProgress
      ? (done: number, total: number, lastResult?: ScoreOutput) => {
          onProgress(done, total, lastResult)
        }
      : undefined

    const queueResults = await this.queue.enqueue<JobInput, JobOutput>(
      jobs,
      handler,
      queueProgress,
    )

    // 把 queueResults 抽成 ScoreOutput 列表（失败的 job 按 fallback 处理）
    const scores: ScoreOutput[] = queueResults.map((r) => {
      if (r.status === 'done' && r.result) {
        return r.result
      }
      // queue 层失败（handler throw）— ScoringAgent.scoreSingle 不抛，所以理论不会进
      // 这里。出于稳健性补一个 fallback。
      const docId = jobs.find((j) => j.jobId === r.jobId)?.input.docId ?? 'unknown'
      return {
        docId,
        score: DEFAULT_MID_SCORE,
        reasoning: FALLBACK_REASON,
        bucket: classifyBucket(DEFAULT_MID_SCORE),
        fallbackUsed: true,
      }
    })

    // cutoff 切桶
    const above: ScoreOutput[] = []
    const below: ScoreOutput[] = []
    for (const s of scores) {
      if (s.score >= cutoff) above.push(s)
      else below.push(s)
    }

    above.sort((a, b) => b.score - a.score)
    below.sort((a, b) => b.score - a.score)

    return { above, below }
  }

  /**
   * 单 doc 评分。
   *
   * 三层兜底：
   * 1. LLM null / parse 失败 → retry 一次
   * 2. retry 也失败 → 返 mid-score 50 + fallbackUsed=true
   * 3. 永不抛（caller 不需要 try/catch）
   */
  async scoreSingle(params: ScoreSingleParams): Promise<ScoreOutput> {
    const { doc, projectDescription, memorySnapshot, bucketExamples = '' } = params

    const promptFile = loadPrompt('agents/scoring')
    const prompt = promptFile.render({
      project_description: projectDescription,
      memory_section: buildMemorySection(memorySnapshot, bucketExamples),
      title: doc.title || '未知',
      doc_type: doc.docType || 'paper',
      source: doc.source || '未知',
      publication_date: pickPublicationDate(doc),
      citation_count: doc.citationCount ?? 0,
      authors: (doc.authors || '未知').slice(0, 200),
      abstract: doc.abstract || '无摘要',
      extra_info: buildExtraInfo(doc),
    })

    for (let attempt = 0; attempt < 2; attempt++) {
      let response: LLMResult | null
      try {
        response = await this.llm.generate(prompt, {
          temperature: 0.15,
          response_format: { type: 'json_object' },
        })
      } catch {
        // throw 视作可重试错误
        if (attempt === 0) continue
        return this.fallback(doc.docId)
      }

      if (!response || !response.text) {
        if (attempt === 0) continue
        return this.fallback(doc.docId)
      }

      const parsed = parseScoringResponse(response.text)
      if (parsed) {
        const score100 = Math.max(0, Math.min(100, Math.round(parsed.score * SCORE_SCALE)))
        return {
          docId: doc.docId,
          score: score100,
          reasoning: parsed.rationale || '',
          bucket: classifyBucket(score100),
          oneLine: parsed.oneLine || undefined,
        }
      }
      // parse 失败 → retry
    }

    return this.fallback(doc.docId)
  }

  private fallback(docId: string): ScoreOutput {
    return {
      docId,
      score: DEFAULT_MID_SCORE,
      reasoning: FALLBACK_REASON,
      bucket: classifyBucket(DEFAULT_MID_SCORE),
      fallbackUsed: true,
    }
  }
}
