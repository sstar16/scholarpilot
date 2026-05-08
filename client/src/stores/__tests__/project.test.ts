/**
 * project store 单测：list/get/upsert/delete 全部走本地 SQLite。
 */
import { setActivePinia, createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { setTestDb } from '@/data/sqlite/connection'

import { useProjectStore } from '../project'
import { mkBetterSqliteHandle, mkProject } from './_dbHelpers'

let dbHandle: ReturnType<typeof mkBetterSqliteHandle>

beforeEach(() => {
  setActivePinia(createPinia())
  dbHandle = mkBetterSqliteHandle()
  setTestDb(dbHandle)
})

afterEach(async () => {
  await dbHandle.close()
  setTestDb(null)
})

describe('useProjectStore.upsert / fetchProject', () => {
  it('upsert 写库 → fetchProject 拿回', async () => {
    const store = useProjectStore()
    await store.upsert(mkProject('p1', { title: 'Foo' }))
    const got = await store.fetchProject('p1')
    expect(got?.title).toBe('Foo')
    expect(store.current?.id).toBe('p1')
  })

  it('fetchProject 不存在返 null + current=null', async () => {
    const store = useProjectStore()
    const r = await store.fetchProject('ghost')
    expect(r).toBeNull()
    expect(store.current).toBeNull()
  })

  it('upsert 同 id 二次 → 更新', async () => {
    const store = useProjectStore()
    await store.upsert(mkProject('p1', { title: 'A' }))
    await store.upsert(mkProject('p1', { title: 'B' }))
    const got = await store.fetchProject('p1')
    expect(got?.title).toBe('B')
  })
})

describe('useProjectStore.fetchList', () => {
  it('返多条按 updated_at 倒序', async () => {
    const store = useProjectStore()
    await store.upsert(mkProject('p1', { title: 'A', updated_at: 1000 }))
    await store.upsert(mkProject('p2', { title: 'B', updated_at: 2000 }))
    await store.upsert(mkProject('p3', { title: 'C', updated_at: 3000 }))
    const list = await store.fetchList()
    expect(list.map((p) => p.id)).toEqual(['p3', 'p2', 'p1'])
    expect(store.list.length).toBe(3)
  })

  it('status filter 生效', async () => {
    const store = useProjectStore()
    await store.upsert(mkProject('p1', { status: 'active' }))
    await store.upsert(mkProject('p2', { status: 'archived' }))
    const list = await store.fetchList({ status: 'archived' })
    expect(list.map((p) => p.id)).toEqual(['p2'])
  })
})

describe('useProjectStore.remove', () => {
  it('删除后 fetchProject 返 null + 列表移除', async () => {
    const store = useProjectStore()
    await store.upsert(mkProject('p1'))
    await store.fetchList()
    await store.remove('p1')
    const after = await store.fetchProject('p1')
    expect(after).toBeNull()
    expect(store.list.find((p) => p.id === 'p1')).toBeUndefined()
  })

  it('删除 current → current = null', async () => {
    const store = useProjectStore()
    await store.upsert(mkProject('p1'))
    await store.fetchProject('p1')
    expect(store.current?.id).toBe('p1')
    await store.remove('p1')
    expect(store.current).toBeNull()
  })
})

describe('useProjectStore.clear', () => {
  it('clear → current null', async () => {
    const store = useProjectStore()
    await store.upsert(mkProject('p1'))
    await store.fetchProject('p1')
    store.clear()
    expect(store.current).toBeNull()
  })
})
