/**
 * FetchPhase 单测 — 验证 14 源并行 / 部分失败容错 / concurrency 限流 / dedup / 事件流。
 *
 * 注入策略：
 * - 通过 `setFetcherApi(mock)` 注入 mock，不再依赖网络
 * - ctx.artifacts 手动 set 上游 phase 输出（plan_query / build_dedup / load_confirmed_keywords / apply_search_mode / load_round）
 *
 * 覆盖：
 *  1. 14 源全部 ok → fetchedDocs 拼好，sourceStats 全 'ok'
 *  2. 部分源 throw → status='error'，其它源不受影响
 *  3. 部分源返回空 docs → status='empty'
 *  4. 并发上限 8 — 即时观察 inflight 峰值不超过 8
 *  5. dedup.excludeKeys 过滤掉已存在的 docs
 *  6. 同一源里 (source, external_id) 重复 → 内部去重
 *  7. abortSignal 提前 abort → 不调 fetcher
 *  8. doc_arrived / source_started 事件正确发出
 *  9. 不传 setFetcherApi 时回退到默认（默认会走真 axios，所以这条测试通过 setFetcherApi(null) 后用 vi.mock 兜底）
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import { ClientEventBus } from '@/data/orchestrator/eventBus'

import { createRoundContext, type RoundContext } from '../../context'
import { fetchPhase, setFetcherApi, type FetcherApiLike } from '../fetch'

// ──────────────────────── Helpers ────────────────────────

interface FixtureOpts {
  sources?: string[]
  excludeKeys?: string[]
  perSourceQueries?: Record<string, { complex: string; medium: string; simple: string }> | null
  yearFrom?: number | null
  yearTo?: number | null
  baseQuery?: string
  aborted?: boolean
}

function mkCtx(opts: FixtureOpts = {}): { ctx: RoundContext; bus: ClientEventBus; ac: AbortController } {
  const sources = opts.sources ?? ['openalex', 'arxiv', 'crossref']
  const ac = new AbortController()
  if (opts.aborted) ac.abort()
  const bus = new ClientEventBus()
  const ctx = createRoundContext({
    roundId: 'r1',
    projectId: 'p1',
    llmManager: { generate: async () => null } as never,
    eventBus: bus,
    abortSignal: ac.signal,
  })

  // Plan
  const perSource: Record<string, { keywords: string[]; filters: Record<string, unknown> }> = {}
  for (const sid of sources) {
    perSource[sid] = { keywords: ['ml', 'agent'], filters: {} }
  }
  ctx.set('plan_query', {
    queryPlan: {
      perSource,
      reasoning: '',
      iterations: 0,
      meta: {
        baseQuery: opts.baseQuery ?? 'machine learning agents',
        chineseQuery: null,
        yearFrom: opts.yearFrom ?? null,
        yearTo: opts.yearTo ?? null,
        languageScope: 'international' as const,
        excludeTerms: [] as string[],
        clarificationNeeded: false,
        clarificationMessage: '',
        mode: 'legacy' as const,
      },
    },
    planSource: 'agent' as const,
  })

  // Dedup
  ctx.set('build_dedup', {
    excludeKeys: new Set(opts.excludeKeys ?? []),
  })

  // Confirmed keywords
  ctx.set('load_confirmed_keywords', {
    perSourceQueries: opts.perSourceQueries ?? null,
    dynamicSynonyms: null,
  })

  // Apply search mode
  ctx.set('apply_search_mode', { finalSources: sources })

  // Load round（fetch.ts 只是 void ctx.get('load_round') 验证可见性）
  ctx.set('load_round', {
    round: {} as never,
    project: {} as never,
    scoringWeights: null,
    scoringCutoff: null,
    searchMode: null,
  })

  return { ctx, bus, ac }
}

function mkDoc(source: string, eid: string, title?: string) {
  return {
    source,
    external_id: eid,
    title: title ?? `${source}-${eid}`,
  }
}

afterEach(() => {
  setFetcherApi(null)
})

beforeEach(() => {
  vi.clearAllMocks()
})

// ──────────────────────── Tests ────────────────────────

describe('FetchPhase happy path', () => {
  it('14 源全部 ok → docs 全收，sourceStats 全 ok', async () => {
    const sources = [
      'openalex', 'arxiv', 'crossref', 'europepmc', 'dblp',
      'openalex_zh', 'epo_ops', 'lens', 'patenthub', 'pubmed',
      'clinicaltrials', 'semantic_scholar', 'biorxiv', 'medrxiv',
    ]
    const search = vi.fn(async (body: { source: string }) => ({
      docs: [mkDoc(body.source, '1'), mkDoc(body.source, '2')],
      latency_ms: 10,
    }))
    setFetcherApi({ search } as FetcherApiLike)

    const { ctx } = mkCtx({ sources })
    const out = (await fetchPhase.execute(ctx)) as {
      selectedDocs: Array<{ source: string; external_id: string }>
      totalCandidates: number
      sourceStats: Record<string, { status: string; count: number }>
      iterations: number
    }

    expect(out.totalCandidates).toBe(14 * 2)
    expect(out.iterations).toBe(1)
    expect(Object.keys(out.sourceStats)).toHaveLength(14)
    for (const s of sources) {
      expect(out.sourceStats[s].status).toBe('ok')
      expect(out.sourceStats[s].count).toBe(2)
    }
    expect(search).toHaveBeenCalledTimes(14)
  })
})

describe('FetchPhase per-source error tolerance', () => {
  it('部分源 throw → 标 error，其它源照样跑完', async () => {
    const sources = ['openalex', 'arxiv', 'crossref', 'europepmc']
    const search = vi.fn(async (body: { source: string }) => {
      if (body.source === 'arxiv') throw new Error('arxiv timeout')
      if (body.source === 'crossref') throw new Error('502 Bad Gateway')
      return { docs: [mkDoc(body.source, '1')] }
    })
    setFetcherApi({ search } as FetcherApiLike)

    const { ctx } = mkCtx({ sources })
    const out = (await fetchPhase.execute(ctx)) as {
      selectedDocs: unknown[]
      sourceStats: Record<string, { status: string; count: number; error?: string }>
    }

    expect(out.selectedDocs).toHaveLength(2) // openalex + europepmc
    expect(out.sourceStats.openalex.status).toBe('ok')
    expect(out.sourceStats.arxiv.status).toBe('error')
    expect(out.sourceStats.arxiv.error).toContain('arxiv timeout')
    expect(out.sourceStats.crossref.status).toBe('error')
    expect(out.sourceStats.europepmc.status).toBe('ok')
    // 全部源都被尝试调过
    expect(search).toHaveBeenCalledTimes(4)
  })

  it('某些源返回空 docs → 标 empty', async () => {
    const sources = ['openalex', 'arxiv']
    const search = vi.fn(async (body: { source: string }) => {
      if (body.source === 'openalex') return { docs: [mkDoc('openalex', '1')] }
      return { docs: [] }
    })
    setFetcherApi({ search } as FetcherApiLike)

    const { ctx } = mkCtx({ sources })
    const out = (await fetchPhase.execute(ctx)) as {
      sourceStats: Record<string, { status: string; count: number }>
    }
    expect(out.sourceStats.openalex.status).toBe('ok')
    expect(out.sourceStats.arxiv.status).toBe('empty')
    expect(out.sourceStats.arxiv.count).toBe(0)
  })
})

describe('FetchPhase concurrency limit (8)', () => {
  it('14 源同时跑，inflight 峰值 ≤ 8', async () => {
    const sources = Array.from({ length: 14 }, (_, i) => `s${i}`)
    let inflight = 0
    let peak = 0
    const search = vi.fn(async (body: { source: string }) => {
      inflight++
      peak = Math.max(peak, inflight)
      // 让 promise 在下一个 microtask 后才 resolve，确保 queue runNext 触发并发观察
      await new Promise<void>((res) => setTimeout(res, 5))
      inflight--
      return { docs: [mkDoc(body.source, '1')] }
    })
    setFetcherApi({ search } as FetcherApiLike)

    const { ctx } = mkCtx({ sources })
    await fetchPhase.execute(ctx)

    expect(peak).toBeGreaterThan(0)
    expect(peak).toBeLessThanOrEqual(8)
    expect(search).toHaveBeenCalledTimes(14)
  })
})

describe('FetchPhase dedup', () => {
  it('excludeKeys 命中 → 该 doc 不进 selectedDocs', async () => {
    const sources = ['openalex']
    const search = vi.fn(async (body: { source: string }) => ({
      docs: [
        mkDoc(body.source, '1'),
        mkDoc(body.source, 'keep'),
        mkDoc(body.source, '3'),
      ],
    }))
    setFetcherApi({ search } as FetcherApiLike)

    const { ctx } = mkCtx({
      sources,
      excludeKeys: ['openalex:1', 'openalex:3'],
    })
    const out = (await fetchPhase.execute(ctx)) as {
      selectedDocs: Array<{ external_id: string }>
      sourceStats: Record<string, { count: number }>
    }
    expect(out.selectedDocs).toHaveLength(1)
    expect(out.selectedDocs[0].external_id).toBe('keep')
    expect(out.sourceStats.openalex.count).toBe(1)
  })

  it('单源同一 (source, external_id) 重复 → 仅保留一份', async () => {
    const sources = ['openalex']
    const search = vi.fn(async (body: { source: string }) => ({
      docs: [
        mkDoc(body.source, 'dup'),
        mkDoc(body.source, 'dup'),
        mkDoc(body.source, 'unique'),
      ],
    }))
    setFetcherApi({ search } as FetcherApiLike)

    const { ctx } = mkCtx({ sources })
    const out = (await fetchPhase.execute(ctx)) as {
      selectedDocs: Array<{ external_id: string }>
    }
    expect(out.selectedDocs).toHaveLength(2)
    const ids = out.selectedDocs.map((d) => d.external_id).sort()
    expect(ids).toEqual(['dup', 'unique'])
  })
})

describe('FetchPhase abort', () => {
  it('abortSignal 已 aborted → 提前退出，不调 fetcher', async () => {
    const search = vi.fn(async (_body: any) => ({ docs: [] }))
    setFetcherApi({ search } as FetcherApiLike)

    const { ctx } = mkCtx({
      sources: ['openalex', 'arxiv'],
      aborted: true,
    })
    const out = (await fetchPhase.execute(ctx)) as { totalCandidates: number }
    expect(out.totalCandidates).toBe(0)
    expect(search).not.toHaveBeenCalled()
  })
})

describe('FetchPhase events', () => {
  it('每源开始/完成 + 每篇 doc 都 publish 对应事件', async () => {
    const sources = ['openalex', 'arxiv']
    const search = vi.fn(async (body: { source: string }) => ({
      docs: [mkDoc(body.source, '1'), mkDoc(body.source, '2')],
    }))
    setFetcherApi({ search } as FetcherApiLike)

    const { ctx, bus } = mkCtx({ sources })
    const sourceStarted: string[] = []
    const docArrived: string[] = []
    bus.subscribe('round:r1', (e) => {
      if (e.event === 'source_started') sourceStarted.push((e.data as any).source)
      if (e.event === 'doc_arrived') docArrived.push(`${(e.data as any).source}:${(e.data as any).external_id}`)
    })

    await fetchPhase.execute(ctx)

    expect(sourceStarted.sort()).toEqual(['arxiv', 'openalex'])
    expect(docArrived.sort()).toEqual([
      'arxiv:1',
      'arxiv:2',
      'openalex:1',
      'openalex:2',
    ])
  })

  it('开始/结束 publish round_status 事件（progress 0.22 → 0.38）', async () => {
    const sources = ['openalex']
    const search = vi.fn(async (body: { source: string }) => ({
      docs: [mkDoc(body.source, '1')],
    }))
    setFetcherApi({ search } as FetcherApiLike)

    const { ctx, bus } = mkCtx({ sources })
    const statuses: number[] = []
    bus.subscribe('round:r1', (e) => {
      if (e.event === 'round_status') statuses.push((e.data as any).progress)
    })
    await fetchPhase.execute(ctx)
    expect(statuses[0]).toBeCloseTo(0.22, 5)
    expect(statuses[statuses.length - 1]).toBeCloseTo(0.38, 5)
  })
})

describe('FetchPhase confirmed keywords passthrough', () => {
  it('perSourceQueries 提供 → 用 complex 当 query，medium/simple 透传', async () => {
    const sources = ['openalex']
    const search = vi.fn(async (_body: any) => ({ docs: [] }))
    setFetcherApi({ search } as FetcherApiLike)

    const { ctx } = mkCtx({
      sources,
      perSourceQueries: {
        openalex: {
          complex: 'transformer AND attention',
          medium: 'transformer attention',
          simple: 'transformer',
        },
      },
    })
    await fetchPhase.execute(ctx)

    expect(search).toHaveBeenCalledTimes(1)
    const [body] = search.mock.calls[0]
    expect(body.source).toBe('openalex')
    expect(body.query).toBe('transformer AND attention')
    expect(body.query_medium).toBe('transformer attention')
    expect(body.query_simple).toBe('transformer')
  })

  it('无 perSourceQueries → 用 plan.perSource[sid].keywords.join(" ") 当 query', async () => {
    const sources = ['openalex']
    const search = vi.fn(async (_body: any) => ({ docs: [] }))
    setFetcherApi({ search } as FetcherApiLike)

    const { ctx } = mkCtx({ sources })
    await fetchPhase.execute(ctx)

    const [body] = search.mock.calls[0]
    expect(body.query).toBe('ml agent') // mkCtx 默认 keywords
  })
})

describe('FetchPhase year filter', () => {
  it('year_from/year_to 透传到 fetcher', async () => {
    const sources = ['openalex']
    const search = vi.fn(async (_body: any) => ({ docs: [] }))
    setFetcherApi({ search } as FetcherApiLike)

    const { ctx } = mkCtx({ sources, yearFrom: 2020, yearTo: 2026 })
    await fetchPhase.execute(ctx)
    const [body] = search.mock.calls[0]
    expect(body.year_from).toBe(2020)
    expect(body.year_to).toBe(2026)
  })
})
