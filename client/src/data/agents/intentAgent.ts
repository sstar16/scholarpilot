/**
 * IntentAgent — 自然语言意图解析（移植自 backend `harness/agents/intent_agent.py`）。
 *
 * 从用户自由文本中提取结构化的研究意图，自动生成项目配置。
 * LLM 不可用 / 解析失败 → 返回 null（调用方应回退到手动表单）。
 *
 * 与 backend 差异：
 * - backend 用 `app.harness.prompts.intent_analysis.build_intent_prompt`，client 直接 loadPrompt
 * - 错误日志走 console.warn 而非 logger
 * - 仍然保留三层兜底：
 *   1. JSON mode response_format（OpenAI/DeepSeek 兼容）
 *   2. regex 提取 `{...}`（兜 anthropic / 不支持 JSON mode 的 provider）
 *   3. 校验 + 占位符关键词 + 置信度阈值（_reject 兜底到 cat 文案）
 */
import { loadPrompt } from './promptLoader'
import type { LLMManagerLike } from './types'

// ── 有效值集合（对齐 backend `intent_agent.py:17-25`）─────────────────────

export const VALID_DOMAINS: ReadonlySet<string> = new Set([
  'biology', 'chemistry', 'physics', 'medicine', 'engineering',
  'computer_science', 'mathematics', 'materials_science',
  'environmental_science', 'agriculture', 'psychology',
  'economics', 'social_science', 'law', 'interdisciplinary',
])
export const VALID_DOC_TYPES: ReadonlySet<string> = new Set(['literature', 'patent', 'both'])
export const VALID_SCOPES: ReadonlySet<string> = new Set(['chinese_first', 'international', 'global'])
export const VALID_YEAR_FOCUS: ReadonlySet<string> = new Set(['recent', 'decade', 'all'])

// ── 占位符 / 复读兜底（对齐 backend）─────────────────────────────────────

const _PLACEHOLDER_KEYWORDS = [
  '待明确', '不明确', '未明确', '待确认', '未确认',
  '未知意图', '未识别', '未命名', '通用研究',
] as const

/** 调皮可爱小猫人格兜底文案池（LLM 没给 reply 时随机抽一条，避免复读）。 */
const _DEFAULT_REPLIES = [
  '喵~这句我没 get 到研究方向，再扔个关键词过来？',
  '呜喵？话有点抽象，给只具体的研究主题来嘛~',
  '(￣▽￣) 猫爪挠了半天没挠出方向，换个说法试试？',
  '喵！想查点什么直说，扔个具体的关键词或研究方向过来~',
  '尾巴抖了抖——没听懂，来个研究领域呗？',
  '嘿嘿，这是闲聊模式没错，但想研究啥直接甩过来更好玩~',
] as const

/** 兜底公式化文案的特征（截图里那种"您好！请告诉我您想研究..."）。 */
const _STALE_REPLY_PATTERNS = [
  '您好', '请告诉我您想研究', '请描述您想了解的研究',
  '我将为您', '请随时告诉我',
] as const

// ── 意图枚举 ─────────────────────────────────────────────────────────────

export type UserIntent =
  | 'start_search'
  | 'start_collaboration'
  | 'start_pdf_import'
  | 'configure_push'
  | 'chat'

const VALID_INTENTS = new Set<UserIntent>([
  'start_search',
  'start_collaboration',
  'start_pdf_import',
  'configure_push',
  'chat',
])

// ── 类型 ────────────────────────────────────────────────────────────────

export interface IntentResult {
  is_research_request: boolean
  /** 5 类意图枚举（必需）。 */
  intent: UserIntent
  /** 非研究请求时的小猫回复；研究请求时省略。 */
  reply?: string
  /** 研究请求字段（is_research_request=true 时存在）。 */
  title?: string
  description?: string
  domains?: string[]
  doc_types?: string
  scope?: string
  year_focus?: string
  key_concepts?: string[]
  suggested_sources?: string[]
  confidence?: number
  clarification_needed?: string | null
}

export interface IntentAnalyzeParams {
  userInput: string
  supplementaryContext?: string
}

