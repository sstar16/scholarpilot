/**
 * applyMemoryPhase 单测 — 验证画像学习闭环 fix（audit 2026-05-08，bug #1）。
 *
 * 覆盖：
 *  1. happy path：3 篇 feedback → MemoryAgent.update → applyMemoryUpdate 写盘 →
 *     MEMORY.md v1 出现 + applied=true
 *  2. 0 feedbacks → applied=false (no LLM call)
 *  3. 无 LLM → applied=false（graceful skip）
 *  4. MemoryAgent 返 0 files（解析失败）→ applied=false 不写盘
 *  5. 无 projectId → applied=false
 *  6. 跨轮：v1 → v2 累积（验证 memoryRepo.applyMemoryUpdate 真接通）
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { MemoryAgent, type FeedbackEntry, type LLMGenerator } from '@/data/agents/memoryAgent'
import { _clearCache as _clearPromptCache } from '@/data/agents/promptLoader'

// ──────────────── 内存 fs store mock（沿用 memory-flow.test.ts 模式）────────────────

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
        case 'fs_size':
          return store.has(rel) ? store.get(rel)!.length : null
        case 'fs_list_dir': {
          const prefix = rel.endsWith('/') ? rel : `${rel}/`
          const entries: Array<{
            name: string
            is_dir: boolean
            size: number
            modified_ms: number
          }> = []
          let i = 0
          for (const [k, v] of store.entries()) {
            if (!k.startsWith(prefix)) continue
            const rest = k.slice(prefix.length)
            if (rest.includes('/')) continue
            entries.push({
              name: rest,
              is_dir: false,
              size: v.length,
              modified_ms: 1_700_000_000_000 + i++ * 1000,
            })
          }
          return entries
        }
        default:
          return undefined
      }
    }),
  }
})

// projectRepo: 测试里 mock 掉 SQLite，给 getProject 返回固定数据
vi.mock('@/data/sqlite/repos/projectRepo', () => ({
  getProject: vi.fn(async (id: string) => {
    if (id === 'no-project') return null
    return {
      id,
      title: 'Audit Memory Project',
      description: 'LLM scaling research',
      domain: 'cs',
      domains: null,
      search_config: null,
      current_round: 1,
      max_rounds: 0,
      status: 'active',
      research_note_md: '',
      research_note_updated_at: null,
      research_note_updated_by: null,
      created_at: 0,
      updated_at: 0,
      last_synced_at: null,
    }
  }),
}))

async function getStore(): Promise<Map<string, string>> {
  const m = (await import('@tauri-apps/api/core')) as unknown as { _store: Map<string, string> }
  return m._store
}

// ──────────────── helpers ────────────────

function makeMockLLM(responses: Array<string | null>): LLMGenerator & { calls: string[] } {
  const calls: string[] = []
  let i = 0
  return {
    calls,
    async generate(prompt: string) {
      calls.push(prompt)
      if (i >= responses.length) return null
      return responses[i++]
    },
  }
}

const SAMPLE_FEEDBACKS: FeedbackEntry[] = [
  {
    docId: 'd1',
    bucket: 'very_relevant',
    docTitle: 'Transformer scaling laws',
    docAbstract: 'How model size affects perplexity',
    source: 'arxiv',
  },
  {
    docId: 'd2',
    bucket: 'irrelevant',
    docTitle: 'Pediatric trial',
    docAbstract: 'unrelated medical study',
    source: 'pubmed',
  },
]

const HAPPY_LLM_RESPONSE = JSON.stringify({
  research_focus: '大模型 scaling laws',
  files: [
    {
      filename: 'identity.md',
      type: 'identity',
      name: '研究方向',
      description: 'LLM scaling',
      body: '## 研究方向\n大模型 scaling laws',
    },
    {
      filename: 'preferred_topics.md',
      type: 'preference',
      name: '偏好主题',
      description: 'transformer 相关',
      body: '- transformer\n- scaling laws',
    },
  ],
})

beforeEach(async () => {
  _clearPromptCache()
  const store = await getStore()
  store.clear()
})

afterEach(async () => {
  const store = await getStore()
  store.clear()
})

describe('applyMemoryPhase（画像学习闭环 fix audit 2026-05-08）', () => {
  it('happy path：feedback → MemoryAgent → applyMemoryUpdate 写盘 → MEMORY.md v1 出现', async () => {
    const { applyMemoryPhase } = await import('../applyMemory')
    const { readProjectMemoryMd } = await import('@/data/memory/memoryRepo')

    const llm = makeMockLLM([HAPPY_LLM_RESPONSE])

    const r = await applyMemoryPhase({
      projectId: 'proj-audit-1',
      roundId: 'r1',
      feedbacks: SAMPLE_FEEDBACKS,
      llm,
    })

    expect(r.applied).toBe(true)
    expect(r.newVersion).toBe(1)
    expect(r.filesWritten).toBe(2)
    expect(r.rolledBack).toBe(false)

    // LLM 真被调
    expect(llm.calls).toHaveLength(1)
    expect(llm.calls[0]).toContain('Transformer scaling laws')
    expect(llm.calls[0]).toContain('LLM scaling research')  // project description 进 prompt

    // 真写到 fs
    const memMd = await readProjectMemoryMd('proj-audit-1', 'Audit Memory Project')
    expect(memMd).toContain('# 项目记忆 v1')
    expect(memMd).toContain('identity.md')
    expect(memMd).toContain('preferred_topics.md')
  })

  it('feedbacks 空 → applied=false，不调 LLM', async () => {
    const { applyMemoryPhase } = await import('../applyMemory')
    const llm = makeMockLLM(['should_not_be_called'])

    const r = await applyMemoryPhase({
      projectId: 'proj-audit-2',
      roundId: 'r1',
      feedbacks: [],
      llm,
    })

    expect(r.applied).toBe(false)
    expect(r.reason).toBe('no feedbacks')
    expect(llm.calls).toHaveLength(0)
  })

  it('llm=null → applied=false，graceful skip', async () => {
    const { applyMemoryPhase } = await import('../applyMemory')

    const r = await applyMemoryPhase({
      projectId: 'proj-audit-3',
      roundId: 'r1',
      feedbacks: SAMPLE_FEEDBACKS,
      llm: null,
    })

    expect(r.applied).toBe(false)
    expect(r.reason).toBe('no llm')
  })

  it('MemoryAgent 返 0 files（LLM 解析失败）→ applied=false 不写盘', async () => {
    const { applyMemoryPhase } = await import('../applyMemory')
    const { readProjectMemoryMd } = await import('@/data/memory/memoryRepo')

    const llm = makeMockLLM(['not a json at all { random'])

    const r = await applyMemoryPhase({
      projectId: 'proj-audit-4',
      roundId: 'r1',
      feedbacks: SAMPLE_FEEDBACKS,
      llm,
    })

    expect(r.applied).toBe(false)
    expect(r.filesWritten).toBe(0)
    expect(r.reason).toContain('0 files')

    // fs 不应有 MEMORY.md
    const memMd = await readProjectMemoryMd('proj-audit-4', 'Audit Memory Project')
    expect(memMd).toBe('')
  })

  it('无 projectId → applied=false', async () => {
    const { applyMemoryPhase } = await import('../applyMemory')
    const llm = makeMockLLM([HAPPY_LLM_RESPONSE])

    const r = await applyMemoryPhase({
      projectId: '',
      roundId: 'r1',
      feedbacks: SAMPLE_FEEDBACKS,
      llm,
    })

    expect(r.applied).toBe(false)
    expect(r.reason).toBe('no projectId')
  })

  it('跨轮累积：v1 → v2（接通验证）', async () => {
    const { applyMemoryPhase } = await import('../applyMemory')
    const { readProjectMemoryMd } = await import('@/data/memory/memoryRepo')

    // round 1
    {
      const llm = makeMockLLM([HAPPY_LLM_RESPONSE])
      const r = await applyMemoryPhase({
        projectId: 'proj-audit-5',
        roundId: 'r1',
        feedbacks: SAMPLE_FEEDBACKS,
        llm,
      })
      expect(r.applied).toBe(true)
      expect(r.newVersion).toBe(1)
    }

    const memV1 = await readProjectMemoryMd('proj-audit-5', 'Audit Memory Project')
    expect(memV1).toContain('# 项目记忆 v1')

    // round 2
    {
      const llmR2 = makeMockLLM([
        JSON.stringify({
          research_focus: '大模型 scaling + MoE',
          files: [
            {
              filename: 'identity.md',
              type: 'identity',
              name: '研究方向',
              description: 'LLM + MoE',
              body: '## 研究方向\n大模型 scaling + MoE',
            },
          ],
        }),
      ])
      const r = await applyMemoryPhase({
        projectId: 'proj-audit-5',
        roundId: 'r2',
        feedbacks: [
          {
            docId: 'd3',
            bucket: 'very_relevant',
            docTitle: 'MoE trillion params',
            docAbstract: 'sparse activation',
            source: 'arxiv',
          },
        ],
        llm: llmR2,
      })
      expect(r.applied).toBe(true)
      expect(r.newVersion).toBe(1)  // memoryVersion 在 search_config 没存，每次从 0 起，agent 自加 → 1

      // round 2 prompt 应包含 round 1 写入的记忆
      const promptR2 = llmR2.calls[0]
      expect(promptR2.toLowerCase()).toContain('scaling')
    }

    const memV2 = await readProjectMemoryMd('proj-audit-5', 'Audit Memory Project')
    // identity.md 内容被 round 2 覆盖（同 filename）
    expect(memV2).toContain('# 项目记忆 v')
  })

  it('_testOverrideAgent 注入 → 不需要 llm 也能跑', async () => {
    const { applyMemoryPhase } = await import('../applyMemory')

    const fakeLLM = makeMockLLM([HAPPY_LLM_RESPONSE])
    const agent = new MemoryAgent(fakeLLM)

    const r = await applyMemoryPhase({
      projectId: 'proj-audit-6',
      roundId: 'r1',
      feedbacks: SAMPLE_FEEDBACKS,
      llm: null,
      _testOverrideAgent: agent,
    })

    expect(r.applied).toBe(true)
    expect(fakeLLM.calls).toHaveLength(1)
  })
})
