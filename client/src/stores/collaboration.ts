/**
 * Collaboration store —— C5：协作研究模式由客户端 ResearchAgent + ProbeAgent 接管。
 *
 * 之前：调 `collaborationApi.start/question/resumePlan/updateDocs/refresh/exit/getNote/saveNote`，
 * 全部 backend HTTP，LLM 在 worker 端。
 * 现在：
 *   - start：装载 docIds 对应的 LocalDocument + 对应的 fulltext_text；不再请求 backend 创建
 *     server-side session，仅在客户端持有 sessionId（复用 conversation.sessionId）
 *   - askQuestion：构造 LibraryDoc[] 喂 ResearchAgent.respond → ResearchResult；
 *     answer + citations 通过 conversation store 注入富消息
 *   - resumePlan：B11 没有 plan→resume 双阶段；保留 API stub
 *   - getNote / saveNote：协作笔记和 notebook 共用 research_note_pages 表（复用项目级 notebook
 *     第一页作为协作 note，后续可拆专用 page_id）
 *   - exit：清状态；archive 仅 noop（本地无云端归档）
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { ProbeAgent } from '@/data/agents/probeAgent'
import { ResearchAgent, type LibraryDoc as AgentLibraryDoc, type ResearchResult } from '@/data/agents/researchAgent'
import { llmManager } from '@/data/llm/manager'
import {
  listClassificationsByProject,
  type ClientBucket,
} from '@/data/sqlite/repos/bucketRepo'
import { getDocumentsByIds } from '@/data/sqlite/repos/documentRepo'
import {
  listPagesByProject,
  upsertNotebookPage,
} from '@/data/sqlite/repos/notebookRepo'
import type { LocalDocument } from '@/types/local'

export type CollaborationState = 'off' | 'selecting' | 'active'

export interface CollaborationDoc {
  id: string
  title: string
  source: string
  bucket: string
  one_line_summary?: string
  fulltext_status?: string
  ai_summary?: string
}

export interface CollaborationSnapshot {
  docs: CollaborationDoc[]
  graph_nodes: number
  memory_sync_at?: string
}

export interface ResearchNote {
  content: string
  updated_at: string | null
  updated_by: 'ai' | 'user' | null
}

export interface LastAiNoteUpdate {
  mode: 'append' | 'replace' | 'patch'
  reason: string
  prev_len: number
  new_len: number
  preview: string
  at: string
}

const _COLLAB_NOTE_TITLE = '协作研究笔记'

function _docToCollabDoc(d: LocalDocument, bucket: ClientBucket | null): CollaborationDoc {
  return {
    id: d.id,
    title: d.title,
    source: d.source,
    bucket: bucket ?? 'uncategorized',
    one_line_summary: d.one_line_summary_user ?? d.one_line_summary ?? undefined,
    fulltext_status: d.fulltext_status,
    ai_summary: d.ai_summary_user ?? d.ai_summary ?? undefined,
  }
}

function _docToAgentDoc(d: LocalDocument): AgentLibraryDoc {
  return {
    docId: d.id,
    title: d.title,
    abstract: d.abstract ?? '',
    score: d.quality_score ?? undefined,
    fulltext: d.fulltext_text ?? undefined,
    keyPoints: d.ai_key_points_user ?? d.ai_key_points ?? undefined,
  }
}

export const useCollaborationStore = defineStore('collaboration', () => {
  const state = ref<CollaborationState>('off')
  const sessionId = ref<string | null>(null)
  const projectId = ref<string | null>(null)
  const docIds = ref<string[]>([])
  const snapshot = ref<CollaborationSnapshot | null>(null)
  const pendingSelection = ref<{ candidate_docs: CollaborationDoc[] } | null>(null)
  const isAsking = ref(false)
  const error = ref<string | null>(null)
  const note = ref<ResearchNote>({ content: '', updated_at: null, updated_by: null })
  const noteLoading = ref(false)
  const noteSaving = ref(false)
  const notePanelOpen = ref(false)
  const lastAiNoteUpdate = ref<LastAiNoteUpdate | null>(null)
  const autoMode = ref(false)
  /** 最近一次 ResearchAgent 跑出来的结果，给富消息渲染。 */
  const lastResearchResult = ref<ResearchResult | null>(null)

  const docs = computed(() => snapshot.value?.docs || [])
  const docCount = computed(() => docIds.value.length)
  const isActive = computed(() => state.value === 'active')

  function reset() {
    state.value = 'off'
    sessionId.value = null
    projectId.value = null
    docIds.value = []
    snapshot.value = null
    pendingSelection.value = null
    isAsking.value = false
    error.value = null
    note.value = { content: '', updated_at: null, updated_by: null }
    noteLoading.value = false
    noteSaving.value = false
    notePanelOpen.value = false
    lastAiNoteUpdate.value = null
    autoMode.value = false
    lastResearchResult.value = null
  }

  async function _buildSnapshot(pid: string, ids: string[]): Promise<CollaborationSnapshot> {
    const classifications = await listClassificationsByProject(pid)
    const bucketByDoc = new Map<string, ClientBucket>()
    for (const c of classifications) bucketByDoc.set(c.document_id, c.bucket)
    const docsList = await getDocumentsByIds(ids)
    return {
      docs: docsList.map((d) => _docToCollabDoc(d, bucketByDoc.get(d.id) ?? null)),
      graph_nodes: 0,
      memory_sync_at: new Date().toISOString(),
    }
  }

  function clearPending() {
    pendingSelection.value = null
    if (state.value === 'selecting') state.value = 'off'
  }

  async function startCollaboration(
    sid: string,
    ids: string[],
    forProjectId?: string,
  ): Promise<CollaborationSnapshot> {
    error.value = null
    const pid = forProjectId ?? projectId.value
    if (!pid) {
      throw new Error('startCollaboration requires projectId (pass it in or set via setProjectId)')
    }
    sessionId.value = sid
    projectId.value = pid
    docIds.value = ids
    const snap = await _buildSnapshot(pid, ids)
    snapshot.value = snap
    state.value = 'active'
    pendingSelection.value = null
    return snap
  }

  function setProjectId(pid: string) {
    projectId.value = pid
  }

  /**
   * 用本地 ResearchAgent 回答用户问题。
   *
   * 输入：当前 docIds 对应的 LocalDocument（带 fulltext_text 用于 probe）
   * 返回：ResearchResult（answer markdown + citations + actions trace）
   */
  async function askQuestion(
    question: string,
    history?: Array<{ role: string; content: string }>,
  ): Promise<ResearchResult | null> {
    const pid = projectId.value
    if (!pid) {
      error.value = 'projectId 未设置'
      return null
    }
    if (!question.trim()) return null
    isAsking.value = true
    error.value = null
    try {
      const docs = await getDocumentsByIds(docIds.value)
      const agentDocs = docs.map(_docToAgentDoc)
      const probe = new ProbeAgent(llmManager)
      const research = new ResearchAgent(llmManager, probe)
      const result = await research.respond({
        userQuestion: question,
        libraryDocs: agentDocs,
        conversationHistory: history,
      })
      lastResearchResult.value = result
      return result
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '问答失败'
      return null
    } finally {
      isAsking.value = false
    }
  }

  /**
   * resumePlan：B11 ResearchAgent 是单循环；这里保留 API stub，把 picks 转成下一次
   * askQuestion 的提示。caller 可以选择忽略。
   */
  async function resumePlan(
    picks: Array<{ doc_id: string; reason?: string }>,
    _kgQueries: Array<{ entity: string; entity_id?: string; node_type?: string; reason?: string }>,
    autoFromNow: boolean,
    _selectedExcerptKeys: string[] | null = null,
  ): Promise<{ accepted: boolean; picks: Array<{ doc_id: string; reason?: string }> } | null> {
    if (!sessionId.value) return null
    if (autoFromNow) autoMode.value = true
    return { accepted: true, picks }
  }

  // ─────────────── Note (复用 notebook 第一页) ───────────────

  async function _findOrCreateCollabNotePageId(): Promise<{ pageId: string; pid: string } | null> {
    const pid = projectId.value
    if (!pid) return null
    const pages = await listPagesByProject(pid)
    let page = pages.find((p) => p.title === _COLLAB_NOTE_TITLE)
    if (!page) {
      const now = Date.now()
      page = {
        id: `local-${crypto.randomUUID()}`,
        project_id: pid,
        title: _COLLAB_NOTE_TITLE,
        body_md: '',
        sort_order: pages.length,
        updated_at: now,
        updated_by: 'user',
        created_at: now,
        last_synced_at: null,
      }
      await upsertNotebookPage(page)
    }
    return { pageId: page.id, pid }
  }

  async function fetchNote(): Promise<ResearchNote | null> {
    noteLoading.value = true
    try {
      const ref0 = await _findOrCreateCollabNotePageId()
      if (!ref0) return null
      const pages = await listPagesByProject(ref0.pid)
      const page = pages.find((p) => p.id === ref0.pageId)
      if (!page) return null
      note.value = {
        content: page.body_md,
        updated_at: page.updated_at ? new Date(page.updated_at).toISOString() : null,
        updated_by: (page.updated_by as ResearchNote['updated_by']) ?? null,
      }
      return note.value
    } finally {
      noteLoading.value = false
    }
  }

  async function saveNote(content: string): Promise<ResearchNote | null> {
    noteSaving.value = true
    try {
      const ref0 = await _findOrCreateCollabNotePageId()
      if (!ref0) return null
      const pages = await listPagesByProject(ref0.pid)
      const page = pages.find((p) => p.id === ref0.pageId)
      if (!page) return null
      const now = Date.now()
      await upsertNotebookPage({
        ...page,
        body_md: content,
        updated_at: now,
        updated_by: 'user',
      })
      note.value = {
        content,
        updated_at: new Date(now).toISOString(),
        updated_by: 'user',
      }
      return note.value
    } finally {
      noteSaving.value = false
    }
  }

  function openNotePanel() {
    notePanelOpen.value = true
    if (sessionId.value) fetchNote().catch(() => { /* ignore */ })
  }

  function closeNotePanel() {
    notePanelOpen.value = false
  }

  function dismissAiNoteUpdate() {
    lastAiNoteUpdate.value = null
  }

  async function updateDocs(action: 'add' | 'remove' | 'replace', ids: string[]): Promise<{ doc_ids: string[]; snapshot: CollaborationSnapshot } | null> {
    const pid = projectId.value
    if (!sessionId.value || !pid) return null
    let nextIds: string[]
    if (action === 'replace') {
      nextIds = [...ids]
    } else if (action === 'add') {
      nextIds = Array.from(new Set([...docIds.value, ...ids]))
    } else {
      const remove = new Set(ids)
      nextIds = docIds.value.filter((x) => !remove.has(x))
    }
    docIds.value = nextIds
    const snap = await _buildSnapshot(pid, nextIds)
    snapshot.value = snap
    return { doc_ids: nextIds, snapshot: snap }
  }

  async function refresh(): Promise<{ snapshot: CollaborationSnapshot; doc_ids: string[] } | null> {
    const pid = projectId.value
    if (!sessionId.value || !pid) return null
    const snap = await _buildSnapshot(pid, docIds.value)
    snapshot.value = snap
    return { snapshot: snap, doc_ids: docIds.value }
  }

  async function exitCollaboration(_archive: boolean): Promise<void> {
    if (!sessionId.value) return
    try {
      // 本地无 archive 概念；直接清状态
      reset()
      // 同步 conversation store 视图，避免 banner 不一致
      try {
        const { useConversationStore } = await import('./conversation')
        const conv = useConversationStore()
        await conv.refreshMessages()
      } catch { /* noop */ }
    } catch (e) {
      console.warn('[collaboration] exit failed:', e)
    }
  }

  async function restoreFromSession(sid: string, sessionData: unknown): Promise<void> {
    const sd = (sessionData as { state_data?: Record<string, unknown>; current_state?: string }) ?? {}
    const collab = sd.state_data?.collaboration as
      | {
          archived?: boolean
          doc_ids?: string[]
          auto_mode?: boolean
          project_id?: string
        }
      | undefined
    if (!collab || collab.archived) return
    sessionId.value = sid
    docIds.value = collab.doc_ids ?? []
    autoMode.value = !!collab.auto_mode
    if (collab.project_id) projectId.value = collab.project_id
    state.value = sd.current_state === 'collaboration_active' ? 'active' : 'off'
    if (state.value === 'active' && projectId.value) {
      try {
        const snap = await _buildSnapshot(projectId.value, docIds.value)
        snapshot.value = snap
      } catch { /* ignore */ }
    }
  }

  function setSelecting(candidates: CollaborationDoc[]) {
    pendingSelection.value = { candidate_docs: candidates }
    state.value = 'selecting'
  }

  return {
    state,
    sessionId,
    projectId,
    docIds,
    snapshot,
    pendingSelection,
    isAsking,
    error,
    docs,
    docCount,
    isActive,
    note,
    noteLoading,
    noteSaving,
    notePanelOpen,
    lastAiNoteUpdate,
    autoMode,
    lastResearchResult,
    setProjectId,
    reset,
    clearPending,
    startCollaboration,
    askQuestion,
    resumePlan,
    updateDocs,
    refresh,
    exitCollaboration,
    restoreFromSession,
    setSelecting,
    fetchNote,
    saveNote,
    openNotePanel,
    closeNotePanel,
    dismissAiNoteUpdate,
  }
})
