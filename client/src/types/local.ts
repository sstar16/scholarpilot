// 本地 SQLite 行类型 — 对应 migrations/v1_initial.sql 各表 schema
// 命名约定：
// - 列类型 INTEGER (unix-ms) → TS number
// - 列类型 TEXT JSON → TS 已 parse 后的对象/数组（repo 层 transparent 解析）
// - 数组 / 字典字段命名带 _json 后缀的，TS 类型已经是 parse 后的 native，但保留 _json 命名以提示来自 JSON 列

export interface LocalProject {
  id: string
  title: string
  description: string
  domain: string
  domains: string[] | null
  search_config: Record<string, unknown> | null
  current_round: number
  max_rounds: number
  status: 'active' | 'monitoring' | 'archived'
  research_note_md: string
  research_note_updated_at: number | null
  research_note_updated_by: 'user' | 'ai' | null
  created_at: number
  updated_at: number
  last_synced_at: number | null
}

export interface LocalRound {
  id: string
  project_id: string
  round_number: number
  status: string
  time_horizon_years: number | null
  max_results: number
  language_scope: string
  sources_used: string[] | null
  search_queries: Record<string, unknown> | null
  total_candidates: number
  selected_count: number
  source_stats: Record<string, unknown> | null
  progress: number
  progress_message: string
  started_at: number | null
  completed_at: number | null
  cancelled_reason: string | null
  cancelled_at: number | null
  partial_answer: Record<string, unknown> | null
  partial_completed_at: number | null
  created_at: number
  last_synced_at: number | null
}

export interface LocalDocument {
  id: string
  source: string
  external_id: string
  doc_type: string
  title: string
  title_zh: string | null
  authors: string | null
  abstract: string | null
  publication_date: string | null
  url: string | null
  doi: string | null
  journal: string | null
  citation_count: number
  pdf_url: string | null
  fulltext_status: string
  fulltext_path: string | null
  fulltext_pdf_path: string | null
  fulltext_pdf_status: string
  fulltext_html_path: string | null
  fulltext_html_status: string
  fulltext_text: string | null
  pdf_local_path: string | null
  html_local_path: string | null
  fulltext_local_path: string | null
  ai_summary: string | null
  ai_key_points: string[] | null
  ai_relevance_reason: string | null
  ai_summary_source: string
  ai_summary_user: string | null
  ai_key_points_user: string[] | null
  countries: string[] | null
  quality_score: number | null
  one_line_summary: string | null
  one_line_summary_user: string | null
  concept_tags: string[] | null
  probe_cache: unknown[] | null
  content_hash: string | null
  import_source: string
  imported_at: number | null
  created_at: number
  last_synced_at: number | null
}

export interface LocalRoundDocument {
  id: string
  round_id: string
  document_id: string
  rank_in_round: number | null
  initial_score: number | null
  agent_score: number | null
  agent_rationale: string | null
  one_line_summary: string | null
  below_cutoff: boolean
}

export interface LocalDocumentClassification {
  project_id: string
  document_id: string
  bucket: 'very_relevant' | 'relevant' | 'uncertain' | 'irrelevant'
  reason: string | null
  classified_at: number
  last_synced_at: number | null
}

export interface LocalConversationSession {
  id: string
  project_id: string | null
  current_state: string
  state_data: Record<string, unknown> | null
  search_mode: string | null
  is_active: boolean
  created_at: number
  updated_at: number
  last_synced_at: number | null
}

export interface LocalMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'system'
  content_md: string
  rich_data: Record<string, unknown> | null
  created_at: number
  seq: number
}

export interface LocalNotebookPage {
  id: string
  project_id: string
  title: string
  body_md: string
  sort_order: number
  updated_at: number
  updated_by: 'user' | 'ai' | null
  created_at: number
  last_synced_at: number | null
}

export interface LocalSyncState {
  entity_type: string
  entity_id: string
  local_version: number
  remote_version: number
  last_synced_at: number | null
  dirty: boolean
}

export interface LocalSetting {
  key: string
  value: string
  updated_at: number
}
