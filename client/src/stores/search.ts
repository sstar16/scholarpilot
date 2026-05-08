/**
 * Search store —— C5：rounds CRUD 走本地 SQLite + RoundOrchestrator。
 *
 * 之前：调 `searchApi.startRound/prepareRound/confirmKeywords/listRounds/getRoundStatus
 *      /getRoundResults/finalizeRound`、`feedbackApi.submit`，全部 backend HTTP。
 * 现在：
 *   - listRounds / loadRoundResults / getRound：roundRepo + documentRepo
 *   - startRound / prepareRound / confirmKeywords：RoundOrchestrator（B7 状态机）
 *   - finalizeRound：直接改 round.status='complete' 写 SQLite
 *   - submitFeedback：upsert document_classifications + fire-and-forget applyMemoryPhase
 *     （audit 2026-05-08 修复 bug #1：之前 `void applyMemoryUpdate` 显式不调，画像学习闭环
 *     断链；现在调本地 MemoryAgent → applyMemoryUpdate 写盘）
 *
 * SSE / 实时进度：保留事件回调入口（handleSSEEvent），但事件源是 ClientEventBus 而非
 * backend SSE。adapter 由 ChatPanel 在 mount 时调 eventBus.subscribe(`round:${id}`, ...)。
 */
import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'

import { applyMemoryPhase } from '@/data/pipeline/phases/applyMemory'
import { getRoundOrchestrator } from '@/data/orchestrator/roundOrchestrator'
import { llmManager } from '@/data/llm/manager'
import type { LLMManagerLike } from '@/data/pipeline/context'
import {
  upsertClassification,
  type ClientBucket,
} from '@/data/sqlite/repos/bucketRepo'
import { getDocumentsByIds } from '@/data/sqlite/repos/documentRepo'
import {
  getRound,
  getRoundDocuments,
  listRoundsByProject,
  upsertRound,
} from '@/data/sqlite/repos/roundRepo'
import type { LocalDocument, LocalRound } from '@/types/local'

import { useProjectStore } from './project'

interface RoundView extends LocalRound {
  // 客户端侧 view 习惯字段补 alias（保 view 兼容）
}

function _genId(): string {
  return `local-${crypto.randomUUID()}`
}

function _bucketOfRelevance(rel: number): ClientBucket {
  // -1 不相关 / 0 待定 / 1 相关 / 2 强相关
  if (rel >= 2) return 'very_relevant'
  if (rel === 1) return 'relevant'
  if (rel === 0) return 'uncertain'
  return 'irrelevant'
}

