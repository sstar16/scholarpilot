/**
 * fetcherApi 单测 — mock axios api 实例验证：
 *  1. search() → POST /api/fetcher/search，translates query → keywords，回填 latency
 *  2. search() docs 缺失 → 空数组兜底
 *  3. sources() → GET /api/fetcher/sources
 *  4. sources() 非数组 → 空数组兜底
 *  5. checkBudget()/consumeBudget()/refundBudget() → POST 对应预算端点
 *  6. consumeBudget(force=true) 透传到 body
 *  7. searchPreview() happy path → 透传到 search
 *  8. searchPreview() 失败 → 返回 {error}
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../client', () => {
  const post = vi.fn()
  const get = vi.fn()
  return {
    default: { post, get },
    // re-export 项目里其他模块依赖的 named exports 占位（fetcher.ts 只用 default）
    authApi: {},
    projectApi: {},
  }
})

import api from '../client'
import { fetcherApi } from '../fetcher'

const _api = api as unknown as {
  post: ReturnType<typeof vi.fn>
  get: ReturnType<typeof vi.fn>
}

beforeEach(() => {
  vi.clearAllMocks()
  _api.post.mockReset()
  _api.get.mockReset()
})

// ──────────────── search ────────────────

describe('fetcherApi.search', () => {
  it('POST /api/fetcher/search，将 query 转 keywords，回填 latency_ms', async () => {
    _api.post.mockResolvedValueOnce({
      data: {
        source: 'openalex',
        count: 2,
        docs: [
          { source: 'openalex', external_id: 'W1', title: 'Paper One' },
          { source: 'openalex', external_id: 'W2', title: 'Paper Two' },
        ],
      },
    })

    const r = await fetcherApi.search({
      source: 'openalex',
      query: 'transformer attention',
      max_results: 25,
      year_from: 2020,
      year_to: 2026,
    })

    expect(_api.post).toHaveBeenCalledTimes(1)
    const [url, body] = _api.post.mock.calls[0]
    expect(url).toBe('/api/fetcher/search')
    expect(body).toMatchObject({
      source: 'openalex',
      keywords: 'transformer attention',
      max_results: 25,
      year_from: 2020,
      year_to: 2026,
    })
    expect(r.docs).toHaveLength(2)
    expect(r.source).toBe('openalex')
    expect(r.count).toBe(2)
    expect(typeof r.latency_ms).toBe('number')
  })

  it('max_results 不传时默认 25', async () => {
    _api.post.mockResolvedValueOnce({ data: { docs: [] } })
    await fetcherApi.search({ source: 'arxiv', query: 'x' })
    const [, body] = _api.post.mock.calls[0]
    expect((body as any).max_results).toBe(25)
  })

  it('year_from/year_to/language 为 null/undefined 时不进 payload', async () => {
    _api.post.mockResolvedValueOnce({ data: { docs: [] } })
    await fetcherApi.search({
      source: 'arxiv',
      query: 'x',
      year_from: null,
      year_to: null,
    })
    const [, body] = _api.post.mock.calls[0]
    expect('year_from' in (body as object)).toBe(false)
    expect('year_to' in (body as object)).toBe(false)
    expect('language' in (body as object)).toBe(false)
  })

  it('返回体没 docs 字段 → 空数组兜底', async () => {
    _api.post.mockResolvedValueOnce({ data: {} })
    const r = await fetcherApi.search({ source: 'arxiv', query: 'x' })
    expect(r.docs).toEqual([])
    expect(r.count).toBe(0)
  })

  it('网络错误 → 抛出（caller 用 try/catch 接）', async () => {
    _api.post.mockRejectedValueOnce(new Error('502 Bad Gateway'))
    await expect(
      fetcherApi.search({ source: 'arxiv', query: 'x' }),
    ).rejects.toThrowError('502 Bad Gateway')
  })
})

// ──────────────── sources ────────────────

describe('fetcherApi.sources', () => {
  it('GET /api/fetcher/sources → 返回数组', async () => {
    _api.get.mockResolvedValueOnce({
      data: [
        {
          id: 'openalex',
          name: 'OpenAlex',
          description: '...',
          doc_type: 'paper',
          category: 'academic',
          language: 'international',
          phase: 1,
          enabled: true,
          paid_pdf: false,
        },
      ],
    })
    const list = await fetcherApi.sources()
    expect(_api.get).toHaveBeenCalledWith('/api/fetcher/sources')
    expect(list).toHaveLength(1)
    expect(list[0].id).toBe('openalex')
    expect(list[0].enabled).toBe(true)
    expect(list[0].paid_pdf).toBe(false)
  })

  it('返回非数组（如 401 错误体）→ 空数组兜底', async () => {
    _api.get.mockResolvedValueOnce({ data: { detail: 'Not authenticated' } })
    const list = await fetcherApi.sources()
    expect(list).toEqual([])
  })
})

// ──────────────── budget ────────────────

describe('fetcherApi.checkBudget', () => {
  it('POST /api/fetcher/budget/patenthub/check', async () => {
    _api.post.mockResolvedValueOnce({
      data: { used: 2, max: 5, remaining: 3, exhausted: false },
    })
    const status = await fetcherApi.checkBudget('run-abc')
    const [url, body] = _api.post.mock.calls[0]
    expect(url).toBe('/api/fetcher/budget/patenthub/check')
    expect(body).toEqual({ client_run_id: 'run-abc' })
    expect(status.remaining).toBe(3)
    expect(status.exhausted).toBe(false)
  })
})

describe('fetcherApi.consumeBudget', () => {
  it('POST consume 默认 force=false', async () => {
    _api.post.mockResolvedValueOnce({
      data: { ok: true, used: 3, max: 5 },
    })
    const r = await fetcherApi.consumeBudget({ client_run_id: 'run-abc' })
    const [url, body] = _api.post.mock.calls[0]
    expect(url).toBe('/api/fetcher/budget/patenthub/consume')
    expect(body).toEqual({ client_run_id: 'run-abc', force: false })
    expect(r.ok).toBe(true)
  })

  it('POST consume force=true 透传', async () => {
    _api.post.mockResolvedValueOnce({
      data: { ok: true, used: 6, max: 5 },
    })
    const r = await fetcherApi.consumeBudget({
      client_run_id: 'run-xyz',
      force: true,
    })
    const [, body] = _api.post.mock.calls[0]
    expect((body as any).force).toBe(true)
    expect(r.used).toBe(6)
  })

  it('软超额 ok=false → 返回正常，不抛', async () => {
    _api.post.mockResolvedValueOnce({
      data: { ok: false, used: 5, max: 5 },
    })
    const r = await fetcherApi.consumeBudget({ client_run_id: 'run-abc' })
    expect(r.ok).toBe(false)
  })
})

describe('fetcherApi.refundBudget', () => {
  it('POST refund', async () => {
    _api.post.mockResolvedValueOnce({
      data: { ok: true, used: 2, max: 5, refunded: true },
    })
    const r = await fetcherApi.refundBudget({ client_run_id: 'run-abc' })
    const [url, body] = _api.post.mock.calls[0]
    expect(url).toBe('/api/fetcher/budget/patenthub/refund')
    expect(body).toEqual({ client_run_id: 'run-abc' })
    expect(r.refunded).toBe(true)
  })
})

// ──────────────── searchPreview ────────────────

describe('fetcherApi.searchPreview', () => {
  it('happy path：返回 {count, topTitles}', async () => {
    _api.post.mockResolvedValueOnce({
      data: {
        source: 'openalex',
        count: 3,
        docs: [
          { source: 'openalex', external_id: 'W1', title: 'Title One' },
          { source: 'openalex', external_id: 'W2', title: 'Title Two' },
          { source: 'openalex', external_id: 'W3', title: 'Title Three' },
        ],
      },
    })
    const r = await fetcherApi.searchPreview('openalex', 'transformer')
    expect('count' in r).toBe(true)
    if ('count' in r) {
      expect(r.count).toBe(3)
      expect(r.topTitles).toEqual(['Title One', 'Title Two', 'Title Three'])
    }
    // 验证传给 search 的 max_results=5
    const [, body] = _api.post.mock.calls[0]
    expect((body as any).max_results).toBe(5)
  })

  it('search 抛错 → 返回 {error: msg}（不再 throw）', async () => {
    _api.post.mockRejectedValueOnce(new Error('502 Bad Gateway'))
    const r = await fetcherApi.searchPreview('arxiv', 'x')
    expect('error' in r).toBe(true)
    if ('error' in r) {
      expect(r.error).toContain('502')
    }
  })

  it('截断到 maxResults 个 title', async () => {
    _api.post.mockResolvedValueOnce({
      data: {
        docs: Array.from({ length: 10 }, (_, i) => ({
          source: 'openalex',
          external_id: `W${i}`,
          title: `T${i}`,
        })),
      },
    })
    const r = await fetcherApi.searchPreview('openalex', 'q', 3)
    expect('topTitles' in r).toBe(true)
    if ('topTitles' in r) {
      expect(r.topTitles).toHaveLength(3)
      expect(r.topTitles).toEqual(['T0', 'T1', 'T2'])
    }
  })
})
