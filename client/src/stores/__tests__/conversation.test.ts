/**
 * conversation store 单测：sessions / messages 走本地 SQLite。
 * LLM 调用 mock 成立即返预设文本，不打实网。
 */
import { setActivePinia, createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setTestDb } from '@/data/sqlite/connection'
import { listMessages } from '@/data/sqlite/repos/conversationRepo'
import { upsertProject } from '@/data/sqlite/repos/projectRepo'

import { useConversationStore } from '../conversation'
import { mkBetterSqliteHandle, mkProject } from './_dbHelpers'

vi.mock('@/data/llm/manager', () => {
  return {
    llmManager: {
      generate: vi.fn(async (_prompt: string) => ({
        text: 'mocked answer',
        usage: { input_tokens: 1, output_tokens: 2 },
        cost_usd: 0,
        latency_ms: 1,
        provider: 'mock',
        model: 'mock',
      })),
    },
  }
})

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

describe('useConversationStore.startSession', () => {
  it('新建 session → SQLite 持久化', async () => {
    const store = useConversationStore()
    await store.startSession('p1')
    expect(store.sessionId).toBeTruthy()
    expect(store.projectId).toBe('p1')
    expect(store.currentState).toBe('idle')
    expect(store.messages.length).toBe(0)
  })
})

describe('useConversationStore.sendMessage', () => {
  it('用户消息 + LLM 回复都写入 SQLite', async () => {
    const store = useConversationStore()
    await store.startSession('p1')
    await store.sendMessage('hello')
    expect(store.messages.length).toBe(2)
    expect(store.messages[0].role).toBe('user')
    expect(store.messages[0].content).toBe('hello')
    expect(store.messages[1].role).toBe('assistant')
    expect(store.messages[1].content).toBe('mocked answer')
    // SQLite 也有
    const sid = store.sessionId!
    const persisted = await listMessages(sid)
    expect(persisted.length).toBe(2)
    expect(persisted[0].role).toBe('user')
    expect(persisted[1].role).toBe('assistant')
  })

  it('空字符串 / 无 session → 无操作', async () => {
    const store = useConversationStore()
    await store.sendMessage('foo') // 没 session
    expect(store.messages.length).toBe(0)
    await store.startSession('p1')
    await store.sendMessage('   ')
    expect(store.messages.length).toBe(0)
  })
})

describe('useConversationStore.findOrCreateSession', () => {
  it('已有 active session → 复用', async () => {
    const store = useConversationStore()
    await store.startSession('p1')
    const sid = store.sessionId
    // 重置 store 状态后再 find
    store.reset()
    await store.findOrCreateSession('p1')
    expect(store.sessionId).toBe(sid)
  })

  it('无 active session → 新建', async () => {
    const store = useConversationStore()
    await store.findOrCreateSession('p1')
    expect(store.sessionId).toBeTruthy()
    expect(store.projectId).toBe('p1')
  })
})

describe('useConversationStore.appendIncomingMessage', () => {
  it('id 重复 → 不重复加', async () => {
    const store = useConversationStore()
    await store.startSession('p1')
    store.appendIncomingMessage({
      id: 'm1', role: 'assistant', content: 'X', timestamp: '2025-01-01T00:00:00Z',
    })
    store.appendIncomingMessage({
      id: 'm1', role: 'assistant', content: 'X dup', timestamp: '2025-01-01T00:00:00Z',
    })
    expect(store.messages.length).toBe(1)
    expect(store.messages[0].content).toBe('X')
  })
})

describe('useConversationStore.restoreSession', () => {
  it('persistAssistantMessage → restoreSession 拿回', async () => {
    const store = useConversationStore()
    await store.startSession('p1')
    const sid = store.sessionId!
    await store.persistAssistantMessage('rich content', { type: 'round_complete' })
    store.reset()
    await store.restoreSession(sid)
    expect(store.messages.find((m) => m.content === 'rich content')).toBeTruthy()
  })

  it('session 不存在 → throw', async () => {
    const store = useConversationStore()
    await expect(store.restoreSession('ghost')).rejects.toThrow()
  })
})
