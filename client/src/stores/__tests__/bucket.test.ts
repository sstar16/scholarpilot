/**
 * bucket store 单测：classify / move / unclassify / fetchBuckets 全部走本地 SQLite。
 */
import { setActivePinia, createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { setTestDb } from '@/data/sqlite/connection'
import { upsertDocument } from '@/data/sqlite/repos/documentRepo'
import { upsertProject } from '@/data/sqlite/repos/projectRepo'

import { useBucketStore } from '../bucket'
import { mkBetterSqliteHandle, mkDoc, mkProject } from './_dbHelpers'

let dbHandle: ReturnType<typeof mkBetterSqliteHandle>

beforeEach(async () => {
  setActivePinia(createPinia())
  dbHandle = mkBetterSqliteHandle()
  setTestDb(dbHandle)
  await upsertProject(mkProject('p1'))
  await upsertDocument(mkDoc('d1', { title: 'A', source: 'arxiv' }))
  await upsertDocument(mkDoc('d2', { title: 'B', source: 'openalex' }))
  await upsertDocument(mkDoc('d3', { title: 'C', source: 'crossref' }))
})

afterEach(async () => {
  await dbHandle.close()
  setTestDb(null)
})

describe('useBucketStore.classify', () => {
  it('分到 very_relevant → 桶 + counts 更新', async () => {
    const store = useBucketStore()
    await store.classify('p1', 'd1', 'very_relevant')
    expect(store.buckets.very_relevant.length).toBe(1)
    expect(store.buckets.very_relevant[0].document_id).toBe('d1')
    expect(store.counts.very_relevant).toBe(1)
    expect(store.total).toBe(1)
  })

  it('再分到 relevant → 从旧桶搬走', async () => {
    const store = useBucketStore()
    await store.classify('p1', 'd1', 'very_relevant')
    await store.classify('p1', 'd1', 'relevant')
    expect(store.buckets.very_relevant.length).toBe(0)
    expect(store.buckets.relevant.length).toBe(1)
    expect(store.counts.very_relevant).toBe(0)
    expect(store.counts.relevant).toBe(1)
  })

  it('classify 多篇 → 各桶都对', async () => {
    const store = useBucketStore()
    await store.classify('p1', 'd1', 'very_relevant')
    await store.classify('p1', 'd2', 'relevant')
    await store.classify('p1', 'd3', 'irrelevant')
    expect(store.total).toBe(3)
    expect(store.counts.very_relevant).toBe(1)
    expect(store.counts.relevant).toBe(1)
    expect(store.counts.irrelevant).toBe(1)
  })
})

describe('useBucketStore.fetchBuckets', () => {
  it('从 SQLite 拉所有分桶 + 拼文档元数据', async () => {
    const store = useBucketStore()
    await store.classify('p1', 'd1', 'very_relevant')
    await store.classify('p1', 'd2', 'relevant')
    store.reset()
    expect(store.total).toBe(0)
    await store.fetchBuckets('p1')
    expect(store.total).toBe(2)
    const vr = store.buckets.very_relevant[0]
    expect(vr.title).toBe('A')
    expect(vr.source).toBe('arxiv')
  })
})

describe('useBucketStore.move', () => {
  it('move → 新桶有，旧桶无', async () => {
    const store = useBucketStore()
    await store.classify('p1', 'd1', 'uncertain')
    await store.move('p1', 'd1', 'irrelevant')
    expect(store.buckets.uncertain.length).toBe(0)
    expect(store.buckets.irrelevant.length).toBe(1)
  })
})

describe('useBucketStore.unclassify', () => {
  it('unclassify → 完全移除', async () => {
    const store = useBucketStore()
    await store.classify('p1', 'd1', 'relevant')
    await store.unclassify('p1', 'd1')
    expect(store.total).toBe(0)
    // SQLite 也清了 → 重新 fetchBuckets 仍是 0
    store.reset()
    await store.fetchBuckets('p1')
    expect(store.total).toBe(0)
  })
})

describe('useBucketStore.getBucket', () => {
  it('docId 在某桶 → 返桶名；不在 → null', async () => {
    const store = useBucketStore()
    await store.classify('p1', 'd1', 'very_relevant')
    expect(store.getBucket('d1')).toBe('very_relevant')
    expect(store.getBucket('ghost')).toBeNull()
  })
})

describe('useBucketStore.reset', () => {
  it('reset → 桶 + counts 全空', async () => {
    const store = useBucketStore()
    await store.classify('p1', 'd1', 'very_relevant')
    store.reset()
    expect(store.total).toBe(0)
    for (const b of ['very_relevant', 'relevant', 'uncertain', 'irrelevant'] as const) {
      expect(store.buckets[b].length).toBe(0)
    }
  })
})
