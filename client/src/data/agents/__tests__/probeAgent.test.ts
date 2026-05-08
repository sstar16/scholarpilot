/**
 * ProbeAgent 单测 — 4 类用例：
 *  1. happy path：mock LLM 返合规 JSON → 返 ProbeResult
 *  2. malformed → retry → 仍失败 → empty fallback
 *  3. cacheGet hit → 不调 LLM
 *  4. cacheGet miss → 调 LLM → cacheSet 被调用
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { ProbeAgent, _parseProbeResponse, type ProbeResult } from '../probeAgent'
import { _clearCache as _clearPromptCache } from '../promptLoader'
import type { LLMManagerLike } from '../types'

beforeEach(() => {
  _clearPromptCache()
  vi.clearAllMocks()
})

// ──────────────────────── helpers ────────────────────────

/** Mock LLM：按预设响应顺序返回 LLMResult-like 或 string；超出 → null */
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
      usage: { input_tokens: 10, output_tokens: 20 },
      cost_usd: 0.0001,
      latency_ms: 100,
      provider: 'mock',
      model: 'mock-model',
    }
  })
  return { generate } as LLMManagerLike & { generate: ReturnType<typeof vi.fn> }
}

const SAMPLE_FULLTEXT = `
# Introduction
This paper proposes a novel transformer variant for long-context understanding.

# Methods
We use sparse attention with sliding-window kernel.

# Results
On the LongBench benchmark, our model achieves 87.3% accuracy, a 12.3 point improvement.

# Conclusion
Sparse attention is effective for long-context tasks.
`.trim()

// ──────────────────────── parseProbeResponse helper tests ────────────────────────

describe('_parseProbeResponse', () => {
  it('解析 schema A：相关 + quote', () => {
    const out = _parseProbeResponse(JSON.stringify({
      relevant: true,
      relevance_score: 0.85,
      excerpt_quote: '原文逐字',
      insight: '一句话概括',
      concepts: ['c1'],
    }))
    expect(out).not.toBeNull()
    expect(out!.relevantPassages).toEqual(['原文逐字'])
    expect(out!.summary).toBe('一句话概括')
    expect(out!.confidence).toBeCloseTo(0.85, 2)
  })

  it('解析 schema A：relevant=false → 空 result', () => {
    const out = _parseProbeResponse('{"relevant": false, "relevance_score": 0.1, "excerpt_quote": "", "insight": "", "concepts": []}')
    expect(out).not.toBeNull()
    expect(out!.relevantPassages).toEqual([])
    expect(out!.confidence).toBe(0.0)
  })

  it('解析 schema B：多 passages', () => {
    const out = _parseProbeResponse(JSON.stringify({
      relevant_passages: ['quote1', 'quote2'],
      summary: 'sum',
      confidence: 0.7,
    }))
    expect(out).not.toBeNull()
    expect(out!.relevantPassages).toEqual(['quote1', 'quote2'])
    expect(out!.summary).toBe('sum')
    expect(out!.confidence).toBeCloseTo(0.7, 2)
  })

  it('剥 markdown fence', () => {
    const out = _parseProbeResponse('```json\n{"relevant":true,"relevance_score":0.6,"excerpt_quote":"q","insight":"i","concepts":[]}\n```')
    expect(out).not.toBeNull()
    expect(out!.relevantPassages).toEqual(['q'])
  })

  it('完全无效 → null', () => {
    expect(_parseProbeResponse('not json')).toBeNull()
    expect(_parseProbeResponse('')).toBeNull()
    expect(_parseProbeResponse(null)).toBeNull()
  })
})

// ──────────────────────── Case 1: happy path ────────────────────────

