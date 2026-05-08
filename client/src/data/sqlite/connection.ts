import Database from '@tauri-apps/plugin-sql'

import { DB_NAME, type DbHandle } from './schema'

let _db: DbHandle | null = null
let _initPromise: Promise<DbHandle> | null = null

async function _open(): Promise<DbHandle> {
  // plugin-sql 的 Database 实例符合 DbHandle 形状（select / execute / close）
  const db = await Database.load(DB_NAME)
  return db as unknown as DbHandle
}

/**
 * 启动时调一次。返回单例。
 * 在 vitest 单测里通过 `setTestDb()` 注入 better-sqlite3 wrapper 替代。
 */
export async function initDatabase(): Promise<DbHandle> {
  if (_db) return _db
  _initPromise ||= _open().then((db) => {
    _db = db
    return db
  })
  return _initPromise
}

export function getDatabase(): DbHandle {
  if (!_db) {
    throw new Error('Database not initialized. Call initDatabase() before any repo call.')
  }
  return _db
}

/** 单测专用 — 注入 in-memory DB */
export function setTestDb(handle: DbHandle | null): void {
  _db = handle
  _initPromise = null
}

export async function closeDatabase(): Promise<void> {
  if (_db) {
    await _db.close()
    _db = null
    _initPromise = null
  }
}
