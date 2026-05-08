/**
 * Bucket store —— C5：分桶状态由本地 SQLite 提供。
 *
 * 之前：调 `bucketApi.getBuckets/classify/move/unclassify` 全走 backend。
 * 现在：调 `bucketRepo`（document_classifications 表）+ `documentRepo`（拼桶里展示的文献元数据）。
 *
 * 4 桶名映射在 bucketRepo 内做（client 名 ↔ backend 名），store 层只见 client 名。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

import {
  type ClientBucket,
  deleteClassification,
  getBucketCounts,
  listClassificationsByProject,
  upsertClassification,
} from '@/data/sqlite/repos/bucketRepo'
import { getDocumentsByIds } from '@/data/sqlite/repos/documentRepo'

export type BucketName = ClientBucket

export interface BucketDoc {
  document_id: string
  title: string
  one_line_summary?: string
  source: string
  agent_score?: number
  classified_at: string
  bucket: BucketName
  // 全文状态字段（FulltextViewer 等组件按这些字段判断 PDF/HTML 状态）
  fulltext_status?: string | null
  fulltext_pdf_status?: string | null
  fulltext_pdf_path?: string | null
  fulltext_html_status?: string | null
  fulltext_html_path?: string | null
  fulltext_path?: string | null
  pdf_url?: string | null
  doi?: string | null
  url?: string | null
  external_id?: string | null
}

const _BUCKETS: BucketName[] = ['very_relevant', 'relevant', 'uncertain', 'irrelevant']

export const useBucketStore = defineStore('bucket', () => {
  const buckets = ref<Record<BucketName, BucketDoc[]>>({
    very_relevant: [],
    relevant: [],
    uncertain: [],
    irrelevant: [],
  })
  const counts = ref<Record<BucketName, number>>({
    very_relevant: 0,
    relevant: 0,
    uncertain: 0,
    irrelevant: 0,
  })
  const loading = ref(false)

  const total = computed(
    () =>
      counts.value.very_relevant
      + counts.value.relevant
      + counts.value.uncertain
      + counts.value.irrelevant,
  )

  function getBucket(docId: string): BucketName | null {
    for (const b of _BUCKETS) {
      if (buckets.value[b].some((d) => d.document_id === docId)) return b
    }
    return null
  }

  async function fetchBuckets(projectId: string): Promise<void> {
    loading.value = true
    try {
      const classifications = await listClassificationsByProject(projectId)
      const docIds = classifications.map((c) => c.document_id)
      const docs = await getDocumentsByIds(docIds)
      const docById = new Map(docs.map((d) => [d.id, d]))

      const grouped: Record<BucketName, BucketDoc[]> = {
        very_relevant: [],
        relevant: [],
        uncertain: [],
        irrelevant: [],
      }
      for (const c of classifications) {
        const d = docById.get(c.document_id)
        const item: BucketDoc = {
          document_id: c.document_id,
          title: d?.title ?? '',
          one_line_summary: d?.one_line_summary ?? undefined,
          source: d?.source ?? '',
          agent_score: d?.quality_score ?? undefined,
          classified_at: new Date(c.classified_at).toISOString(),
          bucket: c.bucket,
          fulltext_status: d?.fulltext_status ?? null,
          fulltext_pdf_status: d?.fulltext_pdf_status ?? null,
          fulltext_pdf_path: d?.fulltext_pdf_path ?? null,
          fulltext_html_status: d?.fulltext_html_status ?? null,
          fulltext_html_path: d?.fulltext_html_path ?? null,
          fulltext_path: d?.fulltext_path ?? null,
          pdf_url: d?.pdf_url ?? null,
          doi: d?.doi ?? null,
          url: d?.url ?? null,
          external_id: d?.external_id ?? null,
        }
        grouped[c.bucket].push(item)
      }
      buckets.value = grouped
      counts.value = await getBucketCounts(projectId)
    } finally {
      loading.value = false
    }
  }

  async function classify(
    projectId: string,
    docId: string,
    bucket: BucketName,
    reason?: string,
  ): Promise<void> {
    const now = Date.now()
    await upsertClassification({
      project_id: projectId,
      document_id: docId,
      bucket,
      reason: reason ?? null,
      classified_at: now,
      last_synced_at: null,
    })
    // 乐观更新本地视图
    for (const b of _BUCKETS) {
      const idx = buckets.value[b].findIndex((d) => d.document_id === docId)
      if (idx >= 0) {
        buckets.value[b].splice(idx, 1)
        counts.value[b] = Math.max(0, counts.value[b] - 1)
      }
    }
    const docs = await getDocumentsByIds([docId])
    const d = docs[0]
    buckets.value[bucket].unshift({
      document_id: docId,
      title: d?.title ?? '',
      one_line_summary: d?.one_line_summary ?? undefined,
      source: d?.source ?? '',
      agent_score: d?.quality_score ?? undefined,
      classified_at: new Date(now).toISOString(),
      bucket,
      fulltext_status: d?.fulltext_status ?? null,
      fulltext_pdf_status: d?.fulltext_pdf_status ?? null,
      fulltext_pdf_path: d?.fulltext_pdf_path ?? null,
      fulltext_html_status: d?.fulltext_html_status ?? null,
      fulltext_html_path: d?.fulltext_html_path ?? null,
      fulltext_path: d?.fulltext_path ?? null,
      pdf_url: d?.pdf_url ?? null,
      doi: d?.doi ?? null,
      url: d?.url ?? null,
      external_id: d?.external_id ?? null,
    })
    counts.value[bucket]++
  }

  async function move(projectId: string, docId: string, toBucket: BucketName): Promise<void> {
    // move 与 classify 同效果；保留单独 API 让 view 不用变
    await classify(projectId, docId, toBucket)
  }

  async function unclassify(projectId: string, docId: string): Promise<void> {
    await deleteClassification(projectId, docId)
    for (const b of _BUCKETS) {
      const idx = buckets.value[b].findIndex((d) => d.document_id === docId)
      if (idx >= 0) {
        buckets.value[b].splice(idx, 1)
        counts.value[b] = Math.max(0, counts.value[b] - 1)
        break
      }
    }
  }

  function reset() {
    buckets.value = { very_relevant: [], relevant: [], uncertain: [], irrelevant: [] }
    counts.value = { very_relevant: 0, relevant: 0, uncertain: 0, irrelevant: 0 }
  }

  return {
    buckets,
    counts,
    total,
    loading,
    getBucket,
    fetchBuckets,
    classify,
    move,
    unclassify,
    reset,
  }
})
