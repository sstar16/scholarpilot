import axios, {
  type AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios'
import { useToast } from '../composables/useToast'

import { SECURE_KEYS, secureDelete, secureGet, secureSet } from './secure_storage'
import { getByokActive, loadByokConfig, type ByokConfig } from './byok_config'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
const CLIENT_TYPE = import.meta.env.VITE_CLIENT_TYPE || 'desktop'
const CLIENT_VERSION = import.meta.env.VITE_CLIENT_VERSION || '0.0.0'

const api: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
})

// ============================================================
// A1 优化：module-level 同步 cache，请求拦截器零 IPC
// ------------------------------------------------------------
// 之前每个 axios 请求都跑 3 次跨进程 IPC：
//   1. secureGet(ACCESS_TOKEN) — Tauri keyring crate
//   2. getByokActive() — SQLite settings 表 query
//   3. loadByokConfig() — keychain (有 in-memory cache)
// 在拦截器是 async 的情况下每个请求 5-10ms 额外开销，连发 10 条消息体感卡顿。
//
// 现在改为 module-level cache：
// - 启动时 hydrateApiCache() 一次 hydrate 三个值（main.ts bootstrap）
// - login/register/logout/saveByok/clearByok 同步刷 cache
// - 拦截器改 sync 函数纯读 cache（< 0.1ms）
// ============================================================

let _accessTokenCache: string | null = null
let _byokActiveCache: boolean = false
let _byokConfigCache: ByokConfig | null = null

/** App bootstrap 时一次 hydrate；之后请求拦截器纯读 module 变量。 */
export async function hydrateApiCache(): Promise<void> {
  try {
    const [tok, active, cfg] = await Promise.all([
      secureGet(SECURE_KEYS.ACCESS_TOKEN),
      getByokActive(),
      loadByokConfig(),
    ])
    _accessTokenCache = tok
    _byokActiveCache = active
    _byokConfigCache = cfg
  } catch (err) {
    console.warn('[ApiClient] hydrateApiCache failed:', err)
  }
}

export function setAccessTokenCache(token: string | null): void {
  _accessTokenCache = token
}
export function setByokActiveCache(active: boolean): void {
  _byokActiveCache = active
}
export function setByokConfigCache(cfg: ByokConfig | null): void {
  _byokConfigCache = cfg
}

/** 单测专用：复位所有 cache。 */
export function _resetApiCacheForTesting(): void {
  _accessTokenCache = null
  _byokActiveCache = false
  _byokConfigCache = null
}

// 同步请求拦截器：纯读 module-level cache，零 IPC
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  if (_accessTokenCache) {
    config.headers.Authorization = `Bearer ${_accessTokenCache}`
  }
  config.headers['X-Client-Type'] = CLIENT_TYPE
  config.headers['X-Client-Version'] = CLIENT_VERSION

  if (_byokActiveCache && _byokConfigCache?.api_key) {
    const cfg = _byokConfigCache
    config.headers['X-User-LLM-Provider'] = cfg.provider
    config.headers['X-User-LLM-Key'] = cfg.api_key
    if (cfg.model) config.headers['X-User-LLM-Model'] = cfg.model
    if (cfg.base_url) config.headers['X-User-LLM-Base-Url'] = cfg.base_url
  }
  return config
})

// module-level toast instance（client.ts 不在 setup() 上下文里，直接调用 composable 返回值即可）
const _toast = useToast()

// 同一条错误 toast 在短时间内只弹一次（避免 fallback / retry 重复触发）
const _toastDedupe = new Map<string, number>()
function _toastOnce(key: string, fire: () => void, ttlMs = 2500) {
  const now = Date.now()
  const last = _toastDedupe.get(key) || 0
  if (now - last < ttlMs) return
  _toastDedupe.set(key, now)
  fire()
}

// 单飞 refresh：并发 401 时只发一次 refresh，所有原始请求等同一个新 token
let _refreshing: Promise<string | null> | null = null

async function _refreshAccessTokenOnce(): Promise<string | null> {
  const refresh = await secureGet(SECURE_KEYS.REFRESH_TOKEN)
  if (!refresh) return null

  try {
    const res = await axios.post(
      `${BASE_URL}/api/auth/refresh`,
      { refresh_token: refresh },
      {
        headers: {
          'X-Client-Type': CLIENT_TYPE,
          'X-Client-Version': CLIENT_VERSION,
        },
      },
    )
    const { access_token, refresh_token: newRefresh } = res.data
    await secureSet(SECURE_KEYS.ACCESS_TOKEN, access_token)
    await secureSet(SECURE_KEYS.REFRESH_TOKEN, newRefresh)
    setAccessTokenCache(access_token)  // A1: 刷 cache 让后续请求立即用新 token
    return access_token
  } catch {
    return null
  }
}

