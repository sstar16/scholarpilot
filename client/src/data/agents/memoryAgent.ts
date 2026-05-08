/**
 * Memory Agent — 客户端版，从 backend `harness/agents/memory_agent.py` 移植。
 *
 * 责任：
 *   feedback (4-bucket) → LLM → 结构化记忆更新（含 markdown / files / index_md）
 *
 * 与 backend 差异：
 * - 删除 DB / Redis 写入（client 侧 caller 直接走 memoryRepo.applyMemoryUpdate）
 * - LLM 走客户端 LLMManager 单例（BYOK），不再传 llm_manager 实例
 * - 失败永远 graceful return null —— memory 不是关键路径，不能挂主流程
 *
 * 输出 MemoryUpdate 结构对齐 memoryRepo.RemoteMemoryUpdate（caller 可直接喂 applyMemoryUpdate）。
 */
import { llmManager as defaultLlmManager } from '../llm/manager'
import type { LLMResult } from '../llm/types'
import { loadPrompt } from './promptLoader'

// ── 类型 ────────────────────────────────────────────────────────────────

/** 4-bucket 反馈分类，对齐 backend `feedback_buckets[2|1|0|-1]`。
 *
 *  桶意义：
 *  - very_relevant (=2)：用户明确感兴趣 → 提炼正向信号
 *  - relevant      (=1)：相关但不是核心 → 弱正向
 *  - uncertain     (=0)：不确定 → 通常忽略
 *  - irrelevant    (=-1)：明确不感兴趣 → 提炼负向信号 / 排除主题
 */
export type FeedbackBucket = 'very_relevant' | 'relevant' | 'uncertain' | 'irrelevant'

const BUCKET_TO_PROMPT_VAR: Record<FeedbackBucket, string> = {
  very_relevant: 'very_relevant_docs',
  relevant: 'relevant_docs',
  uncertain: 'uncertain_docs',
  irrelevant: 'irrelevant_docs',
}

/** 单条文档反馈（caller 视角，包含分桶 + 标题 + 摘要）。 */
export interface FeedbackEntry {
  docId: string
  bucket: FeedbackBucket
  /** 用户在 UI 给出的可选理由（不进 LLM，但 caller 可记录） */
  reason?: string
  docTitle: string
  docAbstract: string
  /** 数据源（可选，影响 LLM 看到的 [source] 标记）*/
  source?: string
}

/** 单个 .md 文件规格 —— caller 写本地时 frontmatter + body 来源。
 *
 *  与 memoryRepo.RemoteMemoryFile 字段一致，applyMemoryUpdate 可直接消费。
 */
export interface MemoryFileSpec {
  /** snake_case + .md 后缀，不含路径 */
  filename: string
  /** identity / preference / reference / note */
  type: 'identity' | 'preference' | 'reference' | 'note'
  name: string
  description: string
  body: string
}

/** Agent 输出。整体结构 = backend MemoryUpdateResult + caller 视角的 newEntries 等增强。 */
export interface MemoryUpdate {
  /** 单段 markdown（兼容 web）。client caller 一般不直接用，改用 files */
  markdown: string
  /** 多 .md 文件规格（client 写本地用） */
  files: MemoryFileSpec[]
  /** backend 给的"快照式"索引（client 优先 rebuild，仅回滚参考） */
  indexMd: string
  /** 新版本号（caller 写 frontmatter / index 头部用） */
  version: number
  /** 一句话研究方向，索引头部 _当前研究方向：X_ 用 */
  focus: string
  /** caller 视角的增量条目（newEntries / modifiedEntries / removedEntries / reasoning） */
  newEntries: Array<{ topic: string; content: string; weight: number }>
  modifiedEntries: Array<{ topicMatch: string; newContent: string }>
  removedEntries: string[]
  reasoning: string
}

export interface UpdateParams {
  /** 项目描述（影响 LLM prompt 上下文） */
  projectDescription?: string
  /** 现有 MEMORY.md 全文（首次 = '' 或 '(空)'） */
  currentMemorySnapshot: string
  /** 当前版本号（默认 0） */
  memoryVersion?: number
  /** 用户分桶反馈 */
  feedbacks: FeedbackEntry[]
}

