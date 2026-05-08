/**
 * GraphAgent — 客户端版知识图谱抽取 agent。
 *
 * 任务：从一篇 doc 的 title/authors/year/abstract（可选 fulltext）抽出 2-5 个实体 + 1-3 条关系。
 * 输出 `GraphFragment` 用于 `graphRepo.mergeFragment` 增量合并到本地 nodes/edges JSON。
 *
 * 三层兜底（对齐项目记忆 `feedback_llm_parser_fallback.md`）：
 *  1. zod schema validate 拒绝错 type/relation enum / 非数 weight
 *  2. 占位符过滤（label 是 "string" / 空白 / `<placeholder>` 等明显未替换的 LLM 模板字面量）
 *  3. parse 失败时重试一次（同一次 extract 调用内追加纠正提示），仍失败 throw `GraphExtractionError`
 *
 * 与 backend 差异：
 *  - backend `harness/knowledge_graph/builder.py` 是 deterministic（concept_tags + 共现）+ 后置 LLM 富化；
 *    客户端走 LLM 一次抽完（成本可控：单文档 < $0.005，BYOK 用户自付）
 *  - 不写 SQLite 也不调 sp-api；调用方（Round finalize）拿到 fragment 立刻 `mergeFragment`
 */
import { z } from 'zod'

import type { LLMResult } from '../llm/types'
import { loadPrompt } from './promptLoader'

// ──────────────────────── Types ────────────────────────

/** V1 6 类实体 enum。 */
export const ENTITY_TYPES = [
  'paper',
  'concept',
  'author',
  'organization',
  'method',
  'technology',
] as const
export type EntityType = (typeof ENTITY_TYPES)[number]

/** V1 6 类关系 enum。 */
export const RELATION_TYPES = [
  'cites',
  'extends',
  'contradicts',
  'coauthor',
  'topic',
  'method_of',
] as const
export type RelationType = (typeof RELATION_TYPES)[number]

/** Agent 抽出的实体（不含 source_doc_ids，后由 mergeFragment 注入）。 */
export interface GraphEntity {
  label: string
  type: EntityType
  weight: number
  /** mergeFragment 后会装哪些 doc 引用了它；agent 自己不写。 */
  source_doc_ids: string[]
}

/** Agent 抽出的关系。 */
export interface GraphRelation {
  source: string
  target: string
  relation: RelationType
  weight: number
}

/** GraphAgent.extract 的返回值；feed 给 graphRepo.mergeFragment。 */
export interface GraphFragment {
  entities: GraphEntity[]
  relations: GraphRelation[]
}

// ──────────────────────── LLM Manager 接口（duck-typed） ────────────────────────

/**
 * 复用 `queryPlanAgent.ts` 的 LLMLike 风格：duck-type 一个 generate 方法，方便 vi.fn mock。
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

// ──────────────────────── Errors ────────────────────────

export class GraphExtractionError extends Error {
  constructor(
    message: string,
    public readonly cause?: unknown,
  ) {
    super(message)
    this.name = 'GraphExtractionError'
  }
}

// ──────────────────────── zod schema（三层兜底 第 1 层） ────────────────────────

const _entitySchema = z.object({
  label: z.string().min(1).max(200),
  type: z.enum(ENTITY_TYPES),
  weight: z.number().min(0).max(1),
})

const _relationSchema = z.object({
  source: z.string().min(1).max(200),
  target: z.string().min(1).max(200),
  relation: z.enum(RELATION_TYPES),
  weight: z.number().min(0).max(1),
})

const _fragmentSchema = z.object({
  entities: z.array(_entitySchema).min(1).max(20),
  relations: z.array(_relationSchema).max(20),
})

// ──────────────────────── 占位符过滤（三层兜底 第 2 层） ────────────────────────

/**
 * 明显是 LLM 没替换的模板字面量 / 占位符 / 空白 → 拒绝。
 *
 * 对齐项目记忆 `feedback_llm_parser_fallback.md`：占位符 keyword 检测。
 */
const _PLACEHOLDER_LABELS = new Set([
  'string',
  'placeholder',
  'unknown',
  'n/a',
  'na',
  'none',
  'null',
  '<placeholder>',
  '<unknown>',
  '<entity>',
  '<concept>',
  '<author>',
  '<paper>',
  'todo',
  'tbd',
  'fixme',
])

