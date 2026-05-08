/**
 * 公共测试工具 —— 给 stores/__tests__ 下的所有 spec 共享：
 *   - mkBetterSqliteHandle()：构造 better-sqlite3 in-memory DbHandle，建好 v1 + v2 schema
 *   - 各种 mkXxx() 工厂：构造 LocalProject / LocalRound / LocalDocument / 等
 *
 * 跑 v1_initial.sql 直接读硬盘原文，保证和 prod 一致。
 */
import fs from 'fs'
import path from 'path'

import Database from 'better-sqlite3'

import type { DbHandle } from '@/data/sqlite/schema'
import type {
  LocalConversationSession,
  LocalDocument,
  LocalNotebookPage,
  LocalProject,
  LocalRound,
} from '@/types/local'

const _MIGRATION_DIR = path.resolve(__dirname, '../../../src-tauri/migrations')

function _readMigration(name: string): string {
  return fs.readFileSync(path.join(_MIGRATION_DIR, name), 'utf-8')
}

export function mkBetterSqliteHandle(): DbHandle & { _raw: Database.Database } {
  const raw = new Database(':memory:')
  raw.exec(_readMigration('v1_initial.sql'))
  raw.exec(_readMigration('v2_llm_run_jobs.sql'))
  return {
    _raw: raw,
    async select<T = unknown>(sql: string, bindings: unknown[] = []): Promise<T[]> {
      const stmt = raw.prepare(sql)
      return stmt.all(...bindings) as T[]
    },
    async execute(sql: string, bindings: unknown[] = []) {
      const stmt = raw.prepare(sql)
      const r = stmt.run(...bindings)
      return { rowsAffected: r.changes, lastInsertId: Number(r.lastInsertRowid) }
    },
    async close() {
      raw.close()
    },
  }
}

export function mkProject(id: string, overrides: Partial<LocalProject> = {}): LocalProject {
  const now = Date.now()
  return {
    id,
    title: overrides.title ?? `Project ${id}`,
    description: overrides.description ?? '',
    domain: overrides.domain ?? 'other',
    domains: overrides.domains ?? null,
    search_config: overrides.search_config ?? null,
    current_round: overrides.current_round ?? 0,
    max_rounds: overrides.max_rounds ?? 0,
    status: overrides.status ?? 'active',
    research_note_md: overrides.research_note_md ?? '',
    research_note_updated_at: overrides.research_note_updated_at ?? null,
    research_note_updated_by: overrides.research_note_updated_by ?? null,
    created_at: overrides.created_at ?? now,
    updated_at: overrides.updated_at ?? now,
    last_synced_at: overrides.last_synced_at ?? null,
  }
}

export function mkRound(
  id: string,
  projectId: string,
  overrides: Partial<LocalRound> = {},
): LocalRound {
  return {
    id,
    project_id: projectId,
    round_number: overrides.round_number ?? 1,
    status: overrides.status ?? 'pending',
    time_horizon_years: overrides.time_horizon_years ?? null,
    max_results: overrides.max_results ?? 10,
    language_scope: overrides.language_scope ?? 'international',
    sources_used: overrides.sources_used ?? null,
    search_queries: overrides.search_queries ?? null,
    total_candidates: overrides.total_candidates ?? 0,
    selected_count: overrides.selected_count ?? 0,
    source_stats: overrides.source_stats ?? null,
    progress: overrides.progress ?? 0,
    progress_message: overrides.progress_message ?? '',
    started_at: overrides.started_at ?? null,
    completed_at: overrides.completed_at ?? null,
    cancelled_reason: overrides.cancelled_reason ?? null,
    cancelled_at: overrides.cancelled_at ?? null,
    partial_answer: overrides.partial_answer ?? null,
    partial_completed_at: overrides.partial_completed_at ?? null,
    created_at: overrides.created_at ?? Date.now(),
    last_synced_at: overrides.last_synced_at ?? null,
  }
}

export function mkDoc(id: string, overrides: Partial<LocalDocument> = {}): LocalDocument {
  const now = Date.now()
  return {
    id,
    source: overrides.source ?? 'arxiv',
    external_id: overrides.external_id ?? id,
    doc_type: overrides.doc_type ?? 'paper',
    title: overrides.title ?? `Doc ${id}`,
    title_zh: overrides.title_zh ?? null,
    authors: overrides.authors ?? 'Author X',
    abstract: overrides.abstract ?? null,
    publication_date: overrides.publication_date ?? '2024-01-01',
    url: overrides.url ?? null,
    doi: overrides.doi ?? null,
    journal: overrides.journal ?? null,
    citation_count: overrides.citation_count ?? 0,
    pdf_url: overrides.pdf_url ?? null,
    fulltext_status: overrides.fulltext_status ?? 'not_attempted',
    fulltext_path: overrides.fulltext_path ?? null,
    fulltext_pdf_path: overrides.fulltext_pdf_path ?? null,
    fulltext_pdf_status: overrides.fulltext_pdf_status ?? 'not_attempted',
    fulltext_html_path: overrides.fulltext_html_path ?? null,
    fulltext_html_status: overrides.fulltext_html_status ?? 'not_attempted',
    fulltext_text: overrides.fulltext_text ?? null,
    pdf_local_path: overrides.pdf_local_path ?? null,
    html_local_path: overrides.html_local_path ?? null,
    fulltext_local_path: overrides.fulltext_local_path ?? null,
    ai_summary: overrides.ai_summary ?? null,
    ai_key_points: overrides.ai_key_points ?? null,
    ai_relevance_reason: overrides.ai_relevance_reason ?? null,
    ai_summary_source: overrides.ai_summary_source ?? 'not_generated',
    ai_summary_user: overrides.ai_summary_user ?? null,
    ai_key_points_user: overrides.ai_key_points_user ?? null,
    countries: overrides.countries ?? null,
    quality_score: overrides.quality_score ?? null,
    one_line_summary: overrides.one_line_summary ?? null,
    one_line_summary_user: overrides.one_line_summary_user ?? null,
    concept_tags: overrides.concept_tags ?? null,
    probe_cache: overrides.probe_cache ?? null,
    content_hash: overrides.content_hash ?? null,
    import_source: overrides.import_source ?? 'search',
    imported_at: overrides.imported_at ?? null,
    created_at: overrides.created_at ?? now,
    last_synced_at: overrides.last_synced_at ?? null,
  }
}

export function mkSession(
  id: string,
  projectId: string | null,
  overrides: Partial<LocalConversationSession> = {},
): LocalConversationSession {
  const now = Date.now()
  return {
    id,
    project_id: projectId,
    current_state: overrides.current_state ?? 'idle',
    state_data: overrides.state_data ?? null,
    search_mode: overrides.search_mode ?? null,
    is_active: overrides.is_active ?? true,
    created_at: overrides.created_at ?? now,
    updated_at: overrides.updated_at ?? now,
    last_synced_at: overrides.last_synced_at ?? null,
  }
}

export function mkNotebookPage(
  id: string,
  projectId: string,
  overrides: Partial<LocalNotebookPage> = {},
): LocalNotebookPage {
  const now = Date.now()
  return {
    id,
    project_id: projectId,
    title: overrides.title ?? '未命名页',
    body_md: overrides.body_md ?? '',
    sort_order: overrides.sort_order ?? 0,
    updated_at: overrides.updated_at ?? now,
    updated_by: overrides.updated_by ?? null,
    created_at: overrides.created_at ?? now,
    last_synced_at: overrides.last_synced_at ?? null,
  }
}
