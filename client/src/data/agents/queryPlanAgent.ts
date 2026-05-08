/**
 * QueryPlan Agent — 客户端版（移植自 backend `app/harness/agents/query_plan_agent.py`）。
 *
 * 两种模式：
 * - `legacyPlan()`: 单次 LLM 调用，快但不自校验（fallback 用）
 * - `agenticPlan()`: Tool-using loop，用 `searchPreview` 试查自校验（推荐）
 *
 * 三层兜底（任务规范 / `feedback_llm_parser_fallback.md`）：
 * 1. agentic LLM JSON 解析失败 → 重试一次（在同一 loop 里追加纠正提示）
 * 2. agentic 仍失败（耗尽 maxIterations 或始终解析不出）→ 自动 fallback 调 `legacyPlan`
 * 3. `legacyPlan` 也失败 → throw `QueryPlanError`
 *
 * 与 backend 差异：
 * - backend `QueryPlan` dataclass 把 sources 拍成一个列表共享 base_query；客户端 spec 要求
 *   每个 source 独立 `{keywords, filters}`，所以这里把 base_query 切词后均摊到所有 sources，
 *   filters 装 year_from/year_to/language_scope/exclude_terms。
 * - 不读 `disabled_sources` Redis 缓存，调用方传进来的 `sources` 列表即真相。
 * - `searchPreview` 工具调用走 `fetcherApi`（**TODO**：客户端 fetcher API 还未实现，目前所有
 *   测试通过 `vi.mock` 注入；正式上线时需要在 `client/src/api/fetcher.ts` 里补一个
 *   `searchPreview(source, keywords)` 端点，或直接在客户端跑 OpenAlex/arXiv 公开 API）。
 */
import type { LLMResult } from '../llm/types'
import { loadPrompt } from './promptLoader'

// ──────────────────────── Types ────────────────────────

/** 单一 source 的检索方案（每个 source 一份）。 */
export interface SourcePlan {
  keywords: string[]
  filters: Record<string, unknown>
}

/** 完整 QueryPlan 输出。 */
export interface QueryPlan {
  /** 每个 source 一份 plan（key=source name）。 */
  perSource: Record<string, SourcePlan>
  /** Agent 给出的 rationale / clarification 信息汇总。 */
  reasoning: string
  /** Agentic loop 实际跑了几次（legacy 路径恒为 0）。 */
  iterations: number
  /** 透传 agent finalize 时的额外字段（base_query、language_scope 等），方便 caller 二次加工。 */
  meta: {
    baseQuery: string
    chineseQuery?: string | null
    yearFrom?: number | null
    yearTo?: number | null
    languageScope: 'chinese_first' | 'international' | 'global'
    excludeTerms: string[]
    clarificationNeeded: boolean
    clarificationMessage: string
    /** 走了哪条路径，便于排查。 */
    mode: 'agentic' | 'legacy'
  }
}

/** Agentic loop 的中间 action JSON 形态。 */
type AgentAction =
  | {
      action: 'search_preview'
      query: string
      source?: string
    }
  | {
      action: 'finalize'
      plan: {
        base_query?: string
        chinese_query?: string | null
        year_from?: number | null
        year_to?: number | null
        language_scope?: string
        rationale?: string
        clarification_needed?: boolean
        clarification_message?: string
        exclude_terms?: string[]
      }
    }
  | { action: string; [k: string]: unknown }

/** Legacy 单次 plan 的 LLM JSON 形态。 */
interface LegacyPlanJson {
  base_query?: string
  chinese_query?: string | null
  expanded_terms?: string[]
  exclude_terms?: string[]
  year_from?: number | null
  year_to?: number | null
  sources?: string[]
  max_per_source?: number
  language_scope?: string
  rationale?: string
}

// ──────────────────────── LLM Manager 接口（duck-typed） ────────────────────────

/**
 * 仅依赖 `generate(prompt, options)` 一个方法，方便测试时注入 mock。
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

// ──────────────────────── fetcherApi 占位 ────────────────────────

/**
 * 客户端 fetcher API 占位类型。
 *
 * **TODO（B5+）**：客户端目前没有 `searchPreview` 实现，正式启用 agentic 模式之前需要：
 * - 选项 A：在 sp-api 加 `POST /api/search/preview` 端点
 * - 选项 B：客户端直接 fetch OpenAlex/arXiv/Crossref 公开 API（绕开 sp-api）
 *
 * 单测中通过 `vi.mock` 注入实现。
 */
export interface FetcherApiLike {
  searchPreview(
    source: string,
    keywords: string,
  ): Promise<{ count: number; topTitles: string[] } | { error: string }>
}