describe('ProbeAgent.probe: happy path', () => {
  it('mock LLM 返合规 schema A JSON → 返 ProbeResult', async () => {
    const llm = makeLLM([
      JSON.stringify({
        relevant: true,
        relevance_score: 0.92,
        excerpt_quote: 'On the LongBench benchmark, our model achieves 87.3% accuracy, a 12.3 point improvement.',
        insight: '本文报告了 87.3% 的准确率提升 12.3 个点',
        concepts: ['LongBench', 'sparse attention'],
      }),
    ])
    const agent = new ProbeAgent(llm)
    const out = await agent.probe({
      docId: 'doc-1',
      docTitle: 'Sparse Attention for Long-Context',
      docFulltext: SAMPLE_FULLTEXT,
      userQuestion: '本文 LongBench 上的准确率是多少？',
    })

    expect(out.relevantPassages.length).toBe(1)
    expect(out.relevantPassages[0]).toContain('87.3% accuracy')
    expect(out.summary).toContain('87.3%')
    expect(out.confidence).toBeCloseTo(0.92, 2)
    expect(llm.generate).toHaveBeenCalledTimes(1)
  })

  it('schema B 多 passages → 全部保留', async () => {
    const llm = makeLLM([
      JSON.stringify({
        relevant_passages: ['p1', 'p2', 'p3'],
        summary: 'multi-quote summary',
        confidence: 0.8,
      }),
    ])
    const agent = new ProbeAgent(llm)
    const out = await agent.probe({
      docId: 'doc-2',
      docTitle: 't',
      docFulltext: SAMPLE_FULLTEXT,
      userQuestion: 'q',
    })
    expect(out.relevantPassages).toEqual(['p1', 'p2', 'p3'])
    expect(out.confidence).toBeCloseTo(0.8, 2)
  })

  it('输入缺 fulltext / question → 立即返 empty，不调 LLM', async () => {
    const llm = makeLLM([])
    const agent = new ProbeAgent(llm)

    const empty1 = await agent.probe({
      docId: 'doc-1',
      docTitle: 't',
      docFulltext: '',
      userQuestion: 'q',
    })
    expect(empty1.confidence).toBe(0)
    expect(empty1.relevantPassages).toEqual([])

    const empty2 = await agent.probe({
      docId: 'doc-1',
      docTitle: 't',
      docFulltext: SAMPLE_FULLTEXT,
      userQuestion: '   ',
    })
    expect(empty2.confidence).toBe(0)
    expect(llm.generate).not.toHaveBeenCalled()
  })
})

// ──────────────────────── Case 2: malformed → retry → fallback ────────────────────────

describe('ProbeAgent.probe: malformed JSON → retry → fallback empty', () => {
  it('两次都返 garbage → empty fallback（confidence=0）', async () => {
    const llm = makeLLM([
      'this is not json at all',
      'still not json, just rambling',
    ])
    const agent = new ProbeAgent(llm)
    const out = await agent.probe({
      docId: 'doc-1',
      docTitle: 't',
      docFulltext: SAMPLE_FULLTEXT,
      userQuestion: 'q',
    })
    expect(out.confidence).toBe(0)
    expect(out.relevantPassages).toEqual([])
    expect(out.summary).toBe('')
    // 1+1 retry
    expect(llm.generate).toHaveBeenCalledTimes(2)
  })

  it('LLM 抛错两次 → empty fallback', async () => {
    const llm: LLMManagerLike = {
      generate: vi.fn(async () => {
        throw new Error('network down')
      }),
    }
    const agent = new ProbeAgent(llm)
    const out = await agent.probe({
      docId: 'doc-1',
      docTitle: 't',
      docFulltext: SAMPLE_FULLTEXT,
      userQuestion: 'q',
    })
    expect(out.confidence).toBe(0)
    expect((llm.generate as ReturnType<typeof vi.fn>)).toHaveBeenCalledTimes(2)
  })

  it('第 1 次 garbage 第 2 次成功 → 仍能返 ProbeResult', async () => {
    const llm = makeLLM([
      'garbage',
      JSON.stringify({
        relevant: true,
        relevance_score: 0.7,
        excerpt_quote: 'recovered quote',
        insight: 'recovered insight',
        concepts: [],
      }),
    ])
    const agent = new ProbeAgent(llm)
    const out = await agent.probe({
      docId: 'doc-1',
      docTitle: 't',
      docFulltext: SAMPLE_FULLTEXT,
      userQuestion: 'q',
    })
    expect(out.relevantPassages).toEqual(['recovered quote'])
    expect(out.confidence).toBeCloseTo(0.7, 2)
  })
})

// ──────────────────────── Case 3: cacheGet hit ────────────────────────