// 用于 MemoryAgent.update 入参的 manager 接口（最小子集，方便测试 mock）
export interface LLMGenerator {
  generate: (
    prompt: string,
    options?: { temperature?: number; max_tokens?: number | null; response_format?: { type: 'json_object' | 'text' } | null },
  ) => Promise<LLMResult | string | null>
}

// ── 工具：JSON 三层兜底解析 ───────────────────────────────────────────────

/** 从 LLM 输出解析记忆 JSON（v4 files 字段优先，v3 顶层字段兜底）。
 *
 *  三层兜底（对齐 backend `_parse_memory_response`）：
 *    1. 直接最外层 `{...}` regex 匹配 → JSON.parse
 *    2. 解析失败 → 逐步缩短尾部找有效 JSON（处理尾部垃圾）
 *    3. 仍失败 → null
 */
function _parseMemoryResponse(text: string): Record<string, any> | null {
  if (!text) return null
  const match = /\{[\s\S]*\}/.exec(text)
  if (!match) return null

  const raw = match[0]
  let data: any = null
  try {
    data = JSON.parse(raw)
  } catch {
    // 尝试缩短尾部
    for (let end = raw.length; end > 0; end--) {
      try {
        data = JSON.parse(raw.slice(0, end))
        break
      } catch {
        continue
      }
    }
    if (!data) return null
  }

  // v4: 有 files 列表 + research_focus（必填）
  if (Array.isArray(data?.files)) {
    if (typeof data.research_focus !== 'string') return null
    return data
  }
  // v3 fallback: 顶层 research_focus
  if (typeof data?.research_focus === 'string') return data
  return null
}

function _truncate(s: string, n: number): string {
  return s.length <= n ? s : s.slice(0, n) + '…'
}

function _filesFromLLMResponse(parsed: Record<string, any>): MemoryFileSpec[] {
  const rawFiles = Array.isArray(parsed.files) ? parsed.files : []
  const seen = new Set<string>()
  const out: MemoryFileSpec[] = []

  for (const item of rawFiles) {
    if (!item || typeof item !== 'object') continue
    const filename = String(item.filename ?? '').trim()
    // 强制 snake_case.md 防注入
    if (!filename || !/^[a-z0-9_]+\.md$/.test(filename)) continue
    if (seen.has(filename)) continue
    seen.add(filename)

    let ftype: MemoryFileSpec['type'] = 'note'
    if (['identity', 'preference', 'reference', 'note'].includes(item.type)) {
      ftype = item.type
    }

    const name = String(item.name ?? filename.replace(/_/g, ' ').replace(/\.md$/, '')).trim()
    const description = _truncate(String(item.description ?? '').trim(), 60)
    const body = String(item.body ?? '').trim()
    if (!body) continue

    out.push({ filename, type: ftype, name, description, body })
  }
  return out
}

function _filesFromParsedV3(parsed: Record<string, any>): MemoryFileSpec[] {
  const out: MemoryFileSpec[] = []

  const focus = String(parsed.research_focus ?? '').trim()
  if (focus) {
    out.push({
      filename: 'research_focus.md',
      type: 'identity',
      name: '研究方向',
      description: _truncate(focus, 60),
      body: focus,
    })
  }
  const pref = (parsed.preferred_topics as any[]) || []
  if (pref.length > 0) {
    const items = pref.filter(Boolean)
    out.push({
      filename: 'preferred_topics.md',
      type: 'preference',
      name: '偏好主题',
      description: `${items.length} 个用户关注的主题`,
      body: items.map((t: any) => `- ${t}`).join('\n'),
    })
  }
  const excl = (parsed.excluded_topics as any[]) || []
  if (excl.length > 0) {
    const items = excl.filter(Boolean)
    out.push({
      filename: 'excluded_topics.md',
      type: 'preference',
      name: '排除主题',
      description: `${items.length} 个不感兴趣的方向`,
      body: items.map((t: any) => `- ${t}`).join('\n'),
    })
  }
  const methods = (parsed.methodology_preferences as any[]) || []
  if (methods.length > 0) {
    const items = methods.filter(Boolean)
    out.push({
      filename: 'methodology.md',
      type: 'preference',
      name: '方法偏好',
      description: `${items.length} 个偏好的研究方法`,
      body: items.map((m: any) => `- ${m}`).join('\n'),
    })
  }
  const authors = (parsed.key_authors as any[]) || []
  if (authors.length > 0) {
    const items = authors.filter(Boolean)
    out.push({
      filename: 'authors.md',
      type: 'reference',
      name: '关键作者',
      description: `${items.length} 个重要作者`,
      body: items.map((a: any) => `- ${a}`).join('\n'),
    })
  }
  const sources = (parsed.source_preferences as any[]) || []
  if (sources.length > 0) {
    const items = sources.filter(Boolean)
    out.push({
      filename: 'sources.md',
      type: 'preference',
      name: '来源偏好',
      description: `${items.length} 个偏好的数据源`,
      body: items.map((s: any) => `- ${s}`).join('\n'),
    })
  }
  const notes = String(parsed.notes ?? '').trim()
  if (notes) {
    out.push({
      filename: 'notes.md',
      type: 'note',
      name: '补充说明',
      description: _truncate(notes, 60),
      body: notes,
    })
  }
  return out
}

