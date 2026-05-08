/**
 * library store 单测：list/groupedFiles 来自 SQLite，detail 来自 LiteratureWriter。
 *
 * Mock files 模块 → 内存 fs，让 LiteratureWriter 真跑。
 */
import { setActivePinia, createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setTestDb } from '@/data/sqlite/connection'
import { upsertClassification } from '@/data/sqlite/repos/bucketRepo'
import { upsertDocument } from '@/data/sqlite/repos/documentRepo'
import { upsertProject } from '@/data/sqlite/repos/projectRepo'

import { useLibraryStore } from '../library'
import { mkBetterSqliteHandle, mkDoc, mkProject } from './_dbHelpers'

vi.mock('@/data/fs/files', () => {
  const store = new Map<string, string>()
  return {
    _store: store,
    async writeText(rel: string, content: string) { store.set(rel, content) },
    async readText(rel: string) { return store.has(rel) ? store.get(rel)! : null },
    async removePath(rel: string) { store.delete(rel) },
    async fileExists(rel: string) { return store.has(rel) },
    async writeBytes() { /* unused */ },
    async readBytes() { return null },
    async fileSize() { return null },
    async listDir() { return [] },
    async downloadToFile() { return { size: 0 } },
  }
})

let dbHandle: ReturnType<typeof mkBetterSqliteHandle>

beforeEach(async () => {
  setActivePinia(createPinia())
  dbHandle = mkBetterSqliteHandle()
  setTestDb(dbHandle)
  await upsertProject(mkProject('p1', { title: 'Demo' }))
  await upsertDocument(mkDoc('d1', { title: 'Paper A', source: 'arxiv', publication_date: '2024-03-01' }))
  await upsertDocument(mkDoc('d2', { title: 'Paper B', source: 'openalex', publication_date: '2025-06-01' }))
  await upsertDocument(mkDoc('d3', { title: 'Paper C', source: 'crossref' }))
  await upsertClassification({
    project_id: 'p1', document_id: 'd1', bucket: 'very_relevant',
    reason: null, classified_at: 1000, last_synced_at: null,
  })
  await upsertClassification({
    project_id: 'p1', document_id: 'd2', bucket: 'relevant',
    reason: null, classified_at: 2000, last_synced_at: null,
  })
  // d3 没分类 → loadFiles 不出现
})

afterEach(async () => {
  await dbHandle.close()
  setTestDb(null)
  const m = await import('@/data/fs/files') as unknown as { _store: Map<string, string> }
  m._store.clear()
})

describe('useLibraryStore.loadFiles', () => {
  it('list 仅含已分类文档', async () => {
    const store = useLibraryStore()
    await store.loadFiles('p1')
    expect(store.files.length).toBe(2)
    expect(store.total).toBe(2)
    const ids = store.files.map((f) => f.slug).sort()
    expect(ids).toEqual(['d1', 'd2'])
  })

  it('byBucket 计数', async () => {
    const store = useLibraryStore()
    await store.loadFiles('p1')
    expect(store.byBucket.very_relevant).toBe(1)
    expect(store.byBucket.relevant).toBe(1)
  })

  it('groupedFiles 按桶分组', async () => {
    const store = useLibraryStore()
    await store.loadFiles('p1')
    expect(store.groupedFiles.very_relevant.length).toBe(1)
    expect(store.groupedFiles.relevant.length).toBe(1)
  })

  it('filter.search 命中 title', async () => {
    const store = useLibraryStore()
    await store.loadFiles('p1')
    store.setFilter({ search: 'Paper A' })
    expect(store.filteredFiles.length).toBe(1)
    expect(store.filteredFiles[0].slug).toBe('d1')
  })

  it('year 从 publication_date 提取', async () => {
    const store = useLibraryStore()
    await store.loadFiles('p1')
    const d1 = store.files.find((f) => f.slug === 'd1')!
    const d2 = store.files.find((f) => f.slug === 'd2')!
    expect(d1.year).toBe(2024)
    expect(d2.year).toBe(2025)
  })
})

describe('useLibraryStore.selectFile', () => {
  it('文件不存在 .md → 用 SQLite 占位', async () => {
    const store = useLibraryStore()
    await store.selectFile('p1', 'd1')
    expect(store.currentDetail?.slug).toBe('d1')
    const fm = store.currentDetail!.frontmatter as Record<string, unknown>
    expect(fm.title).toBe('Paper A')
  })

  it('rebuild 后 selectFile 读 .md', async () => {
    const store = useLibraryStore()
    await store.triggerRebuild('p1')
    await store.selectFile('p1', 'd1')
    expect(store.currentDetail?.body_md).toContain('Paper A')
  })
})

describe('useLibraryStore.triggerRebuild', () => {
  it('写所有 .md + index.md 到 fs', async () => {
    const store = useLibraryStore()
    await store.triggerRebuild('p1')
    const m = await import('@/data/fs/files') as unknown as { _store: Map<string, string> }
    const keys = Array.from(m._store.keys()).sort()
    // 期望：projects/Demo__p1/library/docs/d1.md, d2.md, library/index.md
    const indexKey = keys.find((k) => k.endsWith('library/index.md'))
    expect(indexKey).toBeTruthy()
    const docKeys = keys.filter((k) => k.includes('library/docs/') && k.endsWith('.md'))
    expect(docKeys.length).toBe(2)
  })
})

describe('useLibraryStore.deleteSelected', () => {
  it('选中 → 删 classification + .md', async () => {
    const store = useLibraryStore()
    await store.triggerRebuild('p1')
    await store.loadFiles('p1')
    store.toggleSelect('d1')
    const r = await store.deleteSelected('p1')
    expect(r.deleted).toBe(1)
    expect(r.failed.length).toBe(0)
    // 重新 load → d1 没了
    await store.loadFiles('p1')
    expect(store.files.find((f) => f.slug === 'd1')).toBeUndefined()
    // .md 被删
    const m = await import('@/data/fs/files') as unknown as { _store: Map<string, string> }
    expect(Array.from(m._store.keys()).find((k) => k.includes('d1.md'))).toBeUndefined()
  })
})

describe('useLibraryStore.toggleSelect / selectAll / clearSelection', () => {
  it('toggleSelect 切换', () => {
    const store = useLibraryStore()
    store.toggleSelect('d1')
    expect(store.selectedSlugs.has('d1')).toBe(true)
    store.toggleSelect('d1')
    expect(store.selectedSlugs.has('d1')).toBe(false)
  })

  it('selectAll 全选', () => {
    const store = useLibraryStore()
    store.selectAll(['a', 'b', 'c'])
    expect(store.selectedSlugs.size).toBe(3)
    store.clearSelection()
    expect(store.selectedSlugs.size).toBe(0)
  })
})
