/**
 * Anti-hallucination tests — 移植自 LDR (LearningCircuit/local-deep-research)
 * 反幻觉 + 防 fabricated citation 模式。
 *
 * 覆盖范围：
 *  1. ResearchAgent _extractUrls / _sanitizeAnswerUrls 单元
 *     - 抽 URL（http/https）+ 末尾标点剥离
 *     - libraryDocs 没 url metadata → 宽松保留
 *     - libraryDocs 有 url → 不在白名单的被剥成 `[URL 已移除]`
 *     - DOI URL 归一化（`https://doi.org/<doi>`）
 *
 *  2. ResearchAgent.respond 端到端
 *     - LLM 返回带捏造 URL → answer 中该 URL 被剥掉，actionsTaken.final.result.removedUrls 包含它
 *     - LLM 返回不在 libraryDocs 的 docId → citations 数组将其过滤掉
 *
 *  3. ProbeAgent
 *     - LLM 返回 fulltext 没有的段落 → 当前 schema 验证仅做形态校验（语义难），
 *       但确保 schema 验证通过且不抛；空 quote 走低质量分支（confidence=0.3）
 *     - 不在 fulltext 的凭空 URL：probe schema 不校验 URL（probe 只输出 quote），
 *       所以这块由上层 ResearchAgent 守门
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

import {
  ResearchAgent,
  _extractUrls,
  _sanitizeAnswerUrls,
  type LibraryDoc,
} from '../researchAgent'
import { ProbeAgent, _parseProbeResponse } from '../probeAgent'
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

function makeNoopProbe(): ProbeAgent {
  const probe = new ProbeAgent({ generate: vi.fn(async () => null) } as any)
  probe.probe = vi.fn(async () => ({
    relevantPassages: [],
    summary: '',
    confidence: 0,
  }))
  return probe
}

const LIB_WITH_URLS: LibraryDoc[] = [
  {
    docId: 'doc-aaa',
    title: 'Sparse Attention',
    abstract: 'A novel transformer.',
    score: 0.9,
    url: 'https://arxiv.org/abs/2401.12345',
    doi: '10.1234/sparse-attention',
  },
  {
    docId: 'doc-bbb',
    title: 'MoE at Scale',
    abstract: 'Trillion params via MoE.',
    score: 0.8,
    url: 'https://openalex.org/W123',
  },
]

const LIB_NO_URLS: LibraryDoc[] = [
  { docId: 'doc-aaa', title: 'A', abstract: 'a', score: 0.9 },
  { docId: 'doc-bbb', title: 'B', abstract: 'b', score: 0.8 },
]

// ──────────────────────── 1. _extractUrls ────────────────────────

describe('_extractUrls', () => {
  it('从纯文本抽 http/https URL', () => {
    const out = _extractUrls('参考 https://arxiv.org/abs/2401.12345 和 http://example.com')
    expect(out).toContain('https://arxiv.org/abs/2401.12345')
    expect(out).toContain('http://example.com')
  })

  it('剥末尾标点（中英 . , ; ）', () => {
    const out = _extractUrls('see https://arxiv.org/abs/2401.12345.')
    expect(out).toEqual(['https://arxiv.org/abs/2401.12345'])
  })

  it('markdown link 内的 URL 也能抽出', () => {
    const out = _extractUrls('[link](https://arxiv.org/abs/2401.12345)')
    expect(out).toEqual(['https://arxiv.org/abs/2401.12345'])
  })

  it('无 URL 文本 → 空数组', () => {
    expect(_extractUrls('plain text')).toEqual([])
    expect(_extractUrls('')).toEqual([])
  })
})

// ──────────────────────── 2. _sanitizeAnswerUrls ────────────────────────

describe('_sanitizeAnswerUrls', () => {
  it('libraryDocs 没 url metadata → 宽松保留所有 URL', () => {
    const ans = '参见 https://fake.example.com/paper'
    const { cleaned, removed } = _sanitizeAnswerUrls(ans, LIB_NO_URLS)
    expect(cleaned).toBe(ans)
    expect(removed).toEqual([])
  })

  it('libraryDocs 有 url → 不在白名单的被剥成 `[URL 已移除]`', () => {
    const ans = '参考 https://fake.example.com/paper 和 https://arxiv.org/abs/2401.12345'
    const { cleaned, removed } = _sanitizeAnswerUrls(ans, LIB_WITH_URLS)
    expect(cleaned).toContain('[URL 已移除]')
    expect(cleaned).toContain('https://arxiv.org/abs/2401.12345') // 合法保留
    expect(cleaned).not.toContain('https://fake.example.com/paper')
    expect(removed).toContain('https://fake.example.com/paper')
    expect(removed).not.toContain('https://arxiv.org/abs/2401.12345')
  })

  it('DOI URL（`https://doi.org/<doi>`）匹配 libraryDocs.doi', () => {
    const ans = '参见 https://doi.org/10.1234/sparse-attention'
    const { cleaned, removed } = _sanitizeAnswerUrls(ans, LIB_WITH_URLS)
    expect(removed).toEqual([])
    expect(cleaned).toBe(ans)
  })

  it('多次出现同一捏造 URL → 全部替换 + removed 数组去重', () => {
    const ans = 'A https://fake.com/x B https://fake.com/x C https://fake.com/x'
    const { cleaned, removed } = _sanitizeAnswerUrls(ans, LIB_WITH_URLS)
    expect(cleaned).not.toContain('https://fake.com/x')
    expect(cleaned.match(/\[URL 已移除\]/g)?.length).toBe(3)
    expect(removed).toEqual(['https://fake.com/x']) // 去重
  })

  it('归一化：末尾 `/` 和大小写 host 不影响匹配', () => {
    const lib: LibraryDoc[] = [{
      docId: 'd', title: 't', abstract: 'a', url: 'https://ARXIV.org/abs/2401.12345/',
    }]
    const ans = '见 https://arxiv.org/abs/2401.12345'
    const { removed } = _sanitizeAnswerUrls(ans, lib)
    expect(removed).toEqual([])
  })

  it('空 answer → 直接返回', () => {
    const { cleaned, removed } = _sanitizeAnswerUrls('', LIB_WITH_URLS)
    expect(cleaned).toBe('')
    expect(removed).toEqual([])
  })
})

// ──────────────────────── 3. ResearchAgent: 捏造 URL ────────────────────────

describe('ResearchAgent.respond: 反幻觉 URL', () => {
  it('LLM 返回带捏造 URL → answer 中该 URL 被剥掉 + actionsTaken 记录 removedUrls', async () => {
    const llm = makeLLM([
      JSON.stringify({
        action: 'final',
        answer:
          '## 答案\n本文 [1] 提出稀疏注意力。详见 https://fabricated.example.com/paper.pdf 与 https://arxiv.org/abs/2401.12345。',
        citations: [{ doc_id: 'doc-aaa', evidence: 'sparse attention' }],
        confidence: 0.9,
      }),
    ])
    const probe = makeNoopProbe()
    const agent = new ResearchAgent(llm, probe)

    const out = await agent.respond({
      userQuestion: '本文做了什么？',
      libraryDocs: LIB_WITH_URLS,
    })

    expect(out.answer).not.toContain('fabricated.example.com')
    expect(out.answer).toContain('[URL 已移除]')
    expect(out.answer).toContain('https://arxiv.org/abs/2401.12345') // 合法保留
    expect(out.citations).toHaveLength(1)
    expect(out.citations[0].docId).toBe('doc-aaa')

    // actionsTaken trace 必须含 removedUrls
    const finalAction = out.actionsTaken.find(a => a.action === 'final')
    expect(finalAction).toBeDefined()
    const meta = finalAction!.result as { removedUrls?: string[] }
    expect(meta.removedUrls).toBeDefined()
    expect(meta.removedUrls).toContain('https://fabricated.example.com/paper.pdf')
  })

  it('LLM 返回不在 libraryDocs 的 docId → citation 被过滤', async () => {
    const llm = makeLLM([
      JSON.stringify({
        action: 'final',
        answer: '答案文本足够长以通过校验',
        citations: [
          { doc_id: 'doc-aaa', evidence: 'real' },
          { doc_id: 'doc-FABRICATED', evidence: '完全编造的文献' },
          { doc_id: 'doc-NOT-IN-LIB', evidence: '另一个编造的' },
        ],
        confidence: 0.7,
      }),
    ])
    const probe = makeNoopProbe()
    const agent = new ResearchAgent(llm, probe)

    const out = await agent.respond({
      userQuestion: 'q',
      libraryDocs: LIB_WITH_URLS,
    })

    expect(out.citations).toHaveLength(1)
    expect(out.citations[0].docId).toBe('doc-aaa')
    expect(out.citations.find(c => c.docId === 'doc-FABRICATED')).toBeUndefined()
    expect(out.citations.find(c => c.docId === 'doc-NOT-IN-LIB')).toBeUndefined()
  })

  it('LLM answer 含多个非法 URL + 部分合法 URL → 混合处理正确', async () => {
    const llm = makeLLM([
      JSON.stringify({
        action: 'final',
        answer:
          '参考 [1] https://arxiv.org/abs/2401.12345 和 [2] https://openalex.org/W123，' +
          '另见捏造来源 https://made-up.com/x 和 https://fake.org/y。',
        citations: [
          { doc_id: 'doc-aaa', evidence: 'a' },
          { doc_id: 'doc-bbb', evidence: 'b' },
        ],
        confidence: 0.8,
      }),
    ])
    const probe = makeNoopProbe()
    const agent = new ResearchAgent(llm, probe)

    const out = await agent.respond({
      userQuestion: 'q',
      libraryDocs: LIB_WITH_URLS,
    })

    expect(out.answer).toContain('https://arxiv.org/abs/2401.12345')
    expect(out.answer).toContain('https://openalex.org/W123')
    expect(out.answer).not.toContain('made-up.com')
    expect(out.answer).not.toContain('fake.org')

    const finalAction = out.actionsTaken.find(a => a.action === 'final')
    const meta = finalAction!.result as { removedUrls?: string[] }
    expect(meta.removedUrls?.sort()).toEqual(
      ['https://fake.org/y', 'https://made-up.com/x'].sort(),
    )
  })
})

// ──────────────────────── 4. ProbeAgent: schema 兜底（fulltext 外推检测难，至少不崩） ────────────────────────

describe('ProbeAgent: schema 验证（fulltext 外推由上层守门）', () => {
  it('LLM 返回带凭空 URL 的 quote → schema 验证通过（probe 不校验语义，由 ResearchAgent 守门）', () => {
    const fakeJson = JSON.stringify({
      relevant: true,
      relevance_score: 0.8,
      excerpt_quote: '原文里没有的句子，外加 https://fabricated.com/x',
      insight: '插入的 URL 是凭空的',
      concepts: ['fake'],
    })
    const out = _parseProbeResponse(fakeJson)
    // probe 自己不知道 URL 是不是凭空 → schema 验证只做形态
    expect(out).not.toBeNull()
    expect(out!.relevantPassages).toHaveLength(1)
    expect(out!.confidence).toBeCloseTo(0.8, 2)
    // 说明：probe 这层不能检测「fulltext 外推」，必须靠 ResearchAgent _sanitizeAnswerUrls
    // 这就是为什么 anti-hallucination URL 守门放在 ResearchAgent 出口而非 ProbeAgent
  })

  it('LLM 返回 relevant=true 但 quote 为空 → 走低置信度兜底（不抛）', () => {
    const out = _parseProbeResponse(JSON.stringify({
      relevant: true,
      relevance_score: 0.6,
      excerpt_quote: '',
      insight: '只有 insight 没 quote',
      concepts: [],
    }))
    expect(out).not.toBeNull()
    expect(out!.relevantPassages).toEqual([])
    expect(out!.summary).toContain('只有 insight 没 quote')
    expect(out!.confidence).toBeCloseTo(0.3, 2)
  })

  it('LLM 返回完全无效 JSON → null（caller 走 retry 或 empty fallback）', () => {
    expect(_parseProbeResponse('not json at all')).toBeNull()
    expect(_parseProbeResponse('')).toBeNull()
  })
})
