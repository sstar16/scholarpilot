/**
 * notebook store 单测：本地 research_note_pages 表 CRUD。
 */
import { setActivePinia, createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { setTestDb } from '@/data/sqlite/connection'
import { upsertProject } from '@/data/sqlite/repos/projectRepo'

import { useNotebookStore } from '../notebook'
import { mkBetterSqliteHandle, mkProject } from './_dbHelpers'

let dbHandle: ReturnType<typeof mkBetterSqliteHandle>

beforeEach(async () => {
  setActivePinia(createPinia())
  dbHandle = mkBetterSqliteHandle()
  setTestDb(dbHandle)
  await upsertProject(mkProject('p1'))
})

afterEach(async () => {
  await dbHandle.close()
  setTestDb(null)
})

describe('useNotebookStore.createPage / fetchPages', () => {
  it('创建一页 → 出现在 pages + currentPageId', async () => {
    const store = useNotebookStore()
    store.projectId = 'p1'
    const page = await store.createPage('Hello', 'body md')
    expect(page).toBeTruthy()
    expect(store.pages.length).toBe(1)
    expect(store.currentPageId).toBe(page!.id)
  })

  it('多页 → fetchPages 按 sort_order 升序', async () => {
    const store = useNotebookStore()
    store.projectId = 'p1'
    await store.createPage('A')
    await store.createPage('B')
    await store.createPage('C')
    await store.fetchPages('p1')
    expect(store.pages.map((p) => p.title)).toEqual(['A', 'B', 'C'])
  })
})

describe('useNotebookStore.updateCurrentPage', () => {
  it('更新 title + body → 落库', async () => {
    const store = useNotebookStore()
    store.projectId = 'p1'
    const page = await store.createPage('A', 'old')
    store.currentPageId = page!.id
    const updated = await store.updateCurrentPage({ title: 'A2', body_md: 'new' })
    expect(updated?.title).toBe('A2')
    expect(updated?.body_md).toBe('new')
    await store.fetchPages('p1')
    expect(store.pages[0].title).toBe('A2')
  })

  it('未选 page → no-op', async () => {
    const store = useNotebookStore()
    store.projectId = 'p1'
    const r = await store.updateCurrentPage({ title: 'X' })
    expect(r).toBeNull()
  })
})

describe('useNotebookStore.deletePage', () => {
  it('删除后 pages 缩减', async () => {
    const store = useNotebookStore()
    store.projectId = 'p1'
    const a = await store.createPage('A')
    await store.createPage('B')
    await store.deletePage(a!.id)
    expect(store.pages.length).toBe(1)
    expect(store.pages[0].title).toBe('B')
  })
})

describe('useNotebookStore.applyAiUpdate', () => {
  it('设 lastAiUpdate + 触发 fetchPages', async () => {
    const store = useNotebookStore()
    store.projectId = 'p1'
    const p = await store.createPage('Note', 'old body')
    store.applyAiUpdate({
      mode: 'append_to_page',
      page_id: p!.id,
      title: 'Note',
      reason: 'AI added section',
      prev_len: 8,
      new_len: 30,
      preview: 'AI 追加',
    })
    expect(store.lastAiUpdate?.page_id).toBe(p!.id)
    expect(store.lastAiUpdate?.reason).toBe('AI added section')
    // fetchPages 是异步触发；让微任务跑完
    await new Promise((r) => setTimeout(r, 0))
    expect(store.currentPageId).toBe(p!.id)
  })

  it('dismissAiUpdate → 清空', async () => {
    const store = useNotebookStore()
    store.projectId = 'p1'
    const p = await store.createPage('A')
    store.applyAiUpdate({
      mode: 'update_page',
      page_id: p!.id,
      title: 'A',
      reason: '',
      prev_len: 0,
      new_len: 5,
      preview: '',
    })
    expect(store.lastAiUpdate).toBeTruthy()
    store.dismissAiUpdate()
    expect(store.lastAiUpdate).toBeNull()
  })
})

describe('useNotebookStore.openPanel / closePanel', () => {
  it('openPanel(pid) → panelOpen=true 同时 fetchPages', async () => {
    const store = useNotebookStore()
    store.projectId = 'p1'
    await store.createPage('X')
    // 模拟从外部入口打开（panel 关闭状态下重新打开）
    store.closePanel()
    store.openPanel('p1')
    expect(store.panelOpen).toBe(true)
    // 等异步 fetchPages
    await new Promise((r) => setTimeout(r, 0))
    expect(store.pages.length).toBeGreaterThan(0)
    store.closePanel()
    expect(store.panelOpen).toBe(false)
  })
})
