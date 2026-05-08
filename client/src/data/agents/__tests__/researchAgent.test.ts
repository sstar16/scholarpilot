/**
 * ResearchAgent 单测 — 3 类用例：
 *  1. happy path：probe 一次 → final answer 收敛（≤3 iterations）
 *  2. maxIterations 达到强制返 partial answer
 *  3. LLM 抛错 → graceful fallback（partial answer）
 *
 * Mock 策略：
 * - LLM 用 makeLLM helper 顺序返预设响应（与 queryPlanAgent.test 风格一致）
 * - ProbeAgent 用真实类 + mock 内部 LLM；或者直接 mock probe() 方法（更轻）
 *   这里用直接 mock probe() 方法的方式，避免双层 LLM mock
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

import {
  ResearchAgent,
  parseResearchAction,
  type LibraryDoc,
  type ResearchResult,
} from '../researchAgent'
import { ProbeAgent, type ProbeResult } from '../probeAgent'
import { _clearCache as _clearPromptCache } from '../promptLoader'
import type { LLMManagerLike } from '../types'

beforeEach(() => {
  _clearPromptCache()
  vi.clearAllMocks()
})

// ──────────────────────── helpers ────────────────────────

function makeLLM(
  textsOrFn: Array<string | null> | ((prompt: string, idx: number) => string | null),
): LLMManagerLike & { generate: ReturnType<typeof vi.fn> } {
  let callIdx = 0
  const generate = vi.fn(async (prompt: string) => {
    let text: string | null
    if (typeof textsOrFn === 'function') {
      text = textsOrFn(prompt, callIdx)
    } else {
      text = callIdx < textsOrFn.length ? textsOrFn[callIdx] : null
    }
    callIdx++
    if (text === null) return null
    return {
      text,
      usage: { input_tokens: 100, output_tokens: 200 },
      cost_usd: 0.001,
      latency_ms: 200,
      provider: 'mock',
      model: 'mock-model',
    }
  })
  return { generate } as LLMManagerLike & { generate: ReturnType<typeof vi.fn> }
}

/** Mock ProbeAgent —— 跳过真实 LLM 调用，直接给一个 fake probe 行为。 */
function makeMockProbe(
  probeBehavior: ProbeResult | ((docId: string, q: string) => ProbeResult | Promise<ProbeResult>),
): ProbeAgent {
  // 用一个真实的 ProbeAgent 实例 + 替换 probe 方法
  const probe = new ProbeAgent({ generate: vi.fn(async () => null) } as any)
  probe.probe = vi.fn(async ({ docId, userQuestion }) => {
    if (typeof probeBehavior === 'function') {
      return probeBehavior(docId, userQuestion)
    }
    return probeBehavior
  })
  return probe
}

const SAMPLE_LIBRARY: LibraryDoc[] = [
  {
    docId: 'doc-aaa',
    title: 'Sparse Attention for Long-Context',
    abstract: 'A novel transformer with sliding-window sparse attention.',
    score: 0.92,
    fulltext: 'On LongBench, our model achieves 87.3% accuracy.',
    keyPoints: ['sparse attention', 'LongBench 87.3%'],
  },
  {
    docId: 'doc-bbb',
    title: 'Mixture-of-Experts at Trillion Parameters',
    abstract: 'Sparse activation pattern for trillion-param models.',
    score: 0.85,
    fulltext: 'We scale to 1.6T parameters using MoE.',
  },
  {
    docId: 'doc-ccc',
    title: 'Old paper without fulltext',
    abstract: 'Some old paper.',
    score: 0.5,
  },
]

// ──────────────────────── parseResearchAction ────────────────────────

describe('parseResearchAction', () => {
  it('解析裸 JSON object', () => {
    const out = parseResearchAction('{"action":"final","answer":"hi"}')
    expect(out?.action).toBe('final')
    expect(out?.answer).toBe('hi')
  })

  it('剥 markdown fence', () => {
    const out = parseResearchAction('```json\n{"action":"probe","doc_id":"x"}\n```')
    expect(out?.action).toBe('probe')
  })

  it('多个候选对象 → 取第一个含 action 的', () => {
    const out = parseResearchAction('{"unrelated":1} {"action":"probe","doc_id":"y"}')
    expect(out?.action).toBe('probe')
  })

  it('完全无效 → null', () => {
    expect(parseResearchAction('not json')).toBeNull()
    expect(parseResearchAction('')).toBeNull()
    expect(parseResearchAction(null)).toBeNull()
  })
})

