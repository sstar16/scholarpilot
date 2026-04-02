import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { bucketApi } from '../api/client'

export type BucketName = 'very_relevant' | 'relevant' | 'uncertain' | 'irrelevant'

export interface BucketDoc {
  document_id: string
  title: string
  one_line_summary?: string
  source: string
  agent_score?: number
  classified_at: string
  bucket: BucketName
}

export const useBucketStore = defineStore('bucket', () => {
  const buckets = ref<Record<BucketName, BucketDoc[]>>({
    very_relevant: [],
    relevant: [],
    uncertain: [],
    irrelevant: [],
  })
  const counts = ref<Record<BucketName, number>>({
    very_relevant: 0, relevant: 0, uncertain: 0, irrelevant: 0,
  })
  const loading = ref(false)

  const total = computed(() =>
    counts.value.very_relevant + counts.value.relevant +
    counts.value.uncertain + counts.value.irrelevant
  )

  function getBucket(docId: string): BucketName | null {
    for (const b of (['very_relevant', 'relevant', 'uncertain', 'irrelevant'] as BucketName[])) {
      if (buckets.value[b].some(d => d.document_id === docId)) return b
    }
    return null
  }

  async function fetchBuckets(projectId: string) {
    loading.value = true
    try {
      const res = await bucketApi.getBuckets(projectId)
      const data = res.data
      buckets.value.very_relevant = data.very_relevant || []
      buckets.value.relevant = data.relevant || []
      buckets.value.uncertain = data.uncertain || []
      buckets.value.irrelevant = data.irrelevant || []
      counts.value = data.counts || {
        very_relevant: buckets.value.very_relevant.length,
        relevant: buckets.value.relevant.length,
        uncertain: buckets.value.uncertain.length,
        irrelevant: buckets.value.irrelevant.length,
      }
    } finally {
      loading.value = false
    }
  }

  async function classify(projectId: string, docId: string, bucket: BucketName, reason?: string) {
    const res = await bucketApi.classify(projectId, docId, { bucket, reason })
    // 本地乐观更新：从旧桶移除，加入新桶
    for (const b of (['very_relevant', 'relevant', 'uncertain', 'irrelevant'] as BucketName[])) {
      const idx = buckets.value[b].findIndex(d => d.document_id === docId)
      if (idx >= 0) {
        buckets.value[b].splice(idx, 1)
        counts.value[b]--
      }
    }
    // 添加到新桶需要文档信息——简单占位，下次 fetchBuckets 会补全
    buckets.value[bucket].unshift({
      document_id: docId,
      title: '',
      source: '',
      classified_at: new Date().toISOString(),
      bucket,
    })
    counts.value[bucket]++
    return res.data
  }

  async function move(projectId: string, docId: string, toBucket: BucketName) {
    await bucketApi.move(projectId, docId, { to_bucket: toBucket })
    // 乐观更新
    let doc: BucketDoc | undefined
    for (const b of (['very_relevant', 'relevant', 'uncertain', 'irrelevant'] as BucketName[])) {
      const idx = buckets.value[b].findIndex(d => d.document_id === docId)
      if (idx >= 0) {
        doc = buckets.value[b].splice(idx, 1)[0]
        counts.value[b]--
        break
      }
    }
    if (doc) {
      doc.bucket = toBucket
      buckets.value[toBucket].unshift(doc)
      counts.value[toBucket]++
    }
  }

  async function unclassify(projectId: string, docId: string) {
    await bucketApi.unclassify(projectId, docId)
    for (const b of (['very_relevant', 'relevant', 'uncertain', 'irrelevant'] as BucketName[])) {
      const idx = buckets.value[b].findIndex(d => d.document_id === docId)
      if (idx >= 0) {
        buckets.value[b].splice(idx, 1)
        counts.value[b]--
        break
      }
    }
  }

  function reset() {
    buckets.value = { very_relevant: [], relevant: [], uncertain: [], irrelevant: [] }
    counts.value = { very_relevant: 0, relevant: 0, uncertain: 0, irrelevant: 0 }
  }

  return { buckets, counts, total, loading, getBucket, fetchBuckets, classify, move, unclassify, reset }
})
