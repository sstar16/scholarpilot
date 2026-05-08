import { describe, it, expect, beforeEach, afterEach } from 'vitest'

import { createInMemoryDb, type TestDb } from '../../_helpers/inMemoryDb'
import { setTestDb } from '@/data/sqlite/connection'
import { upsertProject } from '@/data/sqlite/repos/projectRepo'
import {
  upsertNotebookPage,
  getNotebookPage,
  listPagesByProject,
  deleteNotebookPage,
  reorderPage,
} from '@/data/sqlite/repos/notebookRepo'
import type { LocalNotebookPage, LocalProject } from '@/types/local'

const proj: LocalProject = {
  id: 'p1', title: 't', description: '', domain: 'cs', domains: null, search_config: null,
  current_round: 0, max_rounds: 0, status: 'active',
  research_note_md: '', research_note_updated_at: null, research_note_updated_by: null,
  created_at: 1, updated_at: 1, last_synced_at: null,
}

const page = (over: Partial<LocalNotebookPage> = {}): LocalNotebookPage => ({
  id: 'pg1', project_id: 'p1', title: '研究笔记', body_md: '# 标题\n内容',
  sort_order: 0, updated_at: 1, updated_by: 'user', created_at: 1, last_synced_at: null,
  ...over,
})

describe('notebookRepo', () => {
  let db: TestDb
  beforeEach(async () => {
    db = createInMemoryDb()
    await upsertProject(proj)
  })
  afterEach(async () => { await db.raw.close(); setTestDb(null) })

  it('upsert + get', async () => {
    await upsertNotebookPage(page())
    const g = await getNotebookPage('pg1')
    expect(g!.body_md).toBe('# 标题\n内容')
    expect(g!.updated_by).toBe('user')
  })

  it('listPagesByProject 按 sort_order asc', async () => {
    await upsertNotebookPage(page({ id: 'pg1', sort_order: 2 }))
    await upsertNotebookPage(page({ id: 'pg2', sort_order: 0 }))
    await upsertNotebookPage(page({ id: 'pg3', sort_order: 1 }))
    const list = await listPagesByProject('p1')
    expect(list.map((p) => p.id)).toEqual(['pg2', 'pg3', 'pg1'])
  })

  it('reorderPage 单独更新 sort_order', async () => {
    await upsertNotebookPage(page({ id: 'pg1', sort_order: 0 }))
    await reorderPage('pg1', 5)
    const g = await getNotebookPage('pg1')
    expect(g!.sort_order).toBe(5)
  })

  it('delete 移除', async () => {
    await upsertNotebookPage(page())
    await deleteNotebookPage('pg1')
    expect(await getNotebookPage('pg1')).toBeNull()
  })
})
