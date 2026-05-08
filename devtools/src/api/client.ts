import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_BASE || ''

const client = axios.create({
  baseURL: BASE_URL,
  timeout: 15_000,
})

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('devtools_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

/* ─── Auth ─── */

export function login(email: string, password: string) {
  return client.post<{ access_token: string; token_type: string }>(
    '/api/auth/login',
    { email, password },
  )
}

export function getMe() {
  return client.get<{
    id: string
    email: string
    name: string
    is_active: boolean
    is_admin: boolean
  }>('/api/auth/me')
}

/* ─── DevTools Logs ─── */

export interface LogQueryParams {
  level?: string
  source?: string
  category?: string
  search?: string
  round_id?: string
  from_ts?: string
  to_ts?: string
  page?: number
  page_size?: number
}

export interface LogEntry {
  id: number
  created_at: string
  level: string
  source: string
  category?: string
  message: string
  context?: Record<string, unknown>
  round_id?: string
  project_id?: string
  duration_ms?: number
  error_trace?: string
}

export interface PagedLogs {
  items: LogEntry[]
  total: number
  page: number
  page_size: number
}

export function getLogs(params: LogQueryParams) {
  return client.get<PagedLogs>('/api/devtools/logs', { params })
}

export interface StatsData {
  error_count: number
  request_count: number
  llm_count: number
  celery_count: number
  total_count: number
  avg_request_ms: number
  sparkline: Array<{ time: string; count: number }>
}

export function getStats() {
  return client.get<StatsData>('/api/devtools/stats')
}

export interface SourceLatency {
  source: string
  bucket: string | null
  avg_ms: number
  call_count: number
  error_count: number
}

export function getSources() {
  return client.get<SourceLatency[]>('/api/devtools/sources')
}

export interface LogTreeData {
  [source: string]: {
    total: number
    levels: Record<string, number>
    categories: {
      [cat: string]: {
        total: number
        levels: Record<string, number>
      }
    }
  }
}

export function getLogTree() {
  return client.get<LogTreeData>('/api/devtools/log-tree')
}

export function deleteLogs(beforeHours: number = 0) {
  return client.delete<{ deleted: number }>('/api/devtools/logs', { params: { before_hours: beforeHours } })
}

/* ─── Source Registry & Testing ─── */

export interface SourceCredentialInfo {
  required: string[]
  configured: Record<string, string>
}

export interface SourceStats {
  total_invocations: number
  successful_invocations: number
  avg_latency_ms: number
  reliability: number
}

export interface SourceInfo {
  source_id: string
  name: string
  description: string
  doc_type: string
  category: string
  language: string
  phase: number
  enabled: boolean
  has_fetcher: boolean
  credentials: SourceCredentialInfo
  stats: SourceStats
  proxy: string
}

export interface SourceTestParams {
  source_id: string
  query: string
  max_results?: number
  year_from?: number | null
  year_to?: number | null
  language?: string | null
}

export interface SourceTestResult {
  source_id: string
  status: string
  count: number
  elapsed_ms: number
  results: any[]
  error: string | null
  error_trace: string | null
}

export function getSourceRegistry() {
  return client.get<{ sources: SourceInfo[]; global_proxy: string }>('/api/devtools/source-registry')
}

export function testSource(params: SourceTestParams) {
  return client.post<SourceTestResult>('/api/devtools/source-test', params, {
    timeout: 60_000,
  })
}

export function updateSourceConfig(
  sourceId: string,
  config: { enabled?: boolean; credentials?: Record<string, string>; proxy?: string; global_proxy?: string },
) {
  return client.patch(`/api/devtools/source-config/${sourceId}`, config)
}

export function resetSourceStats(sourceId: string) {
  return client.post(`/api/devtools/source-registry/${sourceId}/reset-stats`)
}

/* ─── Local Knowledge Base ─── */

export interface KBStats {
  available: boolean
  message?: string
  total_works?: number
  fts_indexed?: number
  citation_count?: number
  by_year?: Array<{ publication_year: number; count: number }>
  by_language?: Array<{ language: string; count: number }>
  by_type?: Array<{ type: string; count: number }>
  by_domain?: Array<{ primary_domain_name: string; count: number }>
  top_topics?: Array<{ primary_topic_name: string; count: number }>
  file_sizes?: Record<string, number>
  sync_state?: Record<string, any>
}

export function getKBStats() {
  return client.get<KBStats>('/api/devtools/kb/stats')
}

/* ─── Users (Admin) ─── */

export interface UserInfo {
  id: string
  email: string
  name: string
  is_active: boolean
  is_admin: boolean
  created_at: string
  last_seen_at?: string | null
  is_online: boolean
  project_count: number
  invited_by_code?: string | null
}

export interface PagedUsers {
  items: UserInfo[]
  total: number
  page: number
  page_size: number
}

export interface UserListParams {
  search?: string
  status?: 'all' | 'online' | 'admin' | 'inactive'
  page?: number
  page_size?: number
}

export function listUsers(params: UserListParams = {}) {
  return client.get<PagedUsers>('/api/admin/users', { params })
}

export interface UserStats {
  total: number
  admins: number
  inactive: number
  new_today: number
  online: number
}

export function getUserStats() {
  return client.get<UserStats>('/api/admin/users/stats')
}

export function updateUser(
  userId: string,
  patch: { is_admin?: boolean; is_active?: boolean; name?: string },
) {
  return client.patch<UserInfo>(`/api/admin/users/${userId}`, patch)
}

export function deleteUser(userId: string) {
  return client.delete(`/api/admin/users/${userId}`)
}

export interface UserActivityPayload {
  user: {
    id: string
    email: string
    name: string
    is_admin: boolean
    is_active: boolean
    created_at?: string
  }
  recent_projects: Array<{ id: string; title: string; domain?: string; created_at?: string; current_round: number }>
  recent_sessions: Array<{
    id: string
    project_id?: string | null
    current_state?: string | null
    created_at?: string
    last_activity_at?: string | null
  }>
  recent_logs: Array<{
    id: number
    created_at?: string
    level: string
    source: string
    category?: string
    message: string
    duration_ms?: number | null
    project_id?: string | null
  }>
  stats: { total_projects: number; total_sessions: number; log_events: number; errors: number }
  partial_errors?: string[]
}

export function getUserActivity(userId: string, days = 7) {
  return client.get<UserActivityPayload>(`/api/admin/users/${userId}/activity`, { params: { days } })
}

/* ─── Invitations (Admin) ─── */

export interface Invitation {
  id: string
  code: string
  note: string | null
  created_at: string
  expires_at: string | null
  used_at: string | null
  used_by_email: string | null
}

export type InvitationStatusFilter = 'all' | 'unused' | 'used' | 'expired'

export function listInvitations(status: InvitationStatusFilter = 'all') {
  return client.get<Invitation[]>('/api/admin/invitations', { params: { status } })
}

export function createInvitations(
  count: number,
  note?: string,
  expiresInDays?: number,
) {
  return client.post<Invitation[]>('/api/admin/invitations', {
    count,
    note: note || null,
    expires_in_days: expiresInDays ?? null,
  })
}

export function deleteInvitation(codeId: string) {
  return client.delete(`/api/admin/invitations/${codeId}`)
}

export interface InvitationStats {
  total: number
  used: number
  expired: number
  available: number
}

export function getInvitationStats() {
  return client.get<InvitationStats>('/api/admin/invitations/stats')
}

/* ─── Telemetry (stale_hint funnel) ─── */

export interface TelemetryDayStat {
  date: string
  impr: number
  click: number
  dismiss: number
  ignore: number
  ctr: number
  dismiss_rate: number
  ignore_rate: number
}

export interface TelemetryEvent {
  ts: string
  event: string
  user_id?: string
  project_id?: string
  days_ago?: number
  threshold?: number
  mute_days?: number
  [key: string]: any
}

export interface TelemetryResponse {
  available: boolean
  path: string
  window_days: number
  total_events: number
  by_day: TelemetryDayStat[]
  recent_events: TelemetryEvent[]
}

export function getTelemetry(days = 14, recent = 50) {
  return client.get<TelemetryResponse>('/api/devtools/telemetry', {
    params: { days, recent },
  })
}

// ──────────────── M3 F1: cleanup expired rounds ────────────────

export interface CleanupPreview {
  expired_count: number
  has_ttl_count: number
  total_rounds: number
  auto_schedule_enabled: boolean
  auto_schedule_note: string
  now_utc: string
}

export function getCleanupPreview() {
  return client.get<CleanupPreview>('/api/devtools/cleanup-rounds/preview')
}

export function runCleanupRounds() {
  return client.post<{ deleted: number; triggered_by: string }>(
    '/api/devtools/cleanup-rounds/run',
  )
}

export default client
