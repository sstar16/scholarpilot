import { getDatabase } from '../connection'
import type { LocalSyncState } from '@/types/local'

export type SyncEntityType =
  | 'project' | 'round' | 'document' | 'classification'
  | 'session' | 'message' | 'notebook_page'

interface Row {
  entity_type: string
  entity_id: string
  local_version: number
  remote_version: number
  last_synced_at: number | null
  dirty: number
}

function _fromRow(r: Row): LocalSyncState {
  return {
    entity_type: r.entity_type,
    entity_id: r.entity_id,
    local_version: r.local_version,
    remote_version: r.remote_version,
    last_synced_at: r.last_synced_at,
    dirty: !!r.dirty,
  }
}

export async function markDirty(type: SyncEntityType, id: string): Promise<void> {
  const db = getDatabase()
  await db.execute(
    `INSERT INTO sync_state (entity_type, entity_id, local_version, remote_version, dirty)
     VALUES (?,?,?,?,?)
     ON CONFLICT(entity_type, entity_id) DO UPDATE SET
       local_version = sync_state.local_version + 1,
       dirty = 1`,
    [type, id, 1, 0, 1],
  )
}

export interface MarkSyncedOptions {
  remote_version: number
  syncedAtMs: number
}

export async function markSynced(
  type: SyncEntityType,
  id: string,
  opts: MarkSyncedOptions,
): Promise<void> {
  const db = getDatabase()
  await db.execute(
    `INSERT INTO sync_state (entity_type, entity_id, local_version, remote_version, last_synced_at, dirty)
     VALUES (?,?,?,?,?,0)
     ON CONFLICT(entity_type, entity_id) DO UPDATE SET
       remote_version = excluded.remote_version,
       last_synced_at = excluded.last_synced_at,
       dirty = 0`,
    [type, id, 0, opts.remote_version, opts.syncedAtMs],
  )
}

export async function getSyncState(
  type: SyncEntityType,
  id: string,
): Promise<LocalSyncState | null> {
  const db = getDatabase()
  const rows = await db.select<Row>(
    'SELECT * FROM sync_state WHERE entity_type = ? AND entity_id = ?',
    [type, id],
  )
  return rows[0] ? _fromRow(rows[0]) : null
}

export async function listDirty(type?: SyncEntityType): Promise<LocalSyncState[]> {
  const db = getDatabase()
  const sql = type
    ? 'SELECT * FROM sync_state WHERE dirty = 1 AND entity_type = ?'
    : 'SELECT * FROM sync_state WHERE dirty = 1'
  const bindings = type ? [type] : []
  const rows = await db.select<Row>(sql, bindings)
  return rows.map(_fromRow)
}
