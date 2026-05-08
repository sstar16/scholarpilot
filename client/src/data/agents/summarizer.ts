/**
 * LLM Summarizer — 客户端版（移植自 backend `services/llm_summarizer.py`）。
 *
 * 任务：为单篇文献生成 markdown 4 段式摘要 + 3-5 个 key points + 0-3 个 problems。
 *
 * 三层兜底（对齐项目记忆 `feedback_llm_parser_fallback.md`）：
 *  1. 字段校验：`summary` 必存在 + 非空 + ≥ 50 字符；`key_points` ≥ 1 条
 *  2. 占位符过滤：拒绝包含 `{背景}` / `[abstract]` / `TBD` / `示例` / `placeholder` 等明显未替换的字面量
 *  3. 不达标 → 重试一次（同一次 summarize 内追加纠正提示）；仍失败 → fallback 用 abstract
 *     直接当 summary，标记 `quality='low'`
 *
 * 与 backend 差异：
 *  - backend 走 `_is_cjk_text` 判断 abstract 是否为中文 → 直接复用 + 走 EXTRACT_ONLY；客户端
 *    简化为统一走 SUMMARY_PROMPT，由 LLM 自己决定语言（target_language 强制约束）
 *  - backend `summary_source` 字段保留思路但简化为 `quality: 'high' | 'low'`（low = fallback）
 *  - 不写 sp-api，不调 backend ORM；调用方自行持久化结果
 *
 * 与 LLMQueue 集成：
 *  - 单篇走 `summarizeSingle`（不入队列，调用方可自行 wrap）
 *  - 批量走 `summarizeBatch`，内部用 `LLMQueue.enqueue`，享受持久化 + 续跑
 */
import {
  type LLMJob,
  LLMQueue,
  makeJobId,
} from '../llm/concurrent_queue'
import type { LLMResult } from '../llm/types'
import { loadPrompt } from './promptLoader'

// ──────────────────────── Types ────────────────────────

export interface SummarizeInput {
  docId: string
  title: string
  abstract: string
  /** 可选全文（一般不传，token 开销大；传则优先用全文 8K 截断）。 */
  fulltext?: string
  authors?: string
  year?: number
}

export interface SummarizeOutput {
  docId: string
  /** Markdown 4 段式（背景 / 方法 / 结果 / 启发）。 */
  summary: string
  /** 3-5 条 bullet。 */
  keyPoints: string[]
  /** 0-3 条局限 / 待研究问题。 */
  problems?: string[]
  language: 'zh' | 'en'
  /** `'high'` = LLM 正常生成；`'low'` = fallback 用 abstract 当 summary（LLM 失败）。 */
  quality: 'high' | 'low'
}

// ──────────────────────── LLM Manager 接口（duck-typed） ────────────────────────

/**
 * 复用其他 agent 的 LLMLike 风格：duck-type 一个 generate 方法，方便 vi.fn mock。
 * 与 `client/src/data/llm/manager.ts` 的命名空间 export 兼容。
 */
export interface LLMLike {
  generate(
    prompt: string,
    options?: {
      temperature?: number
      response_format?: { type: 'json_object' | 'text' } | null
    },
  ): Promise<LLMResult | null>
}

// ──────────────────────── 三层兜底 第 2 层：占位符 keywords ────────────────────────

/**
 * 占位符关键词集合 — 对齐 backend `_PLACEHOLDER_KEYWORDS` + 模板字面量补充。
 *
 * 检测策略：
 *  - exact match（lower）：单 token "TBD" / "未提供" 等
 *  - contains 模板片段：`{背景}` / `[abstract]` / `${var}` 等
 */
const _PLACEHOLDER_EXACT = new Set([
  '示例',
  '待补充',
  'example',
  'placeholder',
  'todo',
  'tbd',
  '未提供',
  'not provided',
  'n/a',
  'na',
  '-',
  '?',
  '...',
])

/**
 * 模板字面量片段 —— 摘要里出现这些就视为 LLM 没替换变量。
 *
 * 注意 `[abstract]` 这种 markdown link 的 alt text 在正常摘要里不会出现。
 */
