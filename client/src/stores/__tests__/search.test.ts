/**
 * search store 单测：rounds CRUD 走本地 SQLite。
 * RoundOrchestrator 的 startRound 调用 mock 成 noop（避免单测真跑 11-phase）。
 */
import { setActivePinia, createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { setTestDb } from '@/data/sqlite/connection'
import { upsertProject } from '@/data/sqlite/repos/projectRepo'
import { upsertRound, upsertRoundDocument } from '@/data/sqlite/repos/roundRepo'
import { upsertDocument } from '@/data/sqlite/repos/documentRepo'

import { useSearchStore } from '../search'
import { mkBetterSqliteHandle, mkDoc, mkProject, mkRound } from './_dbHelpers'

vi.mock('@/data/llm/manager', () => ({
  llmManager: {
    generate: vi.fn(async () => ({ text: 'm', usage: {}, cost_usd: 0, latency_ms: 1, provider: 'mock', model: 'mock' })),
  },
}))

// 让 applyMemoryPhase 内部 readCombinedMemoryForAgents 不在测试环境炸（无真 Tauri runtime）
// 内存 fs store + 简易 invoke 实现，仅返回必要 fs 命令的安全默认值。
vi.mock('@tauri-apps/api/core', () => {
  const store = new Map<string, string>()
  return {
    _store: store,
    invoke: vi.fn(async (cmd: string, args: Record<string, unknown> = {}) => {
      const rel = String(args.relPath ?? '')
      switch (cmd) {
        case 'fs_write_text':
          store.set(rel, String(args.content ?? ''))
          return undefined
        case 'fs_read_text':
          return store.has(rel) ? store.get(rel)! : null
        case 'fs_exists':
          return store.has(rel)
        case 'fs_remove':
          store.delete(rel)
          return undefined
        case 'fs_list_dir':
          return []
        default:
          return undefined
      }
    }),
  }
})

vi.mock('@/data/orchestrator/roundOrchestrator', async () => {
  return {
    getRoundOrchestrator: () => ({
      setLlmManager: vi.fn(),
      startRound: vi.fn(async () => undefined),
      confirmKeywords: vi.fn(async (roundId: string, plan: Record<string, unknown>) => {
        // 模仿真 orchestrator：写 keyword_plan 到 round.search_queries 并切换 status
        const { getRound, upsertRound } = await import('@/data/sqlite/repos/roundRepo')
        const r = await getRound(roundId)
        if (!r) throw new Error('round not found')
        const sq = (r.search_queries && typeof r.search_queries === 'object'
          ? { ...(r.search_queries as Record<string, unknown>) }
          : {})
        sq.keyword_plan = { ...plan, confirmed: true }
        await upsertRound({ ...r, status: 'searching', search_queries: sq })
      }),
    }),
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

describe('useSearchStore.fetchRounds', () => {
  it('空 → currentRound = null', async () => {
    const store = useSearchStore()
    await store.fetchRounds('p1')
    expect(store.rounds.length).toBe(0)
    expect(store.currentRound).toBeNull()
  })

  it('多轮 → currentRound = 第一个未 complete 的', async () => {
    await upsertRound(mkRound('r1', 'p1', { round_number: 1, status: 'complete' }))
    await upsertRound(mkRound('r2', 'p1', { round_number: 2, status: 'awaiting_feedback' }))
    const store = useSearchStore()
    await store.fetchRounds('p1')
    expect(store.rounds.length).toBe(2)
    expect(store.currentRound?.id).toBe('r2')
  })

  it('awaiting_keywords → 还原 keywordPlan', async () => {
    await upsertRound(mkRound('r1', 'p1', {
      status: 'awaiting_keywords',
      search_queries: { keyword_plan: { base_query: 'foo', confirmed: false } },
    }))
    const store = useSearchStore()
    await store.fetchRounds('p1')
    expect(store.awaitingKeywordConfirmation).toBe(true)
    expect((store.keywordPlan as { base_query?: string })?.base_query).toBe('foo')
  })
})

describe('useSearchStore.startRound', () => {
  it('新建 round → SQLite 持久化 + currentRound', async () => {
    const store = useSearchStore()
    const r = await store.startRound('p1')
    expect(r.id).toBeTruthy()
    expect(r.round_number).toBe(1)
    expect(r.status).toBe('pending')
    expect(store.currentRound?.id).toBe(r.id)
    expect(store.rounds.length).toBe(1)
  })

  it('round_number 自增', async () => {
    await upsertRound(mkRound('r1', 'p1', { round_number: 5 }))
    const store = useSearchStore()
    const r = await store.startRound('p1')
    expect(r.round_number).toBe(6)
  })
})

describe('useSearchStore.confirmKeywords', () => {
  it('写 keyword_plan + status=searching', async () => {
    await upsertRound(mkRound('r1', 'p1', { status: 'awaiting_keywords' }))
    const store = useSearchStore()
    await store.fetchRounds('p1')
    const r = await store.confirmKeywords('p1', 'r1', { base_query: 'X' })
    expect(r.status).toBe('searching')
    const sq = r.search_queries as Record<string, unknown>
    expect((sq.keyword_plan as { base_query?: string }).base_query).toBe('X')
  })
})

describe('useSearchStore.loadRoundResults', () => {
  it('拉 round_documents + 文档元数据', async () => {
    await upsertRound(mkRound('r1', 'p1'))
    await upsertDocument(mkDoc('d1', { title: 'A' }))
    await upsertDocument(mkDoc('d2', { title: 'B' }))
    await upsertRoundDocument({
      id: 'rd1', round_id: 'r1', document_id: 'd1', rank_in_round: 1,
      initial_score: null, agent_score: null, agent_rationale: null,
      one_line_summary: null, below_cutoff: false,
    })
    await upsertRoundDocument({
      id: 'rd2', round_id: 'r1', document_id: 'd2', rank_in_round: 2,
      initial_score: null, agent_score: null, agent_rationale: null,
      one_line_summary: null, below_cutoff: false,
    })
    const store = useSearchStore()
    const { getRound } = await import('@/data/sqlite/repos/roundRepo')
    store.currentRound = await getRound('r1')
    await store.loadRoundResults('r1')
    expect(store.documents.map((d) => d.id).sort()).toEqual(['d1', 'd2'])
  })

  it('below_cutoff 文档过滤', async () => {
    await upsertRound(mkRound('r1', 'p1'))
    await upsertDocument(mkDoc('d1'))
    await upsertDocument(mkDoc('d2'))
    await upsertRoundDocument({
      id: 'rd1', round_id: 'r1', document_id: 'd1', rank_in_round: 1,
      initial_score: null, agent_score: null, agent_rationale: null,
      one_line_summary: null, below_cutoff: false,
    })
    await upsertRoundDocument({
      id: 'rd2', round_id: 'r1', document_id: 'd2', rank_in_round: 2,
      initial_score: null, agent_score: null, agent_rationale: null,
      one_line_summary: null, below_cutoff: true,
    })
    const store = useSearchStore()
    await store.loadRoundResults('r1')
    expect(store.documents.length).toBe(1)
    expect(store.documents[0].id).toBe('d1')
  })
})

describe('useSearchStore.submitFeedback', () => {
  it('写 document_classifications', async () => {
    await upsertRound(mkRound('r1', 'p1'))
    await upsertDocument(mkDoc('d1'))
    const store = useSearchStore()
    await store.fetchRounds('p1')
    store.currentRound = { ...mkRound('r1', 'p1'), search_queries: null }
    store.setFeedback('d1', 2)
    const r = await store.submitFeedback('p1')
    expect(r.saved).toBe(1)
    // SQLite 应有一条 very_relevant
    const { getBucketCounts } = await import('@/data/sqlite/repos/bucketRepo')
    const counts = await getBucketCounts('p1')
    expect(counts.very_relevant).toBe(1)
  })

  it('relevance 映射：-1=irrelevant / 0=uncertain / 1=relevant / 2=very_relevant', async () => {
    await upsertRound(mkRound('r1', 'p1'))
    await upsertDocument(mkDoc('d1'))
    await upsertDocument(mkDoc('d2'))
    await upsertDocument(mkDoc('d3'))
    await upsertDocument(mkDoc('d4'))
    const store = useSearchStore()
    store.currentRound = mkRound('r1', 'p1')
    store.setFeedback('d1', -1)
    store.setFeedback('d2', 0)
    store.setFeedback('d3', 1)
    store.setFeedback('d4', 2)
    await store.submitFeedback('p1')
    const { getBucketCounts } = await import('@/data/sqlite/repos/bucketRepo')
    const counts = await getBucketCounts('p1')
    expect(counts.irrelevant).toBe(1)
    expect(counts.uncertain).toBe(1)
    expect(counts.relevant).toBe(1)
    expect(counts.very_relevant).toBe(1)
  })

  it('画像学习闭环（audit fix bug #1）：submitFeedback 后 memory phase 触发 LLM', async () => {
    // 这是 audit bug #1 的实证测试 ——
    // 之前 stores/search.ts:254 写了 `void applyMemoryUpdate` 显式不调，导致
    // MemoryAgent + memoryRepo 实现完整但生产 0 调用点。修复后 submitFeedback
    // 会 fire-and-forget 跑 applyMemoryPhase。这里验证：
    //   a. submitFeedback 完成后 llmManager.generate **真被调**
    //   b. 反馈条目结构进了 prompt（含 bucket 区段）
    //   c. 主流程 saved=N 仍及时返回（fire-and-forget 不阻塞）
    //
    // 注：不严格断言 doc title 内容（前序测试 fire-and-forget 可能在 mockClear 之前
    // 写入 generate.mock.calls），但断言 prompt 含 memory_update 模板的 marker
    // 来证明 generate 是被本测试触发，而不是前序测试 leak。
    await upsertRound(mkRound('r1', 'p1'))
    await upsertDocument(mkDoc('d1', { title: 'TransformerScalingLawsAuditMarker', abstract: 'How model size affects perplexity' }))
    const store = useSearchStore()
    store.currentRound = mkRound('r1', 'p1')
    store.setFeedback('d1', 2)

    // 拿到 mock 的 generate fn
    const { llmManager } = await import('@/data/llm/manager')
    const generateMock = (llmManager as unknown as { generate: ReturnType<typeof vi.fn> }).generate
    generateMock.mockClear()

    // 让 mock 返一个能解析的 v4 响应
    generateMock.mockImplementationOnce(async () => ({
      text: JSON.stringify({
        research_focus: 'LLM scaling',
        files: [
          {
            filename: 'identity.md',
            type: 'identity',
            name: '研究方向',
            description: 'LLM scaling',
            body: '## 研究方向\nLLM scaling',
          },
        ],
      }),
    }))

    const r = await store.submitFeedback('p1')
    expect(r.saved).toBe(1)

    // fire-and-forget — 等 microtask 完全 flush（applyMemoryPhase 内部多个 await）。
    // 等条件：找到至少一次 generate 调用，且 prompt 含本测试 marker（避免前序测试 leak）。
    let foundOurCall = false
    for (let i = 0; i < 30; i++) {
      await new Promise((resolve) => setTimeout(resolve, 10))
      foundOurCall = generateMock.mock.calls.some((args) =>
        typeof args[0] === 'string' && args[0].includes('TransformerScalingLawsAuditMarker'),
      )
      if (foundOurCall) break
    }

    // 验证 LLM 真被调到（之前 bug 状态下永远是 0），且 prompt 含本测试反馈
    expect(generateMock).toHaveBeenCalled()
    expect(foundOurCall).toBe(true)
  })
})

describe('useSearchStore.finalizeRound', () => {
  it('round.status → complete', async () => {
    await upsertRound(mkRound('r1', 'p1', { status: 'awaiting_feedback' }))
    const store = useSearchStore()
    store.currentRound = mkRound('r1', 'p1', { status: 'awaiting_feedback' })
    await store.finalizeRound('p1')
    const { getRound } = await import('@/data/sqlite/repos/roundRepo')
    const updated = await getRound('r1')
    expect(updated?.status).toBe('complete')
  })
})

describe('useSearchStore.handleSSEEvent', () => {
  it('round_status 更新 currentRound', async () => {
    const store = useSearchStore()
    store.currentRound = mkRound('r1', 'p1')
    store.handleSSEEvent('round_status', { status: 'searching', progress: 0.3, message: 'foo' })
    expect(store.currentRound!.status).toBe('searching')
    expect(store.currentRound!.progress).toBe(0.3)
    expect(store.statusText).toBe('foo')
  })

  it('round_complete 触发 awaiting_feedback', async () => {
    await upsertRound(mkRound('r1', 'p1'))
    const store = useSearchStore()
    store.currentRound = mkRound('r1', 'p1')
    store.handleSSEEvent('round_complete', {})
    expect(store.currentRound!.status).toBe('awaiting_feedback')
    expect(store.currentRound!.progress).toBe(1)
  })
})