// 401 自动 refresh 一次；refresh 失败清 token 跳登录。409 弹互斥提示。
api.interceptors.response.use(
  (res) => res,
  async (err: AxiosError) => {
    const status = err.response?.status
    const original = err.config as
      | (AxiosRequestConfig & { __retried?: boolean })
      | undefined

    if (status === 401 && original && !original.__retried) {
      original.__retried = true
      _refreshing ||= _refreshAccessTokenOnce()
      const newAccess = await _refreshing
      _refreshing = null
      if (newAccess) {
        original.headers = original.headers || {}
        ;(original.headers as any).Authorization = `Bearer ${newAccess}`
        return api.request(original)
      }
      // refresh 也失败：清 token 跳登录
      await secureDelete(SECURE_KEYS.ACCESS_TOKEN)
      await secureDelete(SECURE_KEYS.REFRESH_TOKEN)
      setAccessTokenCache(null)  // A1: 同步清 cache
      window.location.href = '/login'
    } else if (status === 409) {
      const detail = (err.response?.data as any)?.detail
      // detail 是字符串 → 通用互斥提示；detail 是 object → 交给业务层处理（如 pending round 流程）
      if (typeof detail === 'string' && detail) {
        _toastOnce(`409:${detail}`, () =>
          _toast.warning(detail, { duration: 4500 })
        )
        ;(err as any).__handledByInterceptor = true
      }
    }
    return Promise.reject(err)
  }
)

export default api

export const authApi = {
  // 2026-05-08：invitation_code 改为可选 — desktop 客户端注册开放，
  // 后端按 X-Client-Type=desktop 跳过邀请码校验；web 仍要求。
  register: (data: {
    email: string
    name: string
    password: string
    invitation_code?: string
  }) => api.post('/api/auth/register', data),
  login: (data: { email: string; password: string }) =>
    api.post('/api/auth/login', data),
  logout: (refresh_token: string) =>
    api.post('/api/auth/logout', { refresh_token }),
  me: () => api.get('/api/auth/me'),
}

// ============================================================
// Admin API —— 用户管理 + 邀请码管理（2026-05-08 加）
// ============================================================
// 仅 is_admin 用户可调；后端会 403 拒绝普通用户。

export interface AdminUserItem {
  id: string
  email: string
  name: string
  is_active: boolean
  is_admin: boolean
  created_at: string
  last_seen_at: string | null
  is_online: boolean
  invited_by_code: string | null
}

export interface AdminUserListResponse {
  items: AdminUserItem[]
  total: number
  page: number
  page_size: number
}

export interface AdminInvitationItem {
  id: string
  code: string
  note: string | null
  created_at: string
  expires_at: string | null
  used_at: string | null
  used_by_email?: string | null
}

export const adminApi = {
  listUsers: (params?: {
    search?: string
    status?: 'all' | 'online' | 'admin' | 'inactive'
    page?: number
    page_size?: number
  }) => api.get<AdminUserListResponse>('/api/admin/users', { params }),

  patchUser: (
    userId: string,
    patch: { is_admin?: boolean; is_active?: boolean; name?: string },
  ) => api.patch(`/api/admin/users/${userId}`, patch),

  deleteUser: (userId: string) => api.delete(`/api/admin/users/${userId}`),

  userStats: () => api.get('/api/admin/users/stats'),

  // 邀请码管理（V2 切回邀请码模式时用，当前为 admin 备用工具）
  listInvitations: (status: 'all' | 'unused' | 'used' | 'expired' = 'all') =>
    api.get<AdminInvitationItem[]>('/api/admin/invitations', {
      params: { status },
    }),

  createInvitations: (data: {
    count?: number
    note?: string | null
    expires_in_days?: number | null
  }) =>
    api.post<AdminInvitationItem[]>('/api/admin/invitations', {
      count: data.count ?? 1,
      note: data.note ?? null,
      expires_in_days: data.expires_in_days ?? null,
    }),

  deleteInvitation: (codeId: string) =>
    api.delete(`/api/admin/invitations/${codeId}`),

  invitationStats: () => api.get('/api/admin/invitations/stats'),
}