/** 默认 fetcherApi 实现（throw not implemented，强制调用方 inject）。 */
const _DEFAULT_FETCHER_API: FetcherApiLike = {
  async searchPreview() {
    return { error: 'fetcherApi.searchPreview not implemented (B5 TODO)' }
  },
}

// ──────────────────────── Errors ────────────────────────

export class QueryPlanError extends Error {
  constructor(
    message: string,
    public readonly cause?: unknown,
  ) {
    super(message)
    this.name = 'QueryPlanError'
  }
}

// ──────────────────────── JSON Parsing Helpers ────────────────────────

/**
 * 从 agent 回复里提取一个含有 `action` 字段的 JSON 对象。
 *
 * 兼容：
 * - markdown ```json fences
 * - 前后解释文字
 * - 嵌套花括号（用平衡扫描，不用贪婪正则）
 * - 多个候选对象（取第一个含 `action` 的）
 *
 * 对齐 backend `_parse_action_json`。
 */
export function parseActionJson(text: string | null | undefined): AgentAction | null {
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
      if (obj && typeof obj === 'object' && 'action' in obj) {
        return obj as AgentAction
      }
    } catch {
      continue
    }
  }

  // Last-resort: greedy 取第一个 {...} 区段（可能截断）
  const m = body.match(/\{[\s\S]*\}/)
  if (m) {
    try {
      return JSON.parse(m[0]) as AgentAction
    } catch {
      return null
    }
  }
  return null
}

/** 解析 legacy plan 的 LLM JSON。对齐 backend `_parse_query_plan`。 */
export function parseLegacyPlanJson(text: string | null | undefined): LegacyPlanJson | null {
  if (!text) return null
  // 优先匹配含 base_query 字段的对象，避免把别的 JSON 错认成 plan
  let match = text.match(/\{[\s\S]*"base_query"[\s\S]*\}/)
  if (!match) match = text.match(/\{[\s\S]+\}/)
  if (!match) return null

  let data: LegacyPlanJson
  try {
    data = JSON.parse(match[0]) as LegacyPlanJson
  } catch {
    return null
  }
  if (!data.base_query || typeof data.base_query !== 'string' || data.base_query.length < 3) {
    return null
  }
  return data
}

// ──────────────────────── QueryPlanAgent ────────────────────────

export interface AgenticPlanParams {
  projectDescription: string
  /** 历史记忆原文（可选）。 */
  memorySnapshot?: string
  /** 想要规划的 sources 列表（key 必须能在 fetcherApi 里查得到）。 */
  sources: string[]
  /** Agentic loop 上限，默认从 prompt frontmatter 读，否则 5。 */
  maxIterations?: number
}

export interface LegacyPlanParams {
  projectDescription: string
  memorySnapshot?: string
  sources: string[]
  /** 透传给 legacy prompt 的轮次信息（默认 1/5）。 */
  roundNumber?: number
  maxRounds?: number
}

export class QueryPlanAgent {
  constructor(
    private readonly llm: LLMLike,
    private readonly fetcherApi: FetcherApiLike = _DEFAULT_FETCHER_API,
  ) {}

  // ═══════════════════════════════════════════════════════════════════
  // Agentic Mode
  // ═══════════════════════════════════════════════════════════════════

