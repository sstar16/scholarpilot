import { describe, it, expect, beforeEach, afterEach } from 'vitest'

import { createInMemoryDb, type TestDb } from '../../_helpers/inMemoryDb'
import { setTestDb } from '@/data/sqlite/connection'
import {
  upsertProject,
  getProject,
  listProjects,
  deleteProject,
  touchSyncedAt,
} from '@/data/sqlite/repos/projectRepo'
import type { LocalProject } from '@/types/local'

const sample = (over: Partial<LocalProject> = {}): LocalProject => ({
  id: 'p1',
  title: '量子计算',
  description: '研究方向描述',
  domain: 'physics',
  domains: ['physics', 'math'],
  search_config: { foo: 'bar' },
  current_round: 0,
  max_rounds: 10,
  status: 'active',
  research_note_md: '',
  research_note_updated_at: null,
  research_note_updated_by: null,
  created_at: 1700000000000,
  updated_at: 1700000000000,
  last_synced_at: null,
  ...over,
})

describe('projectRepo', () => {
  let db: TestDb

  beforeEach(() => {
    db = createInMemoryDb()
  })
  afterEach(async () => {
    await db.raw.close()
    setTestDb(null)
  })

  it('upsert 新项目并能 get', async () => {
    await upsertProject(sample())
    const got = await getProject('p1')
    expect(got).not.toBeNull()
    expect(got!.title).toBe('量子计算')
    expect(got!.domains).toEqual(['physics', 'math'])
    expect(got!.search_config).toEqual({ foo: 'bar' })
  })

  it('upsert 同 id 更新字段', async () => {
    await upsertProject(sample())
    await upsertProject(sample({ title: 'updated', current_round: 3, updated_at: 1700000001000 }))
    const got = await getProject('p1')
    expect(got!.title).toBe('updated')
    expect(got!.current_round).toBe(3)
  })

  it('list 按 updated_at desc 排序', async () => {
    await upsertProject(sample({ id: 'p1', updated_at: 1700000000000 }))
    await upsertProject(sample({ id: 'p2', updated_at: 1700000010000 }))
    await upsertProject(sample({ id: 'p3', updated_at: 1700000005000 }))
    const list = await listProjects()
    expect(list.map((p) => p.id)).toEqual(['p2', 'p3', 'p1'])
  })

  it('list 可按 status 过滤', async () => {
    await upsertProject(sample({ id: 'p1', status: 'active' }))
    await upsertProject(sample({ id: 'p2', status: 'archived' }))
    const active = await listProjects({ status: 'active' })
    expect(active).toHaveLength(1)
    expect(active[0].id).toBe('p1')
  })

  it('delete 移除 + cascade 不影响其它项目', async () => {
    await upsertProject(sample({ id: 'p1' }))
    await upsertProject(sample({ id: 'p2' }))
    await deleteProject('p1')
    const list = await listProjects()
    expect(list).toHaveLength(1)
    expect(list[0].id).toBe('p2')
  })

  it('touchSyncedAt 更新 last_synced_at', async () => {
    await upsertProject(sample({ id: 'p1', last_synced_at: null }))
    await touchSyncedAt('p1', 1700000999999)
    const got = await getProject('p1')
    expect(got!.last_synced_at).toBe(1700000999999)
  })

  it('null JSON 字段返回 null 而非空对象', async () => {
    await upsertProject(sample({ domains: null, search_config: null }))
    const got = await getProject('p1')
    expect(got!.domains).toBeNull()
    expect(got!.search_config).toBeNull()
  })
})