export const projectApi = {
  list: () => api.get('/api/projects'),
  create: (data: any) =>
    api.post('/api/projects', data),
  get: (id: string) => api.get(`/api/projects/${id}`),
  update: (id: string, data: any) => api.patch(`/api/projects/${id}`, data),
  delete: (id: string) => api.delete(`/api/projects/${id}`),
  // Staleness 软提示：进入项目时调一次。后端有 24h 去重 + 7 天 dismiss 静音，
  // 命中条件才会注入 stale_hint 富消息，所以前端可以安全 fire-and-forget。
  staleCheck: (id: string) =>
    api.post(`/api/projects/${id}/stale-check`),
  staleDismiss: (id: string) =>
    api.post(`/api/projects/${id}/stale-dismiss`),
}

// 通用客户端事件埋点。事件名必须在后端 services/telemetry.py:KNOWN_EVENTS
// 里登记，否则后端返回 422。失败时静默吞掉（埋点不能阻塞用户操作）。
export const telemetryApi = {
  emit: (event: string, projectId?: string, properties?: Record<string, any>) =>
    api.post('/api/telemetry', {
      event,
      project_id: projectId,
      properties,
    }).catch(() => undefined),
}

export const searchApi = {
  startRound: (projectId: string) =>
    api.post(`/api/projects/${projectId}/rounds/start`, undefined, { timeout: 120000 }),
  // prepareRound 内部要跑 QueryPlanAgent 的 agentic_plan loop（多次 LLM 调用）
  // + per-source 关键词优化（每源 1 次 LLM）+ 同义词生成。慢 LLM provider
  // 上累计可达 60s+，所以这里给 120s 上限避免 axios 默认 30s timeout 误报。
  prepareRound: (projectId: string) =>
    api.post(`/api/projects/${projectId}/rounds/prepare`, undefined, { timeout: 120000 }),
  confirmKeywords: (projectId: string, roundId: string, body: any) =>
    api.post(`/api/projects/${projectId}/rounds/${roundId}/confirm-keywords`, body, { timeout: 60000 }),
  getKeywordPlan: (projectId: string, roundId: string) =>
    api.get(`/api/projects/${projectId}/rounds/${roundId}/keyword-plan`),
  getRoundStatus: (projectId: string, roundId: string) =>
    api.get(`/api/projects/${projectId}/rounds/${roundId}/status`),
  getRoundResults: (projectId: string, roundId: string) =>
    api.get(`/api/projects/${projectId}/rounds/${roundId}/results`),
  listRounds: (projectId: string) =>
    api.get(`/api/projects/${projectId}/rounds`),
  // Per-document full-text download
  // format: 'pdf' | 'html' | 'auto' (default auto: PDF 优先，失败退 HTML)
  // force: 仅 patenthub 用 — 超出单轮 5 次 PDF 上限后，前端弹二次确认，用户确认即 force=true 绕过
  downloadFulltext: (
    projectId: string,
    documentId: string,
    format: 'pdf' | 'html' | 'auto' = 'auto',
    force = false,
  ) =>
    api.post(
      `/api/projects/${projectId}/documents/${documentId}/download-fulltext`,
      undefined,
      { params: { format, force } }
    ),
  // 查询单轮 PatentHub PDF 下载预算（前端按钮 tooltip 展示"本轮剩余 N/5 次"）
  getPatenthubBudget: (projectId: string, roundId: string) =>
    api.get<{ used: number; max: number; remaining: number; exhausted: boolean; round_id: string }>(
      `/api/projects/${projectId}/rounds/${roundId}/patenthub-budget`
    ),
  uploadFulltext: (projectId: string, documentId: string, file: File, format: 'pdf' | 'html' = 'pdf') => {
    const form = new FormData()
    form.append('file', file)
    return api.post(
      `/api/projects/${projectId}/documents/${documentId}/upload-fulltext`,
      form,
      {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 120000,
        params: { format },
      }
    )
  },
  regenerateAnalysis: (projectId: string, documentId: string, hint?: string) =>
    api.post(
      `/api/projects/${projectId}/documents/${documentId}/regenerate-analysis`,
      { hint: hint || null },
      { timeout: 120000 }
    ),
  updateDocument: (
    projectId: string,
    documentId: string,
    updates: { ai_summary?: string; ai_key_points?: string[]; ai_relevance_reason?: string; one_line_summary?: string }
  ) => api.patch(`/api/projects/${projectId}/documents/${documentId}`, updates),
  // 用户 Approve AI 卡片更新建议时调用。写 _ai 字段，不覆盖 _user（用户编辑始终优先）
  applyAiUpdate: (
    projectId: string,
    documentId: string,
    payload: { field: 'one_line_summary' | 'ai_summary' | 'ai_key_points'; new_value: any; reason?: string },
  ) => api.post(`/api/projects/${projectId}/documents/${documentId}/ai-apply-update`, payload),
  // Scoring config
  updateScoringConfig: (projectId: string, config: any) =>
    api.patch(`/api/projects/${projectId}/scoring-config`, config),
  // Finalize round (new: user-driven)
  finalizeRound: (projectId: string, roundId: string) =>
    api.post(`/api/projects/${projectId}/rounds/${roundId}/finalize`),
  // Answer Now: 触发快通道，worker 在下个 stage 边界用已有部分文献 LLM 合成 partial 答案 + 转 round.status='partial_complete'
  triggerAnswerNow: (projectId: string, roundId: string) =>
    api.post<{ accepted: boolean; current_stage: string; message: string }>(
      `/api/projects/${projectId}/rounds/${roundId}/answer-now`,
    ),
}

