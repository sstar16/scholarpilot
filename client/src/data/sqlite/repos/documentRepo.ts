import { getDatabase } from '../connection'
import type { LocalDocument } from '@/types/local'

interface Row {
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
  ai_key_points_json: string | null
  ai_relevance_reason: string | null
  ai_summary_source: string
  ai_summary_user: string | null
  ai_key_points_user_json: string | null
  countries_json: string | null
  quality_score: number | null
  one_line_summary: string | null
  one_line_summary_user: string | null
  concept_tags_json: string | null
  probe_cache_json: string | null
  content_hash: string | null
  import_source: string
  imported_at: number | null
  created_at: number
  last_synced_at: number | null
}

function _toRow(d: LocalDocument): Row {
  return {
    ...d,
    ai_key_points_json: d.ai_key_points ? JSON.stringify(d.ai_key_points) : null,
    ai_key_points_user_json: d.ai_key_points_user ? JSON.stringify(d.ai_key_points_user) : null,
    countries_json: d.countries ? JSON.stringify(d.countries) : null,
    concept_tags_json: d.concept_tags ? JSON.stringify(d.concept_tags) : null,
    probe_cache_json: d.probe_cache ? JSON.stringify(d.probe_cache) : null,
  } as unknown as Row
}

function _fromRow(row: Row): LocalDocument {
  const parse = <T>(s: string | null): T | null => (s ? (JSON.parse(s) as T) : null)
  return {
    id: row.id,
    source: row.source,
    external_id: row.external_id,
    doc_type: row.doc_type,
    title: row.title,
    title_zh: row.title_zh,
    authors: row.authors,
    abstract: row.abstract,
    publication_date: row.publication_date,
    url: row.url,
    doi: row.doi,
    journal: row.journal,
    citation_count: row.citation_count,
    pdf_url: row.pdf_url,
    fulltext_status: row.fulltext_status,
    fulltext_path: row.fulltext_path,
    fulltext_pdf_path: row.fulltext_pdf_path,
    fulltext_pdf_status: row.fulltext_pdf_status,
    fulltext_html_path: row.fulltext_html_path,
    fulltext_html_status: row.fulltext_html_status,
    fulltext_text: row.fulltext_text,
    pdf_local_path: row.pdf_local_path,
    html_local_path: row.html_local_path,
    fulltext_local_path: row.fulltext_local_path,
    ai_summary: row.ai_summary,
    ai_key_points: parse<string[]>(row.ai_key_points_json),
    ai_relevance_reason: row.ai_relevance_reason,
    ai_summary_source: row.ai_summary_source,
    ai_summary_user: row.ai_summary_user,
    ai_key_points_user: parse<string[]>(row.ai_key_points_user_json),
    countries: parse<string[]>(row.countries_json),
    quality_score: row.quality_score,
    one_line_summary: row.one_line_summary,
    one_line_summary_user: row.one_line_summary_user,
    concept_tags: parse<string[]>(row.concept_tags_json),
    probe_cache: parse<unknown[]>(row.probe_cache_json),
    content_hash: row.content_hash,
    import_source: row.import_source,
    imported_at: row.imported_at,
    created_at: row.created_at,
    last_synced_at: row.last_synced_at,
  }
}

const COLS = [
  'id','source','external_id','doc_type','title','title_zh','authors','abstract',
  'publication_date','url','doi','journal','citation_count','pdf_url',
  'fulltext_status','fulltext_path','fulltext_pdf_path','fulltext_pdf_status',
  'fulltext_html_path','fulltext_html_status','fulltext_text',
  'pdf_local_path','html_local_path','fulltext_local_path',
  'ai_summary','ai_key_points_json','ai_relevance_reason','ai_summary_source',
  'ai_summary_user','ai_key_points_user_json','countries_json','quality_score',
  'one_line_summary','one_line_summary_user','concept_tags_json','probe_cache_json',
  'content_hash','import_source','imported_at','created_at','last_synced_at',
] as const

const PLACEHOLDERS = COLS.map(() => '?').join(',')
const UPDATE_SET = COLS
  .filter((c) => c !== 'id' && c !== 'created_at')
  .map((c) => `${c} = excluded.${c}`)
  .join(', ')

const UPSERT_SQL =
  `INSERT INTO documents (${COLS.join(',')}) VALUES (${PLACEHOLDERS})
   ON CONFLICT(id) DO UPDATE SET ${UPDATE_SET}`

function _bind(d: LocalDocument): unknown[] {
  const row = _toRow(d)
  return COLS.map((c) => (row as unknown as Record<string, unknown>)[c] ?? null)
}

export async function upsertDocument(d: LocalDocument): Promise<void> {
  const db = getDatabase()
  await db.execute(UPSERT_SQL, _bind(d))
}

export async function upsertManyDocuments(docs: LocalDocument[]): Promise<void> {
  const db = getDatabase()
  for (const d of docs) {
    // plugin-sql 不暴露事务 API（Tauri plugin-sql 2.x 限制）；逐行 upsert 实测够快（10-30 篇 < 50ms）
    await db.execute(UPSERT_SQL, _bind(d))
  }
}

export async function getDocument(id: string): Promise<LocalDocument | null> {
  const db = getDatabase()
  const rows = await db.select<Row>('SELECT * FROM documents WHERE id = ?', [id])
  return rows[0] ? _fromRow(rows[0]) : null
}

export async function getDocumentsByIds(ids: string[]): Promise<LocalDocument[]> {
  if (ids.length === 0) return []
  const db = getDatabase()
  const placeholders = ids.map(() => '?').join(',')
  const rows = await db.select<Row>(
    `SELECT * FROM documents WHERE id IN (${placeholders})`,
    ids,
  )
  return rows.map(_fromRow)
}

export interface DocumentLocalPathPatch {
  pdf_local_path?: string | null
  html_local_path?: string | null
  fulltext_local_path?: string | null
  fulltext_text?: string | null
  fulltext_status?: string
  fulltext_pdf_status?: string
  fulltext_html_status?: string
}

export async function updateDocumentLocalPaths(
  id: string,
  patch: DocumentLocalPathPatch,
): Promise<void> {
  const db = getDatabase()
  const sets: string[] = []
  const bindings: unknown[] = []
  for (const [k, v] of Object.entries(patch)) {
    sets.push(`${k} = ?`)
    bindings.push(v)
  }
  if (sets.length === 0) return
  bindings.push(id)
  await db.execute(`UPDATE documents SET ${sets.join(', ')} WHERE id = ?`, bindings)
}