describe('ProbeAgent.probe: cacheGet hit → 不调 LLM', () => {
  it('cacheGet 返非 null → 直接返该值，generate 不被调用', async () => {
    const cached: ProbeResult = {
      relevantPassages: ['cached passage'],
      summary: 'cached',
      confidence: 0.95,
    }
    const cacheGet = vi.fn(async () => cached)
    const cacheSet = vi.fn(async () => {})
    const llm = makeLLM([])

    const agent = new ProbeAgent(llm)
    const out = await agent.probe({
      docId: 'doc-1',
      docTitle: 't',
      docFulltext: SAMPLE_FULLTEXT,
      userQuestion: 'q',
      cacheGet,
      cacheSet,
    })

    expect(out).toEqual(cached)
    expect(cacheGet).toHaveBeenCalledTimes(1)
    expect(llm.generate).not.toHaveBeenCalled()
    expect(cacheSet).not.toHaveBeenCalled()
  })

  it('cacheGet 抛异常 → 退化到 LLM（不阻塞主流程）', async () => {
    const llm = makeLLM([
      JSON.stringify({
        relevant: true,
        relevance_score: 0.8,
        excerpt_quote: 'fresh quote',
        insight: 'i',
        concepts: [],
      }),
    ])
    const cacheGet = vi.fn(async () => {
      throw new Error('cache disk full')
    })
    const agent = new ProbeAgent(llm)
    const out = await agent.probe({
      docId: 'doc-1',
      docTitle: 't',
      docFulltext: SAMPLE_FULLTEXT,
      userQuestion: 'q',
      cacheGet,
    })
    expect(out.relevantPassages).toEqual(['fresh quote'])
    expect(llm.generate).toHaveBeenCalledTimes(1)
  })
})

// ──────────────────────── Case 4: cacheGet miss → cacheSet 调用 ────────────────────────

describe('ProbeAgent.probe: cacheGet miss → 调 LLM → cacheSet 被调用', () => {
  it('cacheGet 返 null → LLM 出新结果 → cacheSet 写入', async () => {
    const llm = makeLLM([
      JSON.stringify({
        relevant: true,
        relevance_score: 0.88,
        excerpt_quote: 'new quote',
        insight: 'new insight',
        concepts: ['c1'],
      }),
    ])
    const cacheGet = vi.fn(async () => null)
    const cacheSet = vi.fn(async () => {})

    const agent = new ProbeAgent(llm)
    const out = await agent.probe({
      docId: 'doc-1',
      docTitle: 't',
      docFulltext: SAMPLE_FULLTEXT,
      userQuestion: 'q',
      cacheGet,
      cacheSet,
    })

    expect(out.relevantPassages).toEqual(['new quote'])
    expect(cacheGet).toHaveBeenCalledTimes(1)
    expect(llm.generate).toHaveBeenCalledTimes(1)
    expect(cacheSet).toHaveBeenCalledTimes(1)
    // cacheSet 收到的 value 应该等于返回值
    const [, cachedVal] = (cacheSet as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(cachedVal).toEqual(out)
  })

  it('LLM 全失败 → empty fallback → cacheSet 不被调用（不污染缓存）', async () => {
    const llm = makeLLM(['garbage', 'still garbage'])
    const cacheGet = vi.fn(async () => null)
    const cacheSet = vi.fn(async () => {})

    const agent = new ProbeAgent(llm)
    const out = await agent.probe({
      docId: 'doc-1',
      docTitle: 't',
      docFulltext: SAMPLE_FULLTEXT,
      userQuestion: 'q',
      cacheGet,
      cacheSet,
    })

    expect(out.confidence).toBe(0)
    expect(cacheSet).not.toHaveBeenCalled()
  })

  it('同一 docId+question 调 2 次 → 用同一 cache key（基于 hash）', async () => {
    let savedKey: string | null = null
    const cacheGet = vi.fn(async (k: string) => {
      if (savedKey === k) {
        return { relevantPassages: ['from cache'], summary: 's', confidence: 0.9 }
      }
      return null
    })
    const cacheSet = vi.fn(async (k: string) => {
      savedKey = k
    })
    const llm = makeLLM([
      JSON.stringify({
        relevant: true,
        relevance_score: 0.8,
        excerpt_quote: 'first call',
        insight: 'i',
        concepts: [],
      }),
    ])

    const agent = new ProbeAgent(llm)
    // 第一次：miss → LLM → set
    const out1 = await agent.probe({
      docId: 'doc-1',
      docTitle: 't',
      docFulltext: SAMPLE_FULLTEXT,
      userQuestion: 'same question',
      cacheGet,
      cacheSet,
    })
    expect(out1.relevantPassages).toEqual(['first call'])
    expect(savedKey).not.toBeNull()

    // 第二次：hit → 不调 LLM
    const out2 = await agent.probe({
      docId: 'doc-1',
      docTitle: 't',
      docFulltext: SAMPLE_FULLTEXT,
      userQuestion: 'same question',
      cacheGet,
      cacheSet,
    })
    expect(out2.relevantPassages).toEqual(['from cache'])
    expect(llm.generate).toHaveBeenCalledTimes(1)
  })
})
