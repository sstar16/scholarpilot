/**
 * ResearchAgent — 共同研究模式的 LLM 大脑（客户端简化版）。
 *
 * Agentic loop 结构（对齐 prompts/agents/research.md）：
 *   1. 系统消息 = research.md 渲染（含文献库 + history + question）
 *   2. 每轮 LLM 输出一个 action JSON：`probe` / `final` / `search`
 *      - `probe`：调 ProbeAgent.probe(target=docId)；命中作为下一轮 history
 *      - `final`：返 answer + citations，退出 loop
 *      - `search`：fetcherApi 还未对接（Phase C C4 TODO），临时记 actionsTaken
 *   3. JSON 解析三层兜底（与 backend 对齐）：
 *      a. 直接 JSON.parse + action 字段校验
 *      b. 失败 → 同 loop 内追加纠正提示，下一轮 LLM 重试
 *      c. maxIterations 耗尽 → 用 history 里收集到的 partial 信息合成 best-effort answer
 *   4. LLM 抛异常 → graceful fallback（partial answer），不丢用户的对话上下文
 *
 * 与 backend `harness/agents/research_agent.py` 差异：
 * - backend 是两阶段 plan + respond（非 loop）；client 是单循环 agentic（更接近 query_plan_agentic 的形态）
 * - backend 集成 KG 子图 + 笔记 + skill 注入；client B11 只做最小核心：probe + final
 * - 不写本地 SQLite（B11 只移植算法层）
 */
import { ProbeAgent, type ProbeResult } from './probeAgent'
import { loadPrompt } from './promptLoader'
import type { LLMManagerLike } from './types'

// ──────────────────────── Types ────────────────────────

export interface LibraryDoc {
  docId: string
  title: string
  abstract: string
  /** 评分（如有），prompt 排序用。 */
  score?: number
  /** 全文（如有），probe 走它。无全文的文献 LLM 不能 probe。 */
  fulltext?: string
  /** 已有 ai 要点（一句话或 bullets），供 LLM 上下文。 */
  keyPoints?: string[]
  /** 文献来源 URL（OpenAlex/arxiv/DOI 链接）。answer 里只能出现 libraryDocs 的 url。 */
  url?: string
  /** DOI（如有）。 */
  doi?: string
}

export interface ResearchCitation {
  /** 引用文献 docId。 */
  docId: string
  /** 该文献提供的关键证据描述（来自 LLM final 输出）。 */
  evidence: string
}

export interface ResearchAction {
  /** 'probe' / 'final' / 'search' / 其它（unknown 也保留方便 debug）。 */
  action: string
  /** probe 的目标 docId。 */
  target?: string
  /** action 执行结果（probe 命中 / search count / final 全文）。 */
  result?: unknown
}

export interface ResearchResult {
  /** Markdown 答案（含 [N] 引用）。 */
  answer: string
  /** 引用文献清单。 */
  citations: ResearchCitation[]
  /** 实际跑了几轮 loop。 */
  iterations: number
  /** 每轮的 action + result trace（DevTools / 测试用）。 */
  actionsTaken: ResearchAction[]
}

export interface ResearchRespondParams {
  userQuestion: string
  libraryDocs: LibraryDoc[]
  /** 历史对话（role: 'user' | 'assistant'）。 */
  conversationHistory?: Array<{ role: string; content: string }>
  /** 最多 loop 轮数（含 final）。默认 5（与 prompt frontmatter 对齐）。 */
  maxIterations?: number
}

// ──────────────────────── JSON parsing ────────────────────────

/** 平衡扫描提取所有顶层 `{...}`，挑第一个含 `action` 字段的对象。 */
export function parseResearchAction(text: string | null | undefined): Record<string, unknown> | null {
  if (!text) return null
  let body = text.trim()
  if (body.startsWith('```')) {
    body = body.replace(/^```(?:json)?\s*\n?/, '').replace(/\n?\s*```\s*$/, '')
  }

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
      const obj = JSON.parse(cand) as Record<string, unknown>
      if (obj && typeof obj === 'object' && 'action' in obj) {
        return obj
      }
    } catch {
      continue
    }
  }

  // last-resort: greedy
  const m = body.match(/\{[\s\S]*\}/)
  if (m) {
    try {
      const obj = JSON.parse(m[0]) as Record<string, unknown>
      if (obj && typeof obj === 'object') return obj
    } catch {
      return null
    }
  }
  return null
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

