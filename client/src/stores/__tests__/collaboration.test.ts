/**
 * collaboration store 单测：startCollaboration / askQuestion / note 流。
 *
 * Mock：LLMManager 返简单 final answer；ResearchAgent 走真实路径调 mock LLM。
 */
import { setActivePinia, createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setTestDb } from '@/data/sqlite/connection'
import { upsertClassification } from '@/data/sqlite/repos/bucketRepo'
import { upsertDocument } from '@/data/sqlite/repos/documentRepo'
import { upsertProject } from '@/data/sqlite/repos/projectRepo'

import { useCollaborationStore } from '../collaboration'
import { mkBetterSqliteHandle, mkDoc, mkProject } from './_dbHelpers'

vi.mock('@/data/llm/manager', () => ({
  llmManager: {
    generate: vi.fn(async () => ({
      text: JSON.stringify({
        action: 'final',
        answer: 'Mocked answer with [1] citation',
        citations: [{ doc_id: 'd1', evidence: 'evidence text' }],
      }),
      usage: {},
      cost_usd: 0,
      latency_ms: 1,
      provider: 'mock',
      model: 'mock',
    })),
  },
}))

let dbHandle: ReturnType<typeof mkBetterSqliteHandle>

beforeEach(async () => {
  setActivePinia(createPinia())
  dbHandle = mkBetterSqliteHandle()
  setTestDb(dbHandle)
  await upsertProject(mkProject('p1', { title: 'P1' }))
  await upsertDocument(mkDoc('d1', { title: 'A', abstract: 'abs A', fulltext_text: 'full A' }))
  await upsertDocument(mkDoc('d2', { title: 'B', abstract: 'abs B' }))
  await upsertClassification({
    project_id: 'p1', document_id: 'd1', bucket: 'very_relevant',
    reason: null, classified_at: 1, last_synced_at: null,
  })
  await upsertClassification({
    project_id: 'p1', document_id: 'd2', bucket: 'relevant',
    reason: null, classified_at: 2, last_synced_at: null,
  })
})

afterEach(async () => {
  await dbHandle.close()
  setTestDb(null)
})

describe('useCollaborationStore.startCollaboration', () => {
  it('装载 docs + 生成 snapshot', async () => {
    const store = useCollaborationStore()
    const snap = await store.startCollaboration('sess-1', ['d1', 'd2'], 'p1')
    expect(snap.docs.length).toBe(2)
    expect(store.state).toBe('active')
    expect(store.sessionId).toBe('sess-1')
    expect(store.docIds).toEqual(['d1', 'd2'])
    expect(store.isActive).toBe(true)
  })

  it('无 projectId → 抛错', async () => {
    const store = useCollaborationStore()
    await expect(store.startCollaboration('s', ['d1'])).rejects.toThrow(/projectId/)
  })
})

describe('useCollaborationStore.updateDocs', () => {
  it('add → 合并 ids', async () => {
    const store = useCollaborationStore()
    await store.startCollaboration('s', ['d1'], 'p1')
    const r = await store.updateDocs('add', ['d2'])
    expect(r?.doc_ids.sort()).toEqual(['d1', 'd2'])
  })

  it('remove → 减去', async () => {
    const store = useCollaborationStore()
    await store.startCollaboration('s', ['d1', 'd2'], 'p1')
    const r = await store.updateDocs('remove', ['d1'])
    expect(r?.doc_ids).toEqual(['d2'])
  })

  it('replace → 整体覆盖', async () => {
    const store = useCollaborationStore()
    await store.startCollaboration('s', ['d1'], 'p1')
    const r = await store.updateDocs('replace', ['d2'])
    expect(r?.doc_ids).toEqual(['d2'])
  })
})

describe('useCollaborationStore.askQuestion', () => {
  it('调 ResearchAgent → 收 final answer + citations', async () => {
    const store = useCollaborationStore()
    await store.startCollaboration('s', ['d1'], 'p1')
    const result = await store.askQuestion('What is X?')
    expect(result).toBeTruthy()
    expect(result!.answer).toContain('Mocked answer')
    expect(result!.citations.length).toBe(1)
    expect(result!.citations[0].docId).toBe('d1')
    expect(store.lastResearchResult).toEqual(result)
  })

  it('空问题 → null', async () => {
    const store = useCollaborationStore()
    store.setProjectId('p1')
    const r = await store.askQuestion('   ')
    expect(r).toBeNull()
  })

  it('未设 projectId → null + error', async () => {
    const store = useCollaborationStore()
    const r = await store.askQuestion('q')
    expect(r).toBeNull()
    expect(store.error).toMatch(/projectId/)
  })
})

describe('useCollaborationStore.fetchNote / saveNote', () => {
  it('saveNote → 写 research_note_pages 第一页 → fetchNote 拿回', async () => {
    const store = useCollaborationStore()
    await store.startCollaboration('s', ['d1'], 'p1')
    await store.saveNote('hello note')
    expect(store.note.content).toBe('hello note')
    // reset 后 fetchNote 还能拿到
    store.note = { content: '', updated_at: null, updated_by: null }
    await store.fetchNote()
    expect(store.note.content).toBe('hello note')
  })
})

describe('useCollaborationStore.exitCollaboration', () => {
  it('清状态 → state=off', async () => {
    const store = useCollaborationStore()
    await store.startCollaboration('s', ['d1'], 'p1')
    await store.exitCollaboration(false)
    expect(store.state).toBe('off')
    expect(store.sessionId).toBeNull()
    expect(store.docIds.length).toBe(0)
  })
})

describe('useCollaborationStore.restoreFromSession', () => {
  it('从 session.state_data.collaboration 还原', async () => {
    const store = useCollaborationStore()
    await store.restoreFromSession('s', {
      current_state: 'collaboration_active',
      state_data: {
        collaboration: { doc_ids: ['d1'], project_id: 'p1', auto_mode: true },
      },
    })
    expect(store.sessionId).toBe('s')
    expect(store.docIds).toEqual(['d1'])
    expect(store.state).toBe('active')
    expect(store.autoMode).toBe(true)
  })

  it('archived → 不还原', async () => {
    const store = useCollaborationStore()
    await store.restoreFromSession('s', {
      current_state: 'collaboration_active',
      state_data: { collaboration: { archived: true, doc_ids: ['d1'] } },
    })
    expect(store.state).toBe('off')
  })
})
