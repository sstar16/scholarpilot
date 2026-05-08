/**
 * ProbeAgent — 协作研究模式的「精读探针」（客户端简化版）。
 *
 * 设计选择（与 backend 差异）：
 * - **不分段并行**：backend `harness/agents/probe_agent.py` 把全文切 N 段并行 LLM；
 *   client 端为减少 token 成本 + 简化调用合同，把整篇全文一次性丢进 prompt
 *   （prompt 内已硬截 7000 字符）。代价是：超长 paper 会丢失尾部内容；后续可在
 *   ResearchAgent 上层做段切分。
 * - **缓存接口外置**：B11 不直接依赖 SQLite。caller 通过 `cacheGet/cacheSet`
 *   callback 注入持久化（client 侧通常走 `<AppData>/scholarpilot/projects/<id>/probe_cache/`）。
 *
 * 三层兜底（feedback_llm_parser_fallback.md）：
 *   1. cacheGet 命中 → 直接返，不调 LLM
 *   2. LLM 调一次 → JSON 解析失败 → 重试一次
 *   3. 仍失败 → 返 empty fallback（confidence=0，passages=[]）
 */
import { loadPrompt } from './promptLoader'
import type { LLMManagerLike } from './types'

// ──────────────────────── Types ────────────────────────

export interface ProbeResult {
  /** 原文逐字引用列表（按相关性降序）。 */
  relevantPassages: string[]
  /** 一句话概括：探针发现了什么。 */
  summary: string
  /** 0~1，relevance 综合置信度。 */
  confidence: number
}

export interface ProbeParams {
  docId: string
  docTitle: string
  docFulltext: string
  userQuestion: string
  /**
   * 缓存读 callback（可选）。命中直接返，不调 LLM。
   * key 由 agent 内部生成（doc_id + question hash）。
   */
  cacheGet?: (key: string) => Promise<ProbeResult | null>
  /** 缓存写 callback（可选）。新结果写入。 */
  cacheSet?: (key: string, val: ProbeResult) => Promise<void>
}

// ──────────────────────── Helpers ────────────────────────

/**
 * 缓存 key 格式：`probe:<docId>:<questionHashHex>`。
 *
 * 用 djb2 字符串哈希（不引外部依赖；碰撞概率对 cache key 足够低）。
 */
function _cacheKey(docId: string, question: string): string {
  let h = 5381
  const q = question.trim()
  for (let i = 0; i < q.length; i++) {
    h = ((h << 5) + h + q.charCodeAt(i)) >>> 0
  }
  return `probe:${docId}:${h.toString(16)}`
}

/**
 * LLM 输出 → ProbeResult。
 *
 * 兼容两种 schema：
 * - prompt 默认 schema：`{relevant, relevance_score, excerpt_quote, insight, concepts}`（单 quote）
 * - 简化 schema：`{relevant_passages: string[], summary, confidence}`（多 quote，给上层 ResearchAgent 用）
 *
 * 实际 LLM 倾向于按 prompt 默认 schema 输出（probe.md 写得很死），所以这里把单 quote 包成数组。
 */
export function _parseProbeResponse(text: string | null | undefined): ProbeResult | null {
  if (!text) return null

  // 剥 markdown fence
  let body = text.trim()
  if (body.startsWith('```')) {
    body = body.replace(/^```(?:json)?\s*\n?/, '').replace(/\n?\s*```\s*$/, '')
  }

  // 优先匹配含 relevant 字段的对象（probe schema），否则随便挑第一个 {...}
  let match = /\{[\s\S]*"relevant"[\s\S]*\}/.exec(body)
  if (!match) match = /\{[\s\S]+\}/.exec(body)
  if (!match) return null

  let data: Record<string, unknown>
  try {
    data = JSON.parse(match[0]) as Record<string, unknown>
  } catch {
    return null
  }

  // ── schema A：简化版（多 quote） ──
  if (Array.isArray((data as any).relevant_passages)) {
    const passages = ((data as any).relevant_passages as unknown[])
      .filter((s): s is string => typeof s === 'string' && s.trim().length > 0)
      .slice(0, 6)
    const summary = typeof data.summary === 'string' ? data.summary : ''
    const conf = _coerceConfidence(data.confidence)
    return {
      relevantPassages: passages,
      summary: summary.trim().slice(0, 600),
      confidence: conf,
    }
  }

  // ── schema B：probe.md 默认 schema（单 quote） ──
  if ('relevant' in data) {
    const isRelevant = data.relevant === true
    if (!isRelevant) {
      // relevant=false 视为成功探针但无命中
      return { relevantPassages: [], summary: '', confidence: 0.0 }
    }
    const quote = typeof data.excerpt_quote === 'string' ? data.excerpt_quote.trim() : ''
    const insight = typeof data.insight === 'string' ? data.insight.trim() : ''
    if (!quote) {
      // relevant=true 但没 quote → 视为低质量，但保留 insight
      return {
        relevantPassages: [],
        summary: insight.slice(0, 300),
        confidence: 0.3,
      }
    }
    const conf = _coerceConfidence(
      typeof data.relevance_score !== 'undefined' ? data.relevance_score : data.confidence,
    )
    return {
      relevantPassages: [quote.slice(0, 800)],
      summary: insight.slice(0, 300),
      confidence: conf,
    }
  }

  return null
}