// ──────────────────────── Helpers ────────────────────────

function _formatPapersContext(docs: LibraryDoc[]): string {
  if (!docs || docs.length === 0) return '（暂无文献）'
  const lines: string[] = []
  // 排序：score 降序（无 score 视为 0）
  const sorted = [...docs].sort((a, b) => (b.score ?? 0) - (a.score ?? 0))
  for (let i = 0; i < Math.min(sorted.length, 20); i++) {
    const d = sorted[i]
    lines.push(`[${i + 1}] **${(d.title || 'Untitled').slice(0, 200)}**`)
    lines.push(`    doc_id: ${d.docId}`)
    if (typeof d.score === 'number') {
      lines.push(`    score: ${d.score.toFixed(2)}`)
    }
    const abs = (d.abstract || '').trim()
    if (abs) lines.push(`    摘要: ${abs.slice(0, 300)}`)
    if (d.keyPoints && d.keyPoints.length) {
      const kp = d.keyPoints.slice(0, 3).map(k => String(k).slice(0, 80)).join('; ')
      lines.push(`    要点: ${kp}`)
    }
    lines.push(`    全文可用: ${d.fulltext ? '是' : '否'}`)
    lines.push('')
  }
  return lines.join('\n')
}

function _formatActionHistory(actions: ResearchAction[]): string {
  if (!actions.length) return '（尚未执行任何 action）'
  const lines: string[] = []
  for (let i = 0; i < actions.length; i++) {
    const a = actions[i]
    lines.push(`### Round ${i + 1}: ${a.action}${a.target ? ` (target=${a.target})` : ''}`)
    if (a.result !== undefined) {
      const resStr = typeof a.result === 'string' ? a.result : JSON.stringify(a.result)
      lines.push(resStr.slice(0, 1000))
    }
    lines.push('')
  }
  return lines.join('\n')
}

function _formatConversationHistory(history?: Array<{ role: string; content: string }>): string {
  if (!history || history.length === 0) return '（首次提问）'
  const lines: string[] = []
  for (const msg of history.slice(-10)) {
    const role = msg.role === 'user' ? '用户' : '助手'
    const content = (msg.content || '').slice(0, 200)
    lines.push(`${role}: ${content}`)
  }
  return lines.join('\n')
}

/**
 * 抽取 markdown / 纯文本中所有出现的 URL。
 *
 * 抓 `http://...` / `https://...` 直到遇到空白 / `)` / `]` / `>`，
 * 末尾的标点（`,` `.` `;` `:`）剥掉，方便和 metadata 比对。
 */
export function _extractUrls(text: string): string[] {
  if (!text) return []
  const out: string[] = []
  const re = /https?:\/\/[^\s)\]>，。；]+/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    let u = m[0]
    // 剥末尾常见标点
    while (u.length > 0 && /[,.;:!?，。；]/.test(u[u.length - 1])) {
      u = u.slice(0, -1)
    }
    if (u) out.push(u)
  }
  return out
}

/** 把 URL 归一化（lowercase host + 去末尾 `/`），便于和 libraryDocs 的 metadata 对比。 */
function _normUrl(u: string): string {
  try {
    const parsed = new URL(u)
    const host = parsed.host.toLowerCase()
    const path = parsed.pathname.replace(/\/+$/, '')
    return `${parsed.protocol}//${host}${path}${parsed.search}`
  } catch {
    return u.toLowerCase().replace(/\/+$/, '')
  }
}