function _isPlaceholderLabel(label: string): boolean {
  const norm = label.trim().toLowerCase()
  if (!norm) return true
  if (_PLACEHOLDER_LABELS.has(norm)) return true
  // "$xxx" / "${xxx}" 残留模板变量
  if (/^\$\{?\w+\}?$/.test(norm)) return true
  // 整段都是 "..." / "---" / "***" 等
  if (/^[.\-*_=+]{2,}$/.test(norm)) return true
  return false
}

// ──────────────────────── JSON Parsing Helper ────────────────────────

/**
 * 从 LLM 回复里提取一个 JSON 对象。兼容 ```json fence、前后解释文字、嵌套花括号。
 *
 * 与 queryPlanAgent.parseActionJson 设计一致；此处只关心是否含 entities 字段。
 */
export function parseGraphJson(text: string | null | undefined): unknown {
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
      if (obj && typeof obj === 'object' && 'entities' in obj) {
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

// ──────────────────────── GraphAgent ────────────────────────

export interface ExtractParams {
  /** 文档 id，用于装到 entity.source_doc_ids。 */
  docId: string
  title: string
  authors: string
  /** 0 表示未知年；prompt 会原样塞进去。 */
  year: number
  abstract: string
  /** 可选全文（一般不传，太长 token 开销大）。 */
  fulltext?: string
}

export class GraphAgent {
  constructor(private readonly llm: LLMLike) {}

  /**
   * 抽取一篇文档的实体和关系。
   *
   * Throws `GraphExtractionError` 当：
   *  - 入参缺关键字段
   *  - LLM 两次都返 null / 解析失败 / schema 不过 / 全是占位符
   */
  async extract(params: ExtractParams): Promise<GraphFragment> {
    if (!params.docId || !params.title) {
      throw new GraphExtractionError('docId and title are required')
    }

    const promptFile = loadPrompt('agents/graph_extraction')
    const baseRendered = promptFile.render({
      title: params.title.slice(0, 500),
      authors: (params.authors || '未知').slice(0, 500),
      year: params.year > 0 ? params.year : 0,
      abstract: (params.abstract || '').slice(0, 4000),
      fulltext: (params.fulltext || '').slice(0, 8000),
    })

    let lastErr: string | null = null
    let lastRaw: string | null = null

    for (let attempt = 0; attempt < 2; attempt++) {
      // 第二次重试：在 prompt 末尾追加纠正提示（重提 schema）
      const prompt
        = attempt === 0
          ? baseRendered
          : `${baseRendered}\n\n# 上一轮失败原因\n${lastErr ?? '解析失败'}\n请严格按上面 JSON 格式重新输出，不要任何额外文字。`

      let response: LLMResult | null
      try {
        response = await this.llm.generate(prompt, {
          temperature: 0.1,
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
      lastRaw = response.text

      // 三层兜底 第 0 步：JSON parse
      const obj = parseGraphJson(response.text)
      if (!obj) {
        lastErr = `JSON parse failed: ${response.text.slice(0, 200)}`
        continue
      }

      // 三层兜底 第 1 层：zod schema validate
      const parsed = _fragmentSchema.safeParse(obj)
      if (!parsed.success) {
        const issues = parsed.error.issues
          .slice(0, 3)
          .map((i) => `${i.path.join('.')}: ${i.message}`)
          .join('; ')
        lastErr = `schema invalid: ${issues}`
        continue
      }
      const data = parsed.data

      // 三层兜底 第 2 层：占位符 / hallucination 过滤
      const filteredEntities = data.entities.filter(
        (e) => !_isPlaceholderLabel(e.label),
      )
      if (filteredEntities.length === 0) {
        lastErr = 'all entities are placeholders'
        continue
      }
      const validLabels = new Set(filteredEntities.map((e) => e.label))
      const filteredRelations = data.relations.filter(
        (r) =>
          validLabels.has(r.source)
          && validLabels.has(r.target)
          && r.source !== r.target,
      )

      // 装 source_doc_ids（同一 fragment 里所有 entity 都来自同一个 doc）
      const entities: GraphEntity[] = filteredEntities.map((e) => ({
        label: e.label.trim(),
        type: e.type as EntityType,
        weight: e.weight,
        source_doc_ids: [params.docId],
      }))
      const relations: GraphRelation[] = filteredRelations.map((r) => ({
        source: r.source.trim(),
        target: r.target.trim(),
        relation: r.relation as RelationType,
        weight: r.weight,
      }))

      return { entities, relations }
    }

    // 两次重试都失败
    throw new GraphExtractionError(
      `extract failed after 2 attempts: ${lastErr ?? 'unknown'}`,
      lastRaw,
    )
  }
}
