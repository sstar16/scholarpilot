/**
 * LiteratureWriter — 把文献写进项目本地 markdown workspace。
 *
 * 文件布局：
 *   <AppData>/scholarpilot/projects/<projectId>/library/
 *   ├── docs/
 *   │   ├── <docId>.md      # 单篇文献（YAML frontmatter + body）
 *   │   └── ...
 *   └── index.md             # 索引（按 round / 桶 / tag 组织）
 *
 * 写入策略：
 *   - 单篇 doc 文件：事务式（写到 .tmp → readback 校验 → rename），失败留旧版
 *   - index.md：每次重写，事务式（前缀 .tmp 同上）
 *
 * 与 backend `services/library_writer.py` 的差异：
 *   - 不用 backend 路径；走 client paths.ts 的 projectRoot（slug 命名兼容）
 *   - 单文件 frontmatter 由 LiteratureWriter 自己合成（不复用 memoryRepo 的 yaml subset
 *     来保持 LiteratureWriter 的字段独立演化）
 *
 * Hook 点：
 *   - dispatchSummariesPhase 完成后 → writeDoc(每篇) → writeIndex(汇总)
 */
import { fileExists, readText, removePath, writeText } from './files'
import { PATHS, assertSafeId } from './paths'

/**
 * 把任意 docId 投影成 fs 安全的文件名（保留可读性）。
 * - 允许 `[A-Za-z0-9._\-]`，其它字符（含 `:` `/` 等）替换为 `-`
 * - 起头 / 末尾 `-` 修剪
 * - 防 `..`：直接 reject
 * - 上限 120（保留 .md 后缀空间）
 */
function _toSafeFilename(id: string): string {
  if (!id || id.includes('..')) {
    throw new Error(`unsafe docId for filename: ${id}`)
  }
  const out = id.replace(/[^A-Za-z0-9._\-]/g, '-').replace(/-+/g, '-').replace(/^-+|-+$/g, '')
  if (!out) throw new Error(`docId reduces to empty filename: ${id}`)
  return out.slice(0, 120)
}

// ──────────────────────── Types ────────────────────────

export type LibraryBucket = 'very_relevant' | 'relevant' | 'uncertain' | 'irrelevant' | 'uncategorized'

export interface LibraryDoc {
  /** Document id（client uuid）。 */
  docId: string
  title: string
  /** 作者（多人逗号分隔字符串 / 数组皆可，写出统一字符串）。 */
  authors?: string | string[] | null
  year?: number | null
  /** 数据源（openalex / arxiv / patenthub / ...）。 */
  source?: string | null
  doi?: string | null
  /** 一句话总结（中文优先）。 */
  oneLineSummary?: string | null
  /** AI 摘要（多句中文）。 */
  summary?: string | null
  /** AI 提取的要点。 */
  keyPoints?: string[] | null
  /** Round 内 LLM 评分（0~100）。 */
  score?: number | null
  /** 4 桶分类（缺省视为 uncategorized）。 */
  bucket?: LibraryBucket | null
  /** 概念 / 标签。 */
  tags?: string[] | null
  /** 加入时间（ISO date 'YYYY-MM-DD'），缺省由 writer stamp 当天。 */
  addedAt?: string | null
  /** Round number（用于索引分组）。 */
  roundNumber?: number | null
  /** 期刊 / 会议 / 出版方。 */
  journal?: string | null
  /** Backend 全文 url。 */
  url?: string | null
}

export interface LibraryDocFrontmatter {
  doc_id: string
  title: string
  authors: string
  year: number | string
  source: string
  doi: string
  score: number | string
  bucket: string
  tags: string[]
  added_at: string
  /** 索引展示用：round number（仅 frontmatter 字段；body 不展示）。 */
  round?: number
  /** 期刊 / 会议。 */
  journal?: string
  /** 数据源 url。 */
  url?: string
}

export interface ParsedLiteratureDoc {
  frontmatter: Partial<LibraryDocFrontmatter>
  body: string
  /** 如果文件包含 `## 笔记` 段，单独抽出方便编辑器渲染。 */
  noteMarkdown?: string
}

// ──────────────────────── Helpers ────────────────────────

const _FRONT_RE = /^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n?([\s\S]*)$/
const _NOTES_HEADING_RE = /(^|\n)##\s+笔记\s*\n([\s\S]*)$/

