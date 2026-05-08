/**
 * MemoryAgent 单测
 *
 * 用 mock LLM 覆盖：
 *   1. 5 条 feedbacks → MemoryUpdate 结构正确（newEntries / files / version 等）
 *   2. JSON malformed → graceful 返 empty update（不抛）
 *   3. v3 fallback：LLM 输出顶层字段（无 files）→ 走 _filesFromParsedV3
 *   4. 空 feedbacks → 立即 empty
 *   5. LLM throw → graceful empty
 */
import { describe, it, expect, beforeEach } from 'vitest'

import { MemoryAgent, type FeedbackEntry, type LLMGenerator } from '../memoryAgent'
import { _clearCache as _clearPromptCache } from '../promptLoader'

beforeEach(() => {
  _clearPromptCache()
})

/** 简易 mock LLM：按预设响应顺序返回 string；超出 → null */
function makeMockLLM(responses: Array<string | null>): LLMGenerator & { calls: string[] } {
  const calls: string[] = []
  let i = 0
  return {
    calls,
    async generate(prompt) {
      calls.push(prompt)
      if (i >= responses.length) return null
      const r = responses[i++]
      return r
    },
  }
}

/** Throw mock：generate 抛 Error */
function makeThrowingLLM(): LLMGenerator {
  return {
    async generate() {
      throw new Error('mock LLM network error')
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
    bucket: 'very_relevant',
    docTitle: 'Mixture of experts at trillion parameters',
    docAbstract: 'Sparse activation pattern',
    source: 'arxiv',
  },
  {
    docId: 'd3',
    bucket: 'relevant',
    docTitle: 'Long-context attention',
    docAbstract: 'Memory-efficient KV cache',
    source: 'openalex',
  },
  {
    docId: 'd4',
    bucket: 'irrelevant',
    docTitle: 'Clinical trials phase 3 enrollment',
    docAbstract: 'medical study irrelevant to LLM topic',
    source: 'pubmed',
  },
  {
    docId: 'd5',
    bucket: 'uncertain',
    docTitle: 'GPU kernel autotuning',
    docAbstract: '',
    source: 'arxiv',
  },
]

describe('MemoryAgent.update — happy path (v4 files)', () => {
  it('5 条 feedbacks → 解析 LLM v4 输出 → 完整 MemoryUpdate', async () => {
    const llmJSON = JSON.stringify({
      version_summary: 'focus shifts toward LLM scaling',
      research_focus: '大模型 scaling laws 与稀疏激活',
      files: [
        {
          filename: 'core_research_direction.md',
          type: 'identity',
          name: '核心研究方向',
          description: 'Transformer 与 MoE',
          body: '## 核心\n大模型 scaling laws',
        },
        {
          filename: 'preferred_topics.md',
          type: 'preference',
          name: '偏好主题',
          description: '感兴趣主题',
          body: '- scaling laws\n- mixture of experts',
        },
        {
          filename: 'excluded_clinical.md',
          type: 'preference',
          name: '排除主题',
          description: '不相关方向',
          body: '- clinical trials',
        },
      ],
    })

    const mock = makeMockLLM([llmJSON])
    const agent = new MemoryAgent(mock)
    const out = await agent.update({
      currentMemorySnapshot: '',
      memoryVersion: 0,
      feedbacks: SAMPLE_FEEDBACKS,
      projectDescription: 'LLM scaling research',
    })

    expect(mock.calls.length).toBe(1)
    // prompt 应包含分桶后的反馈条目
    expect(mock.calls[0]).toContain('Transformer scaling laws')
    expect(mock.calls[0]).toContain('Clinical trials')
    expect(mock.calls[0]).toContain('LLM scaling research')

    expect(out.version).toBe(1)
    expect(out.focus).toBe('大模型 scaling laws 与稀疏激活')
    expect(out.files).toHaveLength(3)
    expect(out.files[0].filename).toBe('core_research_direction.md')
    expect(out.files[0].type).toBe('identity')
    expect(out.markdown).toContain('# 研究偏好记忆 v1')
    expect(out.indexMd).toContain('# 项目记忆 v1')
    expect(out.indexMd).toContain('_当前研究方向：大模型 scaling laws 与稀疏激活_')
    expect(out.newEntries).toHaveLength(3)
    expect(out.newEntries[0].weight).toBe(1.0)  // identity
    expect(out.newEntries[1].weight).toBe(0.8)  // preference
    expect(out.reasoning).toBe('focus shifts toward LLM scaling')
  })

  it('过滤非法 filename（不含 .md / 含路径 / 含大写）', async () => {
    const llmJSON = JSON.stringify({
      research_focus: '研究方向',
      files: [
        { filename: '../etc/passwd', type: 'note', name: 'x', description: '', body: 'x' },
        { filename: 'BadCase.md', type: 'note', name: 'y', description: '', body: 'y' },
        { filename: 'ok_file.md', type: 'note', name: 'ok', description: 'good', body: 'ok body' },
        { filename: 'no_body.md', type: 'note', name: 'z', description: '', body: '' },
      ],
    })
    const mock = makeMockLLM([llmJSON])
    const agent = new MemoryAgent(mock)
    const out = await agent.update({
      currentMemorySnapshot: '',
      feedbacks: SAMPLE_FEEDBACKS,
    })
    expect(out.files).toHaveLength(1)
    expect(out.files[0].filename).toBe('ok_file.md')
  })
})

describe('MemoryAgent.update — v3 fallback (无 files)', () => {
  it('LLM 输出顶层 preferred_topics / excluded_topics → 拍成 7 类映射', async () => {
    const llmJSON = JSON.stringify({
      research_focus: '量子计算与神经网络融合',
      preferred_topics: ['quantum ML', 'variational circuits'],
      excluded_topics: ['classical optimization'],
      methodology_preferences: ['gradient-based variational'],
      key_authors: ['Maria Schuld'],
      source_preferences: ['arxiv'],
      notes: '关注 NISQ 设备的近期可行性',
    })
    const mock = makeMockLLM([llmJSON])
    const agent = new MemoryAgent(mock)
    const out = await agent.update({
      currentMemorySnapshot: '',
      memoryVersion: 3,
      feedbacks: SAMPLE_FEEDBACKS,
    })
    expect(out.version).toBe(4)
    expect(out.focus).toBe('量子计算与神经网络融合')
    // 7 类全填 → 7 个文件
    const filenames = out.files.map((f) => f.filename)
    expect(filenames).toContain('research_focus.md')
    expect(filenames).toContain('preferred_topics.md')
    expect(filenames).toContain('excluded_topics.md')
    expect(filenames).toContain('methodology.md')
    expect(filenames).toContain('authors.md')
    expect(filenames).toContain('sources.md')
    expect(filenames).toContain('notes.md')
  })
})

describe('MemoryAgent.update — graceful failures', () => {
  it('JSON malformed → empty update (不 throw)', async () => {
    const mock = makeMockLLM(['not a json at all { random garbage'])
    const agent = new MemoryAgent(mock)
    const out = await agent.update({
      currentMemorySnapshot: 'old',
      memoryVersion: 5,
      feedbacks: SAMPLE_FEEDBACKS,
    })
    expect(out.files).toHaveLength(0)
    expect(out.version).toBe(5)  // empty update 保持原 version
    expect(out.reasoning).toContain('skipped')
  })

  it('JSON 缺 research_focus → empty', async () => {
    const mock = makeMockLLM([JSON.stringify({ files: [] })])
    const agent = new MemoryAgent(mock)
    const out = await agent.update({
      currentMemorySnapshot: '',
      feedbacks: SAMPLE_FEEDBACKS,
    })
    expect(out.files).toHaveLength(0)
    expect(out.reasoning).toContain('skipped')
  })

  it('JSON 含尾部垃圾 → 缩短匹配成功', async () => {
    // 故意在合法 JSON 后追加文本，模拟 LLM 偷懒
    const tail = JSON.stringify({
      research_focus: '稀疏激活',
      files: [
        { filename: 'a.md', type: 'identity', name: 'a', description: 'a', body: '## a' },
      ],
    }) + '\n\nHere are extra explanations...'
    const mock = makeMockLLM([tail])
    const agent = new MemoryAgent(mock)
    const out = await agent.update({
      currentMemorySnapshot: '',
      feedbacks: SAMPLE_FEEDBACKS,
    })
    expect(out.focus).toBe('稀疏激活')
    expect(out.files).toHaveLength(1)
  })

  it('LLM 返 null → empty', async () => {
    const mock = makeMockLLM([null])
    const agent = new MemoryAgent(mock)
    const out = await agent.update({
      currentMemorySnapshot: '',
      feedbacks: SAMPLE_FEEDBACKS,
    })
    expect(out.files).toHaveLength(0)
  })

  it('LLM throw → empty (不冒泡)', async () => {
    const agent = new MemoryAgent(makeThrowingLLM())
    const out = await agent.update({
      currentMemorySnapshot: '',
      feedbacks: SAMPLE_FEEDBACKS,
    })
    expect(out.files).toHaveLength(0)
    expect(out.reasoning).toContain('skipped')
  })

  it('feedbacks 为空 → 立即 empty（不 call LLM）', async () => {
    const mock = makeMockLLM(['should_not_be_called'])
    const agent = new MemoryAgent(mock)
    const out = await agent.update({
      currentMemorySnapshot: '',
      memoryVersion: 7,
      feedbacks: [],
    })
    expect(mock.calls).toHaveLength(0)
    expect(out.version).toBe(7)
  })
})

describe('MemoryAgent.update — LLMResult shape support', () => {
  it('llm.generate 返 LLMResult 对象（{ text, ... }）也能解析', async () => {
    const llm: LLMGenerator = {
      async generate() {
        return {
          text: JSON.stringify({
            research_focus: 'focus',
            files: [
              { filename: 'a.md', type: 'identity', name: 'A', description: 'd', body: '## a' },
            ],
          }),
          usage: { input_tokens: 10, output_tokens: 20 },
          cost_usd: 0,
          latency_ms: 100,
          provider: 'mock',
          model: 'mock',
        }
      },
    }
    const agent = new MemoryAgent(llm)
    const out = await agent.update({
      currentMemorySnapshot: '',
      feedbacks: SAMPLE_FEEDBACKS,
    })
    expect(out.focus).toBe('focus')
    expect(out.files).toHaveLength(1)
  })
})
