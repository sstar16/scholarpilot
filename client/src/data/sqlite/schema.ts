export const SCHEMA_VERSION = 1
export const DB_NAME = 'sqlite:scholarpilot.db'
export const DB_FILE = 'scholarpilot.db'

// 在 vitest 等不依赖 Tauri runtime 的环境下，repo 实现需要兼容一个 better-sqlite3 实例。
// connection.ts 决定真实运行时用哪个 driver。
export type DbHandle = {
  select<T = unknown>(sql: string, bindings?: unknown[]): Promise<T[]>
  execute(sql: string, bindings?: unknown[]): Promise<{ rowsAffected: number; lastInsertId?: number }>
  close(): Promise<void>
}
