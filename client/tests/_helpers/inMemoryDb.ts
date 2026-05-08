import BetterSqlite3 from 'better-sqlite3'
import { readFileSync } from 'fs'
import { resolve } from 'path'

import type { DbHandle } from '@/data/sqlite/schema'
import { setTestDb } from '@/data/sqlite/connection'

const SCHEMA_PATH = resolve(__dirname, '../../src-tauri/migrations/v1_initial.sql')

/**
 * 创建一个 in-memory SQLite 实例 + 跑 v1 schema + 把它注入到 connection 单例。
 * 用法：
 *   const db = createInMemoryDb()
 *   afterEach(() => db.raw.close())
 */
export interface TestDb {
  handle: DbHandle
  raw: BetterSqlite3.Database
}

export function createInMemoryDb(): TestDb {
  const raw = new BetterSqlite3(':memory:')
  raw.pragma('foreign_keys = ON')
  raw.exec(readFileSync(SCHEMA_PATH, 'utf-8'))

  const handle: DbHandle = {
    async select<T = unknown>(sql: string, bindings: unknown[] = []): Promise<T[]> {
      const stmt = raw.prepare(sql)
      return stmt.all(...(bindings as any[])) as T[]
    },
    async execute(sql: string, bindings: unknown[] = []) {
      const stmt = raw.prepare(sql)
      const info = stmt.run(...(bindings as any[]))
      return { rowsAffected: info.changes, lastInsertId: Number(info.lastInsertRowid) }
    },
    async close() {
      raw.close()
    },
  }
  setTestDb(handle)
  return { handle, raw }
}