// ── Agent ───────────────────────────────────────────────────────────────

export class IntentAgent {
  private readonly _llm: LLMManagerLike

  constructor(llm: LLMManagerLike) {
    this._llm = llm
  }

  /**
   * 解析用户自由文本为结构化研究意图。
   *
   * @returns 解析后的 intent dict，或 null（调用方应回退到手动表单）。
   */
  async analyze(params: IntentAnalyzeParams): Promise<IntentResult | null> {
    const { userInput, supplementaryContext = '' } = params

    if (!this._llm) {
      console.warn('[IntentAgent] LLM 不可用，需要 fallback 到手动表单')
      return null
    }
    if (!userInput || userInput.trim().length < 2) {
      return null
    }

    const pf = loadPrompt('agents/intent_analysis')
    const supplementSection = supplementaryContext
      ? `## 用户补充说明\n${supplementaryContext}`
      : ''

    const prompt = pf.render({
      user_input: userInput.slice(0, 1000),
      supplement_section: supplementSection,
    })

    const maxRetries = Number(pf.get('max_retries', 2)) || 2
    const temperature = Number(pf.get('temperature', 0.4)) || 0.4

    // 三层兜底：(1) JSON mode → (2) regex 解析 → (3) 字段校验 + reject 兜底
    for (let attempt = 0; attempt < maxRetries; attempt++) {
      try {
        const result = await this._llm.generate(prompt, {
          temperature,
          response_format: { type: 'json_object' },
        })
        const text = _extractText(result)
        if (!text) {
          if (attempt + 1 < maxRetries) continue
          return null
        }
        const parsed = _parseIntent(text)
        if (parsed) {
          console.info(
            `[IntentAgent] 解析成功: title='${(parsed.title || '').slice(0, 30)}', `
            + `domains=${JSON.stringify(parsed.domains)}, `
            + `doc_types=${parsed.doc_types}, `
            + `confidence=${(parsed.confidence ?? 0).toFixed(2)}`,
          )
          return parsed
        }
        if (attempt + 1 < maxRetries) {
          console.warn(`[IntentAgent] 解析失败，重试: ${text.slice(0, 150)}`)
        }
      } catch (e) {
        console.warn(`[IntentAgent] 解析异常 (attempt ${attempt + 1}):`, e)
        if (attempt + 1 < maxRetries) continue
      }
    }

    return null
  }
}

// ── 工具：text 提取（manager.generate 返回 LLMResult | string | null）────

function _extractText(result: unknown): string | null {
  if (!result) return null
  if (typeof result === 'string') return result
  if (typeof result === 'object' && result !== null && 'text' in result) {
    const t = (result as { text?: unknown }).text
    return typeof t === 'string' ? t : null
  }
  return null
}

// ── 内部：解析 ───────────────────────────────────────────────────────────

/** 构建"非研究请求"短路结果。LLM 给了小猫 reply 就用；否则从兜底池随机抽。 */
function _reject(reply: unknown, intent: UserIntent = 'chat'): IntentResult {
  let text = (typeof reply === 'string' ? reply : '').trim()
  if (!text || _STALE_REPLY_PATTERNS.some(p => text.includes(p))) {
    text = _DEFAULT_REPLIES[Math.floor(Math.random() * _DEFAULT_REPLIES.length)]
  }
  return { is_research_request: false, intent, reply: text.slice(0, 500) }
}

