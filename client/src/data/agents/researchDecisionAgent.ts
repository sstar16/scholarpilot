/**
 * ResearchDecisionAgent — 客户端版（移植自 backend `app/harness/agents/research_decision_agent.py`）。
 *
 * 一次 LLM 调用完成"项目意图解析 + 首轮查询方案"。Phase B B9 任务规范要求的
 * 调用形态（`planNewProject`）输出 `ProjectPlan`：
 *   - suggestedTitle: 建议项目标题
 *   - researchScope: 研究方向描述
 *   - initialKeywords: 首轮检索关键词（核心英文术语）
 *   - estimatedRounds: 预估轮次
 *   - reasoning: 决策理由
 *
 * 三层兜底：
 *   1. JSON mode response_format（OpenAI/DeepSeek 兼容）+ regex 提取 JSON
 *   2. malformed → 重试一次（同 prompt，不同温度）
 *   3. 仍失败 → 返回简单 fallback plan（不抛，调用方一定能拿到可用结果）
 *
 * 与 backend 差异：
 * - 输出形态不一样：backend 输出 intent + query_plan 嵌套；client 视角是
 *   `ProjectPlan`（4 个标量字段 + reasoning）。两者由 caller 选用。
 * - 不复用 promptLoader（因为 promptLoader 注册表锁定，B9 阶段不动），改用 `?raw`
 *   原生 vite 导入直接拿 prompt body + frontmatter。
 */
import yaml from 'js-yaml'

import type { LLMResult } from '../llm/types'
import type { LLMManagerLike } from './types'

// vite raw import — 编译时把 md 打成字符串。`?raw` 在 vitest 里也工作。
import researchDecisionRaw from './prompts/agents/research_decision.md?raw'

// ── 公共类型 ────────────────────────────────────────────────────────────

export interface ProjectPlan {
  /** 建议的项目标题（中文，15 字内）。 */
  suggestedTitle: string
  /** 研究方向描述（中文，扩展自用户输入）。 */
  researchScope: string
  /** 首轮检索关键词（英文学术/专利术语优先）。 */
  initialKeywords: string[]
  /** 预估的检索轮次（启发式，1-5）。 */
  estimatedRounds: number
  /** Agent 给出的决策理由。 */
  reasoning: string
}

export interface PlanNewProjectParams {
  /** 用户对研究方向的自由描述。 */
  userDescription: string
  /** 可选示例（参考用户给的例子，影响 LLM 拓展方向）。 */
  examples?: string[]
}

// ── 内部 prompt 解析（绕开 promptLoader 锁定）──────────────────────────────

interface ParsedPrompt {
  body: string
  meta: Record<string, unknown>
}

const _FRONTMATTER_RE = /^---\s*\n([\s\S]*?)\n---\s*\n?/

function _parsePrompt(raw: string): ParsedPrompt {
  const m = _FRONTMATTER_RE.exec(raw)
  if (!m) return { body: raw.trim(), meta: {} }
  let meta: Record<string, unknown> = {}
  try {
    const parsed = yaml.load(m[1] || '')
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      meta = parsed as Record<string, unknown>
    }
  } catch (e) {
    console.warn('[ResearchDecisionAgent] frontmatter parse failed:', e)
  }
  return { body: raw.slice(m[0].length).trim(), meta }
}

const _PROMPT = _parsePrompt(researchDecisionRaw)

/** safe_substitute 风格替换 `$var` / `${var}`。 */
function _renderPrompt(vars: Record<string, string>): string {
  return _PROMPT.body.replace(/\$(?:\{(\w+)\}|(\w+))/g, (m, braced: string, bare: string) => {
    const key = braced ?? bare
    const v = vars[key]
    return v === undefined ? m : v
  })
}

// ── JSON 解析三层兜底（对齐 backend `_parse_decision`）─────────────────────

interface DecisionJson {
  is_research_request?: boolean
  reply?: string | null
  title?: string | null
  description?: string | null
  domains?: unknown
  doc_types?: string | null
  scope?: string | null
  year_focus?: string | null
  key_concepts?: unknown
  suggested_sources?: unknown
  confidence?: number | string | null
  clarification_needed?: string | null
  query_plan?: {
    base_query?: string | null
    chinese_query?: string | null
    year_from?: number | null
    year_to?: number | null
    language_scope?: string | null
    rationale?: string | null
  } | null
}

/** 从 LLM 自由文本里挑一段 JSON。优先含 is_research_request / title 字段。
 *
 *  使用平衡扫描而非贪婪正则，因为 LLM 可能在前后塞别的 `{...}` 片段（如解释里的
 *  示例对象），贪婪正则会跨越多个对象边界导致 JSON.parse 失败。
 */