export const useSearchStore = defineStore('search', () => {
  const projectId = ref<string>('')
  const currentRound = ref<RoundView | null>(null)
  const rounds = ref<RoundView[]>([])
  const documents = ref<LocalDocument[]>([])
  const sourceStats = ref<Record<string, unknown>>({})
  // keyed by document_id (UUID string) → relevance score (-1/0/1/2)
  const feedbackDrafts = reactive<Record<string, number>>({})
  const loading = ref(false)
  const sseConnected = ref(false)
  const streamingDocs = ref<unknown[]>([])
  const docQueue: unknown[] = []
  let drainTimer: ReturnType<typeof setInterval> | null = null
  const statusText = ref('')

  // Per-source keyword confirmation state
  const keywordPlan = ref<unknown>(null)
  const awaitingKeywordConfirmation = ref(false)

  const isStarting = computed(() => loading.value)
  const ratedCount = computed(() => Object.keys(feedbackDrafts).length)

  async function fetchRounds(pid: string): Promise<void> {
    if (projectId.value && projectId.value !== pid) reset()
    projectId.value = pid
    const items = await listRoundsByProject(pid)
    rounds.value = items
    if (items.length === 0) {
      currentRound.value = null
      return
    }
    const active = items.find((r) => r.status !== 'complete')
    currentRound.value = active ?? items[items.length - 1]
    if (currentRound.value && currentRound.value.status === 'awaiting_keywords') {
      awaitingKeywordConfirmation.value = true
      const sq = currentRound.value.search_queries as Record<string, unknown> | null
      if (sq && sq.keyword_plan) {
        keywordPlan.value = sq.keyword_plan
      }
    }
  }

  async function startRound(pid: string): Promise<RoundView> {
    projectId.value = pid
    loading.value = true
    try {
      // 创建一个新 round 行，交给 orchestrator 跑 11-phase
      const existingRounds = await listRoundsByProject(pid)
      const nextNum =
        existingRounds.length === 0 ? 1 : Math.max(...existingRounds.map((r) => r.round_number)) + 1
      const now = Date.now()
      const round: LocalRound = {
        id: _genId(),
        project_id: pid,
        round_number: nextNum,
        status: 'pending',
        time_horizon_years: null,
        max_results: 10,
        language_scope: 'international',
        sources_used: null,
        search_queries: null,
        total_candidates: 0,
        selected_count: 0,
        source_stats: null,
        progress: 0,
        progress_message: '',
        started_at: now,
        completed_at: null,
        cancelled_reason: null,
        cancelled_at: null,
        partial_answer: null,
        partial_completed_at: null,
        created_at: now,
        last_synced_at: null,
      }
      await upsertRound(round)
      currentRound.value = round
      rounds.value = [round, ...rounds.value]

      // fire-and-forget orchestrator；事件 / 状态推进由 eventBus + roundRepo poll 触发
      const orch = getRoundOrchestrator()
      // llmManager 的 generateStream 签名比 LLMManagerLike 更具体，需 cast
      const llm = llmManager as unknown as LLMManagerLike
      try {
        orch.setLlmManager(llm)
      } catch {
        // setter 抛是因为已被设置；忽略
      }
      void orch.startRound({
        roundId: round.id,
        projectId: pid,
        userTriggered: true,
        llmManager: llm,
      })

      return round
    } finally {
      loading.value = false
    }
  }

  /**
   * Prepare round = 起 round + 跑到 plan_query / load_confirmed_keywords，落到
   * status='awaiting_keywords'。orchestrator 接通后由 phase 内部决定何时停下让用户确认。
   *
   * 客户端目前没有 backend "prepare 后停" 的纯路径，复用 startRound（11 phase 中的
   * planQuery / loadConfirmedKeywords 会按 round.search_queries.keyword_plan.confirmed 决定
   * 是否跳过 awaiting）。
   */
  async function prepareRound(pid: string): Promise<RoundView> {
    return startRound(pid)
  }

  async function confirmKeywords(
    pid: string,
    roundId: string,
    payload: unknown,
  ): Promise<RoundView> {
    loading.value = true
    try {
      const body = Array.isArray(payload)
        ? { source_plans: payload as Array<Record<string, unknown>> }
        : (payload as Record<string, unknown>)
      const orch = getRoundOrchestrator()
      await orch.confirmKeywords(roundId, body as Parameters<typeof orch.confirmKeywords>[1])
      const updated = await getRound(roundId)
      if (updated) {
        currentRound.value = updated
        const idx = rounds.value.findIndex((r) => r.id === roundId)
        if (idx >= 0) rounds.value[idx] = updated
      }
      awaitingKeywordConfirmation.value = false
      void pid
      return updated as RoundView
    } finally {
      loading.value = false
    }
  }

  /** 拉本地 round 状态（替代 polling backend status endpoint）。 */
  async function refreshRoundStatus(roundId: string): Promise<RoundView | null> {
    const r = await getRound(roundId)
    if (!r) return null
    currentRound.value = r
    const idx = rounds.value.findIndex((x) => x.id === roundId)
    if (idx >= 0) rounds.value[idx] = r
    return r
  }

  async function loadRoundResults(roundId: string): Promise<void> {
    const links = await getRoundDocuments(roundId)
    const docIds = links
      .filter((l) => !l.below_cutoff)
      .sort((a, b) => (a.rank_in_round ?? 0) - (b.rank_in_round ?? 0))
      .map((l) => l.document_id)
    documents.value = await getDocumentsByIds(docIds)
    const r = await getRound(roundId)
    if (r) {
      sourceStats.value = (r.source_stats as Record<string, unknown>) ?? {}
      currentRound.value = r
    }
  }

  function setFeedback(docId: string, relevance: number) {
    feedbackDrafts[docId] = relevance
  }

  /**
   * 提交 feedback：写本地 document_classifications + 触发画像学习闭环。
   *
   * 流程：
   *   1. 收集 feedbackDrafts → 解析为 4-bucket
   *   2. upsertClassification 落 SQLite（主流程，必须成功）
   *   3. fire-and-forget 跑 applyMemoryPhase（MemoryAgent → applyMemoryUpdate）
   *      - 失败仅 console.warn，不挂主流程（memory 不是关键路径）
   *      - 异步执行让 UI 立即返回 saved count，不等 LLM 出结果
   *
   * 这里是画像学习闭环的入口。下一轮 scoring/queryPlan 看到的 memorySnapshot
   * 会含本轮反馈提炼的偏好。
   */
  async function submitFeedback(pid: string): Promise<{ saved: number }> {
    if (!currentRound.value) throw new Error('no active round')
    const roundId = currentRound.value.id
    const entries = Object.entries(feedbackDrafts)
    if (entries.length === 0) return { saved: 0 }
    const now = Date.now()
    let saved = 0
    // 收集成功 upsert 的 (docId, relevance) → 后面给 memory agent 用
    const memoryFeedbackInputs: Array<{ docId: string; relevance: number }> = []
    for (const [docId, rel] of entries) {
      try {
        await upsertClassification({
          project_id: pid,
          document_id: docId,
          bucket: _bucketOfRelevance(rel),
          reason: null,
          classified_at: now,
          last_synced_at: null,
        })
        memoryFeedbackInputs.push({ docId, relevance: rel })
        saved++
      } catch (e) {
        console.warn('[search] feedback upsert failed:', docId, e)
      }
    }
    Object.keys(feedbackDrafts).forEach((k) => delete feedbackDrafts[k])

    // ── 画像学习闭环：fire-and-forget memory update ──
    //
    // - 不 await：UI 立即拿到 saved count；LLM 可能跑几秒
    // - 失败仅 console.warn（applyMemoryPhase 内部已 graceful 兜底）
    // - 跑完后 `<AppData>/.../memory/MEMORY.md` 更新；下轮 loadMemoryPhase 读到
    if (saved > 0) {
      const docIds = memoryFeedbackInputs.map((x) => x.docId)
      const relevanceById = new Map(memoryFeedbackInputs.map((x) => [x.docId, x.relevance]))
      void (async () => {
        try {
          // 拉 documents 拿 title / abstract / source（memory agent prompt 用）
          const docs = await getDocumentsByIds(docIds)
          const docByid = new Map(docs.map((d) => [d.id, d]))
          const feedbackEntries = memoryFeedbackInputs.map((fb) => {
            const d = docByid.get(fb.docId)
            return {
              docId: fb.docId,
              bucket: _bucketOfRelevance(fb.relevance),
              docTitle: d?.title ?? '',
              docAbstract: d?.abstract ?? d?.ai_summary ?? '',
              source: d?.source ?? '',
              reason: undefined as string | undefined,
            }
          })
          void relevanceById
          await applyMemoryPhase({
            projectId: pid,
            roundId,
            feedbacks: feedbackEntries,
            llm: llmManager as unknown as Parameters<typeof applyMemoryPhase>[0]['llm'],
          })
        } catch (e) {
          console.warn('[search] applyMemoryPhase failed (non-fatal):', e)
        }
      })()
    }

    return { saved }
  }

  async function finalizeRound(_pid: string): Promise<{ status: string }> {
    if (!currentRound.value) throw new Error('no active round')
    const roundId = currentRound.value.id
    const r = await getRound(roundId)
    if (!r) throw new Error('round not found')
    const updated: LocalRound = {
      ...r,
      status: 'complete',
      completed_at: r.completed_at ?? Date.now(),
    }
    await upsertRound(updated)
    currentRound.value = updated
    const idx = rounds.value.findIndex((x) => x.id === roundId)
    if (idx >= 0) rounds.value[idx] = updated
    return { status: 'complete' }
  }

  async function classifyDocument(
    pid: string,
    docId: string,
    bucket: ClientBucket,
  ): Promise<void> {
    await upsertClassification({
      project_id: pid,
      document_id: docId,
      bucket,
      reason: null,
      classified_at: Date.now(),
      last_synced_at: null,
    })
    const doc = documents.value.find((d) => d.id === docId)
    if (doc) (doc as unknown as Record<string, unknown>).bucket = bucket
  }

  function startDrainTimer() {
    if (drainTimer) return
    drainTimer = setInterval(() => {
      if (docQueue.length > 0) {
        streamingDocs.value.push(docQueue.shift()!)
      } else {
        clearInterval(drainTimer!)
        drainTimer = null
      }
    }, 350)
  }

  function stopDrain() {
    if (drainTimer) {
      clearInterval(drainTimer)
      drainTimer = null
    }
    while (docQueue.length) streamingDocs.value.push(docQueue.shift()!)
  }

  /**
   * 处理 RoundOrchestrator/eventBus 推送事件（C5：之前是 backend SSE，已切本地）。
   * ChatPanel 等组件 subscribe `round:${id}` 后 forward 到此函数。
   */
  function handleSSEEvent(event: string, data: Record<string, unknown>) {
    switch (event) {
      case 'round_status':
        if (currentRound.value) {
          currentRound.value = {
            ...currentRound.value,
            status: (data.status as string) ?? currentRound.value.status,
            progress: typeof data.progress === 'number' ? data.progress : currentRound.value.progress,
            progress_message: (data.message as string) ?? currentRound.value.progress_message,
          }
        }
        statusText.value = (data.message as string) || ''
        break
      case 'doc_arrived':
        docQueue.push(data)
        startDrainTimer()
        break
      case 'summary_ready': {
        const docId = data.docId as string | undefined
        const externalId = data.external_id as string | undefined
        const source = data.source as string | undefined
        const doc = documents.value.find((d) =>
          docId
            ? d.id === docId
            : d.external_id === externalId && d.source === source,
        )
        if (doc) {
          (doc as unknown as Record<string, unknown>).ai_summary = data.summary
          if (Array.isArray(data.key_points)) {
            (doc as unknown as Record<string, unknown>).ai_key_points = data.key_points
          }
        }
        const streamDoc = streamingDocs.value.find((d) => {
          const x = d as Record<string, unknown>
          return docId
            ? x.docId === docId
            : x.external_id === externalId && x.source === source
        }) as Record<string, unknown> | undefined
        if (streamDoc) streamDoc.has_summary = true
        break
      }
      case 'round_complete':
        stopDrain()
        statusText.value = '检索完成'
        if (currentRound.value) {
          currentRound.value = {
            ...currentRound.value,
            status: 'awaiting_feedback',
            progress: 1.0,
          }
        }
        if (currentRound.value?.id) {
          loadRoundResults(currentRound.value.id).catch(() => { /* ignore */ })
        }
        break
    }
  }

  function startPolling(_pid: string, _roundId: string) {
    // C5：本地 orchestrator + eventBus 已实时推进；保留 stub 让旧 view 不报错。
    // 仅在断电恢复 / 进入页面时调一次 refreshRoundStatus 即可。
  }

  function stopPolling() {
    // no-op；保留 API 不破坏调用方
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
    Object.keys(feedbackDrafts).forEach((k) => delete feedbackDrafts[k])
  }

  // 兼容旧 view：暴露 useProjectStore 引用让 store 内部能取 title（applyMemoryUpdate 接通时用）
  void useProjectStore

  return {
    currentRound,
    rounds,
    documents,
    sourceStats,
    feedbackDrafts,
    loading,
    isStarting,
    ratedCount,
    sseConnected,
    streamingDocs,
    statusText,
    handleSSEEvent,
    keywordPlan,
    awaitingKeywordConfirmation,
    fetchRounds,
    startRound,
    prepareRound,
    confirmKeywords,
    refreshRoundStatus,
    startPolling,
    stopPolling,
    loadRoundResults,
    setFeedback,
    submitFeedback,
    finalizeRound,
    classifyDocument,
    reset,
  }
})
