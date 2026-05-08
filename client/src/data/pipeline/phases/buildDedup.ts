/**
 * BuildDedupPhase — 收集需要排除的 (source, external_id) 对：
 * 1. 该 project 的所有 prior-round documents
 * 2. 该 project 用户标记为 irrelevant 的 documents（取代 backend feedback 表）
 *
 * 移植自 backend `phases/build_dedup.py:8-44`，差异：
 * - 客户端没有 feedback 表，改用 document_classifications.bucket=='irrelevant'
 * - 直接 SQL JOIN 走 SQLite，避免单独拉 repo 引入循环依赖
 */
import { getDatabase } from '@/data/sqlite/connection'

import type { RoundContext } from '../context'
import type { Phase } from '../runner'

export interface BuildDedupOutput {
  /** Set<`${source}:${external_id}`> */
  excludeKeys: Set<string>
}

interface DedupRow {
  source: string
  external_id: string
}

export const buildDedupPhase: Phase = {
  name: 'build_dedup',
  deps: ['load_round'],
  progressRange: [0.08, 0.10] as const,

  async execute(ctx: RoundContext): Promise<BuildDedupOutput> {
    const db = getDatabase()
    const projectId = ctx.projectId

    // 1. prior-round documents in this project
    const priorRows = await db.select<DedupRow>(
      `SELECT DISTINCT d.source AS source, d.external_id AS external_id
         FROM documents d
         INNER JOIN round_documents rd ON rd.document_id = d.id
         INNER JOIN search_rounds r ON r.id = rd.round_id
        WHERE r.project_id = ?`,
      [projectId],
    )

    // 2. user-flagged irrelevant documents (client equivalent of backend feedback.relevance=-1)
    //    NOTE: 客户端 4-bucket schema = very_relevant | relevant | uncertain | irrelevant
    //    (与 stores/bucket.ts / scoringAgent.ts 一致). 之前误用旧 backend 'not_relevant',
    //    永远命不中本地 SQLite 行，导致去重失效。
    const negRows = await db.select<DedupRow>(
      `SELECT DISTINCT d.source AS source, d.external_id AS external_id
         FROM documents d
         INNER JOIN document_classifications dc ON dc.document_id = d.id
        WHERE dc.project_id = ?
          AND dc.bucket = 'irrelevant'`,
      [projectId],
    )

    const excludeKeys = new Set<string>()
    for (const r of priorRows) excludeKeys.add(`${r.source}:${r.external_id}`)
    for (const r of negRows) excludeKeys.add(`${r.source}:${r.external_id}`)

    return { excludeKeys }
  },
}
