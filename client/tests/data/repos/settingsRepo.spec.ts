import { describe, it, expect, beforeEach, afterEach } from 'vitest'

import { createInMemoryDb, type TestDb } from '../../_helpers/inMemoryDb'
import { setTestDb } from '@/data/sqlite/connection'
import { setSetting, getSetting, deleteSetting } from '@/data/sqlite/repos/settingsRepo'
import {
  markDirty, markSynced, getSyncState, listDirty,
} from '@/data/sqlite/repos/syncStateRepo'

describe('settingsRepo', () => {
  let db: TestDb
  beforeEach(() => { db = createInMemoryDb() })
  afterEach(async () => { await db.raw.close(); setTestDb(null) })

  it('set + get string', async () => {
    await setSetting('theme', 'dark')
    expect(await getSetting('theme')).toBe('dark')
  })

  it('get 不存在的 key 返回 null', async () => {
    expect(await getSetting('nope')).toBeNull()
  })

  it('set 同 key 覆盖', async () => {
    await setSetting('k', 'v1')
    await setSetting('k', 'v2')
    expect(await getSetting('k')).toBe('v2')
  })

  it('delete 清除', async () => {
    await setSetting('k', 'v')
    await deleteSetting('k')
    expect(await getSetting('k')).toBeNull()
  })
})

describe('syncStateRepo', () => {
  let db: TestDb
  beforeEach(() => { db = createInMemoryDb() })
  afterEach(async () => { await db.raw.close(); setTestDb(null) })

  it('markDirty + markSynced 正确翻 dirty 标记', async () => {
    await markDirty('project', 'p1')
    let s = await getSyncState('project', 'p1')
    expect(s!.dirty).toBe(true)
    expect(s!.local_version).toBe(1)

    await markSynced('project', 'p1', { remote_version: 5, syncedAtMs: 12345 })
    s = await getSyncState('project', 'p1')
    expect(s!.dirty).toBe(false)
    expect(s!.remote_version).toBe(5)
    expect(s!.last_synced_at).toBe(12345)
  })

  it('listDirty 仅返回 dirty=1 的', async () => {
    await markDirty('project', 'p1')
    await markDirty('project', 'p2')
    await markDirty('round', 'r1')
    await markSynced('project', 'p2', { remote_version: 1, syncedAtMs: 1 })

    const all = await listDirty()
    expect(all.map((s) => s.entity_id).sort()).toEqual(['p1', 'r1'])

    const onlyProjects = await listDirty('project')
    expect(onlyProjects).toHaveLength(1)
    expect(onlyProjects[0].entity_id).toBe('p1')
  })

  it('markDirty 多次累加 local_version', async () => {
    await markDirty('project', 'p1')
    await markDirty('project', 'p1')
    await markDirty('project', 'p1')
    const s = await getSyncState('project', 'p1')
    expect(s!.local_version).toBe(3)
  })
})