// ──────────────────────── Case 1: happy path ────────────────────────

describe('ResearchAgent.respond: happy path', () => {
  it('iter1=probe iter2=final → 返回 ResearchResult，iterations=2', async () => {
    const llm = makeLLM([
      // iter1: probe doc-aaa
      JSON.stringify({
        action: 'probe',
        doc_id: 'doc-aaa',
        reason: '需要 LongBench 数据',
      }),
      // iter2: final
      JSON.stringify({
        action: 'final',
        answer: '## 答案\n根据 [1] 文献，模型在 LongBench 上达到 87.3% 准确率。\n> "On LongBench, our model achieves 87.3% accuracy."',
        citations: [
          { doc_id: 'doc-aaa', evidence: 'LongBench 87.3% accuracy' },
        ],
        confidence: 0.9,
      }),
    ])

    const probe = makeMockProbe({
      relevantPassages: ['On LongBench, our model achieves 87.3% accuracy.'],
      summary: '本文报告 87.3% 准确率',
      confidence: 0.9,
    })

    const agent = new ResearchAgent(llm, probe)
    const out = await agent.respond({
      userQuestion: '本文 LongBench 上的准确率是多少？',
      libraryDocs: SAMPLE_LIBRARY,
    })

    expect(out.iterations).toBe(2)
    expect(out.answer).toContain('87.3%')
    expect(out.citations).toHaveLength(1)
    expect(out.citations[0].docId).toBe('doc-aaa')
    expect(out.actionsTaken).toHaveLength(2)
    expect(out.actionsTaken[0].action).toBe('probe')
    expect(out.actionsTaken[0].target).toBe('doc-aaa')
    expect(out.actionsTaken[1].action).toBe('final')
    expect(probe.probe).toHaveBeenCalledTimes(1)
    expect(llm.generate).toHaveBeenCalledTimes(2)
  })

  it('单轮 final（无 probe）→ iterations=1', async () => {
    const llm = makeLLM([
      JSON.stringify({
        action: 'final',
        answer: '基于摘要直接回答：本文使用稀疏注意力 [1][2]。',
        citations: [
          { doc_id: 'doc-aaa', evidence: 'sparse attention' },
          { doc_id: 'doc-bbb', evidence: 'MoE' },
        ],
        confidence: 0.7,
      }),
    ])
    const probe = makeMockProbe({ relevantPassages: [], summary: '', confidence: 0 })

    const agent = new ResearchAgent(llm, probe)
    const out = await agent.respond({
      userQuestion: '这两篇都做了什么？',
      libraryDocs: SAMPLE_LIBRARY,
    })

    expect(out.iterations).toBe(1)
    expect(out.citations).toHaveLength(2)
    expect(probe.probe).not.toHaveBeenCalled()
  })

  it('不合法 docId 的 citation 被剔除', async () => {
    const llm = makeLLM([
      JSON.stringify({
        action: 'final',
        answer: 'answer text long enough',
        citations: [
          { doc_id: 'doc-aaa', evidence: 'valid' },
          { doc_id: 'doc-INVALID', evidence: 'fake' },
          { doc_id: 'doc-aaa', evidence: 'duplicate' }, // 重复 doc_id
        ],
        confidence: 0.7,
      }),
    ])
    const probe = makeMockProbe({ relevantPassages: [], summary: '', confidence: 0 })
    const agent = new ResearchAgent(llm, probe)
    const out = await agent.respond({
      userQuestion: 'q',
      libraryDocs: SAMPLE_LIBRARY,
    })
    expect(out.citations).toHaveLength(1)
    expect(out.citations[0].docId).toBe('doc-aaa')
  })

  it('probe 不存在的 docId → 记 error trace，继续', async () => {
    const llm = makeLLM([
      // iter1: probe 不存在的 doc
      JSON.stringify({ action: 'probe', doc_id: 'doc-NONEXISTENT' }),
      // iter2: final
      JSON.stringify({
        action: 'final',
        answer: 'answer text',
        citations: [],
        confidence: 0.5,
      }),
    ])
    const probe = makeMockProbe({ relevantPassages: [], summary: '', confidence: 0 })
    const agent = new ResearchAgent(llm, probe)
    const out = await agent.respond({
      userQuestion: 'q',
      libraryDocs: SAMPLE_LIBRARY,
    })
    expect(out.iterations).toBe(2)
    expect(out.actionsTaken[0].action).toBe('probe')
    expect((out.actionsTaken[0].result as any).error).toContain('not in library')
    expect(probe.probe).not.toHaveBeenCalled()
  })

  it('probe 无 fulltext 的 doc → 记 error，不调 ProbeAgent', async () => {
    const llm = makeLLM([
      JSON.stringify({ action: 'probe', doc_id: 'doc-ccc' }),
      JSON.stringify({
        action: 'final',
        answer: 'answer text',
        citations: [],
      }),
    ])
    const probe = makeMockProbe({ relevantPassages: [], summary: '', confidence: 0 })
    const agent = new ResearchAgent(llm, probe)
    const out = await agent.respond({
      userQuestion: 'q',
      libraryDocs: SAMPLE_LIBRARY,
    })
    expect((out.actionsTaken[0].result as any).error).toContain('no fulltext')
    expect(probe.probe).not.toHaveBeenCalled()
  })
})

