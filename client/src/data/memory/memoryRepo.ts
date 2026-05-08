/**
 * 项目记忆 repo（学 Claude Code MEMORY.md 模式）
 *
 * 文件布局：
 *   <AppData>/scholarpilot/projects/<project_uuid>/memory/
 *   ├── MEMORY.md              # 索引
 *   ├── identity.md            # 研究身份
 *   ├── feedback_*.md          # 反馈偏好
 *   ├── round_<n>.md           # 每轮摘要
 *   ├── source_preference.md   # 数据源偏好
 *   └── decisions.md           # 决策记录
 *
 * 路径走 fs/paths.ts 的 PATHS.memoryDir/memoryFile，自动支持 slug 命名 + legacy UUID 兜底。
 *
 * 不走 backend / 不入 SQLite —— 客户端文件系统是单一真相。
 */
import { listDir, readText, writeText, removePath, fileExists } from '../fs/files'
import { PATHS } from '../fs/paths'

export type MemoryType = 'identity' | 'feedback' | 'summary' | 'preference' | 'decision' | 'index' | string

export interface MemoryFrontmatter {
  /** 人类可读名称（用于 MEMORY.md 索引展示）*/
  name?: string
  /** 一句话描述（用于索引展示）*/
  description?: string
  /** 记忆类型 */
  type?: MemoryType
  /** 上次更新时间（unix ms），写入时自动 stamp */
  updated_at?: number
  [key: string]: unknown
}

export interface ParsedMemory {
  meta: MemoryFrontmatter
  body: string
}

export interface MemoryFileEntry {
  name: string                 // 含扩展名，如 "MEMORY.md"
  type: MemoryType | null      // 来自 frontmatter；listMemoryFiles 不读 body 故为 null
  updated_at: number           // 文件 mtime（unix ms）
  size: number
}

// ────────────── frontmatter parser（最小 yaml subset）──────────────

const FRONT_RE = /^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n?([\s\S]*)$/

export function parseFrontmatter(text: string): ParsedMemory {
  const m = FRONT_RE.exec(text)
  if (!m) return { meta: {}, body: text }
  const front = m[1]
  const body = m[2] ?? ''
  const meta: MemoryFrontmatter = {}
  for (const raw of front.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    const colon = line.indexOf(':')
    if (colon < 0) continue
    const key = line.slice(0, colon).trim()
    const valRaw = line.slice(colon + 1).trim()
    if (!key) continue
    meta[key] = parseScalar(valRaw)
  }
  return { meta, body }
}

function parseScalar(s: string): unknown {
  if (!s) return ''
  if (s === 'true' || s === 'yes') return true
  if (s === 'false' || s === 'no') return false
  if (s === 'null' || s === '~') return null
  if (/^-?\d+$/.test(s)) return parseInt(s, 10)
  if (/^-?\d+\.\d+$/.test(s)) return parseFloat(s)
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
    return s.slice(1, -1)
  }
  if (s.startsWith('[') && s.endsWith(']')) {
    const inner = s.slice(1, -1).trim()
    if (!inner) return []
    return inner.split(',').map((item) => parseScalar(item.trim()))
  }
  return s
}

export function serializeWithFrontmatter(meta: MemoryFrontmatter, body: string): string {
  const keys = Object.keys(meta).filter((k) => meta[k] !== undefined)
  if (keys.length === 0) return body
  const lines: string[] = ['---']
  for (const k of keys) {
    lines.push(`${k}: ${serializeScalar(meta[k])}`)
  }
  lines.push('---', '', body)
  return lines.join('\n')
}

