import { getDatabase } from '../connection'
import type { LocalConversationSession, LocalMessage } from '@/types/local'

// ─────────────── sessions ───────────────

interface SessionRow {
  id: string
  project_id: string | null
  current_state: string
  state_data_json: string | null
  search_mode: string | null
  is_active: number
  created_at: number
  updated_at: number
  last_synced_at: number | null
}

function _sessionFromRow(r: SessionRow): LocalConversationSession {
  return {
    id: r.id,
    project_id: r.project_id,
    current_state: r.current_state,
    state_data: r.state_data_json
      ? (JSON.parse(r.state_data_json) as Record<string, unknown>)
      : null,
    search_mode: r.search_mode,
    is_active: !!r.is_active,
    created_at: r.created_at,
    updated_at: r.updated_at,
    last_synced_at: r.last_synced_at,
  }
}

export async function upsertSession(s: LocalConversationSession): Promise<void> {
  const db = getDatabase()
  await db.execute(
    `INSERT INTO conversation_sessions
      (id, project_id, current_state, state_data_json, search_mode,
       is_active, created_at, updated_at, last_synced_at)
     VALUES (?,?,?,?,?,?,?,?,?)
     ON CONFLICT(id) DO UPDATE SET
       project_id = excluded.project_id,
       current_state = excluded.current_state,
       state_data_json = excluded.state_data_json,
       search_mode = excluded.search_mode,
       is_active = excluded.is_active,
       updated_at = excluded.updated_at,
       last_synced_at = excluded.last_synced_at`,
    [
      s.id, s.project_id, s.current_state,
      s.state_data ? JSON.stringify(s.state_data) : null,
      s.search_mode, s.is_active ? 1 : 0,
      s.created_at, s.updated_at, s.last_synced_at,
    ],
  )
}

export async function getSession(id: string): Promise<LocalConversationSession | null> {
  const db = getDatabase()
  const rows = await db.select<SessionRow>(
    'SELECT * FROM conversation_sessions WHERE id = ?', [id],
  )
  return rows[0] ? _sessionFromRow(rows[0]) : null
}

export async function getActiveSessionForProject(
  projectId: string,
): Promise<LocalConversationSession | null> {
  const db = getDatabase()
  const rows = await db.select<SessionRow>(
    'SELECT * FROM conversation_sessions WHERE project_id = ? AND is_active = 1 LIMIT 1',
    [projectId],
  )
  return rows[0] ? _sessionFromRow(rows[0]) : null
}

/** 把 sessionId 设为 active；同 project 内其它 session 全部置为 inactive。 */
export async function setSessionActive(sessionId: string): Promise<void> {
  const db = getDatabase()
  // 先取得 project_id
  const rows = await db.select<{ project_id: string | null }>(
    'SELECT project_id FROM conversation_sessions WHERE id = ?',
    [sessionId],
  )
  if (!rows[0]) return
  const projectId = rows[0].project_id
  if (projectId !== null) {
    await db.execute(
      'UPDATE conversation_sessions SET is_active = 0 WHERE project_id = ?',
      [projectId],
    )
  }
  await db.execute(
    'UPDATE conversation_sessions SET is_active = 1 WHERE id = ?',
    [sessionId],
  )
}

// ─────────────── messages ───────────────

interface MessageRow {
  id: string
  session_id: string
  role: string
  content_md: string
  rich_data_json: string | null
  created_at: number
  seq: number
}

function _msgFromRow(r: MessageRow): LocalMessage {
  return {
    id: r.id,
    session_id: r.session_id,
    role: r.role as LocalMessage['role'],
    content_md: r.content_md,
    rich_data: r.rich_data_json
      ? (JSON.parse(r.rich_data_json) as Record<string, unknown>)
      : null,
    created_at: r.created_at,
    seq: r.seq,
  }
}

export interface AppendMessageInput {
  session_id: string
  role: LocalMessage['role']
  content_md: string
  rich_data: Record<string, unknown> | null
  created_at: number
  /** 可选：用云端给的 message id；不传则用 'local-' + uuid */
  id?: string
}

export async function appendMessage(input: AppendMessageInput): Promise<LocalMessage> {
  const db = getDatabase()
  const seqRows = await db.select<{ max_seq: number | null }>(
    'SELECT MAX(seq) AS max_seq FROM messages WHERE session_id = ?',
    [input.session_id],
  )
  const seq = (seqRows[0]?.max_seq ?? 0) + 1
  const id = input.id ?? `local-${crypto.randomUUID()}`
  const msg: LocalMessage = {
    id,
    session_id: input.session_id,
    role: input.role,
    content_md: input.content_md,
    rich_data: input.rich_data,
    created_at: input.created_at,
    seq,
  }
  await upsertMessage(msg)
  return msg
}

export async function upsertMessage(m: LocalMessage): Promise<void> {
  const db = getDatabase()
  await db.execute(
    `INSERT INTO messages (id, session_id, role, content_md, rich_data_json, created_at, seq)
     VALUES (?,?,?,?,?,?,?)
     ON CONFLICT(id) DO UPDATE SET
       role = excluded.role,
       content_md = excluded.content_md,
       rich_data_json = excluded.rich_data_json,
       created_at = excluded.created_at,
       seq = excluded.seq`,
    [
      m.id, m.session_id, m.role, m.content_md,
      m.rich_data ? JSON.stringify(m.rich_data) : null,
      m.created_at, m.seq,
    ],
  )
}

export interface ListMessagesOptions {
  /** 最多返回多少条；默认无限制 */
  limit?: number
  /** 仅返回 seq < before_seq 的（向前翻历史） */
  before_seq?: number
}

export async function listMessages(
  sessionId: string,
  opts: ListMessagesOptions = {},
): Promise<LocalMessage[]> {
  const db = getDatabase()
  const where = ['session_id = ?']
  const bindings: unknown[] = [sessionId]
  if (opts.before_seq !== undefined) {
    where.push('seq < ?')
    bindings.push(opts.before_seq)
  }
  // 分页时取最新 N 条 → DESC + limit，再在 TS 侧 reverse 成 asc
  const desc = opts.limit !== undefined
  const order = desc ? 'DESC' : 'ASC'
  const limitClause = opts.limit !== undefined ? `LIMIT ${opts.limit | 0}` : ''
  const rows = await db.select<MessageRow>(
    `SELECT * FROM messages WHERE ${where.join(' AND ')}
     ORDER BY seq ${order} ${limitClause}`,
    bindings,
  )
  const list = rows.map(_msgFromRow)
  return desc ? list.reverse() : list
}