/** 解析 LLM 输出的 intent JSON（与 backend `_parse_intent` 一致）。 */
export function _parseIntent(text: string): IntentResult | null {
  // 优先去 markdown code fence
  let cleaned = text.trim()
  if (cleaned.startsWith('```')) {
    cleaned = cleaned.replace(/^```(?:json)?\s*\n?/, '').replace(/\n?\s*```\s*$/, '')
  }

  // 优先匹配 is_research_request 的拒绝 JSON，再匹配 title JSON，最后兜底
  const m = (
    /\{[\s\S]*"is_research_request"[\s\S]*\}/.exec(cleaned)
    || /\{[\s\S]*"title"[\s\S]*\}/.exec(cleaned)
    || /\{[\s\S]+\}/.exec(cleaned)
  )
  if (!m) return null

  let data: Record<string, unknown>
  try {
    data = JSON.parse(m[0])
  } catch {
    return null
  }

  // 意图字段规范化（先提取，后面 _reject 和成功路径都需要）
  const rawIntentRaw = String(data.intent ?? (data.is_research_request ? 'start_search' : 'chat'))
    .toLowerCase().replace(/[\s-]+/g, '_')
  const parsedIntent: UserIntent = VALID_INTENTS.has(rawIntentRaw as UserIntent)
    ? (rawIntentRaw as UserIntent)
    : 'chat'

  // 非研究请求短路
  if (data.is_research_request === false) {
    return _reject(data.reply, parsedIntent)
  }

  // 校验必需字段
  const rawTitle = data.title
  if (typeof rawTitle !== 'string' || rawTitle.length < 2) {
    return null
  }
  const title = rawTitle.trim()

  // 占位符兜底：LLM 有时仍然会编造"研究意图待明确"这类无意义 title
  if (_PLACEHOLDER_KEYWORDS.some(kw => title.includes(kw))) {
    return _reject(data.clarification_needed)
  }

  // 低置信度兜底：confidence < 0.35 也视为非研究请求
  let confidence = 0.5
  const rawConf = data.confidence
  if (typeof rawConf === 'number' && Number.isFinite(rawConf)) {
    confidence = rawConf
  } else if (typeof rawConf === 'string') {
    const f = parseFloat(rawConf)
    if (Number.isFinite(f)) confidence = f
  }
  if (confidence < 0.45) {
    return _reject(data.clarification_needed, parsedIntent)
  }
  confidence = Math.max(0.0, Math.min(1.0, confidence))

  let description = typeof data.description === 'string' ? data.description : title

  // 校验 domains
  let domains: string[] = []
  if (Array.isArray(data.domains)) {
    domains = (data.domains as unknown[]).filter(
      (d): d is string => typeof d === 'string' && VALID_DOMAINS.has(d),
    )
  }
  if (!domains.length) domains = ['interdisciplinary']

  // 校验 doc_types
  const rawDocTypes = data.doc_types
  const docTypes = typeof rawDocTypes === 'string' && VALID_DOC_TYPES.has(rawDocTypes)
    ? rawDocTypes
    : 'literature'

  // 校验 scope
  const rawScope = data.scope
  const scope = typeof rawScope === 'string' && VALID_SCOPES.has(rawScope)
    ? rawScope
    : 'international'

  // 校验 year_focus
  const rawYearFocus = data.year_focus
  const yearFocus = typeof rawYearFocus === 'string' && VALID_YEAR_FOCUS.has(rawYearFocus)
    ? rawYearFocus
    : 'recent'

  // key_concepts
  let keyConcepts: string[] = []
  if (Array.isArray(data.key_concepts)) {
    keyConcepts = (data.key_concepts as unknown[]).slice(0, 15).map(c => String(c))
  }

  // suggested_sources
  let suggestedSources: string[] = []
  if (Array.isArray(data.suggested_sources)) {
    suggestedSources = (data.suggested_sources as unknown[])
      .filter((s): s is string => typeof s === 'string')
  }
  if (!suggestedSources.length) {
    suggestedSources = ['openalex', 'crossref']
  }

  // clarification_needed
  let clarification: string | null = null
  if (typeof data.clarification_needed === 'string' && data.clarification_needed) {
    clarification = data.clarification_needed
  }

  // 成功路径：intent 优先用解析值，若为 chat 则强制为 start_search（研究请求）
  const finalIntent: UserIntent = parsedIntent === 'chat' ? 'start_search' : parsedIntent

  return {
    is_research_request: true,
    intent: finalIntent,
    title: title.slice(0, 100),
    description: description.trim().slice(0, 2000),
    domains,
    doc_types: docTypes,
    scope,
    year_focus: yearFocus,
    key_concepts: keyConcepts,
    suggested_sources: suggestedSources,
    confidence,
    clarification_needed: clarification,
  }
}