  /**
   * Agentic loop 规划。
   *
   * 三层兜底：
   * 1. JSON parse 失败 → 在 history 里追加纠正提示，下一轮 LLM 重试
   * 2. 耗尽 `maxIterations` 仍未 finalize → fallback 调 `legacyPlan`
   * 3. `legacyPlan` 也失败 → throw `QueryPlanError`
   */
  async agenticPlan(params: AgenticPlanParams): Promise<QueryPlan> {
    const { projectDescription, memorySnapshot = '', sources } = params
    if (!projectDescription || !projectDescription.trim()) {
      throw new QueryPlanError('projectDescription is required')
    }
    if (!Array.isArray(sources) || sources.length === 0) {
      throw new QueryPlanError('sources must be a non-empty array')
    }

    const promptFile = loadPrompt('agents/query_plan_agentic')
    const maxIterations
      = params.maxIterations
      ?? (promptFile.get<number>('max_iterations', 5) as number)
      ?? 5
    const previewSource = promptFile.get<string>('preview_source', 'local_kb') as string

    type Message = { role: 'user' | 'assistant'; content: string }
    const history: Message[] = [
      {
        role: 'user',
        content:
          `【研究描述】\n${projectDescription}\n\n`
          + (memorySnapshot ? `【历史记忆】\n${memorySnapshot}\n\n` : '')
          + '请开始规划。先 search_preview 试你判断的核心概念。',
      },
    ]

    let iterations = 0
    let lastParseError: string | null = null

    for (let i = 0; i < maxIterations; i++) {
      iterations = i + 1
      const prompt = this.renderConversation(history, promptFile.body)

      let response: LLMResult | null
      try {
        response = await this.llm.generate(prompt, {
          temperature: 0.1,
          response_format: { type: 'json_object' },
        })
      } catch (e) {
        return this.fallbackToLegacy(params, `LLM threw: ${(e as Error).message}`)
      }

      if (!response || !response.text) {
        return this.fallbackToLegacy(params, 'LLM returned empty response')
      }

      const action = parseActionJson(response.text)
      if (!action) {
        // 三层兜底 1：parse 失败，让 LLM 在下一轮纠正
        lastParseError = response.text.slice(0, 200)
        history.push({ role: 'assistant', content: response.text.slice(0, 500) })
        history.push({
          role: 'user',
          content: '你的回复不是合法 JSON。请严格输出一个 JSON 对象，无任何其它文字。',
        })
        continue
      }

      // 成功 parse,清掉上一次的 parse error 标记
      lastParseError = null
      history.push({ role: 'assistant', content: JSON.stringify(action) })

      const actName = (action as { action: string }).action

      if (actName === 'search_preview') {
        const a = action as { query?: string; source?: string }
        const query = (a.query ?? '').trim()
        const source = a.source ?? previewSource
        if (!query) {
          history.push({ role: 'user', content: '[tool_result]\n{"error":"empty query"}' })
          continue
        }
        let result: { count: number; topTitles: string[] } | { error: string }
        try {
          result = await this.fetcherApi.searchPreview(source, query)
        } catch (e) {
          result = { error: (e as Error).message?.slice(0, 200) ?? 'unknown' }
        }
        history.push({
          role: 'user',
          content: `[tool_result]\n${JSON.stringify(result)}`,
        })
        continue
      }

      if (actName === 'finalize') {
        const a = action as Extract<AgentAction, { action: 'finalize' }>
        const plan = this.buildQueryPlan(a.plan ?? {}, sources, 'agentic', iterations)
        if (plan) return plan
        // finalize 解析出来 base_query 都没有 → fallback
        return this.fallbackToLegacy(params, 'finalize plan missing base_query')
      }

      // 未知 action：提醒并继续
      history.push({
        role: 'user',
        content: '未知 action。只能用 search_preview 或 finalize。',
      })
    }

    // 三层兜底 2：耗尽 iterations 仍未 finalize → fallback
    return this.fallbackToLegacy(
      params,
      lastParseError
        ? `agentic loop exhausted (last parse error: ${lastParseError})`
        : `agentic loop exhausted after ${maxIterations} iterations`,
    )
  }

  // ═══════════════════════════════════════════════════════════════════
  // Legacy Mode
  // ═══════════════════════════════════════════════════════════════════