const _PLACEHOLDER_FRAGMENTS = [
  '{背景}',
  '{方法}',
  '{结果}',
  '{启发}',
  '[abstract]',
  '[fulltext]',
  '<placeholder>',
  '${',
  '$title',
  '$abstract',
]

/** 检测一段文本是否包含占位符。 */
function _containsPlaceholder(text: string): boolean {
  if (!text) return true
  const trimmed = text.trim()
  if (!trimmed) return true
  const lower = trimmed.toLowerCase()
  if (_PLACEHOLDER_EXACT.has(lower)) return true
  for (const frag of _PLACEHOLDER_FRAGMENTS) {
    if (lower.includes(frag.toLowerCase())) return true
  }
  return false
}

// ──────────────────────── 内容选择 + 标签 ────────────────────────

interface ContentChoice {
  content: string
  contentLabel: string
}

/** 选用最佳输入：fulltext > abstract > title。返回截断好的内容 + label。 */
function _chooseContent(input: SummarizeInput): ContentChoice | null {
  const fulltext = input.fulltext || ''
  const abstract = input.abstract || ''
  const title = input.title || ''

  if (fulltext.length > 200) {
    return { content: fulltext.slice(0, 8000), contentLabel: '全文节选' }
  }
  if (abstract.length > 50) {
    return { content: abstract.slice(0, 3000), contentLabel: '摘要' }
  }
  if (title.length > 3) {
    return { content: title, contentLabel: '标题' }
  }
  return null
}

// ──────────────────────── JSON Parsing Helper ────────────────────────

/**
 * 从 LLM 回复里提取一个 JSON 对象（含 `summary` 字段）。
 *
 * 兼容：
 *  - markdown ```json fences
 *  - 前后解释文字
 *  - 嵌套花括号（平衡扫描）
 *  - 多个候选对象（取第一个含 `summary` 的）
 */
export function parseSummarizerJson(text: string | null | undefined): unknown {
  if (!text) return null
  let body = text.trim()
  if (body.startsWith('```')) {
    body = body.replace(/^```(?:json)?\s*\n?/, '')
    body = body.replace(/\n?\s*```\s*$/, '')
  }

  // 平衡扫描所有顶层 {...} 对象
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

  for (const cand of candidates) {
    try {
      const obj = JSON.parse(cand)
      if (obj && typeof obj === 'object' && 'summary' in obj) {
        return obj
      }
    } catch {
      continue
    }
  }

  // Last-resort: greedy 取第一个 {...} 区段
  const m = body.match(/\{[\s\S]*\}/)
  if (m) {
    try {
      return JSON.parse(m[0])
    } catch {
      return null
    }
  }
  return null
}

// ──────────────────────── 三层兜底：sanitize ────────────────────────

interface SanitizedSummary {
  summary: string
  keyPoints: string[]
  problems: string[]
  language: 'zh' | 'en'
}

/**
 * Sanitize LLM 输出。返回 null 表示**不达标**（caller 应重试或 fallback）。
 *
 * 三层兜底：
 *  1. 字段校验：summary 字段必须存在 + 非空 + ≥ 50 字符
 *  2. 占位符过滤：summary 含 `{背景}` 等 → 拒绝
 *  3. 置信度阈值：keyPoints < 1 个 → 拒绝
 *
 * 通过校验则归一化输出（裁剪、过滤占位符 keyPoints / problems）。
 */
