/**
 * QueryPlanAgent 单测 — 5 个用例覆盖任务规范要求：
 *  1. agenticPlan happy path（≤2 iterations 收敛）
 *  2. agenticPlan LLM JSON malformed → 同 loop 内重试成功
 *  3. agenticPlan max iterations 达到 → fallback legacy
 *  4. legacyPlan happy path
 *  5. 所有 LLM 调用失败 → throw QueryPlanError
 *
 * Mock 策略：
 * - LLM 用 vi.fn() mockImplementation 伪造 generate 返回 LLMResult
 * - fetcherApi.searchPreview 也用 vi.fn() 直接注入到 agent 构造
 *   （不需要 vi.mock 整模块，因为 agent 通过 ctor 注入 fetcherApi）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

import {
  QueryPlanAgent,
  QueryPlanError,
  parseActionJson,
  parseLegacyPlanJson,
  type FetcherApiLike,
  type LLMLike,
} from '../queryPlanAgent'

// ──────────────────────── Helpers ────────────────────────

function makeLLM(textsOrFn: string[] | ((prompt: string, idx: number) => string | null)): LLMLike {
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
  return { generate } as LLMLike & { generate: ReturnType<typeof vi.fn> }
}

function makeFetcher(
  responsesByIdx: Array<{ count: number; topTitles: string[] } | { error: string }>,
): FetcherApiLike & { searchPreview: ReturnType<typeof vi.fn> } {
  let idx = 0
  return {
    searchPreview: vi.fn(async () => {
      const r = responsesByIdx[idx] ?? { count: 0, topTitles: [] }
      idx++
      return r
    }),
  }
}

function finalizeJson(plan: Record<string, unknown>): string {
  return JSON.stringify({ action: 'finalize', plan })
}

function previewJson(query: string, source = 'local_kb'): string {
  return JSON.stringify({ action: 'search_preview', query, source })
}

// ──────────────────────── Reset ────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
})

// ──────────────────────── Helpers Tests ────────────────────────

describe('parseActionJson', () => {
  it('解析裸 JSON object（含 action 字段）', () => {
    const out = parseActionJson('{"action":"finalize","plan":{"base_query":"foo"}}')
    expect(out?.action).toBe('finalize')
  })

  it('剥 ```json fence', () => {
    const out = parseActionJson('```json\n{"action":"search_preview","query":"q"}\n```')
    expect(out?.action).toBe('search_preview')
  })

  it('从前后解释里挑出 JSON', () => {
    const out = parseActionJson(
      'Sure, here is my action:\n{"action":"finalize","plan":{"base_query":"x"}}\nDone.',
    )
    expect(out?.action).toBe('finalize')
  })

  it('多个候选对象 → 取第一个含 action 的', () => {
    const out = parseActionJson(
      '{"unrelated":1} {"action":"search_preview","query":"y"} {"action":"finalize"}',
    )
    expect(out?.action).toBe('search_preview')
  })

  it('完全无效 → null', () => {
    expect(parseActionJson('not a json at all')).toBeNull()
    expect(parseActionJson('')).toBeNull()
    expect(parseActionJson(null)).toBeNull()
  })
})

describe('parseLegacyPlanJson', () => {
  it('合法 plan → 解析出 base_query', () => {
    const out = parseLegacyPlanJson(
      '{"base_query":"machine learning","year_to":2026,"sources":["openalex"]}',
    )
    expect(out?.base_query).toBe('machine learning')
  })

  it('base_query 太短 → null', () => {
    expect(
      parseLegacyPlanJson('{"base_query":"x"}'),
    ).toBeNull()
  })

  it('无 base_query → null', () => {
    expect(parseLegacyPlanJson('{"foo":1}')).toBeNull()
  })

  it('完全不是 JSON → null', () => {
    expect(parseLegacyPlanJson('not json')).toBeNull()
  })
})

// ──────────────────────── Case 1: agentic happy path ────────────────────────

describe('agenticPlan: happy path（2 iterations 收敛）', () => {
  it('iter1=preview iter2=finalize → 返回完整 QueryPlan', async () => {
    const llm = makeLLM([
      previewJson('large language model agent'),
      finalizeJson({
        base_query: 'large language model agent',
        chinese_query: '大语言模型 智能体',
        year_from: 2022,
        year_to: 2026,
        language_scope: 'international',
        rationale: '核心概念命中正常',
        clarification_needed: false,
      }),
    ])
    const fetcher = makeFetcher([
      { count: 47, topTitles: ['LLM agents survey', 'Reasoning loop'] },
    ])

    const agent = new QueryPlanAgent(llm, fetcher)
    const plan = await agent.agenticPlan({
      projectDescription: 'LLM agent reasoning',
      memorySnapshot: '',
      sources: ['openalex', 'arxiv'],
    })

    expect(plan.iterations).toBe(2)
    expect(plan.meta.mode).toBe('agentic')
    expect(plan.meta.baseQuery).toBe('large language model agent')
    expect(plan.meta.chineseQuery).toBe('大语言模型 智能体')
    expect(plan.meta.yearFrom).toBe(2022)
    expect(plan.meta.yearTo).toBe(2026)
    expect(plan.meta.clarificationNeeded).toBe(false)
    expect(plan.reasoning).toContain('核心概念命中正常')
    expect(Object.keys(plan.perSource).sort()).toEqual(['arxiv', 'openalex'])
    expect(plan.perSource.openalex.keywords).toEqual([
      'large',
      'language',
      'model',
      'agent',
    ])
    expect(plan.perSource.openalex.filters).toEqual({
      year_from: 2022,
      year_to: 2026,
      language_scope: 'international',
      exclude_terms: [],
    })
    // fetcherApi.searchPreview 调过一次（iter1）
    expect((fetcher.searchPreview as ReturnType<typeof vi.fn>)).toHaveBeenCalledTimes(1)
    expect((fetcher.searchPreview as ReturnType<typeof vi.fn>)).toHaveBeenCalledWith(
      'local_kb',
      'large language model agent',
    )
  })
})

// ──────────────────────── Case 2: malformed JSON → 重试成功 ────────────────────────

describe('agenticPlan: LLM 返回 malformed JSON → 同 loop 内重试成功', () => {
  it('iter1=garbage iter2=finalize → 解析成功（iterations=2）', async () => {
    const llm = makeLLM([
      'I think we should look into this... (no JSON here)',
      finalizeJson({
        base_query: 'graph neural network',
        year_from: 2020,
        year_to: 2026,
        language_scope: 'international',
        rationale: 'retry 成功',
      }),
    ])
    const fetcher = makeFetcher([])

    const agent = new QueryPlanAgent(llm, fetcher)
    const plan = await agent.agenticPlan({
      projectDescription: 'GNN survey',
      sources: ['openalex'],
    })

    expect(plan.iterations).toBe(2)
    expect(plan.meta.mode).toBe('agentic')
    expect(plan.meta.baseQuery).toBe('graph neural network')
    expect(plan.perSource.openalex.keywords).toEqual(['graph', 'neural', 'network'])
    // fetcher 没被调用（没有任何 search_preview action）
    expect((fetcher.searchPreview as ReturnType<typeof vi.fn>)).not.toHaveBeenCalled()
  })
})

// ──────────────────────── Case 3: max iterations 达到 → fallback legacy ────────────────────────

describe('agenticPlan: 耗尽 maxIterations → fallback legacyPlan', () => {
  it('agentic 全是 preview 不 finalize → fallback 到 legacy 成功', async () => {
    // agentic loop: 3 次都是 preview，第 4 次（legacy 用）返回合法 plan
    const llm = makeLLM([
      previewJson('iter1 query'),
      previewJson('iter2 query'),
      previewJson('iter3 query'),
      // 这次是 legacyPlan 调用 → legacy 格式 JSON
      JSON.stringify({
        base_query: 'fallback query terms',
        year_from: 2018,
        year_to: 2025,
        language_scope: 'global',
        rationale: 'legacy 兜底',
      }),
    ])
    const fetcher = makeFetcher([
      { count: 5, topTitles: ['t1'] },
      { count: 3, topTitles: ['t2'] },
      { count: 7, topTitles: ['t3'] },
    ])

    const agent = new QueryPlanAgent(llm, fetcher)
    const plan = await agent.agenticPlan({
      projectDescription: 'AI alignment',
      sources: ['openalex', 'arxiv'],
      maxIterations: 3,
    })

    // fallback 后 mode 应该是 legacy
    expect(plan.meta.mode).toBe('legacy')
    expect(plan.meta.baseQuery).toBe('fallback query terms')
    expect(plan.meta.languageScope).toBe('global')
    expect(plan.reasoning).toMatch(/fallback from agentic/)
    expect(plan.reasoning).toMatch(/exhausted/)
    expect(plan.perSource.openalex.keywords).toEqual(['fallback', 'query', 'terms'])
    // 3 次 preview 调用都跑过了
    expect((fetcher.searchPreview as ReturnType<typeof vi.fn>)).toHaveBeenCalledTimes(3)
  })
})

// ──────────────────────── Case 4: legacyPlan happy path ────────────────────────

describe('legacyPlan: happy path', () => {
  it('一次 LLM 返回合法 JSON → 解析成功', async () => {
    const llm = makeLLM([
      JSON.stringify({
        base_query: 'transformer attention mechanism',
        chinese_query: '注意力机制 变换器',
        expanded_terms: ['self-attention', 'multi-head'],
        exclude_terms: ['lstm'],
        year_from: 2017,
        year_to: 2026,
        sources: ['arxiv'],
        max_per_source: 25,
        language_scope: 'international',
        rationale: 'transformer 主线',
      }),
    ])

    const agent = new QueryPlanAgent(llm)
    const plan = await agent.legacyPlan({
      projectDescription: 'transformer review',
      sources: ['openalex', 'arxiv'],
    })

    expect(plan.iterations).toBe(0)
    expect(plan.meta.mode).toBe('legacy')
    expect(plan.meta.baseQuery).toBe('transformer attention mechanism')
    expect(plan.meta.chineseQuery).toBe('注意力机制 变换器')
    expect(plan.meta.yearFrom).toBe(2017)
    expect(plan.meta.excludeTerms).toEqual(['lstm'])
    expect(plan.reasoning).toBe('transformer 主线')
    expect(Object.keys(plan.perSource).sort()).toEqual(['arxiv', 'openalex'])
    expect(plan.perSource.arxiv.keywords).toEqual([
      'transformer',
      'attention',
      'mechanism',
    ])
    expect(plan.perSource.arxiv.filters).toEqual({
      year_from: 2017,
      year_to: 2026,
      language_scope: 'international',
      exclude_terms: ['lstm'],
    })
  })

  it('legacy 第一次 parse 失败 → 第二次重试成功', async () => {
    const llm = makeLLM([
      'garbage text no json here',
      JSON.stringify({
        base_query: 'retry succeeded',
        year_from: 2020,
        year_to: 2025,
      }),
    ])
    const agent = new QueryPlanAgent(llm)
    const plan = await agent.legacyPlan({
      projectDescription: 'x',
      sources: ['openalex'],
    })
    expect(plan.meta.baseQuery).toBe('retry succeeded')
  })
})

// ──────────────────────── Case 5: 所有 LLM 调用失败 → throw QueryPlanError ────────────────────────

describe('全失败：throws QueryPlanError', () => {
  it('agentic + legacy 两层都返回 null/garbage → throw QueryPlanError', async () => {
    // agentic 3 iterations 全 garbage + legacy 2 attempts 全 garbage = 5 次
    const llm = makeLLM(() => 'totally not json')
    const agent = new QueryPlanAgent(llm)

    await expect(
      agent.agenticPlan({
        projectDescription: 'something',
        sources: ['openalex'],
        maxIterations: 3,
      }),
    ).rejects.toBeInstanceOf(QueryPlanError)
  })

  it('legacy LLM 始终返回 null → throw QueryPlanError', async () => {
    const llm = makeLLM(() => null)
    const agent = new QueryPlanAgent(llm)
    await expect(
      agent.legacyPlan({
        projectDescription: 'x',
        sources: ['openalex'],
      }),
    ).rejects.toBeInstanceOf(QueryPlanError)
  })

  it('legacy LLM throws → 仍 throw QueryPlanError（包了原异常）', async () => {
    const llm: LLMLike = {
      generate: vi.fn(async () => {
        throw new Error('network down')
      }),
    }
    const agent = new QueryPlanAgent(llm)
    await expect(
      agent.legacyPlan({
        projectDescription: 'x',
        sources: ['openalex'],
      }),
    ).rejects.toThrow(/legacyPlan failed/)
  })

  it('入参缺 projectDescription → throw QueryPlanError', async () => {
    const agent = new QueryPlanAgent(makeLLM([]))
    await expect(
      agent.legacyPlan({ projectDescription: '', sources: ['x'] }),
    ).rejects.toBeInstanceOf(QueryPlanError)
    await expect(
      agent.agenticPlan({ projectDescription: '   ', sources: ['x'] }),
    ).rejects.toBeInstanceOf(QueryPlanError)
  })

  it('入参 sources 空 → throw QueryPlanError', async () => {
    const agent = new QueryPlanAgent(makeLLM([]))
    await expect(
      agent.legacyPlan({ projectDescription: 'x', sources: [] }),
    ).rejects.toBeInstanceOf(QueryPlanError)
  })
})