  /**
   * 单次 LLM plan（无 search preview 自检）。
   *
   * 失败时 retry 一次；两次都失败 throw `QueryPlanError`。
   */
  async legacyPlan(params: LegacyPlanParams): Promise<QueryPlan> {
    const { projectDescription, memorySnapshot = '', sources, roundNumber = 1, maxRounds = 5 } = params
    if (!projectDescription || !projectDescription.trim()) {
      throw new QueryPlanError('projectDescription is required')
    }
    if (!Array.isArray(sources) || sources.length === 0) {
      throw new QueryPlanError('sources must be a non-empty array')
    }

    const promptFile = loadPrompt('agents/query_plan_legacy')
    const rendered = promptFile.render({
      project_description: projectDescription,
      memory_section: memorySnapshot || '（无历史记忆）',
      round_number: roundNumber,
      max_rounds: maxRounds,
      tool_reliability: '（客户端不传可靠性）',
      disabled_sources: '（由调用方过滤）',
      prev_stats_section: '',
    })

    let lastErr: unknown = null
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const response = await this.llm.generate(rendered, {
          temperature: 0.2,
          response_format: { type: 'json_object' },
        })
        if (!response || !response.text) {
          lastErr = new Error('LLM returned empty')
          continue
        }
        const data = parseLegacyPlanJson(response.text)
        if (!data) {
          lastErr = new Error(`parse failed: ${response.text.slice(0, 150)}`)
          continue
        }
        const plan = this.buildQueryPlanFromLegacy(data, sources)
        if (plan) return plan
        lastErr = new Error('plan missing base_query')
      } catch (e) {
        lastErr = e
      }
    }
    throw new QueryPlanError(
      `legacyPlan failed after 2 attempts: ${(lastErr as Error)?.message ?? 'unknown'}`,
      lastErr,
    )
  }

  // ═══════════════════════════════════════════════════════════════════
  // Helpers
  // ═══════════════════════════════════════════════════════════════════

  private async fallbackToLegacy(
    params: AgenticPlanParams,
    reason: string,
  ): Promise<QueryPlan> {
    try {
      const plan = await this.legacyPlan({
        projectDescription: params.projectDescription,
        memorySnapshot: params.memorySnapshot,
        sources: params.sources,
      })
      return {
        ...plan,
        reasoning: `[fallback from agentic: ${reason}] ${plan.reasoning}`,
      }
    } catch (e) {
      // 三层兜底 3：legacy 也挂 → throw
      throw new QueryPlanError(
        `agentic + legacy both failed. agentic reason: ${reason}; legacy: ${(e as Error).message}`,
        e,
      )
    }
  }

  /** 把对话历史拼成单 string prompt（给不支持 native messages 的 provider）。 */
  private renderConversation(
    history: ReadonlyArray<{ role: string; content: string }>,
    systemPrompt: string,
  ): string {
    const parts = [systemPrompt, '']
    for (const m of history) {
      parts.push(`=== ${m.role.toUpperCase()} ===`)
      parts.push(m.content)
      parts.push('')
    }
    parts.push('=== ASSISTANT ===')
    return parts.join('\n')
  }

  /** 把 agent finalize 的 dict 转成 QueryPlan。返回 null 表示数据不可用。 */
  private buildQueryPlan(
    planData: Extract<AgentAction, { action: 'finalize' }>['plan'],
    sources: string[],
    mode: 'agentic' | 'legacy',
    iterations: number,
  ): QueryPlan | null {
    const baseQuery = (planData.base_query ?? '').trim()
    const clarificationNeeded = Boolean(planData.clarification_needed)
    const clarificationMessage = (planData.clarification_message ?? '').slice(0, 500)

    if (!baseQuery && !clarificationNeeded) return null

    // 年份消毒
    const currentYear = new Date().getFullYear()
    let yearTo = planData.year_to ?? null
    if (typeof yearTo !== 'number' || yearTo > currentYear + 1) yearTo = currentYear
    let yearFrom = planData.year_from ?? null
    if (yearFrom !== null && (typeof yearFrom !== 'number' || yearFrom < 1900)) {
      yearFrom = null
    }

    // language_scope 消毒
    let languageScope = (planData.language_scope ?? 'international') as
      | 'chinese_first'
      | 'international'
      | 'global'
    if (!['chinese_first', 'international', 'global'].includes(languageScope)) {
      languageScope = 'international'
    }

    const excludeTerms = Array.isArray(planData.exclude_terms) ? planData.exclude_terms : []

    // base_query 切词作为 keywords
    const keywords = (baseQuery || 'placeholder')
      .split(/\s+/)
      .filter((w) => w.length >= 2)
    if (keywords.length === 0) keywords.push(baseQuery || 'placeholder')

    const filters: Record<string, unknown> = {
      year_from: yearFrom,
      year_to: yearTo,
      language_scope: languageScope,
      exclude_terms: excludeTerms,
    }

    const perSource: Record<string, SourcePlan> = {}
    for (const s of sources) {
      perSource[s] = { keywords: [...keywords], filters: { ...filters } }
    }

    const rationale = (planData.rationale ?? '').slice(0, 300)
    const reasoning = clarificationNeeded
      ? `[clarification_needed] ${clarificationMessage} | ${rationale}`
      : rationale

    return {
      perSource,
      reasoning,
      iterations,
      meta: {
        baseQuery,
        chineseQuery: planData.chinese_query ?? null,
        yearFrom,
        yearTo,
        languageScope,
        excludeTerms,
        clarificationNeeded,
        clarificationMessage,
        mode,
      },
    }
  }

  /** 用 legacy LLM 输出（已验过 base_query）构造 QueryPlan。 */
  private buildQueryPlanFromLegacy(
    data: LegacyPlanJson,
    callerSources: string[],
  ): QueryPlan | null {
    return this.buildQueryPlan(
      {
        base_query: data.base_query,
        chinese_query: data.chinese_query,
        year_from: data.year_from,
        year_to: data.year_to,
        language_scope: data.language_scope,
        rationale: data.rationale,
        exclude_terms: data.exclude_terms,
        clarification_needed: false,
        clarification_message: '',
      },
      callerSources,
      'legacy',
      0,
    )
  }
}