// P0.5：feedback submit response 携带 memory_update，客户端写本地多 .md + MEMORY.md 索引
export interface MemoryFileOut {
  filename: string
  type: string                 // identity / preference / reference / note
  name: string
  description: string
  body: string
}

export interface MemoryUpdateOut {
  version: number
  index_md: string
  files: MemoryFileOut[]
  focus: string
}

export interface FeedbackSubmitResponse {
  saved: number
  next_round_id: string | null
  next_round_number: number | null
  monitoring_activated: boolean
  message: string
  memory_update: MemoryUpdateOut | null
}

export const feedbackApi = {
  submit: (projectId: string, roundId: string, feedbacks: any[]) =>
    api.post<FeedbackSubmitResponse>(
      `/api/projects/${projectId}/rounds/${roundId}/feedback`,
      { feedbacks },
    ),
}

// 首页产品反馈（bug / 建议 / 其他）— 与上面的文献相关性反馈不同
export interface SiteFeedbackItem {
  id: string
  user_id: string | null
  user_email: string | null
  category: 'bug' | 'suggestion' | 'praise' | 'other'
  content: string
  contact: string | null
  page_url: string | null
  user_agent: string | null
  status: 'open' | 'triaged' | 'resolved' | 'wontfix'
  admin_note: string | null
  created_at: string
  updated_at: string
}

export const siteFeedbackApi = {
  submit: (data: {
    category: string
    content: string
    contact?: string | null
    page_url?: string | null
  }) => api.post<SiteFeedbackItem>('/api/site-feedback', data),

  adminList: (params?: {
    status?: string
    category?: string
    limit?: number
    offset?: number
  }) => api.get<{ total: number; items: SiteFeedbackItem[] }>(
    '/api/site-feedback/admin', { params },
  ),

  adminUpdate: (id: string, patch: { status?: string; admin_note?: string }) =>
    api.patch<SiteFeedbackItem>(`/api/site-feedback/admin/${id}`, patch),
}

export const bucketApi = {
  classify: (projectId: string, docId: string, data: { bucket: string; reason?: string }) =>
    api.put(`/api/projects/${projectId}/documents/${docId}/classify`, data),
  move: (projectId: string, docId: string, data: { to_bucket: string }) =>
    api.put(`/api/projects/${projectId}/documents/${docId}/move`, data),
  unclassify: (projectId: string, docId: string) =>
    api.delete(`/api/projects/${projectId}/documents/${docId}/classify`),
  getBuckets: (projectId: string) =>
    api.get(`/api/projects/${projectId}/buckets`),
}

