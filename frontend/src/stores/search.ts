import { defineStore } from 'pinia'
import { ref, reactive, computed } from 'vue'
import { searchApi, feedbackApi, bucketApi } from '../api/client'

export const useSearchStore = defineStore('search', () => {
  const projectId = ref<string>('')
  const currentRound = ref<any>(null)
  const rounds = ref<any[]>([])
  const documents = ref<any[]>([])
  const sourceStats = ref<Record<string, any>>({})
  // keyed by document_id (UUID string) → relevance score (-1/0/1/2)
  const feedbackDrafts = reactive<Record<string, number>>({})
  const loading = ref(false)
  const pollingTimer = ref<ReturnType<typeof setInterval> | null>(null)
  const sseConnected = ref(false)
  const streamingDocs = ref<any[]>([]) // visible docs (revealed gradually)
  const docQueue: any[] = [] // internal buffer — backend pushes here, timer drains to streamingDocs
  let drainTimer: ReturnType<typeof setInterval> | null = null
  const statusText = ref('') // current status description

  // Per-source keyword confirmation state
  const keywordPlan = ref<any>(null)
  const awaitingKeywordConfirmation = ref(false)

  const isStarting = computed(() => loading.value)

  const ratedCount = computed(() => Object.keys(feedbackDrafts).length)

  async function fetchRounds(pid: string) {
    projectId.value = pid
    const res = await searchApi.listRounds(pid)
    rounds.value = res.data
    if (res.data.length > 0) {
      const active = res.data.find((r: any) => r.status !== 'complete')
      currentRound.value = active ?? res.data[res.data.length - 1]
      // Auto-start polling if a round is still running (e.g. after page refresh)
      if (active && (active.status === 'running' || active.status === 'pending')) {
        startPolling(pid, active.id)
      }
      // Restore keyword confirmation state if round is awaiting_keywords
      if (active && active.status === 'awaiting_keywords') {
        awaitingKeywordConfirmation.value = true
        // Try to recover keyword plan from Redis
        try {
          const kwRes = await searchApi.getKeywordPlan(pid, active.id)
          keywordPlan.value = kwRes.data
        } catch {
          // Plan expired — user needs to restart
          awaitingKeywordConfirmation.value = false
        }
      }
    }
  }

  async function startRound(pid: string) {
    projectId.value = pid
    loading.value = true
    try {
      const res = await searchApi.startRound(pid)
      currentRound.value = res.data
      const idx = rounds.value.findIndex((r: any) => r.id === res.data.id)
      if (idx >= 0) rounds.value[idx] = res.data
      else rounds.value.push(res.data)
      startPolling(pid, res.data.id)
      return res.data
    } finally {
      loading.value = false
    }
  }

  async function prepareRound(pid: string) {
    projectId.value = pid
    loading.value = true
    try {
      const res = await searchApi.prepareRound(pid)
      keywordPlan.value = res.data
      awaitingKeywordConfirmation.value = true
      // Also update currentRound with round info
      currentRound.value = {
        id: res.data.round_id,
        round_number: res.data.round_number,
        status: 'awaiting_keywords',
        progress: 0.05,
        progress_message: '关键词已生成，等待确认...',
        search_queries: {
          base_query: res.data.base_query,
          original_chinese_query: res.data.original_chinese_query,
          english_query_source: res.data.english_query_source,
          cn_query_source: res.data.cn_query_source,
        },
      }
      const idx = rounds.value.findIndex((r: any) => r.id === res.data.round_id)
      if (idx >= 0) rounds.value[idx] = currentRound.value
      else rounds.value.push(currentRound.value)
      return res.data
    } finally {
      loading.value = false
    }
  }

  async function confirmKeywords(pid: string, roundId: string, payload: any) {
    loading.value = true
    try {
      // payload 可以是旧格式 (source_plans[]) 或新格式 ({source_plans, base_query, ...})
      const body = Array.isArray(payload) ? { source_plans: payload } : payload
      const res = await searchApi.confirmKeywords(pid, roundId, body)
      currentRound.value = res.data
      awaitingKeywordConfirmation.value = false
      // keywordPlan 保留（DevView 需要展示 per-source 优化结果），prepareRound 时自然覆盖
      const idx = rounds.value.findIndex((r: any) => r.id === roundId)
      if (idx >= 0) rounds.value[idx] = res.data
      startPolling(pid, roundId)
      return res.data
    } finally {
      loading.value = false
    }
  }

  function startPolling(pid: string, roundId: string) {
    stopPolling()
    pollingTimer.value = setInterval(async () => {
      try {
        const res = await searchApi.getRoundStatus(pid, roundId)
        currentRound.value = res.data
        const idx = rounds.value.findIndex((r: any) => r.id === roundId)
        if (idx >= 0) rounds.value[idx] = res.data
        if (['awaiting_feedback', 'complete', 'failed'].includes(res.data.status)) {
          stopPolling()
          if (res.data.status === 'awaiting_feedback') {
            await loadRoundResults(roundId)
          }
        }
      } catch {
        // ignore transient poll errors
      }
    }, 2000)
  }

  function stopPolling() {
    if (pollingTimer.value) {
      clearInterval(pollingTimer.value)
      pollingTimer.value = null
    }
  }

  async function loadRoundResults(roundId: string) {
    const res = await searchApi.getRoundResults(projectId.value, roundId)
    documents.value = res.data.documents ?? []
    sourceStats.value = res.data.source_stats ?? {}
    // Also persist search_queries from results (has enriched per-source stats)
    if (res.data.search_queries && currentRound.value) {
      currentRound.value = { ...currentRound.value, search_queries: res.data.search_queries }
    }
  }

  function setFeedback(docId: string, relevance: number) {
    feedbackDrafts[docId] = relevance
  }

  async function submitFeedback(pid: string) {
    if (!currentRound.value) throw new Error('no active round')
    const roundId = currentRound.value.id
    const feedbacks = Object.entries(feedbackDrafts).map(([docId, relevance]) => ({
      document_id: docId,
      relevance,
    }))
    const res = await feedbackApi.submit(pid, roundId, feedbacks)
    Object.keys(feedbackDrafts).forEach(k => delete feedbackDrafts[k])
    return res.data
  }

  async function finalizeRound(pid: string) {
    if (!currentRound.value) throw new Error('no active round')
    const roundId = currentRound.value.id
    const res = await searchApi.finalizeRound(pid, roundId)
    // 更新轮次状态为已完成
    if (currentRound.value) {
      currentRound.value = { ...currentRound.value, status: 'complete' }
    }
    const idx = rounds.value.findIndex((r: any) => r.id === roundId)
    if (idx >= 0) rounds.value[idx] = { ...rounds.value[idx], status: 'complete' }
    return res.data
  }

  async function classifyDocument(pid: string, docId: string, bucket: string) {
    const res = await bucketApi.classify(pid, docId, { bucket })
    // 同步更新 documents 列表中的 bucket 字段
    const doc = documents.value.find((d: any) => d.id === docId)
    if (doc) doc.bucket = bucket
    return res.data
  }

  function startDrainTimer() {
    if (drainTimer) return
    drainTimer = setInterval(() => {
      if (docQueue.length > 0) {
        streamingDocs.value.push(docQueue.shift()!)
      } else {
        // queue empty, stop timer
        clearInterval(drainTimer!)
        drainTimer = null
      }
    }, 350) // one doc every 350ms — smooth flowing reveal
  }

  function stopDrain() {
    if (drainTimer) { clearInterval(drainTimer); drainTimer = null }
    // flush remaining
    while (docQueue.length) streamingDocs.value.push(docQueue.shift()!)
  }

  function handleSSEEvent(event: string, data: any) {
    switch (event) {
      case 'round_status':
        if (currentRound.value) {
          currentRound.value = { ...currentRound.value, status: data.status, progress: data.progress, progress_message: data.message }
        }
        statusText.value = data.message || ''
        break
      case 'doc_arrived':
        docQueue.push(data) // buffer it
        startDrainTimer()   // start draining if not already
        break
      case 'summary_ready': {
        // Update the matching doc with summary
        const doc = documents.value.find(d => d.external_id === data.external_id && d.source === data.source)
        if (doc) {
          doc.ai_summary = data.summary_preview
          doc.ai_key_points = data.key_points
        }
        // 同步更新 streamingDocs 中的 has_summary（让 spinner 变成 ✓）
        const streamDoc = streamingDocs.value.find(
          (d: any) => d.external_id === data.external_id && d.source === data.source
        )
        if (streamDoc) {
          streamDoc.has_summary = true
        }
        break
      }
      case 'round_complete':
        stopDrain() // flush remaining docs immediately
        statusText.value = '检索完成'
        if (currentRound.value) {
          currentRound.value = { ...currentRound.value, status: 'awaiting_feedback', progress: 1.0 }
        }
        if (currentRound.value?.id) {
          loadRoundResults(currentRound.value.id)
        }
        break
    }
  }

  function reset() {
    stopPolling()
    stopDrain()
    docQueue.length = 0
    projectId.value = ''
    currentRound.value = null
    rounds.value = []
    documents.value = []
    sourceStats.value = {}
    streamingDocs.value = []
    sseConnected.value = false
    statusText.value = ''
    Object.keys(feedbackDrafts).forEach(k => delete feedbackDrafts[k])
  }

  return {
    currentRound, rounds, documents, sourceStats, feedbackDrafts, loading,
    isStarting, ratedCount,
    sseConnected, streamingDocs, statusText, handleSSEEvent,
    keywordPlan, awaitingKeywordConfirmation,
    fetchRounds, startRound, prepareRound, confirmKeywords,
    startPolling, loadRoundResults, setFeedback, submitFeedback,
    finalizeRound, classifyDocument, reset,
  }
})