function _isoToday(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function _formatAuthors(a: string | string[] | null | undefined): string {
  if (!a) return ''
  if (Array.isArray(a)) return a.filter(Boolean).join(', ')
  return String(a)
}

function _quoteIfNeeded(s: string): string {
  // YAML 1.1 的最小引用规则：含特殊字符 / 起头空白 / 数字字符串 → 双引号
  if (s === '') return '""'
  if (/[:#'"\[\]{}]|^\s|\s$|^\d+$|^(true|false|null|yes|no)$/i.test(s)) {
    return JSON.stringify(s)
  }
  return s
}

function _serializeArray(arr: string[]): string {
  if (!arr.length) return '[]'
  return '[' + arr.map((x) => _quoteIfNeeded(String(x))).join(', ') + ']'
}

function _serializeFrontmatter(fm: LibraryDocFrontmatter): string {
  const lines: string[] = ['---']
  lines.push(`doc_id: ${_quoteIfNeeded(fm.doc_id)}`)
  lines.push(`title: ${_quoteIfNeeded(fm.title)}`)
  lines.push(`authors: ${_quoteIfNeeded(fm.authors)}`)
  lines.push(`year: ${fm.year === '' ? '""' : fm.year}`)
  lines.push(`source: ${_quoteIfNeeded(fm.source)}`)
  lines.push(`doi: ${_quoteIfNeeded(fm.doi)}`)
  lines.push(`score: ${fm.score === '' ? '""' : fm.score}`)
  lines.push(`bucket: ${_quoteIfNeeded(fm.bucket)}`)
  lines.push(`tags: ${_serializeArray(fm.tags)}`)
  lines.push(`added_at: ${_quoteIfNeeded(fm.added_at)}`)
  if (typeof fm.round === 'number') lines.push(`round: ${fm.round}`)
  if (fm.journal) lines.push(`journal: ${_quoteIfNeeded(fm.journal)}`)
  if (fm.url) lines.push(`url: ${_quoteIfNeeded(fm.url)}`)
  lines.push('---')
  return lines.join('\n')
}

function _parseScalar(s: string): unknown {
  const t = s.trim()
  if (!t) return ''
  if (t === 'true' || t === 'yes') return true
  if (t === 'false' || t === 'no') return false
  if (t === 'null' || t === '~') return null
  if ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'"))) {
    try {
      return JSON.parse(t)
    } catch {
      return t.slice(1, -1)
    }
  }
  if (t.startsWith('[') && t.endsWith(']')) {
    const inner = t.slice(1, -1).trim()
    if (!inner) return []
    return inner.split(',').map((x) => _parseScalar(x.trim()))
  }
  if (/^-?\d+$/.test(t)) return parseInt(t, 10)
  if (/^-?\d+\.\d+$/.test(t)) return parseFloat(t)
  return t
}

function _parseFrontmatter(text: string): { fm: Partial<LibraryDocFrontmatter>; body: string } {
  const m = _FRONT_RE.exec(text)
  if (!m) return { fm: {}, body: text }
  const front = m[1]
  const body = m[2] ?? ''
  const fm: Record<string, unknown> = {}
  for (const raw of front.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const colon = line.indexOf(':')
    if (colon < 0) continue
    const key = line.slice(0, colon).trim()
    const val = line.slice(colon + 1).trim()
    if (!key) continue
    fm[key] = _parseScalar(val)
  }
  return { fm: fm as Partial<LibraryDocFrontmatter>, body }
}

function _formatBody(doc: LibraryDoc, fm: LibraryDocFrontmatter): string {
  const lines: string[] = []
  lines.push('', `# ${doc.title || 'Untitled'}`, '')
  lines.push(`**Authors**: ${fm.authors || '未知'}`)
  if (fm.year) lines.push(`**Year**: ${fm.year}`)
  if (fm.source) lines.push(`**Source**: ${fm.source}`)
  if (fm.doi) lines.push(`**DOI**: ${fm.doi}`)
  if (fm.url) lines.push(`**URL**: ${fm.url}`)
  if (fm.journal) lines.push(`**Journal**: ${fm.journal}`)
  if (typeof fm.score === 'number' && !Number.isNaN(fm.score)) {
    lines.push(`**Score**: ${fm.score}`)
  }
  lines.push('')

  if (doc.oneLineSummary) {
    lines.push('## 一句话总结', '', doc.oneLineSummary, '')
  }

  if (doc.summary) {
    lines.push('## 摘要', '', doc.summary, '')
  }

  if (Array.isArray(doc.keyPoints) && doc.keyPoints.length > 0) {
    lines.push('## 要点')
    lines.push('')
    for (const p of doc.keyPoints) {
      const txt = String(p ?? '').trim()
      if (txt) lines.push(`- ${txt}`)
    }
    lines.push('')
  }

  lines.push('## 笔记', '', '（用户可手动编辑）', '')
  return lines.join('\n')
}

// 单文件路径：library/docs/<safeDocId>.md（不再 slug，用 docId 保稳定）
function _docRelPath(projectId: string, docId: string, projectTitle?: string | null): string {
  assertSafeId(projectId, 'projectId')
  const fn = _toSafeFilename(docId)
  return `${PATHS.projectRoot(projectId, projectTitle)}/library/docs/${fn}.md`
}
function _indexRelPath(projectId: string, projectTitle?: string | null): string {
  assertSafeId(projectId, 'projectId')
  return `${PATHS.projectRoot(projectId, projectTitle)}/library/index.md`
}

/**
 * 事务式写：先写 .tmp，再 rename（client fs 当前没有原生 rename，所以 readback 校验
 * + 复盖目标 + 删 .tmp，等价的「写新内容；旧内容只在 readback 失败时保留」语义）。
 */
async function _atomicWrite(relPath: string, content: string): Promise<void> {
  const tmp = `${relPath}.tmp`
  try {
    await writeText(tmp, content)
    const verify = await readText(tmp)
    if (verify !== content) {
      // tmp 写出和原内容不一致 → 不要污染目标
      throw new Error(`atomic write verify mismatch for ${relPath}`)
    }
    // 直接覆盖目标（fs_write_text 已是 ensure_parent + 覆盖语义）
    await writeText(relPath, content)
  } finally {
    try {
      if (await fileExists(tmp)) await removePath(tmp)
    } catch {
      // 删 tmp 失败不致命
    }
  }
}

// ──────────────────────── Index helpers ────────────────────────

const _BUCKET_LABELS: Record<LibraryBucket, string> = {
  very_relevant: '强相关',
  relevant: '相关',
  uncertain: '待定',
  irrelevant: '不相关',
  uncategorized: '未分类',
}

function _normalizedBucket(b?: string | null): LibraryBucket {
  if (!b) return 'uncategorized'
  const s = String(b).toLowerCase()
  if (s in _BUCKET_LABELS) return s as LibraryBucket
  return 'uncategorized'
}

function _formatIndex(docs: LibraryDoc[]): string {
  const total = docs.length
  const lines: string[] = []
  lines.push('# 文献库索引')
  lines.push('')
  lines.push(`> 共 ${total} 篇 · 由 ScholarPilot 自动维护，编辑请直接打开 docs/`)
  lines.push('')

  if (total === 0) {
    lines.push('_暂无文献_')
    return lines.join('\n')
  }

  // ── 按桶分组 ──
  lines.push('## 按桶分组')
  lines.push('')
  const buckets: Record<LibraryBucket, LibraryDoc[]> = {
    very_relevant: [],
    relevant: [],
    uncertain: [],
    irrelevant: [],
    uncategorized: [],
  }
  for (const d of docs) {
    const b = _normalizedBucket(d.bucket)
    buckets[b].push(d)
  }
  for (const b of ['very_relevant', 'relevant', 'uncertain', 'irrelevant', 'uncategorized'] as LibraryBucket[]) {
    const list = buckets[b]
    if (!list.length) continue
    lines.push(`### ${_BUCKET_LABELS[b]}（${list.length}）`)
    lines.push('')
    for (const d of list) {
      const yr = d.year ? ` (${d.year})` : ''
      const author = _formatAuthors(d.authors)
      const authorPart = author ? ` — ${author.split(',')[0].trim()}` : ''
      lines.push(`- [${d.title || 'Untitled'}](docs/${d.docId}.md)${yr}${authorPart}`)
    }
    lines.push('')
  }

  // ── 按 round 分组 ──
  const byRound = new Map<number, LibraryDoc[]>()
  let hasRound = false
  for (const d of docs) {
    if (typeof d.roundNumber !== 'number') continue
    hasRound = true
    if (!byRound.has(d.roundNumber)) byRound.set(d.roundNumber, [])
    byRound.get(d.roundNumber)!.push(d)
  }
  if (hasRound) {
    lines.push('## 按轮次分组')
    lines.push('')
    const sortedRounds = Array.from(byRound.keys()).sort((a, b) => b - a)
    for (const r of sortedRounds) {
      const list = byRound.get(r)!
      lines.push(`### Round ${r}（${list.length}）`)
      lines.push('')
      for (const d of list) {
        lines.push(`- [${d.title || 'Untitled'}](docs/${d.docId}.md)`)
      }
      lines.push('')
    }
  }

  // ── 按 tag 分组 ──
  const tagBuckets = new Map<string, LibraryDoc[]>()
  for (const d of docs) {
    if (!Array.isArray(d.tags)) continue
    for (const t of d.tags) {
      const tag = String(t || '').trim()
      if (!tag) continue
      if (!tagBuckets.has(tag)) tagBuckets.set(tag, [])
      tagBuckets.get(tag)!.push(d)
    }
  }
  if (tagBuckets.size > 0) {
    lines.push('## 按标签分组')
    lines.push('')
    const sortedTags = Array.from(tagBuckets.keys()).sort((a, b) =>
      tagBuckets.get(b)!.length - tagBuckets.get(a)!.length || a.localeCompare(b),
    )
    for (const tag of sortedTags) {
      const list = tagBuckets.get(tag)!
      lines.push(`### #${tag}（${list.length}）`)
      lines.push('')
      for (const d of list) {
        lines.push(`- [${d.title || 'Untitled'}](docs/${d.docId}.md)`)
      }
      lines.push('')
    }
  }

  return lines.join('\n')
}

// ──────────────────────── Class ────────────────────────

/**
 * LiteratureWriter
 *
 * Per-project markdown workspace 写入器。所有方法对失败 throw（caller 决定吞 / 上抛）。
 */
export class LiteratureWriter {
  constructor(
    public readonly projectId: string,
    public readonly projectTitle: string | null = null,
  ) {
    if (!projectId) throw new Error('LiteratureWriter requires non-empty projectId')
    assertSafeId(projectId, 'projectId')
  }

  /** 单篇文献 → library/docs/<safeDocId>.md（事务式）。 */
  async writeDoc(doc: LibraryDoc): Promise<void> {
    if (!doc?.docId) throw new Error('writeDoc requires docId')
    const fm: LibraryDocFrontmatter = {
      doc_id: doc.docId,
      title: doc.title || '',
      authors: _formatAuthors(doc.authors),
      year: doc.year ?? '',
      source: doc.source ?? '',
      doi: doc.doi ?? '',
      score: typeof doc.score === 'number' && !Number.isNaN(doc.score) ? doc.score : '',
      bucket: _normalizedBucket(doc.bucket),
      tags: Array.isArray(doc.tags) ? doc.tags.map(String).filter(Boolean) : [],
      added_at: doc.addedAt || _isoToday(),
    }
    if (typeof doc.roundNumber === 'number') fm.round = doc.roundNumber
    if (doc.journal) fm.journal = doc.journal
    if (doc.url) fm.url = doc.url

    const front = _serializeFrontmatter(fm)
    const body = _formatBody(doc, fm)
    const text = `${front}\n${body}`
    await _atomicWrite(_docRelPath(this.projectId, doc.docId, this.projectTitle), text)
  }

  /** 写 / 重写 library/index.md（事务式）。 */
  async writeIndex(docs: LibraryDoc[]): Promise<void> {
    const text = _formatIndex(Array.isArray(docs) ? docs : [])
    await _atomicWrite(_indexRelPath(this.projectId, this.projectTitle), text)
  }

  /** 读单篇文献 .md，解析 frontmatter + body。文件不存在返 null。 */
  async readDoc(docId: string): Promise<ParsedLiteratureDoc | null> {
    if (!docId) return null
    const text = await readText(_docRelPath(this.projectId, docId, this.projectTitle))
    if (text == null) return null
    const { fm, body } = _parseFrontmatter(text)
    let noteMarkdown: string | undefined
    const m = _NOTES_HEADING_RE.exec(body)
    if (m) noteMarkdown = (m[2] ?? '').trim()
    return { frontmatter: fm, body, noteMarkdown }
  }

  /**
   * 给单篇文献追加用户笔记。
   *
   * 实现：读现有 .md → 找 `## 笔记` 段（无则附加）→ 在末尾再追加一条带时间戳的 bullet → 重写。
   */
  async appendNote(docId: string, noteMd: string): Promise<void> {
    const note = (noteMd || '').trim()
    if (!note) return
    if (!docId) throw new Error('appendNote requires docId')
    const text = await readText(_docRelPath(this.projectId, docId, this.projectTitle))
    if (text == null) {
      throw new Error(`document not found: ${docId}`)
    }
    const stamp = new Date().toISOString().replace('T', ' ').slice(0, 16)
    const noteBlock = `\n\n> _${stamp}_\n${note}\n`

    let updated: string
    const m = _NOTES_HEADING_RE.exec(text)
    if (m) {
      // 已有 ## 笔记 段：在原段尾追加
      // 替换占位「（用户可手动编辑）」如出现于该段
      const before = text.slice(0, m.index + m[1].length + '## 笔记'.length)
      let after = text.slice(m.index + m[1].length + '## 笔记'.length)
      after = after.replace(/^\s*\n\s*（用户可手动编辑）\s*\n?/, '\n\n')
      updated = `${before}${after.replace(/\s*$/, '')}${noteBlock}`
    } else {
      updated = `${text.replace(/\s*$/, '')}\n\n## 笔记${noteBlock}`
    }
    await _atomicWrite(_docRelPath(this.projectId, docId, this.projectTitle), updated)
  }
}

// ──────────────────────── Module-level helpers (export for tests) ────────────────────────

export const _internal = {
  parseFrontmatter: _parseFrontmatter,
  serializeFrontmatter: _serializeFrontmatter,
  formatIndex: _formatIndex,
  isoToday: _isoToday,
}
