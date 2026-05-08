/**
 * Bucket / classification repo —— 本地 4-bucket 分类表（document_classifications）。
 *
 * 桶名映射（client ↔ backend）：
 *   - very_relevant  ↔ highly_relevant
 *   - relevant       ↔ relevant
 *   - uncertain      ↔ maybe
 *   - irrelevant     ↔ not_relevant
 *
 * 约定：所有公共 API 用 client 名（very_relevant / relevant / uncertain / irrelevant）；
 *       store 层不需要再做映射。
 */
import { getDatabase } from '../connection'

export type ClientBucket = 'very_relevant' | 'relevant' | 'uncertain' | 'irrelevant'
export type LocalBucket = 'highly_relevant' | 'relevant' | 'maybe' | 'not_relevant'

const _CLIENT_TO_LOCAL: Record<ClientBucket, LocalBucket> = {
  very_relevant: 'highly_relevant',
  relevant: 'relevant',
  uncertain: 'maybe',
  irrelevant: 'not_relevant',
}
const _LOCAL_TO_CLIENT: Record<LocalBucket, ClientBucket> = {
  highly_relevant: 'very_relevant',
  relevant: 'relevant',
  maybe: 'uncertain',
  not_relevant: 'irrelevant',
}

export function clientBucketToLocal(b: ClientBucket): LocalBucket {
  return _CLIENT_TO_LOCAL[b] ?? 'maybe'
}
export function localBucketToClient(b: string): ClientBucket {
  return (_LOCAL_TO_CLIENT[b as LocalBucket] ?? 'uncertain') as ClientBucket
}

export interface BucketClassification {
  project_id: string
  document_id: string
  bucket: ClientBucket
  reason: string | null
  classified_at: number
  last_synced_at: number | null
}

interface Row {
  project_id: string
  document_id: string
  bucket: string
  reason: string | null
  classified_at: number
  last_synced_at: number | null
}

function _fromRow(r: Row): BucketClassification {
  return {
    project_id: r.project_id,
    document_id: r.document_id,
    bucket: localBucketToClient(r.bucket),
    reason: r.reason,
    classified_at: r.classified_at,
    last_synced_at: r.last_synced_at,
  }
}

/** 写 / upsert 一条分类（client 桶名输入，存 backend 桶名）。 */
export async function upsertClassification(c: BucketClassification): Promise<void> {
  const db = getDatabase()
  await db.execute(
    `INSERT INTO document_classifications
       (project_id, document_id, bucket, reason, classified_at, last_synced_at)
     VALUES (?,?,?,?,?,?)
     ON CONFLICT(project_id, document_id) DO UPDATE SET
       bucket = excluded.bucket,
       reason = excluded.reason,
       classified_at = excluded.classified_at,
       last_synced_at = excluded.last_synced_at`,
    [
      c.project_id,
      c.document_id,
      clientBucketToLocal(c.bucket),
      c.reason,
      c.classified_at,
      c.last_synced_at,
    ],
  )
}

export async function getClassification(
  projectId: string,
  documentId: string,
): Promise<BucketClassification | null> {
  const db = getDatabase()
  const rows = await db.select<Row>(
    'SELECT * FROM document_classifications WHERE project_id = ? AND document_id = ?',
    [projectId, documentId],
  )
  return rows[0] ? _fromRow(rows[0]) : null
}

export async function listClassificationsByProject(
  projectId: string,
): Promise<BucketClassification[]> {
  const db = getDatabase()
  const rows = await db.select<Row>(
    'SELECT * FROM document_classifications WHERE project_id = ? ORDER BY classified_at DESC',
    [projectId],
  )
  return rows.map(_fromRow)
}

export async function deleteClassification(
  projectId: string,
  documentId: string,
): Promise<void> {
  const db = getDatabase()
  await db.execute(
    'DELETE FROM document_classifications WHERE project_id = ? AND document_id = ?',
    [projectId, documentId],
  )
}

/** 项目内每桶计数（client 桶名）。 */
export async function getBucketCounts(
  projectId: string,
): Promise<Record<ClientBucket, number>> {
  const db = getDatabase()
  const rows = await db.select<{ bucket: string; cnt: number }>(
    'SELECT bucket, COUNT(*) AS cnt FROM document_classifications WHERE project_id = ? GROUP BY bucket',
    [projectId],
  )
  const out: Record<ClientBucket, number> = {
    very_relevant: 0,
    relevant: 0,
    uncertain: 0,
    irrelevant: 0,
  }
  for (const r of rows) {
    const b = localBucketToClient(r.bucket)
    out[b] = (out[b] ?? 0) + r.cnt
  }
  return out
}
