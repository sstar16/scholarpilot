/**
 * LLM Cache — IndexedDB 实现（idb 包封装）。
 *
 * 设计：
 * - 单 store `cache`：keyPath=`key`，value 含 `value` / `expires_at`（unix-ms）
 * - 索引 `expires_at` 用于批量 cleanup（删过期）
 * - 默认 TTL 7200s（2 小时）；调用方可覆盖
 * - 不做 LRU 淘汰：cleanup() 由调用方按需触发（启动时 / settings 里的"清缓存"）
 *
 * 与 backend `Redis cache` 差异：
 * - 客户端单进程，无并发写问题
 * - 没有 Redis ttl 自动过期，需要手动 cleanup（或读时校验过期）
 */
import { openDB, type IDBPDatabase } from 'idb'

import { makeCacheKey } from './utils'

interface CacheRecord {
  key: string
  value: unknown
  expires_at: number  // unix-ms，0 表示永不过期（保留口子，当前不用）
  created_at: number
}

interface CacheSchema {
  cache: {
    key: string
    value: CacheRecord
    indexes: { expires_at: number }
  }
}

/** 默认 TTL：2 小时（与 backend `MIN_CACHE_TTL` 一致量级）。 */
const DEFAULT_TTL_SECONDS = 7200

/** Clock 注入接口 — 测试可替换 now() 而无需 vi.useFakeTimers()
 * （fake timers 会让 fake-indexeddb 内部 setTimeout 永挂） */
export interface CacheClock {
  now: () => number
}

const _defaultClock: CacheClock = { now: () => Date.now() }

export class LLMCache {
  private dbPromise: Promise<IDBPDatabase<CacheSchema>>
  readonly dbName: string
  private clock: CacheClock

  constructor(dbName = 'scholarpilot-llm-cache', clock: CacheClock = _defaultClock) {
    this.dbName = dbName
    this.clock = clock
    this.dbPromise = openDB<CacheSchema>(dbName, 1, {
      upgrade(db) {
        if (!db.objectStoreNames.contains('cache')) {
          const store = db.createObjectStore('cache', { keyPath: 'key' })
          store.createIndex('expires_at', 'expires_at')
        }
      },
    })
  }

  /** 读 cache。命中且未过期返回 value，过期/未命中返回 null。 */
  async get<T = unknown>(key: string): Promise<T | null> {
    const db = await this.dbPromise
    const rec = (await db.get('cache', key)) as CacheRecord | undefined
    if (!rec) return null
    if (rec.expires_at !== 0 && rec.expires_at < this.clock.now()) {
      // 顺手删掉过期项
      await db.delete('cache', key)
      return null
    }
    return rec.value as T
  }

  /** 写 cache。ttl_seconds=0 表示永不过期。 */
  async set(key: string, value: unknown, ttl_seconds = DEFAULT_TTL_SECONDS): Promise<void> {
    const db = await this.dbPromise
    const now = this.clock.now()
    const expires_at = ttl_seconds <= 0 ? 0 : now + ttl_seconds * 1000
    const rec: CacheRecord = {
      key,
      value,
      expires_at,
      created_at: now,
    }
    await db.put('cache', rec)
  }

  /** 删除单条。 */
  async delete(key: string): Promise<void> {
    const db = await this.dbPromise
    await db.delete('cache', key)
  }

  /** 清空所有缓存（settings 里"重置缓存"按钮用）。 */
  async clear(): Promise<void> {
    const db = await this.dbPromise
    await db.clear('cache')
  }

  /** 删除过期项，返回删除数量。 */
  async cleanup(): Promise<number> {
    const db = await this.dbPromise
    const tx = db.transaction('cache', 'readwrite')
    const idx = tx.store.index('expires_at')
    const now = this.clock.now()
    let deleted = 0
    // expires_at=0 表示永不过期，跳过；只扫 (0, now] 的
    const range = IDBKeyRange.bound(1, now)
    for await (const cursor of idx.iterate(range)) {
      await cursor.delete()
      deleted++
    }
    await tx.done
    return deleted
  }

  /** 关闭底层 DB（测试用，避免句柄泄漏）。 */
  async close(): Promise<void> {
    const db = await this.dbPromise
    db.close()
  }
}

// 复导出便于使用
export { makeCacheKey }

/** 全局单例（首选用法），避免每个 caller 都开 DB。 */
let _singleton: LLMCache | null = null

export function getLLMCache(): LLMCache {
  if (!_singleton) {
    _singleton = new LLMCache()
  }
  return _singleton
}

/** 测试用：重置单例（每个测试独立 dbName）。 */
export function _resetLLMCacheForTesting(): void {
  _singleton = null
}