function serializeScalar(v: unknown): string {
  if (v === null) return 'null'
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  if (typeof v === 'number') return String(v)
  if (Array.isArray(v)) return '[' + v.map((x) => serializeScalar(x)).join(', ') + ']'
  const s = String(v)
  if (/[:#'"\[\]\n]/.test(s)) return JSON.stringify(s)
  return s
}

// ────────────── 路径辅助（slug 优先 + legacy UUID 兜底）──────────────

function memoryDir(projectId: string, projectTitle?: string | null): string {
  return PATHS.memoryDir(projectId, projectTitle)
}

function memoryFile(projectId: string, filename: string, projectTitle?: string | null): string {
  validateFilename(filename)
  return PATHS.memoryFile(projectId, filename, projectTitle)
}

function memoryFileLegacy(projectId: string, filename: string): string {
  validateFilename(filename)
  return PATHS.memoryFileLegacy(projectId, filename)
}

/** 防止 ../ / windows drive prefix 等绕过 sandbox（虽 Rust 端 resolve_safe 也会拦，提前拒省一次 IPC）*/
function validateFilename(filename: string): void {
  if (!filename || filename.includes('..') || filename.includes('/') || filename.includes('\\')) {
    throw new Error(`invalid memory filename: ${filename}`)
  }
}

// ────────────── repo API ──────────────

/** 列项目所有 memory .md 文件（不读 body，只看文件元信息）*/
export async function listMemoryFiles(
  projectId: string,
  projectTitle?: string | null,
): Promise<MemoryFileEntry[]> {
  const slugDir = memoryDir(projectId, projectTitle)
  let entries = await listDir(slugDir)
  // 若 slug 路径空目录 + projectTitle 提供，再试 legacy UUID 路径
  if (entries.length === 0 && projectTitle) {
    entries = await listDir(PATHS.memoryDirLegacy(projectId))
  }
  const out: MemoryFileEntry[] = []
  for (const e of entries) {
    if (e.is_dir) continue
    if (!e.name.endsWith('.md')) continue
    out.push({
      name: e.name,
      type: null,
      updated_at: e.modified_ms,
      size: e.size,
    })
  }
  return out
}

/** 读 memory 文件并解析 frontmatter；不存在 → null */
export async function readMemoryFile(
  projectId: string,
  filename: string,
  projectTitle?: string | null,
): Promise<ParsedMemory | null> {
  let text = await readText(memoryFile(projectId, filename, projectTitle))
  if (text == null && projectTitle) {
    text = await readText(memoryFileLegacy(projectId, filename))
  }
  if (text == null) return null
  return parseFrontmatter(text)
}

/** 读 raw markdown 不解析（编辑器 / 直接渲染时用）*/
export async function readMemoryRaw(
  projectId: string,
  filename: string,
  projectTitle?: string | null,
): Promise<string | null> {
  let text = await readText(memoryFile(projectId, filename, projectTitle))
  if (text == null && projectTitle) {
    text = await readText(memoryFileLegacy(projectId, filename))
  }
  return text
}

/**
 * 写 memory 文件（自动 stamp `updated_at`）。
 * Rust 端 fs_write_text 会 ensure_parent，目录不存在自动建。
 */
export async function writeMemoryFile(
  projectId: string,
  filename: string,
  meta: MemoryFrontmatter,
  body: string,
  projectTitle?: string | null,
): Promise<void> {
  const finalMeta: MemoryFrontmatter = { ...meta, updated_at: Date.now() }
  const text = serializeWithFrontmatter(finalMeta, body)
  await writeText(memoryFile(projectId, filename, projectTitle), text)
}

/** 写 raw markdown（不加 frontmatter；MEMORY.md 索引等用）*/
export async function writeMemoryRaw(
  projectId: string,
  filename: string,
  content: string,
  projectTitle?: string | null,
): Promise<void> {
  await writeText(memoryFile(projectId, filename, projectTitle), content)
}

export async function deleteMemoryFile(
  projectId: string,
  filename: string,
  projectTitle?: string | null,
): Promise<void> {
  await removePath(memoryFile(projectId, filename, projectTitle))
}

export async function memoryFileExists(
  projectId: string,
  filename: string,
  projectTitle?: string | null,
): Promise<boolean> {
  return fileExists(memoryFile(projectId, filename, projectTitle))
}

// ────────────── 高层辅助 ──────────────

/**
 * 确保 MEMORY.md 索引存在（项目首次写记忆时 bootstrap）。
 * 已存在 → no-op；不存在 → 写最小骨架。
 */
export async function ensureMemoryIndex(
  projectId: string,
  projectTitle: string,
): Promise<void> {
  const exists = await memoryFileExists(projectId, 'MEMORY.md', projectTitle)
  if (exists) return
  const skeleton = `# 项目记忆 · ${projectTitle}

> AI 自动更新；用户可手动编辑

_暂无记忆条目_
`
  await writeMemoryRaw(projectId, 'MEMORY.md', skeleton, projectTitle)
}

// ────────────── 用户 + 项目记忆联合读取（喂 LLM agent）──────────────

/** 用户级 MEMORY.md 路径：`<AppData>/scholarpilot/users/<userId>/memory/MEMORY.md` */
function _userMemoryFile(userId: string): string {
  if (!userId || userId.includes('..') || userId.includes('/') || userId.includes('\\')) {
    throw new Error(`invalid userId: ${userId}`)
  }
  return `users/${userId}/memory/MEMORY.md`
}

/** 用户级 memory 子文件路径（promote 升级时写）。filename 必须是 snake_case + .md。 */
function _userMemoryDetailFile(userId: string, filename: string): string {
  if (!userId || userId.includes('..') || userId.includes('/') || userId.includes('\\')) {
    throw new Error(`invalid userId: ${userId}`)
  }
  validateFilename(filename)
  return `users/${userId}/memory/${filename}`
}

/**
 * 读用户级 MEMORY.md 全文。
 *
 * 文件不存在 → 返空字符串（不抛错），让上层 phase 拼 combined 时安全降级。
 */
export async function readUserMemoryMd(userId: string): Promise<string> {
  if (!userId) return ''
  const text = await readText(_userMemoryFile(userId))
  return (text ?? '').trim()
}

/**
 * 写用户级 MEMORY.md 全文（覆盖式）。
 *
 * 用于 promoteToUserMemory 等用户主动操作。日常 round 反馈 → 项目记忆，**不会** 自动
 * 写到这里（避免污染跨项目画像）。
 *
 * 失败抛错（caller 可决定 graceful 降级）。
 */
export async function writeUserMemoryMd(userId: string, content: string): Promise<void> {
  if (!userId) throw new Error('writeUserMemoryMd: userId required')
  await writeText(_userMemoryFile(userId), content)
}

/**
 * 用户级 entry 追加器（无原子重建索引，简易 append-only 模式）。
 *
 * 用于把项目记忆 entry 提升为跨项目偏好（用户身份 / 长期方法偏好等）。
 * 当前 V1：把 entry 以 markdown bullet 形式 append 到 `users/<userId>/memory/MEMORY.md`
 * 末尾，时间戳 + 来源标注。V2 可改成多 .md 索引模式（学项目记忆）。
 *
 * 不存在的 MEMORY.md → 写最小骨架后再 append。
 */
export async function appendUserMemoryEntry(
  userId: string,
  entry: { topic: string; content: string; weight?: number; addedAt?: number },
): Promise<void> {
  if (!userId) throw new Error('appendUserMemoryEntry: userId required')
  const existing = (await readText(_userMemoryFile(userId))) ?? ''
  const now = entry.addedAt ?? Date.now()
  const weight = typeof entry.weight === 'number' ? entry.weight : 0.5
  const dateStr = new Date(now).toISOString().slice(0, 10)
  const lines: string[] = []
  if (!existing.trim()) {
    lines.push('# 用户记忆（跨项目）', '', '> 用户主动从项目记忆提升而来；AI 也可写', '')
  } else {
    lines.push(existing.replace(/\s+$/, ''), '')
  }
  lines.push(
    `## ${entry.topic} (${dateStr}, weight=${weight.toFixed(2)})`,
    '',
    entry.content.trim(),
    '',
  )
  await writeUserMemoryMd(userId, lines.join('\n'))
}

/**
 * 读项目级 MEMORY.md 全文（不含 detail .md 详情，只读索引文件）。
 *
 * 文件不存在 → 返空字符串。
 */
export async function readProjectMemoryMd(
  projectId: string,
  projectTitle?: string | null,
): Promise<string> {
  if (!projectId) return ''
  const raw = await readMemoryRaw(projectId, 'MEMORY.md', projectTitle)
  return (raw ?? '').trim()
}

export interface CombinedMemoryForAgents {
  userMemoryMd: string
  projectMemoryMd: string
  combined: string
}

/**
 * 读用户 + 项目两份 MEMORY.md，拼成给 LLM agent 用的 combined markdown。
 *
 * 任一不存在 → 返空字符串占位（agent 仍可继续工作）；两者都空 → combined 为空。
 *
 * 用于 `LoadMemoryPhase` 喂 QueryPlanAgent / ScoringAgent 的 memory snapshot。
 */
export async function readCombinedMemoryForAgents(
  userId: string,
  projectId: string,
  projectTitle?: string | null,
): Promise<CombinedMemoryForAgents> {
  const [userMemoryMd, projectMemoryMd] = await Promise.all([
    readUserMemoryMd(userId),
    readProjectMemoryMd(projectId, projectTitle),
  ])
  const parts: string[] = []
  if (userMemoryMd) {
    parts.push('# 用户记忆（用户级）', '', userMemoryMd)
  }
  if (projectMemoryMd) {
    if (parts.length > 0) parts.push('', '')
    parts.push('# 项目记忆（项目级）', '', projectMemoryMd)
  }
  return {
    userMemoryMd,
    projectMemoryMd,
    combined: parts.join('\n'),
  }
}

// ────────────── P0.5: 应用 backend memory_update ──────────────
// feedback POST 返回 MemoryUpdateOut → 客户端写多文件 + MEMORY.md 索引

export interface RemoteMemoryFile {
  filename: string
  type: string
  name: string
  description: string
  body: string
}

export interface RemoteMemoryUpdate {
  version: number
  index_md: string                // backend 给的快照索引；client 优先 rebuild，只在 rebuild 失败时作回滚参考
  files: RemoteMemoryFile[]
  focus: string                   // 一句话研究方向，rebuildMemoryIndex 头部展示
}

/**
 * 从本地所有 .md（除 MEMORY.md）重建索引，按 updated_at 倒序。
 * 直接覆盖写 MEMORY.md，不加 frontmatter。
 */
export async function rebuildMemoryIndex(
  projectId: string,
  projectTitle: string | null | undefined,
  currentVersion: number,
  focus: string,
): Promise<void> {
  const entries = await listMemoryFiles(projectId, projectTitle)
  const detailEntries = entries.filter((e) => e.name !== 'MEMORY.md')

  // 读每个 file 的 frontmatter 以获取 name / description
  const items: Array<{ filename: string; name: string; description: string; updated_at: number }> = []
  for (const e of detailEntries) {
    const parsed = await readMemoryFile(projectId, e.name, projectTitle)
    items.push({
      filename: e.name,
      name: (parsed?.meta.name as string) || e.name.replace(/\.md$/, ''),
      description: (parsed?.meta.description as string) || '',
      updated_at: (parsed?.meta.updated_at as number) || e.updated_at,
    })
  }

  // 按 updated_at 倒序
  items.sort((a, b) => b.updated_at - a.updated_at)

  const lines: string[] = [
    `# 项目记忆 v${currentVersion}`,
    '',
    '> AI 自动维护；编辑请直接打开 .md',
    '',
    `_当前研究方向：${focus}_`,
    '',
  ]
  for (const item of items) {
    lines.push(`- [${item.name}](${item.filename}) — ${item.description}`)
  }

  await writeMemoryRaw(projectId, 'MEMORY.md', lines.join('\n'), projectTitle)
}

/**
 * 把 backend memory_agent 输出落到本地（事务式，失败自动回滚）：
 *   1. 备份当前所有 .md raw 内容到内存 Map
 *   2. 写所有 detail files（带 frontmatter）
 *   3. 任一写失败 → 回写旧版（有备份）或删除（新文件）→ 返回 rolledBack=true
 *   4. 全部成功 → rebuildMemoryIndex 增量重建 MEMORY.md
 *   5. rebuild 失败 → 回滚 MEMORY.md → 返回 rolledBack=true
 *
 * 失败不抛异常 —— memory 不是关键路径，feedback 提交主流程要保活。
 *
 * `scope`（默认 'project'）：
 *   - 'project'：写 `<AppData>/scholarpilot/projects/<id>/memory/`（默认行为，所有 round
 *     反馈走这里）
 *   - 'user'：保留扩展点。当前未实现（用户级 memory 仅由 promoteToUserMemory 主动升级），
 *     传 'user' 直接 no-op 返回 0/[]/false。日后若 LLM 决定哪些 entries 是跨项目通用，
 *     再扩这里走 user 路径。
 */
export async function applyMemoryUpdate(
  projectId: string,
  projectTitle: string | null | undefined,
  update: RemoteMemoryUpdate,
  scope: 'project' | 'user' = 'project',
): Promise<{ written: number; failed: string[]; rolledBack: boolean }> {
  if (scope === 'user') {
    // V1 简化方案：用户级 memory 仅由 promoteToUserMemory 主动升级（用户在 UI 点
    // "提升到全局画像"），不由 round 反馈自动写。这里保留入口防 caller 误调。
    console.warn('[applyMemoryUpdate] scope=user is no-op in V1 (use promoteToUserMemory)')
    return { written: 0, failed: [], rolledBack: false }
  }
  const failed: string[] = []
  let written = 0

  // ── 1. 备份现有所有 .md raw 内容 ──
  const backup = new Map<string, string | null>()
  try {
    const existingEntries = await listMemoryFiles(projectId, projectTitle)
    for (const e of existingEntries) {
      const raw = await readMemoryRaw(projectId, e.name, projectTitle)
      backup.set(e.name, raw)
    }
  } catch {
    // 备份失败不阻断主流程，降级为无法回滚
  }

  // ── 2. 写 detail files ──
  const successfullyWritten: string[] = []
  for (const f of update.files) {
    try {
      await writeMemoryFile(
        projectId,
        f.filename,
        {
          name: f.name,
          description: f.description,
          type: f.type,
          version: update.version,
        },
        f.body,
        projectTitle,
      )
      successfullyWritten.push(f.filename)
      written++
    } catch (e) {
      failed.push(f.filename)
      console.warn('[applyMemoryUpdate] write failed:', f.filename, e)
    }
  }

  // ── 3. 任一写失败 → 回滚已写的 ──
  if (failed.length > 0) {
    for (const filename of successfullyWritten) {
      try {
        if (backup.has(filename) && backup.get(filename) != null) {
          await writeMemoryRaw(projectId, filename, backup.get(filename)!, projectTitle)
        } else {
          await deleteMemoryFile(projectId, filename, projectTitle)
        }
      } catch (re) {
        console.warn('[applyMemoryUpdate] rollback failed for:', filename, re)
      }
    }
    return { written: 0, failed, rolledBack: true }
  }

  // ── 4. 全部成功 → rebuildMemoryIndex ──
  const memoryBackup = backup.get('MEMORY.md') ?? null
  try {
    await rebuildMemoryIndex(projectId, projectTitle, update.version, update.focus)
  } catch (e) {
    console.warn('[applyMemoryUpdate] rebuildMemoryIndex failed, rolling back MEMORY.md:', e)
    if (memoryBackup != null) {
      try {
        await writeMemoryRaw(projectId, 'MEMORY.md', memoryBackup, projectTitle)
      } catch {}
    }
    failed.push('MEMORY.md')
    return { written, failed, rolledBack: true }
  }

  return { written, failed, rolledBack: false }
}

// ────────────── promoteToUserMemory（用户主动升级项目记忆 → 跨项目画像）──────────────

/**
 * 把项目记忆中选中的 entry/.md 文件升级为用户级 memory。
 *
 * 设计：
 * - 当前 V1 走"简单 append"模式：把指定 .md 的 frontmatter `name`/`description` 加上
 *   body 拼成 entry，append 到 `<AppData>/scholarpilot/users/<userId>/memory/MEMORY.md`
 * - V2 待办：支持升级到 user-level 多 .md 索引（学项目记忆机制）+ UI 点选 → 当前
 *   `entryFilenames` 由 caller 决定（V2 加 UI）
 *
 * 失败抛错（caller 决定 graceful）。
 *
 * @returns 升级了多少条 entry
 */
export async function promoteToUserMemory(
  userId: string,
  projectId: string,
  entryFilenames: string[],
  projectTitle?: string | null,
): Promise<{ promoted: number; skipped: string[] }> {
  if (!userId) throw new Error('promoteToUserMemory: userId required')
  if (!projectId) throw new Error('promoteToUserMemory: projectId required')
  const skipped: string[] = []
  let promoted = 0
  const now = Date.now()

  for (const filename of entryFilenames) {
    try {
      const parsed = await readMemoryFile(projectId, filename, projectTitle)
      if (!parsed) {
        skipped.push(filename)
        continue
      }
      const topic = String(parsed.meta.name ?? filename.replace(/\.md$/, ''))
      const description = String(parsed.meta.description ?? '')
      const body = parsed.body.trim()
      if (!body && !description) {
        skipped.push(filename)
        continue
      }
      // 拼内容：description（可选）+ body
      const content = description
        ? `${description}\n\n${body}`
        : body
      const weight = parsed.meta.type === 'identity' ? 1.0
        : parsed.meta.type === 'preference' ? 0.8 : 0.5
      await appendUserMemoryEntry(userId, {
        topic,
        content,
        weight,
        addedAt: now,
      })
      promoted++
    } catch (e) {
      console.warn('[promoteToUserMemory] failed for:', filename, e)
      skipped.push(filename)
    }
  }
  return { promoted, skipped }
}

/** 用户级 memory 子文件直写（V2 用，当前 promoteToUserMemory 走 append 模式不调）。 */
export async function writeUserMemoryFile(
  userId: string,
  filename: string,
  meta: MemoryFrontmatter,
  body: string,
): Promise<void> {
  const finalMeta: MemoryFrontmatter = { ...meta, updated_at: Date.now() }
  const text = serializeWithFrontmatter(finalMeta, body)
  await writeText(_userMemoryDetailFile(userId, filename), text)
}

