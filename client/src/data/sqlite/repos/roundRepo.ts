import { getDatabase } from '../connection'
import type { LocalRound, LocalRoundDocument } from '@/types/local'

interface RoundRow {
  id: string
  project_id: string
  round_number: number
  status: string
  time_horizon_years: number | null
  max_results: number
  language_scope: string
  sources_used_json: string | null
  search_queries_json: string | null
  total_candidates: number
  selected_count: number
  source_stats_json: string | null
  progress: number
  progress_message: string
  started_at: number | null
  completed_at: number | null
  cancelled_reason: string | null
  cancelled_at: number | null
  partial_answer_json: string | null
  partial_completed_at: number | null
  created_at: number
  last_synced_at: number | null
}

function _roundToRow(r: LocalRound): RoundRow {
  return {
    ...r,
    sources_used_json: r.sources_used ? JSON.stringify(r.sources_used) : null,
    search_queries_json: r.search_queries ? JSON.stringify(r.search_queries) : null,
    source_stats_json: r.source_stats ? JSON.stringify(r.source_stats) : null,
    partial_answer_json: r.partial_answer ? JSON.stringify(r.partial_answer) : null,
  } as unknown as RoundRow
}

function _roundFromRow(row: RoundRow): LocalRound {
  return {
    id: row.id,
    project_id: row.project_id,
    round_number: row.round_number,
    status: row.status,
    time_horizon_years: row.time_horizon_years,
    max_results: row.max_results,
    language_scope: row.language_scope,
    sources_used: row.sources_used_json ? (JSON.parse(row.sources_used_json) as string[]) : null,
    search_queries: row.search_queries_json
      ? (JSON.parse(row.search_queries_json) as Record<string, unknown>)
      : null,
    total_candidates: row.total_candidates,
    selected_count: row.selected_count,
    source_stats: row.source_stats_json
      ? (JSON.parse(row.source_stats_json) as Record<string, unknown>)
      : null,
    progress: row.progress,
    progress_message: row.progress_message,
    started_at: row.started_at,
    completed_at: row.completed_at,
    cancelled_reason: row.cancelled_reason,
    cancelled_at: row.cancelled_at,
    partial_answer: row.partial_answer_json
      ? (JSON.parse(row.partial_answer_json) as Record<string, unknown>)
      : null,
    partial_completed_at: row.partial_completed_at,
    created_at: row.created_at,
    last_synced_at: row.last_synced_at,
  }
}

export async function upsertRound(r: LocalRound): Promise<void> {
  const db = getDatabase()
  const row = _roundToRow(r)
  await db.execute(
    `INSERT INTO search_rounds (
        id, project_id, round_number, status, time_horizon_years, max_results,
        language_scope, sources_used_json, search_queries_json,
        total_candidates, selected_count, source_stats_json,
        progress, progress_message, started_at, completed_at,
        cancelled_reason, cancelled_at, partial_answer_json, partial_completed_at,
        created_at, last_synced_at
      ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(id) DO UPDATE SET
        status = excluded.status,
        time_horizon_years = excluded.time_horizon_years,
        max_results = excluded.max_results,
        language_scope = excluded.language_scope,
        sources_used_json = excluded.sources_used_json,
        search_queries_json = excluded.search_queries_json,
        total_candidates = excluded.total_candidates,
        selected_count = excluded.selected_count,
        source_stats_json = excluded.source_stats_json,
        progress = excluded.progress,
        progress_message = excluded.progress_message,
        started_at = excluded.started_at,
        completed_at = excluded.completed_at,
        cancelled_reason = excluded.cancelled_reason,
        cancelled_at = excluded.cancelled_at,
        partial_answer_json = excluded.partial_answer_json,
        partial_completed_at = excluded.partial_completed_at,
        last_synced_at = excluded.last_synced_at`,
    [
      row.id, row.project_id, row.round_number, row.status, row.time_horizon_years, row.max_results,
      row.language_scope, row.sources_used_json, row.search_queries_json,
      row.total_candidates, row.selected_count, row.source_stats_json,
      row.progress, row.progress_message, row.started_at, row.completed_at,
      row.cancelled_reason, row.cancelled_at, row.partial_answer_json, row.partial_completed_at,
      row.created_at, row.last_synced_at,
    ],
  )
}

export async function getRound(id: string): Promise<LocalRound | null> {
  const db = getDatabase()
  const rows = await db.select<RoundRow>('SELECT * FROM search_rounds WHERE id = ?', [id])
  return rows[0] ? _roundFromRow(rows[0]) : null
}

export async function listRoundsByProject(projectId: string): Promise<LocalRound[]> {
  const db = getDatabase()
  const rows = await db.select<RoundRow>(
    'SELECT * FROM search_rounds WHERE project_id = ? ORDER BY round_number DESC',
    [projectId],
  )
  return rows.map(_roundFromRow)
}

export async function deleteRound(id: string): Promise<void> {
  const db = getDatabase()
  await db.execute('DELETE FROM search_rounds WHERE id = ?', [id])
}

// ─────────────── round_documents ───────────────

interface RoundDocRow {
  id: string
  round_id: string
  document_id: string
  rank_in_round: number | null
  initial_score: number | null
  agent_score: number | null
  agent_rationale: string | null
  one_line_summary: string | null
  below_cutoff: number   // 0/1
}

function _rdFromRow(row: RoundDocRow): LocalRoundDocument {
  return {
    id: row.id,
    round_id: row.round_id,
    document_id: row.document_id,
    rank_in_round: row.rank_in_round,
    initial_score: row.initial_score,
    agent_score: row.agent_score,
    agent_rationale: row.agent_rationale,
    one_line_summary: row.one_line_summary,
    below_cutoff: !!row.below_cutoff,
  }
}

export async function upsertRoundDocument(link: LocalRoundDocument): Promise<void> {
  const db = getDatabase()
  await db.execute(
    `INSERT INTO round_documents (
        id, round_id, document_id, rank_in_round, initial_score,
        agent_score, agent_rationale, one_line_summary, below_cutoff
      ) VALUES (?,?,?,?,?,?,?,?,?)
      ON CONFLICT(round_id, document_id) DO UPDATE SET
        rank_in_round = excluded.rank_in_round,
        initial_score = excluded.initial_score,
        agent_score = excluded.agent_score,
        agent_rationale = excluded.agent_rationale,
        one_line_summary = excluded.one_line_summary,
        below_cutoff = excluded.below_cutoff`,
    [
      link.id, link.round_id, link.document_id, link.rank_in_round, link.initial_score,
      link.agent_score, link.agent_rationale, link.one_line_summary,
      link.below_cutoff ? 1 : 0,
    ],
  )
}

export async function getRoundDocuments(roundId: string): Promise<LocalRoundDocument[]> {
  const db = getDatabase()
  const rows = await db.select<RoundDocRow>(
    'SELECT * FROM round_documents WHERE round_id = ? ORDER BY rank_in_round ASC',
    [roundId],
  )
  return rows.map(_rdFromRow)
}

export async function deleteRoundDocument(roundId: string, documentId: string): Promise<void> {
  const db = getDatabase()
  await db.execute(
    'DELETE FROM round_documents WHERE round_id = ? AND document_id = ?',
    [roundId, documentId],
  )
}
