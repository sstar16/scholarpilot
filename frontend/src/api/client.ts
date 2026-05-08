import axios from 'axios'
import { ElMessage } from 'element-plus'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 30000,
})

// 自动注入 JWT
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('urip_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 同一条错误 toast 在短时间内只弹一次（避免 fallback / retry 重复触发）
const _toastDedupe = new Map<string, number>()
function _toastOnce(key: string, fire: () => void, ttlMs = 2500) {
  const now = Date.now()
  const last = _toastDedupe.get(key) || 0
  if (now - last < ttlMs) return
  _toastDedupe.set(key, now)
  fire()
}

// 401 自动跳转登录；409 模式互斥冲突弹小猫提示
api.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err.response?.status
    if (status === 401) {
      localStorage.removeItem('urip_token')
      window.location.href = '/login'
    } else if (status === 409) {
      const detail = err.response?.data?.detail
      // detail 是字符串 → 通用互斥提示；detail 是 object → 交给业务层处理（如 pending round 流程）
      if (typeof detail === 'string' && detail) {
        _toastOnce(`409:${detail}`, () =>
          ElMessage.warning({ message: detail, duration: 4500, showClose: true })
        )
        ;(err as any).__handledByInterceptor = true
      }
    }
    return Promise.reject(err)
  }
)

export default api

export const authApi = {
  register: (data: { email: string; name: string; password: string; invitation_code: string }) =>
    api.post('/api/auth/register', data),
  login: (data: { email: string; password: string }) =>
    api.post('/api/auth/login', data),
  me: () => api.get('/api/auth/me'),
}

export const memoryApi = {
  getUser: () => api.get('/api/memory/user'),
  putUser: (markdown_text: string) => api.put('/api/memory/user', { markdown_text }),
  refineUserFromChat: () =>
    api.post('/api/memory/user/extract-from-chat', undefined, { timeout: 90000 }),
  getProject: (projectId: string) => api.get(`/api/memory/project/${projectId}`),
  getProjectRecipe: (projectId: string) => api.get(`/api/memory/project/${projectId}/recipe`),
  regenerateProjectRecipe: (projectId: string) =>
    api.post(`/api/memory/project/${projectId}/recipe/regenerate`),
  putProject: (projectId: string, markdown_text: string) =>
    api.put(`/api/memory/project/${projectId}`, { markdown_text }),
  refineProjectFromChat: (projectId: string) =>
    api.post(`/api/memory/project/${projectId}/extract-from-chat`, undefined, { timeout: 90000 }),
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

export const feedbackApi = {
  submit: (projectId: string, roundId: string, feedbacks: any[]) =>
    api.post(`/api/projects/${projectId}/rounds/${roundId}/feedback`, { feedbacks }),
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
  getRoundStreamUrl: (roundId: string) => {
    const token = localStorage.getItem('urip_token')
    const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
    return `${baseUrl}/api/stream/rounds/${roundId}?token=${token}`
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
