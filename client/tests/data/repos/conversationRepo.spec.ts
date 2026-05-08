import { describe, it, expect, beforeEach, afterEach } from 'vitest'

import { createInMemoryDb, type TestDb } from '../../_helpers/inMemoryDb'
import { setTestDb } from '@/data/sqlite/connection'
import { upsertProject } from '@/data/sqlite/repos/projectRepo'
import {
  upsertSession,
  getSession,
  getActiveSessionForProject,
  setSessionActive,
  appendMessage,
  listMessages,
  upsertMessage,
} from '@/data/sqlite/repos/conversationRepo'
import type { LocalConversationSession, LocalMessage, LocalProject } from '@/types/local'

const proj: LocalProject = {
  id: 'p1', title: 't', description: '', domain: 'cs', domains: null, search_config: null,
  current_round: 0, max_rounds: 0, status: 'active',
  research_note_md: '', research_note_updated_at: null, research_note_updated_by: null,
  created_at: 1, updated_at: 1, last_synced_at: null,
}

const session = (over: Partial<LocalConversationSession> = {}): LocalConversationSession => ({
  id: 's1', project_id: 'p1', current_state: 'idle', state_data: null,
  search_mode: null, is_active: true, created_at: 1, updated_at: 1, last_synced_at: null,
  ...over,
})

describe('conversationRepo', () => {
  let db: TestDb
  beforeEach(async () => {
    db = createInMemoryDb()
    await upsertProject(proj)
  })
  afterEach(async () => { await db.raw.close(); setTestDb(null) })

  it('upsert session + get', async () => {
    await upsertSession(session({ state_data: { foo: 'bar' } }))
    const g = await getSession('s1')
    expect(g!.state_data).toEqual({ foo: 'bar' })
    expect(g!.is_active).toBe(true)
  })

  it('getActiveSessionForProject 返回唯一 active', async () => {
    await upsertSession(session({ id: 's1', is_active: true }))
    await upsertSession(session({ id: 's2', is_active: false }))
    const act = await getActiveSessionForProject('p1')
    expect(act!.id).toBe('s1')
  })

  it('setSessionActive 互斥同 project 内只能一个 active', async () => {
    await upsertSession(session({ id: 's1', is_active: true }))
    await upsertSession(session({ id: 's2', is_active: false }))
    await setSessionActive('s2')   // 切换
    const a1 = await getSession('s1')
    const a2 = await getSession('s2')
    expect(a1!.is_active).toBe(false)
    expect(a2!.is_active).toBe(true)
  })

  it('appendMessage 自动单调 seq', async () => {
    await upsertSession(session())
    const m1 = await appendMessage({
      session_id: 's1', role: 'user', content_md: 'hi', rich_data: null, created_at: 100,
    })
    const m2 = await appendMessage({
      session_id: 's1', role: 'assistant', content_md: 'hello', rich_data: null, created_at: 200,
    })
    expect(m1.seq).toBe(1)
    expect(m2.seq).toBe(2)
  })

  it('listMessages 默认按 seq asc', async () => {
    await upsertSession(session())
    await appendMessage({ session_id: 's1', role: 'user', content_md: 'a', rich_data: null, created_at: 1 })
    await appendMessage({ session_id: 's1', role: 'assistant', content_md: 'b', rich_data: null, created_at: 2 })
    await appendMessage({ session_id: 's1', role: 'user', content_md: 'c', rich_data: null, created_at: 3 })
    const list = await listMessages('s1')
    expect(list.map((m) => m.content_md)).toEqual(['a', 'b', 'c'])
  })

  it('listMessages 支持 limit + before_seq 分页', async () => {
    await upsertSession(session())
    for (let i = 1; i <= 5; i++) {
      await appendMessage({ session_id: 's1', role: 'user', content_md: 'msg' + i, rich_data: null, created_at: i })
    }
    const last3 = await listMessages('s1', { limit: 3 })
    expect(last3.map((m) => m.content_md)).toEqual(['msg3', 'msg4', 'msg5'])

    const earlier = await listMessages('s1', { limit: 2, before_seq: 3 })
    expect(earlier.map((m) => m.content_md)).toEqual(['msg1', 'msg2'])
  })

  it('upsertMessage with explicit id 是幂等的', async () => {
    await upsertSession(session())
    const msg: LocalMessage = {
      id: 'm-server-1', session_id: 's1', role: 'user',
      content_md: 'cloud', rich_data: { kind: 'rich' }, created_at: 1, seq: 1,
    }
    await upsertMessage(msg)
    await upsertMessage({ ...msg, content_md: 'updated' })
    const list = await listMessages('s1')
    expect(list).toHaveLength(1)
    expect(list[0].content_md).toBe('updated')
  })
})
