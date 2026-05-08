/**
 * Memory flow 3-round 集成测试（audit 2026-05-08）
 *
 * 模拟 3 轮 round → 4-bucket 反馈 → MemoryAgent.update → applyMemoryUpdate
 * 验证：
 *   1. 3 轮过后 `<AppData>/.../memory/MEMORY.md` 累积版本号正确（v1 → v2 → v3）
 *   2. 详情 .md 跨轮保留（v3 时 v1 写入的 identity.md 仍可见于索引）
 *   3. 第 3 轮 ScoringAgent prompt 里包含 round 1+2 沉淀的记忆 hint
 *
 * 这是审计用的 boundary 测试 —— 不依赖真实 LLM / SQLite / Tauri，
 * 在内存 fs store 里跑完整 memoryRepo 流程。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { MemoryAgent, type FeedbackEntry, type LLMGenerator } from '@/data/agents/memoryAgent'
import { _clearCache as _clearPromptCache } from '@/data/agents/promptLoader'

// ──────────────── 内存 fs store mock（仿 literatureWriter.test.ts 模式）────────────────

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
          // 列 store 中以 `${rel}/` 为前缀的直接子文件（不递归）
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
            if (rest.includes('/')) continue // 子目录里的文件跳过
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

async function getStore(): Promise<Map<string, string>> {
  const m = (await import('@tauri-apps/api/core')) as unknown as { _store: Map<string, string> }
  return m._store
}

// ──────────────── helpers ────────────────

function makeMockLLM(responses: string[]): LLMGenerator & { calls: string[] } {
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

const ROUND1_FEEDBACK: FeedbackEntry[] = [
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
    docTitle: 'Pediatric dental cavities trial',
    docAbstract: 'unrelated medical study',
    source: 'pubmed',
  },
]

const ROUND2_FEEDBACK: FeedbackEntry[] = [
  {
    docId: 'd3',
    bucket: 'very_relevant',
    docTitle: 'Mixture of experts trillion params',
    docAbstract: 'sparse activation',
    source: 'arxiv',
  },
]

const ROUND3_FEEDBACK: FeedbackEntry[] = [
  {
    docId: 'd4',
    bucket: 'relevant',
    docTitle: 'Long-context attention KV cache',
    docAbstract: 'memory-efficient attention',
    source: 'openalex',
  },
]

const LLM_RESPONSE_R1 = JSON.stringify({
  version_summary: 'r1: focus on LLM scaling',
  research_focus: '大模型 scaling laws',
  files: [
    {
      filename: 'identity.md',
      type: 'identity',
      name: '研究方向',
      description: 'LLM scaling laws',
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

const LLM_RESPONSE_R2 = JSON.stringify({
  version_summary: 'r2: add MoE',
  research_focus: '大模型 scaling laws + MoE',
  files: [
    {
      filename: 'identity.md',
      type: 'identity',
      name: '研究方向',
      description: 'LLM scaling + MoE',
      body: '## 研究方向\n大模型 scaling laws 与 mixture of experts',
    },
    {
      filename: 'preferred_topics.md',
      type: 'preference',
      name: '偏好主题',
      description: 'MoE / 稀疏激活',
      body: '- transformer\n- scaling laws\n- mixture of experts',
    },
  ],
})

const LLM_RESPONSE_R3 = JSON.stringify({
  version_summary: 'r3: long context attention',
  research_focus: '大模型 scaling + MoE + long context',
  files: [
    {
      filename: 'identity.md',
      type: 'identity',
      name: '研究方向',
      description: 'LLM scaling + MoE + 长上下文',
      body: '## 研究方向\n大模型 scaling laws / mixture of experts / long context',
    },
    {
      filename: 'methodology.md',
      type: 'preference',
      name: '方法偏好',
      description: 'KV cache / 高效注意力',
      body: '- KV cache\n- 高效注意力',
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

// ──────────────── 测试 ────────────────

describe('memory-flow 3 轮累积（audit）', () => {
  it('3 轮 feedback → MEMORY.md 版本号 1→2→3 累积', async () => {
    const projectId = 'proj-flow-001'
    const projectTitle = 'Memory Flow Audit'

    const { applyMemoryUpdate, readProjectMemoryMd, readMemoryRaw } = await import(
      '../memoryRepo'
    )

    /** 拼项目记忆全文（MEMORY.md + 所有 detail .md raw）— 模拟 LLM 看到的 snapshot */
    async function readFullProjectMemory(): Promise<string> {
      const idx = await readProjectMemoryMd(projectId, projectTitle)
      const parts = [idx]
      for (const fn of ['identity.md', 'preferred_topics.md', 'methodology.md']) {
        const raw = await readMemoryRaw(projectId, fn, projectTitle)
        if (raw) parts.push(raw)
      }
      return parts.join('\n\n')
    }

    // ─── round 1 ───
    {
      const llm = makeMockLLM([LLM_RESPONSE_R1])
      const agent = new MemoryAgent(llm)
      const update = await agent.update({
        currentMemorySnapshot: '',
        memoryVersion: 0,
        feedbacks: ROUND1_FEEDBACK,
      })
      expect(update.version).toBe(1)
      expect(update.files.length).toBeGreaterThan(0)

      const r = await applyMemoryUpdate(projectId, projectTitle, {
        version: update.version,
        index_md: update.indexMd,
        focus: update.focus,
        files: update.files.map((f) => ({
          filename: f.filename,
          type: f.type,
          name: f.name,
          description: f.description,
          body: f.body,
        })),
      })
      expect(r.rolledBack).toBe(false)
      expect(r.failed).toEqual([])
      expect(r.written).toBeGreaterThan(0)

      const memMd = await readProjectMemoryMd(projectId, projectTitle)
      expect(memMd).toContain('# 项目记忆 v1')
      expect(memMd).toContain('identity.md')
      expect(memMd).toContain('preferred_topics.md')
    }

    // ─── round 2 ───
    {
      const prevSnapshot = await readFullProjectMemory()
      const llm = makeMockLLM([LLM_RESPONSE_R2])
      const agent = new MemoryAgent(llm)
      const update = await agent.update({
        currentMemorySnapshot: prevSnapshot,
        memoryVersion: 1,
        feedbacks: ROUND2_FEEDBACK,
      })
      expect(update.version).toBe(2)

      const r = await applyMemoryUpdate(projectId, projectTitle, {
        version: update.version,
        index_md: update.indexMd,
        focus: update.focus,
        files: update.files.map((f) => ({
          filename: f.filename,
          type: f.type,
          name: f.name,
          description: f.description,
          body: f.body,
        })),
      })
      expect(r.rolledBack).toBe(false)

      const memMd = await readProjectMemoryMd(projectId, projectTitle)
      expect(memMd).toContain('# 项目记忆 v2')
    }

    // ─── round 3 ───
    {
      const prevSnapshot = await readFullProjectMemory()
      // round 3 应当能看到 round 1+2 留下的记忆痕迹
      expect(prevSnapshot).toContain('mixture')
      expect(prevSnapshot.toLowerCase()).toContain('moe')

      const llm = makeMockLLM([LLM_RESPONSE_R3])
      const agent = new MemoryAgent(llm)
      const update = await agent.update({
        currentMemorySnapshot: prevSnapshot,
        memoryVersion: 2,
        feedbacks: ROUND3_FEEDBACK,
      })
      expect(update.version).toBe(3)

      // 关键：LLM 收到的 prompt 含 round 1+2 提炼的信号
      expect(llm.calls.length).toBe(1)
      const promptR3 = llm.calls[0]
      expect(promptR3).toContain('mixture')
      expect(promptR3.toLowerCase()).toContain('moe')

      const r = await applyMemoryUpdate(projectId, projectTitle, {
        version: update.version,
        index_md: update.indexMd,
        focus: update.focus,
        files: update.files.map((f) => ({
          filename: f.filename,
          type: f.type,
          name: f.name,
          description: f.description,
          body: f.body,
        })),
      })
      expect(r.rolledBack).toBe(false)

      const memMd = await readProjectMemoryMd(projectId, projectTitle)
      expect(memMd).toContain('# 项目记忆 v3')
      // round 3 update 没提 preferred_topics.md，但 rebuildMemoryIndex 应保留它
      expect(memMd).toContain('preferred_topics.md')
      // 新增的 methodology.md 也要进索引
      expect(memMd).toContain('methodology.md')
    }
  })

  it('round 3 scoring 时 memorySnapshot 真实进入 prompt', async () => {
    // 直接验证 ScoringAgent buildMemorySection 逻辑：memorySnapshot 进入 ## 用户研究偏好记忆 段
    const { ScoringAgent } = await import('@/data/agents/scoringAgent')
    const { LLMQueue } = await import('@/data/llm/concurrent_queue')

    const captured: string[] = []
    const llm: any = {
      async generate(prompt: string) {
        captured.push(prompt)
        return JSON.stringify({ score: 8, rationale: 'ok', one_line: 'sample' })
      },
    }
    // Mock DB so LLMQueue 不调 Tauri Database.load (window undefined in vitest)
    const mockDb: any = {
      async execute() { return { rowsAffected: 0, lastInsertId: 0 } },
      async select() { return [] },
      async close() {},
    }
    const queue = new LLMQueue({ _dbForTesting: mockDb })
    const agent = new ScoringAgent(llm, queue)

    const memSnapshot
      = '## 用户研究方向\n大模型 scaling laws 与 mixture of experts\n## 偏好主题\n- transformer\n- MoE'

    await agent.scoreAll({
      runId: 'run-r3',
      docs: [
        {
          docId: 'doc-r3-1',
          title: 'Long context attention',
          abstract: 'KV cache compression for 1M tokens',
          publicationDate: '2026-04',
          authors: 'A, B',
        } as any,
      ],
      projectDescription: 'LLM scaling research',
      memorySnapshot: memSnapshot,
      cutoff: 6,
    })

    // ScoringAgent 可能为同一 doc 调多次（retry / once-per-side）—— 这里只关心至少一个 prompt 含记忆段
    expect(captured.length).toBeGreaterThanOrEqual(1)
    const merged = captured.join('\n')
    expect(merged).toContain('用户研究偏好记忆')
    expect(merged).toContain('mixture of experts')
    expect(merged).toContain('MoE')
  })
})