function _formatIndexMd(files: MemoryFileSpec[], version: number, focus: string): string {
  const lines: string[] = [
    `# 项目记忆 v${version}`,
    '',
    '> AI 自动维护；编辑请直接打开本目录下的 .md 文件',
    '',
  ]
  if (focus) {
    lines.push(`_当前研究方向：${focus}_`)
    lines.push('')
  }
  if (files.length === 0) {
    lines.push('_暂无记忆条目_')
  } else {
    for (const f of files) {
      lines.push(`- [${f.name}](${f.filename}) — ${f.description}`)
    }
  }
  lines.push('')
  return lines.join('\n')
}

function _formatMarkdown(parsed: Record<string, any>, version: number): string {
  const lines: string[] = [`# 研究偏好记忆 v${version}`, '']

  const focus = String(parsed.research_focus ?? '')
  if (focus) lines.push(`## 核心方向\n${focus}\n`)

  const sections: Array<[string, string]> = [
    ['preferred_topics', '## 偏好主题'],
    ['excluded_topics', '## 排除方向'],
    ['methodology_preferences', '## 方法偏好'],
    ['key_authors', '## 关键作者'],
    ['source_preferences', '## 来源偏好'],
  ]
  for (const [key, header] of sections) {
    const items = parsed[key] as any[] | undefined
    if (Array.isArray(items) && items.length > 0) {
      lines.push(header)
      for (const t of items) lines.push(`- ${t}`)
      lines.push('')
    }
  }
  const notes = String(parsed.notes ?? '')
  if (notes) lines.push(`## 备注\n${notes}\n`)

  return lines.join('\n')
}

/** 把分桶 feedbacks 渲染成 prompt 里的 bucket 字符串（每桶最多 10 篇）。 */
function _formatBucket(entries: FeedbackEntry[]): string {
  if (!entries || entries.length === 0) return '（无）'
  const lines: string[] = []
  for (const e of entries.slice(0, 10)) {
    const title = (e.docTitle || '未知').slice(0, 100)
    const summary = e.docAbstract || ''
    const source = e.source || ''
    let line = source ? `- [${source}] ${title}` : `- ${title}`
    if (summary) line += ` — ${summary}`
    lines.push(line)
  }
  return lines.join('\n')
}

function _emptyUpdate(version: number): MemoryUpdate {
  return {
    markdown: '',
    files: [],
    indexMd: '',
    version,
    focus: '',
    newEntries: [],
    modifiedEntries: [],
    removedEntries: [],
    reasoning: 'memory update skipped (no LLM / no feedback / parse failed)',
  }
}

// ── MemoryAgent ─────────────────────────────────────────────────────────

export class MemoryAgent {
  private llm: LLMGenerator

  /** 默认走客户端 LLMManager 单例；测试时传 mock 进来。 */
  constructor(llm?: LLMGenerator | null) {
    this.llm = (llm as LLMGenerator) ?? defaultLlmManager
  }