export function _parseDecisionJson(text: string | null | undefined): DecisionJson | null {
  if (!text) return null
  let cleaned = text.trim()
  if (cleaned.startsWith('```')) {
    cleaned = cleaned.replace(/^```(?:json)?\s*\n?/, '')
    cleaned = cleaned.replace(/\n?\s*```\s*$/, '')
  }

  // 平衡扫描所有顶层 {...}（忽略字符串里的 `{` `}`，按双引号转义规则跳过）
  const candidates: string[] = []
  let depth = 0
  let start = -1
  let inString = false
  let escape = false
  for (let i = 0; i < cleaned.length; i++) {
    const ch = cleaned[i]
    if (inString) {
      if (escape) {
        escape = false
      } else if (ch === '\\') {
        escape = true
      } else if (ch === '"') {
        inString = false
      }
      continue
    }
    if (ch === '"') {
      inString = true
      continue
    }
    if (ch === '{') {
      if (depth === 0) start = i
      depth++
    } else if (ch === '}') {
      depth--
      if (depth === 0 && start >= 0) {
        candidates.push(cleaned.slice(start, i + 1))
        start = -1
      }
    }
  }

  // 优先含 is_research_request 的对象
  const tryParse = (s: string): DecisionJson | null => {
    try {
      return JSON.parse(s) as DecisionJson
    } catch {
      return null
    }
  }

  for (const c of candidates) {
    const obj = tryParse(c)
    if (obj && typeof obj === 'object' && 'is_research_request' in obj) {
      return obj
    }
  }
  for (const c of candidates) {
    const obj = tryParse(c)
    if (obj && typeof obj === 'object' && typeof (obj as { title?: unknown }).title === 'string') {
      return obj
    }
  }
  // 兜底：返第一个能 parse 出来的对象
  for (const c of candidates) {
    const obj = tryParse(c)
    if (obj && typeof obj === 'object') return obj
  }
  return null
}

// ── ProjectPlan 构建（解析成功 → 客户端形态）────────────────────────────────

/** 关键词消毒 / 抽取 —— 优先 query_plan.base_query，回退 key_concepts。 */
function _extractKeywords(d: DecisionJson): string[] {
  // 1) 优先从 query_plan.base_query 切词
  const base = (d.query_plan?.base_query ?? '').trim()
  if (base) {
    const tokens = base.split(/\s+/).map(t => t.trim()).filter(t => t.length >= 2)
    if (tokens.length > 0) return tokens.slice(0, 12)
  }
  // 2) 回退 key_concepts
  if (Array.isArray(d.key_concepts)) {
    const out = (d.key_concepts as unknown[])
      .filter((c): c is string => typeof c === 'string' && c.trim().length >= 2)
      .map(c => c.trim())
    if (out.length > 0) return out.slice(0, 12)
  }
  return []
}

/** 启发式估算轮次：confidence 高 / 关键词多 → 少轮；clarification_needed → 多轮。 */
function _estimateRounds(d: DecisionJson, keywords: string[]): number {
  let conf = 0.5
  const c = d.confidence
  if (typeof c === 'number' && Number.isFinite(c)) conf = c
  else if (typeof c === 'string') {
    const f = parseFloat(c)
    if (Number.isFinite(f)) conf = f
  }
  if (d.clarification_needed) return 4
  if (conf >= 0.8 && keywords.length >= 4) return 2
  if (conf >= 0.6) return 3
  return 4
}

/** 把 LLM 解析结果包装成 ProjectPlan。non-research 输入会回 fallback。 */
function _toProjectPlan(d: DecisionJson, userDescription: string): ProjectPlan | null {
  // 非研究请求 → 直接 null（caller 应 fallback）
  if (d.is_research_request === false) return null

  const title = (d.title ?? '').trim()
  if (!title || title.length < 2) return null

  const description = (d.description ?? title).trim()
  const keywords = _extractKeywords(d)
  if (keywords.length === 0) return null // 没关键词 = 无效 plan

  const estimatedRounds = _estimateRounds(d, keywords)
  const rationale = (d.query_plan?.rationale ?? '').trim()
  const clarification = (d.clarification_needed ?? '').trim()
  const reasoning = [
    rationale ? `策略：${rationale}` : '',
    clarification ? `待澄清：${clarification}` : '',
    `关键词：${keywords.join(', ')}`,
  ].filter(Boolean).join(' | ') || `基于用户描述「${userDescription.slice(0, 40)}」生成的初步方案。`

  return {
    suggestedTitle: title.slice(0, 100),
    researchScope: description.slice(0, 2000),
    initialKeywords: keywords,
    estimatedRounds,
    reasoning: reasoning.slice(0, 500),
  }
}