/** 收集 libraryDocs 里所有合法 URL（含 DOI 形式 `https://doi.org/<doi>`）。 */
function _allowedUrls(docs: LibraryDoc[]): Set<string> {
  const out = new Set<string>()
  for (const d of docs) {
    if (d.url) out.add(_normUrl(d.url))
    if (d.doi) {
      const doi = d.doi.replace(/^https?:\/\/doi\.org\//i, '').trim()
      if (doi) out.add(_normUrl(`https://doi.org/${doi}`))
    }
  }
  return out
}

/**
 * 反幻觉：从 LLM answer 中剔除任何不在 libraryDocs metadata 出现的 URL。
 *
 * 策略（保守，不破坏 markdown 结构）：
 * - 找出所有 http(s) URL → 与 allowed 集合比对（normalized）
 * - 不允许的 URL 替换成 `[URL 已移除]` 标记，便于 caller / 用户识别
 *
 * @returns `{cleaned, removed}` — `removed` 是被剥掉的 URL 列表（去重）
 */
export function _sanitizeAnswerUrls(
  answer: string,
  docs: LibraryDoc[],
): { cleaned: string; removed: string[] } {
  if (!answer) return { cleaned: answer, removed: [] }
  const allowed = _allowedUrls(docs)
  if (allowed.size === 0) {
    // libraryDocs 没 url metadata 时，宽松起见全部保留（不然误伤面太大）
    // 但仍记录 URL 数量便于上层 audit
    const seen = _extractUrls(answer)
    return { cleaned: answer, removed: [] }
  }

  const seen = _extractUrls(answer)
  const removed: string[] = []
  let cleaned = answer
  const seenRemoved = new Set<string>()
  for (const u of seen) {
    if (!allowed.has(_normUrl(u))) {
      // 全文替换该 URL 为占位符（注意转义正则元字符）
      const escaped = u.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      cleaned = cleaned.replace(new RegExp(escaped, 'g'), '[URL 已移除]')
      if (!seenRemoved.has(u)) {
        removed.push(u)
        seenRemoved.add(u)
      }
    }
  }
  return { cleaned, removed }
}

/** Citation 数组消毒：剔除非法项 + docId 必须能在 libraryDocs 命中。 */
function _sanitizeCitations(raw: unknown, docs: LibraryDoc[]): ResearchCitation[] {
  if (!Array.isArray(raw)) return []
  const validIds = new Set(docs.map(d => d.docId))
  const out: ResearchCitation[] = []
  const seen = new Set<string>()
  for (const item of raw.slice(0, 20)) {
    if (!item || typeof item !== 'object') continue
    const obj = item as Record<string, unknown>
    const did = String(obj.doc_id ?? obj.docId ?? '').trim()
    if (!did || !validIds.has(did) || seen.has(did)) continue
    seen.add(did)
    const evidence = String(obj.evidence ?? obj.relevance ?? '').trim().slice(0, 500)
    out.push({ docId: did, evidence })
  }
  return out
}

// ──────────────────────── Agent ────────────────────────

export class ResearchAgent {
  private readonly _llm: LLMManagerLike
  private readonly _probe: ProbeAgent

  constructor(llm: LLMManagerLike, probe: ProbeAgent) {
    this._llm = llm
    this._probe = probe
  }

  /**
   * Agentic 循环回答用户问题。
   *
   * @returns ResearchResult（即便 LLM 全失败也返 partial answer，不抛）
   */
  async respond(params: ResearchRespondParams): Promise<ResearchResult> {
    const { userQuestion, libraryDocs, conversationHistory, maxIterations: maxIterParam } = params

    // 输入校验
    const question = (userQuestion || '').trim()
    if (!question) {
      return {
        answer: '（用户问题为空）',
        citations: [],
        iterations: 0,
        actionsTaken: [],
      }
    }
    const docs = Array.isArray(libraryDocs) ? libraryDocs : []

    // 加载 prompt
    let pf
    try {
      pf = loadPrompt('agents/research')
    } catch (e) {
      console.warn('[ResearchAgent] prompt load failed:', e)
      return {
        answer: '系统提示词加载失败，无法回答。请稍后再试。',
        citations: [],
        iterations: 0,
        actionsTaken: [],
      }
    }

    const maxIterations = maxIterParam ?? Number(pf.get('max_iterations', 5)) ?? 5
    const temperature = Number(pf.get('temperature', 0.3)) || 0.3
    const maxTokens = Number(pf.get('max_tokens', 8192)) || 8192

    const actionsTaken: ResearchAction[] = []
    let iterations = 0
    let parseErrorHint: string | null = null

    for (let i = 0; i < maxIterations; i++) {
      iterations = i + 1

      // 渲染 prompt（每轮都重渲，把最新 action_history 灌进去）
      const systemPrompt = pf.render({
        max_iterations: maxIterations,
        n_papers: docs.length,
        papers_context: _formatPapersContext(docs),
        n_history: actionsTaken.length,
        action_history: _formatActionHistory(actionsTaken),
        question: question.slice(0, 500),
        conversation_history: _formatConversationHistory(conversationHistory),
      })

      // parse error hint 加在 prompt 末尾（让 LLM 看到上一轮的纠错）
      const finalPrompt = parseErrorHint
        ? `${systemPrompt}\n\n[系统纠正] 你上次的回复不是合法 JSON：${parseErrorHint}\n请严格输出一个 JSON 对象。`
        : systemPrompt

      // 第 maxIterations 轮强制 final（在 prompt 里加约束）
      const isLastRound = iterations >= maxIterations
      const promptWithLastHint = isLastRound
        ? `${finalPrompt}\n\n[系统] 这是最后一轮，必须输出 action="final"，不再 probe。`
        : finalPrompt

      // 调 LLM
      let rawText: string | null = null
      try {
        const result = await this._llm.generate(promptWithLastHint, {
          temperature,
          max_tokens: maxTokens,
          response_format: { type: 'json_object' },
        })
        rawText = _extractText(result)
      } catch (e) {
        console.warn(`[ResearchAgent] LLM error (round ${iterations}):`, e)
        // graceful：用现有 actionsTaken 合成 partial answer
        return this._partialAnswer(question, docs, actionsTaken, iterations,
          `LLM 调用失败：${(e as Error).message?.slice(0, 200) ?? 'unknown'}`)
      }

      if (!rawText) {
        return this._partialAnswer(question, docs, actionsTaken, iterations,
          'LLM 返回空响应。')
      }

      // 解析
      const action = parseResearchAction(rawText)
      if (!action) {
        // 三层兜底 b：parse 失败，下一轮加纠错提示重试
        parseErrorHint = rawText.slice(0, 200)
        actionsTaken.push({
          action: '_parse_failed',
          result: rawText.slice(0, 500),
        })
        continue
      }
      parseErrorHint = null

      const actName = String(action.action ?? '').toLowerCase()

      // ── action: final ──
      if (actName === 'final' || actName === 'finalize') {
        const rawAnswer = String(action.answer ?? '').trim()
        const citations = _sanitizeCitations(action.citations, docs)
        // 反幻觉：剥掉不在 libraryDocs metadata 里的 URL
        const { cleaned: answer, removed: removedUrls } = _sanitizeAnswerUrls(rawAnswer, docs)
        actionsTaken.push({
          action: 'final',
          result: {
            answerLen: answer.length,
            citations: citations.length,
            removedUrls: removedUrls.length > 0 ? removedUrls : undefined,
          },
        })
        if (!answer || answer.length < 5) {
          // final 但 answer 空 → partial fallback
          return this._partialAnswer(question, docs, actionsTaken, iterations,
            'LLM 返回 final 但 answer 为空。')
        }
        return {
          answer: answer.slice(0, 15000),
          citations,
          iterations,
          actionsTaken,
        }
      }

      // ── action: probe ──
      if (actName === 'probe') {
        const target = String(action.doc_id ?? action.target ?? '').trim()
        if (!target) {
          actionsTaken.push({ action: 'probe', result: { error: 'missing doc_id' } })
          continue
        }
        const doc = docs.find(d => d.docId === target)
        if (!doc) {
          actionsTaken.push({ action: 'probe', target, result: { error: 'doc not in library' } })
          continue
        }
        if (!doc.fulltext || !doc.fulltext.trim()) {
          actionsTaken.push({ action: 'probe', target, result: { error: 'no fulltext available' } })
          continue
        }
        let probeRes: ProbeResult
        try {
          probeRes = await this._probe.probe({
            docId: doc.docId,
            docTitle: doc.title,
            docFulltext: doc.fulltext,
            userQuestion: question,
          })
        } catch (e) {
          actionsTaken.push({
            action: 'probe',
            target,
            result: { error: `probe error: ${(e as Error).message?.slice(0, 150)}` },
          })
          continue
        }
        actionsTaken.push({
          action: 'probe',
          target,
          result: {
            relevantPassages: probeRes.relevantPassages,
            summary: probeRes.summary,
            confidence: probeRes.confidence,
          },
        })
        continue
      }

      // ── action: search（B11 暂不实现，等 Phase C C4 fetcherApi）──
      if (actName === 'search') {
        // TODO(B11→C4): 接 fetcherApi.search()。客户端目前没有运行时 fetcher API；
        // 见 queryPlanAgent.ts FetcherApiLike 注释，后续 search 工具复用同一接口。
        actionsTaken.push({
          action: 'search',
          target: String(action.query ?? ''),
          result: { error: 'search action not implemented in B11; will land in Phase C C4' },
        })
        continue
      }

      // 未知 action：记下 trace，继续 loop
      actionsTaken.push({
        action: actName || '_unknown',
        result: { error: `unknown action: ${actName}` },
      })
    }

    // maxIterations 耗尽 → 强制返 partial answer
    return this._partialAnswer(question, docs, actionsTaken, iterations,
      `已达 maxIterations=${maxIterations}，未收敛到 final。`)
  }

  // ──────────────────────── Partial answer ────────────────────────

  /**
   * graceful 兜底：根据现有 actionsTaken 合成一个 best-effort 答案。
   *
   * 策略：
   *   1. 提取所有 probe 命中的 passages 作为 evidence
   *   2. 简单拼接成 markdown，标注 confidence=0.3（声明这是 partial）
   *   3. citations 来自 probe 过的 docId
   */
  private _partialAnswer(
    question: string,
    docs: LibraryDoc[],
    actionsTaken: ResearchAction[],
    iterations: number,
    reason: string,
  ): ResearchResult {
    const docTitleById = new Map(docs.map(d => [d.docId, d.title]))
    const probedHits: Array<{ docId: string; title: string; passages: string[]; summary: string }> = []

    for (const a of actionsTaken) {
      if (a.action !== 'probe' || !a.target) continue
      const r = a.result as { relevantPassages?: unknown; summary?: unknown } | undefined
      if (!r) continue
      const passages = Array.isArray(r.relevantPassages)
        ? (r.relevantPassages as unknown[]).filter((s): s is string => typeof s === 'string' && s.trim().length > 0)
        : []
      if (passages.length === 0) continue
      probedHits.push({
        docId: a.target,
        title: docTitleById.get(a.target) || a.target,
        passages,
        summary: typeof r.summary === 'string' ? r.summary : '',
      })
    }

    const lines: string[] = []
    lines.push(`> [部分答案] ${reason}`)
    lines.push('')
    lines.push(`关于「${question.slice(0, 200)}」，目前已收集到的证据：`)
    lines.push('')

    if (probedHits.length === 0) {
      lines.push('未能从已选文献中抽取到与问题直接相关的证据。建议：')
      lines.push('- 重新提问，使用更具体的关键词')
      lines.push('- 补充更多文献到文献库')
    } else {
      probedHits.forEach((h, i) => {
        lines.push(`## [${i + 1}] ${h.title}`)
        if (h.summary) lines.push(`概括：${h.summary}`)
        for (const p of h.passages.slice(0, 3)) {
          lines.push(`> ${p.slice(0, 400)}`)
        }
        lines.push('')
      })
    }

    const citations: ResearchCitation[] = probedHits.map(h => ({
      docId: h.docId,
      evidence: h.summary || (h.passages[0] || '').slice(0, 200),
    }))

    return {
      answer: lines.join('\n'),
      citations,
      iterations,
      actionsTaken,
    }
  }
}