export const monitorApi = {
  enable: (projectId: string, data?: { schedule?: string; search_config?: any }) =>
    api.post(`/api/projects/${projectId}/monitoring/enable`, data || {}),
  disable: (projectId: string) =>
    api.post(`/api/projects/${projectId}/monitoring/disable`),
  get: (projectId: string) =>
    api.get(`/api/projects/${projectId}/monitoring`),
  update: (projectId: string, data: any) =>
    api.patch(`/api/projects/${projectId}/monitoring`, data),
  getResults: (projectId: string) =>
    api.get(`/api/projects/${projectId}/monitoring/results`),
  // Phase 3.4: Push system
  getPushes: (projectId: string) =>
    api.get(`/api/projects/${projectId}/monitoring/pushes`),
  classifyPush: (projectId: string, pushId: string, data: { bucket: string }) =>
    api.post(`/api/projects/${projectId}/monitoring/pushes/${pushId}/classify`, data),
  dismissPush: (projectId: string, pushId: string) =>
    api.post(`/api/projects/${projectId}/monitoring/pushes/${pushId}/dismiss`),
  clearPushes: (projectId: string) =>
    api.post(`/api/projects/${projectId}/monitoring/pushes/clear`),
}

export const sseApi = {
  // 异步：从 keychain 取 token 拼 SSE URL（dead code 兼容；所有 SSE 路径
  // 实际改用 useSSE composable 走 useAuthStore().token）
  getRoundStreamUrl: async (roundId: string) => {
    const token = await secureGet(SECURE_KEYS.ACCESS_TOKEN)
    const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
    return `${baseUrl}/api/stream/rounds/${roundId}?token=${token ?? ''}`
  }
}

export const conversationApi = {
  start: (data?: { project_id?: string }) =>
    api.post('/api/conversation/start', data || {}),
  getSession: (sessionId: string) =>
    api.get(`/api/conversation/${sessionId}`),
  sendMessage: (sessionId: string, content: string) =>
    api.post(`/api/conversation/${sessionId}/message`, { content }),
  confirm: (sessionId: string, data: {
    confirmation_id: string
    action: string
    supplement_text?: string
    edits?: Record<string, any>
    search_mode?: string
  }) =>
    api.post(`/api/conversation/${sessionId}/confirm`, data),
  getByProject: (projectId: string) =>
    api.get(`/api/conversation/by-project/${projectId}`),
}

export const collaborationApi = {
  start: (sessionId: string, docIds: string[]) =>
    api.post(`/api/conversation/${sessionId}/collaboration/start`, { doc_ids: docIds }),
  // 协作问答走 plan → [可能] LLM respond；带全文 + KG + 笔记 + retry，DeepSeek 常需 60s+
  question: (sessionId: string, question: string) =>
    api.post(`/api/conversation/${sessionId}/collaboration/question`, { question }, { timeout: 180000 }),
  updateDocs: (sessionId: string, action: 'add' | 'remove' | 'replace', docIds: string[]) =>
    api.post(`/api/conversation/${sessionId}/collaboration/update-docs`, { action, doc_ids: docIds }),
  exit: (sessionId: string, archive: boolean) =>
    api.post(`/api/conversation/${sessionId}/collaboration/exit`, { archive }),
  refresh: (sessionId: string) =>
    api.post(`/api/conversation/${sessionId}/collaboration/refresh`),
  regenerateDocAnalysis: (projectId: string, docId: string, hint?: string) =>
    api.post(`/api/projects/${projectId}/documents/${docId}/regenerate-analysis`, { hint }),
  suggestScope: (sessionId: string) =>
    api.post(`/api/conversation/${sessionId}/collaboration/suggest-scope`),
  // 共享研究笔记（AI 可写 / 用户可编辑）
  getNote: (sessionId: string) =>
    api.get<{ content: string; updated_at: string | null; updated_by: 'ai' | 'user' | null }>(
      `/api/conversation/${sessionId}/collaboration/note`,
    ),
  saveNote: (sessionId: string, content: string) =>
    api.put<{ content: string; updated_at: string; updated_by: 'user' }>(
      `/api/conversation/${sessionId}/collaboration/note`,
      { content },
    ),
  // vibe ReadPlan：用户确认 picks + kg_queries + 探针节选勾选后续跑 Stage 2
  // selectedExcerptKeys: 形如 ["docid:0", "docid:3"]；null=默认全选；[]=一个都不用
  resumePlan: (
    sessionId: string,
    picks: Array<{ doc_id: string; reason?: string }>,
    kgQueries: Array<{ entity: string; entity_id?: string; node_type?: string; reason?: string }>,
    autoFromNow: boolean,
    selectedExcerptKeys: string[] | null = null,
  ) =>
    api.post(
      `/api/conversation/${sessionId}/collaboration/resume`,
      {
        picks,
        kg_queries: kgQueries,
        auto_from_now: autoFromNow,
        selected_excerpt_keys: selectedExcerptKeys,
      },
      { timeout: 180000 },  // full-text 注入 + LLM retry 可能 >1 分钟
    ),
}

