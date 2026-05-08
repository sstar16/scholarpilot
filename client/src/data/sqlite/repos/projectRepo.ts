import { getDatabase } from '../connection'
import type { LocalProject } from '@/types/local'

interface Row {
  id: string
  title: string
  description: string
  domain: string
  domains_json: string | null
  search_config_json: string | null
  current_round: number
  max_rounds: number
  status: string
  research_note_md: string
  research_note_updated_at: number | null
  research_note_updated_by: string | null
  created_at: number
  updated_at: number
  last_synced_at: number | null
}

function _toRow(p: LocalProject): Row {
  return {
    id: p.id,
    title: p.title,
    description: p.description,
    domain: p.domain,
    domains_json: p.domains ? JSON.stringify(p.domains) : null,
    search_config_json: p.search_config ? JSON.stringify(p.search_config) : null,
    current_round: p.current_round,
    max_rounds: p.max_rounds,
    status: p.status,
    research_note_md: p.research_note_md,
    research_note_updated_at: p.research_note_updated_at,
    research_note_updated_by: p.research_note_updated_by,
    created_at: p.created_at,
    updated_at: p.updated_at,
    last_synced_at: p.last_synced_at,
  }
}

function _fromRow(row: Row): LocalProject {
  return {
    id: row.id,
    title: row.title,
    description: row.description,
    domain: row.domain,
    domains: row.domains_json ? (JSON.parse(row.domains_json) as string[]) : null,
    search_config: row.search_config_json
      ? (JSON.parse(row.search_config_json) as Record<string, unknown>)
      : null,
    current_round: row.current_round,
    max_rounds: row.max_rounds,
    status: row.status as LocalProject['status'],
    research_note_md: row.research_note_md,
    research_note_updated_at: row.research_note_updated_at,
    research_note_updated_by:
      (row.research_note_updated_by as LocalProject['research_note_updated_by']) ?? null,
    created_at: row.created_at,
    updated_at: row.updated_at,
    last_synced_at: row.last_synced_at,
  }
}

export async function upsertProject(p: LocalProject): Promise<void> {
  const db = getDatabase()
  const r = _toRow(p)
  await db.execute(
    `INSERT INTO projects
       (id, title, description, domain, domains_json, search_config_json,
        current_round, max_rounds, status, research_note_md,
        research_note_updated_at, research_note_updated_by,
        created_at, updated_at, last_synced_at)
     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
     ON CONFLICT(id) DO UPDATE SET
       title = excluded.title,
       description = excluded.description,
       domain = excluded.domain,
       domains_json = excluded.domains_json,
       search_config_json = excluded.search_config_json,
       current_round = excluded.current_round,
       max_rounds = excluded.max_rounds,
       status = excluded.status,
       research_note_md = excluded.research_note_md,
       research_note_updated_at = excluded.research_note_updated_at,
       research_note_updated_by = excluded.research_note_updated_by,
       updated_at = excluded.updated_at,
       last_synced_at = excluded.last_synced_at`,
    [
      r.id, r.title, r.description, r.domain, r.domains_json, r.search_config_json,
      r.current_round, r.max_rounds, r.status, r.research_note_md,
      r.research_note_updated_at, r.research_note_updated_by,
      r.created_at, r.updated_at, r.last_synced_at,
    ],
  )
}

export async function getProject(id: string): Promise<LocalProject | null> {
  const db = getDatabase()
  const rows = await db.select<Row>('SELECT * FROM projects WHERE id = ?', [id])
  return rows[0] ? _fromRow(rows[0]) : null
}

export interface ListProjectsOptions {
  status?: LocalProject['status']
}

export async function listProjects(opts: ListProjectsOptions = {}): Promise<LocalProject[]> {
  const db = getDatabase()
  const where: string[] = []
  const bindings: unknown[] = []
  if (opts.status) {
    where.push('status = ?')
    bindings.push(opts.status)
  }
  const sql = `SELECT * FROM projects ${where.length ? 'WHERE ' + where.join(' AND ') : ''} ORDER BY updated_at DESC`
  const rows = await db.select<Row>(sql, bindings)
  return rows.map(_fromRow)
}

export async function deleteProject(id: string): Promise<void> {
  const db = getDatabase()
  await db.execute('DELETE FROM projects WHERE id = ?', [id])
}

export async function touchSyncedAt(id: string, syncedAtMs: number): Promise<void> {
  const db = getDatabase()
  await db.execute('UPDATE projects SET last_synced_at = ? WHERE id = ?', [syncedAtMs, id])
}
