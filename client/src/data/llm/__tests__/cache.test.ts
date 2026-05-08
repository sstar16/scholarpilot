/**
 * LLM Cache 单测：set/get/TTL 失效 + cleanup。
 *
 * 用 fake-indexeddb 在 node 环境模拟 IndexedDB（vitest config environment='node'）。
 */
import 'fake-indexeddb/auto'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LLMCache, makeCacheKey, _resetLLMCacheForTesting } from '../cache'

// node 环境下 crypto.subtle 在 node ≥17 已经是全局 webcrypto，但 vitest node env 需要点拨一下
import { webcrypto } from 'node:crypto'
if (typeof globalThis.crypto === 'undefined' || !globalThis.crypto.subtle) {
  // @ts-expect-error 注入 polyfill
  globalThis.crypto = webcrypto
}

describe('LLMCache', () => {
  let cache: LLMCache
  // 注入式 clock — 不用 vi.useFakeTimers (会让 fake-indexeddb 内部 setTimeout 永挂)
  let mockNow: number
  const clock = { now: () => mockNow }

  beforeEach(() => {
    _resetLLMCacheForTesting()
    mockNow = new Date(2026, 4, 8, 10, 0, 0).getTime()
    // 每个测试用唯一 db 名，避免 fake-indexeddb 状态串
    cache = new LLMCache(`test-llm-cache-${Math.random().toString(36).slice(2)}`, clock)
  })

  afterEach(async () => {
    await cache.close()
    vi.useRealTimers()
  })

  it('set + get returns the stored value', async () => {
    await cache.set('k1', { foo: 'bar', n: 42 })
    const got = await cache.get<{ foo: string, n: number }>('k1')
    expect(got).toEqual({ foo: 'bar', n: 42 })
  })

  it('returns null for missing key', async () => {
    const got = await cache.get('does-not-exist')
    expect(got).toBeNull()
  })

  it('honours TTL: expired entries return null + auto-purge', async () => {
    await cache.set('expiring', 'value', 1) // 1 秒 TTL

    // 未过期 → 命中
    let got = await cache.get('expiring')
    expect(got).toBe('value')

    // 推进 2 秒 → 过期
    mockNow += 2000
    got = await cache.get('expiring')
    expect(got).toBeNull()
  })

  it('ttl=0 means never expire', async () => {
    await cache.set('forever', 'value', 0)

    // 推进 1 年
    mockNow += 365 * 24 * 3600 * 1000
    const got = await cache.get('forever')
    expect(got).toBe('value')
  })

  it('cleanup deletes expired records', async () => {
    await cache.set('a', 1, 1)
    await cache.set('b', 2, 100)
    await cache.set('c', 3, 0) // 永不过期

    mockNow += 5000
    const deleted = await cache.cleanup()
    expect(deleted).toBe(1) // 只有 'a' 过期

    expect(await cache.get('a')).toBeNull()
    expect(await cache.get('b')).toBe(2)
    expect(await cache.get('c')).toBe(3)
  })

  it('clear removes all', async () => {
    await cache.set('x', 1)
    await cache.set('y', 2)
    await cache.clear()
    expect(await cache.get('x')).toBeNull()
    expect(await cache.get('y')).toBeNull()
  })

  it('delete removes single key', async () => {
    await cache.set('x', 1)
    await cache.set('y', 2)
    await cache.delete('x')
    expect(await cache.get('x')).toBeNull()
    expect(await cache.get('y')).toBe(2)
  })
})

describe('makeCacheKey', () => {
  beforeEach(() => {
    if (typeof globalThis.crypto === 'undefined' || !globalThis.crypto.subtle) {
      // @ts-expect-error
      globalThis.crypto = webcrypto
    }
  })

  it('is deterministic for same inputs', async () => {
    const k1 = await makeCacheKey('hello', 'gpt-4o-mini', 0.0)
    const k2 = await makeCacheKey('hello', 'gpt-4o-mini', 0.0)
    expect(k1).toBe(k2)
    expect(k1).toHaveLength(32)
  })

  it('differs by prompt', async () => {
    const k1 = await makeCacheKey('hello', 'gpt-4o-mini', 0.0)
    const k2 = await makeCacheKey('hello!', 'gpt-4o-mini', 0.0)
    expect(k1).not.toBe(k2)
  })

  it('differs by model', async () => {
    const k1 = await makeCacheKey('hello', 'gpt-4o-mini', 0.0)
    const k2 = await makeCacheKey('hello', 'claude-haiku-4-5-20251001', 0.0)
    expect(k1).not.toBe(k2)
  })

  it('differs by temperature', async () => {
    const k1 = await makeCacheKey('hello', 'gpt-4o-mini', 0.0)
    const k2 = await makeCacheKey('hello', 'gpt-4o-mini', 0.7)
    expect(k1).not.toBe(k2)
  })
})