export const featuresApi = {
  checkAll: (projectId: string) =>
    api.get(`/api/projects/${projectId}/features/check-all`),
  trigger: (projectId: string, feature: string, sessionId: string) =>
    api.post(`/api/projects/${projectId}/features/trigger`, {
      feature,
      session_id: sessionId,
    }),
  exitSession: (sessionId: string) =>
    api.post(`/api/conversation/sessions/${sessionId}/exit`),
  resetForNewRound: (sessionId: string) =>
    api.post(`/api/conversation/sessions/${sessionId}/reset-for-new-round`),
}

export const llmApi = {
  listProviders: () => api.get('/api/llm/providers'),
  configureProvider: (data: any) => api.post('/api/llm/configure', data),
  switchProvider: (providerId: string) => api.post(`/api/llm/switch/${providerId}`),
  testProvider: () => api.get('/api/llm/test'),
  deleteProvider: (providerId: string) => api.delete(`/api/llm/${providerId}`),
}

// ============================================================
// Library API —— 文献库 markdown workspace
// ============================================================

export interface LibraryFile {
  slug: string
  title: string
  title_zh?: string | null
  authors_short: string
  year?: number | null
  bucket?: string | null
  quality_score?: number | null
  updated_at?: string | null
  extract_status?: string | null
  // P1: 卡片操作按钮所需字段
  document_id?: string | null
  source?: string | null
  external_id?: string | null
  doi?: string | null
  url?: string | null
  pdf_url?: string | null
}

export interface LibraryListResponse {
  total: number
  by_bucket: Record<string, number>
  files: LibraryFile[]
}

export interface LibraryDetailResponse {
  slug: string
  frontmatter: Record<string, any>
  body_md: string
  raw: string
}

export interface LibraryRebuildResponse {
  status: string
  task_id?: string
}

export const libraryApi = {
  list: (projectId: string) =>
    api.get<LibraryListResponse>(`/api/projects/${projectId}/library`),

  detail: (projectId: string, slug: string) =>
    api.get<LibraryDetailResponse>(
      `/api/projects/${projectId}/library/${slug}`
    ),

  raw: (projectId: string, slug: string) =>
    api.get<string>(`/api/projects/${projectId}/library/${slug}/raw`, {
      responseType: 'text',
    }),

  rebuild: (projectId: string) =>
    api.post<LibraryRebuildResponse>(
      `/api/projects/${projectId}/library/rebuild`
    ),

  // P1: 批量删除（仅从当前项目移除，保留 global Document）
  deleteBatch: (projectId: string, slugs: string[]) =>
    api.post<{ deleted: number; failed: string[]; remaining_total: number }>(
      `/api/projects/${projectId}/library/delete-batch`,
      { slugs },
    ),
}

export const documentApi = {
  get: (documentId: string) => api.get(`/api/documents/${documentId}`),
}

// ============================================================
// Notebook API —— 项目级笔记本（多 page，AI 可决策更新哪页）
// ============================================================

export interface NotebookPage {
  id: string
  title: string
  body_md: string
  sort_order: number
  updated_at: string | null
  updated_by: 'ai' | 'user' | null
  created_at: string | null
}

export const notebookApi = {
  listPages: (projectId: string) =>
    api.get<{ pages: NotebookPage[] }>(`/api/projects/${projectId}/notebook/pages`),
  createPage: (projectId: string, data: { title?: string; body_md?: string }) =>
    api.post<NotebookPage>(`/api/projects/${projectId}/notebook/pages`, data),
  getPage: (projectId: string, pageId: string) =>
    api.get<NotebookPage>(`/api/projects/${projectId}/notebook/pages/${pageId}`),
  updatePage: (projectId: string, pageId: string, data: { title?: string; body_md?: string }) =>
    api.put<NotebookPage>(`/api/projects/${projectId}/notebook/pages/${pageId}`, data),
  deletePage: (projectId: string, pageId: string) =>
    api.delete(`/api/projects/${projectId}/notebook/pages/${pageId}`),
  reorderPage: (projectId: string, pageId: string, sortOrder: number) =>
    api.post(
      `/api/projects/${projectId}/notebook/pages/${pageId}/reorder`,
      { sort_order: sortOrder },
    ),
}

