/**
 * Fetcher API — 客户端调 sp-api 的 14 数据源代理桥。
 *
 * 客户端不直连数据源（CN GFW / Lens.org / EPO 鉴权 / PatentHub 付费均依赖
 * 服务端环境），统一走 sp-api（HK 机器）做 fetcher proxy + patenthub 预算守门。
 *
 * 上游：`sp-api/app/api/fetcher.py`
 *   GET  /api/fetcher/sources                    - 列源元数据
 *   POST /api/fetcher/search                     - 单源检索 → docs[]
 *   POST /api/fetcher/budget/patenthub/check     - 仅查
 *   POST /api/fetcher/budget/patenthub/consume   - 消费 1 次（force=true 越权）
 *   POST /api/fetcher/budget/patenthub/refund    - 失败回退
 *
 * 同时实现 Phase C `FetchPhase` 的 `FetcherApiLike` 鸭子接口（fetch.ts:58-68）
 * 和 `QueryPlanAgent` 的 `searchPreview` 鸭子接口（queryPlanAgent.ts:120-125）。
 */
import api from './client'

// ──────────────────────── Schemas ────────────────────────

/** Fetcher.search 请求体（与 fetch.ts FetcherApiLike 对齐）。 */
export interface FetcherSearchRequest {
  source: string
  query: string
  max_results?: number
  year_from?: number | null
  year_to?: number | null
  language?: string | null
  /** 三档 query — 当前 sp-api 只取 complex (query)；预留给 fetcher level 三档检索。 */
  query_medium?: string
  query_simple?: string
}

/** Fetcher 返回的单篇 doc（透传 backend dict，关键字段类型化）。 */
export interface FetcherDoc {
  source: string
  external_id: string
  title: string
  abstract?: string
  authors?: string
  publication_date?: string
  url?: string
  doi?: string
  journal?: string
  citation_count?: number
  pdf_url?: string
  doc_type?: string
  metadata?: Record<string, unknown>
  /** 允许任意字段透传。 */
  [k: string]: unknown
}

/** Fetcher search 响应（对齐 sp-api SearchResponse）。 */
export interface FetcherSearchResponse {
  docs: FetcherDoc[]
  latency_ms?: number
  /** sp-api 实际返回了 source/count；客户端不强依赖。 */
  source?: string
  count?: number
}

/** Source 元数据（对齐 sp-api SourceInfo）。 */
export interface SourceMeta {
  id: string
  name: string
  description: string
  doc_type: string
  category: string
  language: string
  phase: number
  enabled: boolean
  paid_pdf: boolean
}

/** PatentHub 预算状态。 */
export interface PatenthubBudgetStatus {
  used: number
  max: number
  remaining: number
  exhausted: boolean
}

/** PatentHub consume 响应。 */
export interface PatenthubConsumeResponse {
  ok: boolean
  used: number
  max: number
  refunded?: boolean
}

// ──────────────────────── API ────────────────────────

/**
 * 客户端 → sp-api 的 fetcher 代理 facade。
 *
 * 错误传递：所有方法直接 throw（axios reject），caller 用 try/catch 包；
 * `Promise.allSettled` 风控由 caller（fetchPhase）做。
 */
export const fetcherApi = {
  /** 单源检索。sp-api 的 `keywords` 字段对应客户端 `query`。 */
  async search(req: FetcherSearchRequest): Promise<FetcherSearchResponse> {
    const t0 = Date.now()
    // sp-api SearchRequest.keywords 上限 2000 — boolean query 太长就截断防御
    // （QueryPlanAgent 偶尔会出 1500+ 的复合 query；超 2000 会 400 Bad Request）
    const keywords = (req.query ?? '').slice(0, 1900).trim() || ' '
    const payload: Record<string, unknown> = {
      source: req.source,
      keywords,
      max_results: req.max_results ?? 25,
    }
    if (req.year_from != null) payload.year_from = req.year_from
    if (req.year_to != null) payload.year_to = req.year_to
    if (req.language != null) payload.language = req.language

    const { data } = await api.post('/api/fetcher/search', payload)
    const latency = Date.now() - t0
    return {
      source: data?.source ?? req.source,
      count: data?.count ?? data?.docs?.length ?? 0,
      docs: Array.isArray(data?.docs) ? data.docs : [],
      latency_ms: latency,
    }
  },

  /** 列出 14 源元数据 + 启用/禁用状态（UI 勾选框用）。 */
  async sources(): Promise<SourceMeta[]> {
    const { data } = await api.get('/api/fetcher/sources')
    return Array.isArray(data) ? data : []
  },

  /** 不消费仅查 PatentHub PDF 预算（前端 tooltip "本轮剩余 N/5"）。 */
  async checkBudget(clientRunId: string): Promise<PatenthubBudgetStatus> {
    const { data } = await api.post(
      '/api/fetcher/budget/patenthub/check',
      { client_run_id: clientRunId },
    )
    return data as PatenthubBudgetStatus
  },

  /**
   * 消费 1 次 PatentHub 预算。`force=true` 表示用户已二次确认越权。
   *
   * 返回 `ok=false`：软超额 — caller 弹二次确认后带 `force=true` 重发。
   */
  async consumeBudget(params: {
    client_run_id: string
    force?: boolean
  }): Promise<PatenthubConsumeResponse> {
    const { data } = await api.post(
      '/api/fetcher/budget/patenthub/consume',
      { client_run_id: params.client_run_id, force: params.force ?? false },
    )
    return data as PatenthubConsumeResponse
  },

  /** 下载失败时回退 1 次预算。 */
  async refundBudget(params: { client_run_id: string }): Promise<PatenthubConsumeResponse> {
    const { data } = await api.post(
      '/api/fetcher/budget/patenthub/refund',
      { client_run_id: params.client_run_id },
    )
    return data as PatenthubConsumeResponse
  },

  /**
   * QueryPlanAgent 的 search_preview 工具实现 —— 给 LLM 跑试探查询用。
   *
   * 返回 `{count, topTitles}` 或 `{error}`，对齐 `queryPlanAgent.ts:120-125`。
   * 失败不抛（agent 会自行处理 `error` 分支）。
   */
  async searchPreview(
    source: string,
    keywords: string,
    maxResults = 5,
  ): Promise<{ count: number; topTitles: string[] } | { error: string }> {
    try {
      const r = await this.search({
        source,
        query: keywords,
        max_results: maxResults,
      })
      return {
        count: r.count ?? r.docs.length,
        topTitles: r.docs.slice(0, Math.min(maxResults, 5)).map((d) => String(d.title ?? '')),
      }
    } catch (e) {
      const msg = (e as Error).message ?? String(e)
      return { error: msg.slice(0, 200) }
    }
  },
}

export type FetcherApi = typeof fetcherApi
