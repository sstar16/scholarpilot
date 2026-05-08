import { getDatabase } from '../connection'
import type { LocalNotebookPage } from '@/types/local'

interface Row {
  id: string
  project_id: string
  title: string
  body_md: string
  sort_order: number
  updated_at: number
  updated_by: string | null
  created_at: number
  last_synced_at: number | null
}

function _fromRow(r: Row): LocalNotebookPage {
  return {
    id: r.id,
    project_id: r.project_id,
    title: r.title,
    body_md: r.body_md,
    sort_order: r.sort_order,
    updated_at: r.updated_at,
    updated_by: (r.updated_by as LocalNotebookPage['updated_by']) ?? null,
    created_at: r.created_at,
    last_synced_at: r.last_synced_at,
  }
}

export async function upsertNotebookPage(p: LocalNotebookPage): Promise<void> {
  const db = getDatabase()
  await db.execute(
    `INSERT INTO research_note_pages
      (id, project_id, title, body_md, sort_order, updated_at, updated_by, created_at, last_synced_at)
     VALUES (?,?,?,?,?,?,?,?,?)
     ON CONFLICT(id) DO UPDATE SET
       title = excluded.title,
       body_md = excluded.body_md,
       sort_order = excluded.sort_order,
       updated_at = excluded.updated_at,
       updated_by = excluded.updated_by,
       last_synced_at = excluded.last_synced_at`,
    [
      p.id, p.project_id, p.title, p.body_md, p.sort_order,
      p.updated_at, p.updated_by, p.created_at, p.last_synced_at,
    ],
  )
}

export async function getNotebookPage(id: string): Promise<LocalNotebookPage | null> {
  const db = getDatabase()
  const rows = await db.select<Row>('SELECT * FROM research_note_pages WHERE id = ?', [id])
  return rows[0] ? _fromRow(rows[0]) : null
}

export async function listPagesByProject(projectId: string): Promise<LocalNotebookPage[]> {
  const db = getDatabase()
  const rows = await db.select<Row>(
    'SELECT * FROM research_note_pages WHERE project_id = ? ORDER BY sort_order ASC, created_at ASC',
    [projectId],
  )
  return rows.map(_fromRow)
}

export async function deleteNotebookPage(id: string): Promise<void> {
  const db = getDatabase()
  await db.execute('DELETE FROM research_note_pages WHERE id = ?', [id])
}

export async function reorderPage(id: string, newSortOrder: number): Promise<void> {
  const db = getDatabase()
  await db.execute(
    'UPDATE research_note_pages SET sort_order = ?, updated_at = ? WHERE id = ?',
    [newSortOrder, Date.now(), id],
  )
}