// ──────────────────────── Case 2: maxIterations 达到 ────────────────────────

describe('ResearchAgent.respond: maxIterations 达到 → partial answer', () => {
  it('LLM 一直 probe 不 finalize → maxIterations 后强制返 partial answer', async () => {
    // 5 次都是 probe，没 final
    const llm = makeLLM(() =>
      JSON.stringify({ action: 'probe', doc_id: 'doc-aaa' }),
    )
    const probe = makeMockProbe({
      relevantPassages: ['evidence chunk'],
      summary: 'partial info',
      confidence: 0.7,
    })

    const agent = new ResearchAgent(llm, probe)
    const out = await agent.respond({
      userQuestion: 'q',
      libraryDocs: SAMPLE_LIBRARY,
      maxIterations: 3,
    })

    expect(out.iterations).toBe(3)
    expect(out.answer).toContain('部分答案')
    expect(out.answer).toContain('已达 maxIterations=3')
    // partial 答案应该把 probe 命中的 evidence 拼进去
    expect(out.answer).toContain('partial info')
    expect(out.answer).toContain('evidence chunk')
    expect(out.citations.length).toBeGreaterThan(0)
    expect(out.citations[0].docId).toBe('doc-aaa')
  })

  it('LLM 全返 garbage（parse 失败） → 耗尽 iterations → partial fallback', async () => {
    const llm = makeLLM(() => 'totally not json at all')
    const probe = makeMockProbe({ relevantPassages: [], summary: '', confidence: 0 })
    const agent = new ResearchAgent(llm, probe)
    const out = await agent.respond({
      userQuestion: 'q',
      libraryDocs: SAMPLE_LIBRARY,
      maxIterations: 2,
    })

    expect(out.iterations).toBe(2)
    expect(out.answer).toContain('部分答案')
    // 没有 probe 命中 → 提示用户重新提问
    expect(out.answer).toContain('未能从已选文献')
    expect(out.actionsTaken.every(a => a.action === '_parse_failed')).toBe(true)
  })

  it('search action 在 B11 还未实现 → 记 error trace，继续 loop', async () => {
    const llm = makeLLM([
      JSON.stringify({ action: 'search', query: 'sparse attention 2025' }),
      JSON.stringify({
        action: 'final',
        answer: 'after a search trace, here is answer',
        citations: [],
      }),
    ])
    const probe = makeMockProbe({ relevantPassages: [], summary: '', confidence: 0 })
    const agent = new ResearchAgent(llm, probe)
    const out = await agent.respond({
      userQuestion: 'q',
      libraryDocs: SAMPLE_LIBRARY,
    })
    expect(out.iterations).toBe(2)
    expect(out.actionsTaken[0].action).toBe('search')
    expect((out.actionsTaken[0].result as any).error).toMatch(/not implemented/)
  })
})