  /** 4-bucket 反馈 → 结构化记忆更新。失败永远 graceful return _emptyUpdate（不 throw）。
   *
   *  对齐 backend `MemoryAgent.update_memory` 行为：
   *  - 无 LLM / 无反馈 → 立即返回 empty update
   *  - LLM 调一次（temperature 0.2 / json_object response_format）
   *  - 解析三层兜底；失败 → empty update
   *  - 成功 → 组装 MemoryUpdate（v4 优先，v3 兜底）
   */
  async update(params: UpdateParams): Promise<MemoryUpdate> {
    const memoryVersion = params.memoryVersion ?? 0
    const newVersion = memoryVersion + 1

    if (!params.feedbacks || params.feedbacks.length === 0) {
      return _emptyUpdate(memoryVersion)
    }

    // 分桶
    const buckets: Record<FeedbackBucket, FeedbackEntry[]> = {
      very_relevant: [],
      relevant: [],
      uncertain: [],
      irrelevant: [],
    }
    for (const fb of params.feedbacks) {
      if (buckets[fb.bucket]) {
        buckets[fb.bucket].push(fb)
      }
    }
    let promptText: string
    try {
      const pf = loadPrompt('agents/memory_update')
      const renderVars: Record<string, string | number> = {
        project_description: (params.projectDescription || '').slice(0, 500),
        current_memory: params.currentMemorySnapshot || '（首次，无历史记忆）',
        memory_version: memoryVersion,
      }
      for (const b of Object.keys(BUCKET_TO_PROMPT_VAR) as FeedbackBucket[]) {
        renderVars[BUCKET_TO_PROMPT_VAR[b]] = _formatBucket(buckets[b])
      }
      promptText = pf.render(renderVars)
    } catch (e) {
      console.warn('[MemoryAgent] prompt render failed:', e)
      return _emptyUpdate(memoryVersion)
    }

    // 调 LLM —— 失败 graceful 返 empty
    let rawText: string | null = null
    try {
      const result = await this.llm.generate(promptText, {
        temperature: 0.2,
        response_format: { type: 'json_object' },
      })
      if (typeof result === 'string') {
        rawText = result
      } else if (result && typeof (result as LLMResult).text === 'string') {
        rawText = (result as LLMResult).text
      }
    } catch (e) {
      console.warn('[MemoryAgent] LLM call failed:', e)
      return _emptyUpdate(memoryVersion)
    }

    if (!rawText) {
      console.warn('[MemoryAgent] LLM 返回空结果')
      return _emptyUpdate(memoryVersion)
    }

    const parsed = _parseMemoryResponse(rawText)
    if (!parsed) {
      console.warn('[MemoryAgent] JSON 解析失败:', rawText.slice(0, 200))
      return _emptyUpdate(memoryVersion)
    }

    const focus = String(parsed.research_focus ?? '').trim()
    let files: MemoryFileSpec[]
    if (Array.isArray(parsed.files)) {
      files = _filesFromLLMResponse(parsed)
      if (files.length === 0) files = _filesFromParsedV3(parsed)
    } else {
      files = _filesFromParsedV3(parsed)
    }

    const markdown = _formatMarkdown(parsed, newVersion)
    const indexMd = _formatIndexMd(files, newVersion, focus)

    // 增量描述（caller 视角，便于 UI 展示更新摘要）
    const newEntries = files.map((f) => ({
      topic: f.name,
      content: f.body,
      weight: f.type === 'identity' ? 1.0 : f.type === 'preference' ? 0.8 : 0.5,
    }))
    const removedEntries: string[] = Array.isArray(parsed.removed_topics)
      ? (parsed.removed_topics as any[]).map((s: any) => String(s))
      : []
    const modifiedEntries: Array<{ topicMatch: string; newContent: string }>
      = Array.isArray(parsed.modified_topics)
        ? (parsed.modified_topics as any[])
            .filter((m) => m && typeof m === 'object')
            .map((m: any) => ({
              topicMatch: String(m.topic_match ?? m.topic ?? ''),
              newContent: String(m.new_content ?? m.content ?? ''),
            }))
            .filter((m) => m.topicMatch && m.newContent)
        : []
    const reasoning = String(parsed.version_summary ?? parsed.reasoning ?? '').trim()
      || 'memory updated from feedback'

    return {
      markdown,
      files,
      indexMd,
      version: newVersion,
      focus,
      newEntries,
      modifiedEntries,
      removedEntries,
      reasoning,
    }
  }
}

// ── 单例便捷入口 ─────────────────────────────────────────────────────────

let _singleton: MemoryAgent | null = null
export function getMemoryAgent(): MemoryAgent {
  if (!_singleton) _singleton = new MemoryAgent()
  return _singleton
}

/** 测试用：替换内部单例 / 重置。 */
export function _resetMemoryAgentForTesting(replacement: MemoryAgent | null = null): void {
  _singleton = replacement
}