export const uploadApi = {
  importPdf: (
    projectId: string,
    sessionId: string,
    file: File,
    onProgress?: (pct: number) => void,
  ) => {
    const form = new FormData()
    form.append('file', file)
    form.append('session_id', sessionId)
    return api.post(
      `/api/projects/${projectId}/documents/import-pdf`,
      form,
      {
        timeout: 120000,
        onUploadProgress: (e) => {
          if (onProgress && e.total) {
            onProgress(Math.round((e.loaded / e.total) * 100))
          }
        },
      },
    )
  },
  confirmImport: (documentId: string, payload: any) =>
    api.put(`/api/documents/${documentId}/import-confirm`, payload),
  cancelImport: (jobId: string) =>
    api.post(`/api/documents/import-jobs/${jobId}/cancel`),
}

// C1: Skills API — harness skill registry 的 list / run 入口
export const skillsApi = {
  list: (currentRound: number = 1) =>
    api.get(`/api/skills`, { params: { current_round: currentRound } }),
  run: (projectId: string, skillId: string, documentId?: string) =>
    api.post(
      `/api/skills/${projectId}/${skillId}/run`,
      documentId ? { document_id: documentId } : {},
      { timeout: 60_000 },
    ),
}

// ============================================================
// Notifications API —— 用户绑定的推送通道（飞书/Server酱/邮件/Telegram）
// 调研 wiki: notification-channels-china.md
// ============================================================

export interface NotificationChannelMeta {
  channel_id: 'feishu' | 'serverchan' | 'email' | 'telegram'
  display_name: string
  config_kind: 'webhook' | 'email' | 'telegram'
}

export interface NotificationSetting {
  id: string
  channel: 'feishu' | 'serverchan' | 'email' | 'telegram'
  // 脱敏后的 view（webhook/key 都会 mask）
  config: Record<string, any>
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface NotificationTestResult {
  ok: boolean
  message: string
  channel: string
  response_body?: string | null
}

export const notificationsApi = {
  // 平台可用的所有通道（前端绑定 UI 选项）
  listChannels: () =>
    api.get<NotificationChannelMeta[]>('/api/users/me/notifications/channels'),

  // 当前用户已配的通道
  list: () =>
    api.get<NotificationSetting[]>('/api/users/me/notifications'),

  // 新建/更新（user × channel 唯一）；config 字段是明文 webhook URL / send_key 等
  upsert: (data: {
    channel: NotificationChannelMeta['channel_id']
    config: Record<string, any>
    is_active?: boolean
  }) => api.post<NotificationSetting>('/api/users/me/notifications', data),

  toggle: (channel: string, is_active: boolean) =>
    api.post<NotificationSetting>(
      `/api/users/me/notifications/${channel}/toggle`,
      { is_active },
    ),

  remove: (channel: string) =>
    api.delete(`/api/users/me/notifications/${channel}`),

  // 不持久化的测试发送（用于"测试连接"按钮）
  test: (data: {
    channel: NotificationChannelMeta['channel_id']
    config: Record<string, any>
    title?: string
    body?: string
  }) =>
    api.post<NotificationTestResult>(
      '/api/users/me/notifications/test',
      data,
      { timeout: 30_000 },
    ),
}

// 0028: PDF 多设备 ownership API（spec docs/spec-pdf-ownership-sync.md）
export interface OwnedDocumentDto {
  document_id: string
  project_id: string
  source: 'downloaded' | 'uploaded_local' | 'uploaded_synced'
  format: 'pdf' | 'html'
  owned_at: string
  last_seen_at: string
}

export const userDocsApi = {
  listOwned: (projectId?: string, format?: 'pdf' | 'html') =>
    api.get<{ items: OwnedDocumentDto[] }>('/api/users/me/documents', {
      params: { project_id: projectId, format },
    }),
  markOwn: (
    projectId: string,
    documentId: string,
    payload: {
      source: 'downloaded' | 'uploaded_local' | 'uploaded_synced'
      format: 'pdf' | 'html'
    },
  ) =>
    api.post<{
      document_id: string
      project_id: string
      source: string
      format: string
      owned_at: string
      last_seen_at: string
      created: boolean
    }>(`/api/projects/${projectId}/documents/${documentId}/own`, payload),
  markUnown: (
    projectId: string,
    documentId: string,
    format: 'pdf' | 'html' = 'pdf',
  ) =>
    api.delete<{ removed: boolean }>(
      `/api/projects/${projectId}/documents/${documentId}/own`,
      { params: { format } },
    ),
}