export function sanitizeSummarizerOutput(raw: unknown): SanitizedSummary | { reason: string } {
  if (!raw || typeof raw !== 'object') return { reason: 'output is not an object' }
  const r = raw as Record<string, unknown>

  // 第 1 层：字段校验 — summary 必存在 + 非空 + ≥ 50 字符
  const summary = typeof r.summary === 'string' ? r.summary.trim() : ''
  if (!summary) return { reason: 'summary missing or empty' }
  if (summary.length < 50) return { reason: `summary too short (${summary.length} < 50)` }

  // 第 2 层：占位符过滤 — summary 不能含模板残留
  if (_containsPlaceholder(summary)) {
    return { reason: 'summary contains placeholder/template fragment' }
  }

  // key_points 数组 — 至少 1 条非占位符
  const keyPointsRaw = Array.isArray(r.key_points) ? r.key_points : []
  const keyPoints: string[] = []
  for (const kp of keyPointsRaw) {
    if (typeof kp !== 'string') continue
    const t = kp.trim()
    if (!t) continue
    if (_containsPlaceholder(t)) continue
    keyPoints.push(t.slice(0, 100))
    if (keyPoints.length >= 5) break
  }
  // 第 3 层：置信度阈值 — keyPoints < 1 个 → 拒绝
  if (keyPoints.length < 1) {
    return { reason: 'keyPoints empty after placeholder filter' }
  }

  // problems 数组（可选）
  const problemsRaw = Array.isArray(r.problems) ? r.problems : []
  const problems: string[] = []
  for (const p of problemsRaw) {
    if (typeof p !== 'string') continue
    const t = p.trim()
    if (!t) continue
    if (_containsPlaceholder(t)) continue
    problems.push(t.slice(0, 200))
    if (problems.length >= 3) break
  }

  // language 字段消毒
  const langRaw = typeof r.language === 'string' ? r.language.toLowerCase() : ''
  const language: 'zh' | 'en' = langRaw === 'en' ? 'en' : 'zh'

  return { summary, keyPoints, problems, language }
}

// ──────────────────────── Summarizer ────────────────────────

export interface SummarizeBatchParams {
  runId: string
  docs: SummarizeInput[]
  targetLanguage?: 'zh' | 'en'
  /** Done count、total、最近一篇结果 — 与 LLMQueue.enqueue 的 progress 签名一致。 */
  onProgress?: (done: number, total: number, lastResult?: SummarizeOutput) => void
}

export interface SummarizeSingleParams {
  doc: SummarizeInput
  targetLanguage?: 'zh' | 'en'
}

export class LLMSummarizer {
  constructor(
    private readonly llm: LLMLike,
    private readonly queue?: LLMQueue,
  ) {}

  /**
   * 单篇摘要 —— 不进队列。
   *
   * 流程：
   *  1. 选 content（fulltext > abstract > title）；都没 → fallback empty
   *  2. LLM generate 一次，sanitize；不达标则重试一次（追加纠正提示）
   *  3. 两次都不达标 → fallback：用 abstract 当 summary，quality='low'
   */
  async summarizeSingle(params: SummarizeSingleParams): Promise<SummarizeOutput> {
    const { doc, targetLanguage = 'zh' } = params
    return this._runSummarize(doc, targetLanguage)
  }

  /**
   * 批量摘要 —— 走 LLMQueue（持久化 + 限流 + 并发）。
   *
   * 调用方必须传 `runId`（用于 SQLite job 表 group by）。
   * 没传 queue 时 fallback 串行（仅供测试）。
   */
  async summarizeBatch(params: SummarizeBatchParams): Promise<SummarizeOutput[]> {
    const { runId, docs, targetLanguage = 'zh', onProgress } = params
    if (!docs.length) return []

    if (!this.queue) {
      // 无队列 → 串行（mainly for test 路径）
      const results: SummarizeOutput[] = []
      for (let i = 0; i < docs.length; i++) {
        const out = await this._runSummarize(docs[i], targetLanguage)
        results.push(out)
        onProgress?.(i + 1, docs.length, out)
      }
      return results
    }

    type JobInput = { doc: SummarizeInput; targetLanguage: 'zh' | 'en' }
    const jobs: LLMJob<JobInput, SummarizeOutput>[] = docs.map((d) => ({
      jobId: makeJobId(),
      runId,
      docId: d.docId,
      agentKind: 'summary',
      input: { doc: d, targetLanguage },
      // promptHash 不必精确（caller 用于去重 / 调试），用 docId+lang 足够
      promptHash: `summary:${d.docId}:${targetLanguage}`,
    }))

    const handler = async (job: LLMJob<JobInput, SummarizeOutput>) => {
      const inp = job.input
      return this._runSummarize(inp.doc, inp.targetLanguage)
    }

    const queueResults = await this.queue.enqueue<JobInput, SummarizeOutput>(
      jobs,
      handler,
      onProgress,
    )

    // queueResults 与 jobs 一一对应；保留 input 顺序（不靠 jobId 重排，因为 enqueue 内部用 Promise.all）
    const byJobId = new Map(queueResults.map((r) => [r.jobId, r]))
    const out: SummarizeOutput[] = []
    for (const j of jobs) {
      const r = byJobId.get(j.jobId)
      if (r && r.status === 'done' && r.result) {
        out.push(r.result)
      } else {
        // queue handler 内部不会 throw（_runSummarize 永远兜底成 'low'），所以走到这里
        // 仅当 queue 自身错误（DB 写失败等）。仍补一个 low quality 占位，让调用方保持顺序。
        out.push(this._lowQualityFallback(j.input.doc, j.input.targetLanguage))
      }
    }
    return out
  }