/** 失败兜底：从 userDescription 切词造个最简 plan，永不抛。 */
function _buildFallbackPlan(userDescription: string, reason: string): ProjectPlan {
  const cleaned = userDescription.trim()
  const tokens = cleaned
    .split(/[\s,，、；;]+/)
    .map(t => t.trim())
    .filter(t => t.length >= 2)
  const keywords = tokens.slice(0, 6).length > 0 ? tokens.slice(0, 6) : [cleaned.slice(0, 30) || 'research']
  return {
    suggestedTitle: cleaned.slice(0, 30) || '未命名研究',
    researchScope: cleaned.slice(0, 200) || '（用户未提供详细描述）',
    initialKeywords: keywords,
    estimatedRounds: 3,
    reasoning: `[fallback: ${reason}] LLM 不可用或解析失败，已基于用户原文切词生成简单方案，建议手动调整。`,
  }
}

// ── Agent ───────────────────────────────────────────────────────────────

export class ResearchDecisionAgent {
  private readonly _llm: LLMManagerLike

  constructor(llm: LLMManagerLike) {
    this._llm = llm
  }

  /**
   * 根据用户描述生成项目方案。
   *
   * 三层兜底：
   *   1. LLM JSON mode → parse 成功 → 返 ProjectPlan
   *   2. parse 失败 → 重试一次（max_retries 次，从 frontmatter 读，默认 2）
   *   3. 最终失败 → 返 fallback plan（不抛）
   */
  async planNewProject(params: PlanNewProjectParams): Promise<ProjectPlan> {
    const userDescription = (params.userDescription || '').trim()
    if (!userDescription || userDescription.length < 2) {
      return _buildFallbackPlan(userDescription || '', 'empty user description')
    }

    let supplementSection = ''
    if (params.examples && params.examples.length > 0) {
      const lines = params.examples
        .filter(s => typeof s === 'string' && s.trim().length > 0)
        .slice(0, 5)
        .map(s => `- ${s.trim()}`)
      if (lines.length > 0) {
        supplementSection = `## 用户补充示例\n${lines.join('\n')}`
      }
    }

    const prompt = _renderPrompt({
      user_input: userDescription.slice(0, 1000),
      supplement_section: supplementSection,
    })

    const maxRetries = Number(_PROMPT.meta.max_retries ?? 2) || 2
    const baseTemperature = Number(_PROMPT.meta.temperature ?? 0.2) || 0.2

    let lastError: string | null = null

    for (let attempt = 0; attempt < maxRetries; attempt++) {
      // 第二次重试用稍高 temperature 让 LLM 跳出格式怪圈
      const temperature = attempt === 0 ? baseTemperature : Math.min(baseTemperature + 0.2, 0.9)
      let result: LLMResult | string | null = null
      try {
        result = await this._llm.generate(prompt, {
          temperature,
          response_format: { type: 'json_object' },
        })
      } catch (e) {
        lastError = `LLM threw: ${(e as Error).message}`
        continue
      }
      const text = _extractText(result)
      if (!text) {
        lastError = 'LLM returned empty'
        continue
      }
      const parsed = _parseDecisionJson(text)
      if (!parsed) {
        lastError = `parse failed: ${text.slice(0, 150)}`
        continue
      }
      const plan = _toProjectPlan(parsed, userDescription)
      if (plan) return plan
      lastError = parsed.is_research_request === false
        ? 'non-research input'
        : 'plan missing required fields (title/keywords)'
    }

    return _buildFallbackPlan(
      userDescription,
      lastError ?? `exhausted ${maxRetries} retries`,
    )
  }
}

// ── helpers exposed for testing ─────────────────────────────────────────

function _extractText(result: unknown): string | null {
  if (!result) return null
  if (typeof result === 'string') return result
  if (typeof result === 'object' && result !== null && 'text' in result) {
    const t = (result as { text?: unknown }).text
    return typeof t === 'string' ? t : null
  }
  return null
}

export const __test__ = {
  parsePrompt: _parsePrompt,
  parseDecisionJson: _parseDecisionJson,
  toProjectPlan: _toProjectPlan,
  buildFallbackPlan: _buildFallbackPlan,
  estimateRounds: _estimateRounds,
  extractKeywords: _extractKeywords,
}