function _coerceConfidence(raw: unknown): number {
  let v = 0.5
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    v = raw
  } else if (typeof raw === 'string') {
    const f = parseFloat(raw)
    if (Number.isFinite(f)) v = f
  }
  return Math.max(0.0, Math.min(1.0, v))
}

function _extractText(result: unknown): string | null {
  if (!result) return null
  if (typeof result === 'string') return result
  if (typeof result === 'object' && result !== null && 'text' in result) {
    const t = (result as { text?: unknown }).text
    return typeof t === 'string' ? t : null
  }
  return null
}

const _EMPTY_FALLBACK: ProbeResult = {
  relevantPassages: [],
  summary: '',
  confidence: 0.0,
}

// ──────────────────────── Agent ────────────────────────

export class ProbeAgent {
  private readonly _llm: LLMManagerLike

  constructor(llm: LLMManagerLike) {
    this._llm = llm
  }

  /**
   * 精读单篇文献的全文，回答用户问题。
   *
   * - 优先 cacheGet（key = docId + questionHash）
   * - LLM 调用 1+1 retry；仍失败 → empty fallback（不抛）
   * - 成功 → cacheSet（caller 决定持久化策略）
   */
  async probe(params: ProbeParams): Promise<ProbeResult> {
    const { docId, docTitle, docFulltext, userQuestion, cacheGet, cacheSet } = params

    // 输入校验：缺关键字段直接返 empty
    const question = (userQuestion || '').trim()
    const fulltext = (docFulltext || '').trim()
    if (!docId || !question || !fulltext) {
      return _EMPTY_FALLBACK
    }

    // 缓存
    const key = _cacheKey(docId, question)
    if (cacheGet) {
      try {
        const hit = await cacheGet(key)
        if (hit) return hit
      } catch (e) {
        console.warn('[ProbeAgent] cacheGet failed:', e)
      }
    }

    // 渲染 prompt
    let prompt: string
    try {
      const pf = loadPrompt('agents/probe')
      // 把整篇全文当做"一段"喂给 prompt（idx=0, label=docTitle）
      prompt = pf.render({
        question: question.slice(0, 500),
        section_idx: 0,
        section_label: (docTitle || 'Full Document').slice(0, 80),
        char_start: 0,
        char_end: Math.min(fulltext.length, 7000),
        section_text: fulltext.slice(0, 7000),
      })
    } catch (e) {
      console.warn('[ProbeAgent] prompt render failed:', e)
      return _EMPTY_FALLBACK
    }

    // 1+1 retry
    let result: ProbeResult | null = null
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const raw = await this._llm.generate(prompt, {
          temperature: 0.1,
          max_tokens: 1024,
          response_format: { type: 'json_object' },
        })
        const text = _extractText(raw)
        if (!text) {
          if (attempt + 1 < 2) continue
          break
        }
        const parsed = _parseProbeResponse(text)
        if (parsed) {
          result = parsed
          break
        }
        if (attempt + 1 < 2) {
          console.warn('[ProbeAgent] parse failed, retrying:', text.slice(0, 150))
        }
      } catch (e) {
        console.warn(`[ProbeAgent] LLM error (attempt ${attempt + 1}):`, e)
        if (attempt + 1 < 2) continue
        break
      }
    }

    if (!result) {
      result = _EMPTY_FALLBACK
    }

    // 缓存写（只有解析出非空结果才写，避免污染缓存）
    if (cacheSet && result.confidence > 0) {
      try {
        await cacheSet(key, result)
      } catch (e) {
        console.warn('[ProbeAgent] cacheSet failed:', e)
      }
    }

    return result
  }
}