  // ═══════════════════════════════════════════════════════════════════
  // Internals
  // ═══════════════════════════════════════════════════════════════════

  private async _runSummarize(
    doc: SummarizeInput,
    targetLanguage: 'zh' | 'en',
  ): Promise<SummarizeOutput> {
    if (!doc.docId) {
      throw new Error('docId is required')
    }

    const choice = _chooseContent(doc)
    if (!choice) {
      // 三种字段都没 → 直接 low quality
      return this._lowQualityFallback(doc, targetLanguage)
    }

    const promptFile = loadPrompt('agents/summarizer')
    const baseRendered = promptFile.render({
      title: (doc.title || '').slice(0, 500),
      authors: (doc.authors || '未知').slice(0, 300),
      year: doc.year && doc.year > 0 ? doc.year : 0,
      content_label: choice.contentLabel,
      content: choice.content,
      target_language: targetLanguage,
    })

    let lastErr: string | null = null

    for (let attempt = 0; attempt < 2; attempt++) {
      const prompt
        = attempt === 0
          ? baseRendered
          : `${baseRendered}\n\n# 上一轮失败原因\n${lastErr ?? '解析失败'}\n请严格按上面 JSON 格式重新输出，不要任何额外文字。summary 字段必须 ≥ 100 字符，key_points 至少 3 条。`

      let response: LLMResult | null
      try {
        response = await this.llm.generate(prompt, {
          temperature: 0.3,
          response_format: { type: 'json_object' },
        })
      } catch (e) {
        lastErr = `LLM threw: ${(e as Error).message?.slice(0, 200) ?? 'unknown'}`
        continue
      }

      if (!response || !response.text) {
        lastErr = 'LLM returned empty response'
        continue
      }

      const obj = parseSummarizerJson(response.text)
      if (!obj) {
        lastErr = `JSON parse failed: ${response.text.slice(0, 200)}`
        continue
      }

      const sanitized = sanitizeSummarizerOutput(obj)
      if ('reason' in sanitized) {
        lastErr = sanitized.reason
        continue
      }

      return {
        docId: doc.docId,
        summary: sanitized.summary,
        keyPoints: sanitized.keyPoints,
        problems: sanitized.problems.length > 0 ? sanitized.problems : undefined,
        language: sanitized.language,
        quality: 'high',
      }
    }

    // 两次都失败 → fallback：用 abstract 当 summary
    return this._lowQualityFallback(doc, targetLanguage)
  }

  /**
   * Fallback：LLM 多次失败时用原始 abstract 直接当 summary，quality='low'。
   *
   * 对齐 backend `llm_summarizer.py` 行为：当 LLM 返空或解析失败，仍返回一个 result
   * （不 throw），只是 summary_source / quality 标记成 low，让 UI 能显示「自动摘要失败，
   * 已显示原文摘要」。
   */
  private _lowQualityFallback(
    doc: SummarizeInput,
    targetLanguage: 'zh' | 'en',
  ): SummarizeOutput {
    const fallbackSummary
      = (doc.abstract && doc.abstract.trim())
        || (doc.title && doc.title.trim())
        || '（无可用内容）'
    return {
      docId: doc.docId,
      summary: fallbackSummary.slice(0, 3000),
      keyPoints: [],
      problems: undefined,
      language: targetLanguage,
      quality: 'low',
    }
  }
}