// ──────────────────────── Case 3: LLM 抛错 → graceful ────────────────────────

describe('ResearchAgent.respond: LLM 抛错 → graceful partial fallback', () => {
  it('第一轮 LLM 直接 throw → graceful 返 partial answer', async () => {
    const llm: LLMManagerLike = {
      generate: vi.fn(async () => {
        throw new Error('network down')
      }),
    }
    const probe = makeMockProbe({ relevantPassages: [], summary: '', confidence: 0 })
    const agent = new ResearchAgent(llm, probe)
    const out = await agent.respond({
      userQuestion: 'q',
      libraryDocs: SAMPLE_LIBRARY,
    })

    expect(out.answer).toContain('部分答案')
    expect(out.answer).toContain('LLM 调用失败')
    expect(out.answer).toContain('network down')
    expect(out.iterations).toBe(1)
    expect(out.citations).toEqual([])
  })

  it('第二轮 LLM throw（已 probe 一次） → partial 包含 probe 的 evidence', async () => {
    let callIdx = 0
    const llm: LLMManagerLike = {
      generate: vi.fn(async () => {
        callIdx++
        if (callIdx === 1) {
          return {
            text: JSON.stringify({ action: 'probe', doc_id: 'doc-aaa' }),
            usage: { input_tokens: 1, output_tokens: 1 },
            cost_usd: 0,
            latency_ms: 1,
            provider: 'mock',
            model: 'm',
          }
        }
        throw new Error('connection lost on round 2')
      }),
    }
    const probe = makeMockProbe({
      relevantPassages: ['recovered evidence'],
      summary: 'partial info from probe',
      confidence: 0.8,
    })
    const agent = new ResearchAgent(llm, probe)
    const out = await agent.respond({
      userQuestion: 'q',
      libraryDocs: SAMPLE_LIBRARY,
    })

    expect(out.iterations).toBe(2)
    expect(out.answer).toContain('LLM 调用失败')
    expect(out.answer).toContain('connection lost')
    expect(out.answer).toContain('partial info from probe')
    expect(out.answer).toContain('recovered evidence')
    expect(out.citations).toHaveLength(1)
    expect(out.citations[0].docId).toBe('doc-aaa')
  })

  it('LLM 返 null（empty） → graceful partial', async () => {
    const llm = makeLLM(() => null)
    const probe = makeMockProbe({ relevantPassages: [], summary: '', confidence: 0 })
    const agent = new ResearchAgent(llm, probe)
    const out = await agent.respond({
      userQuestion: 'q',
      libraryDocs: SAMPLE_LIBRARY,
    })

    expect(out.answer).toContain('部分答案')
    expect(out.answer).toContain('返回空响应')
  })

  it('userQuestion 为空 → 立即返 empty result，不调 LLM', async () => {
    const llm = makeLLM([])
    const probe = makeMockProbe({ relevantPassages: [], summary: '', confidence: 0 })
    const agent = new ResearchAgent(llm, probe)
    const out = await agent.respond({
      userQuestion: '   ',
      libraryDocs: SAMPLE_LIBRARY,
    })

    expect(out.iterations).toBe(0)
    expect(llm.generate).not.toHaveBeenCalled()
  })

  it('final answer 长度 < 5 → 视为不可用，partial fallback', async () => {
    const llm = makeLLM([
      JSON.stringify({ action: 'final', answer: 'hi', citations: [] }),
    ])
    const probe = makeMockProbe({ relevantPassages: [], summary: '', confidence: 0 })
    const agent = new ResearchAgent(llm, probe)
    const out = await agent.respond({
      userQuestion: 'q',
      libraryDocs: SAMPLE_LIBRARY,
    })
    expect(out.answer).toContain('部分答案')
    expect(out.answer).toContain('answer 为空')
  })
})
