import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { collaborationApi } from '../api/client'

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
  at: string // client-side ISO
}

export const useCollaborationStore = defineStore('collaboration', () => {
  const state = ref<CollaborationState>('off')
  const sessionId = ref<string | null>(null)
  const docIds = ref<string[]>([])
  const snapshot = ref<{ docs: CollaborationDoc[]; graph_nodes: number; memory_sync_at?: string } | null>(null)
  const pendingSelection = ref<{ candidate_docs: CollaborationDoc[] } | null>(null)
  const isAsking = ref(false)
  const error = ref<string | null>(null)
  // 共享研究笔记
  const note = ref<ResearchNote>({ content: '', updated_at: null, updated_by: null })
  const noteLoading = ref(false)
  const noteSaving = ref(false)
  const notePanelOpen = ref(false)
  const lastAiNoteUpdate = ref<LastAiNoteUpdate | null>(null)
  // vibe / auto：初次进入协作默认 vibe；一旦用户点"自动模式继续"就变 true，退出后清
  const autoMode = ref(false)

  const docs = computed(() => snapshot.value?.docs || [])
  const docCount = computed(() => docIds.value.length)
  const isActive = computed(() => state.value === 'active')

  function reset() {
    state.value = 'off'
    sessionId.value = null
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
  }

  async function _consumeNoteUpdate(res: any) {
    const nu = res?.note_update
    if (!nu || typeof nu !== 'object') return
    // 新结构：{mode: create_page|update_page|append_to_page, page_id, title, ...}
    // 交给 notebook store 负责刷新 pages、切换到被写入的页、显示 toast
    try {
      const { useNotebookStore } = await import('./notebook')
      const nb = useNotebookStore()
      nb.applyAiUpdate(nu)
    } catch { /* ignore */ }
  }

  async function resumePlan(
    picks: Array<{ doc_id: string; reason?: string }>,
    kgQueries: Array<{ entity: string; entity_id?: string; node_type?: string; reason?: string }>,
    autoFromNow: boolean,
    selectedExcerptKeys: string[] | null = null,
  ) {
    if (!sessionId.value) return null
    isAsking.value = true
    error.value = null
    try {
      const res = await collaborationApi.resumePlan(
        sessionId.value, picks, kgQueries, autoFromNow, selectedExcerptKeys,
      )
      if (autoFromNow) autoMode.value = true
      _consumeNoteUpdate(res.data)
      return res.data
    } catch (e: any) {
      error.value = e?.response?.data?.detail || '继续调研失败'
      throw e
    } finally {
      isAsking.value = false
    }
  }

  function clearPending() {
    pendingSelection.value = null
    if (state.value === 'selecting') state.value = 'off'
  }

  async function startCollaboration(sid: string, ids: string[]) {
    error.value = null
    try {
      const res = await collaborationApi.start(sid, ids)
      sessionId.value = sid
      docIds.value = ids
      snapshot.value = res.data.snapshot
      state.value = 'active'
      pendingSelection.value = null
      return res.data
    } catch (e: any) {
      error.value = e?.response?.data?.detail || '进入协作模式失败'
      throw e
    }
  }

  async function askQuestion(question: string) {
    if (!sessionId.value) return null
    isAsking.value = true
    error.value = null
    try {
      const res = await collaborationApi.question(sessionId.value, question)
      // auto 模式或无需精读 → 后端直接返回 answer；此时有 note_update 要消费
      // vibe 模式 → 后端返回 {state: "awaiting_plan", plan: {...}}，ReadPlanBubble 会由
      // 下一次 refreshMessages 拉下来渲染
      if (res.data?.ok || res.data?.answer) {
        _consumeNoteUpdate(res.data)
      }
      return res.data
    } catch (e: any) {
      error.value = e?.response?.data?.detail || '问答失败'
      throw e
    } finally {
      isAsking.value = false
    }
  }

  async function fetchNote() {
    if (!sessionId.value) return null
    noteLoading.value = true
    try {
      const res = await collaborationApi.getNote(sessionId.value)
      note.value = {
        content: res.data.content || '',
        updated_at: res.data.updated_at,
        updated_by: res.data.updated_by,
      }
      return note.value
    } finally {
      noteLoading.value = false
    }
  }

  async function saveNote(content: string) {
    if (!sessionId.value) return null
    noteSaving.value = true
    try {
      const res = await collaborationApi.saveNote(sessionId.value, content)
      note.value = {
        content: res.data.content,
        updated_at: res.data.updated_at,
        updated_by: 'user',
      }
      return note.value
    } finally {
      noteSaving.value = false
    }
  }

  function openNotePanel() {
    notePanelOpen.value = true
    // 打开时刷新一次（若 sessionId 已就绪）
    if (sessionId.value) fetchNote().catch(() => { /* ignore */ })
  }

  function closeNotePanel() {
    notePanelOpen.value = false
  }

  function dismissAiNoteUpdate() {
    lastAiNoteUpdate.value = null
  }

  async function updateDocs(action: 'add' | 'remove' | 'replace', ids: string[]) {
    if (!sessionId.value) return
    const res = await collaborationApi.updateDocs(sessionId.value, action, ids)
    docIds.value = res.data.doc_ids
    snapshot.value = res.data.snapshot
    return res.data
  }

  async function refresh() {
    if (!sessionId.value) return
    const res = await collaborationApi.refresh(sessionId.value)
    snapshot.value = res.data.snapshot
    docIds.value = res.data.doc_ids
    return res.data
  }

  async function exitCollaboration(archive: boolean) {
    if (!sessionId.value) return
    try {
      await collaborationApi.exit(sessionId.value, archive)
    } finally {
      reset()
      // 同步 conversation store 的 currentState / messages，避免 banner 消失后底部按钮仍判断"在协作中"
      try {
        const { useConversationStore } = await import('./conversation')
        const conv = useConversationStore()
        await conv.refreshMessages()
      } catch { /* noop */ }
    }
  }

  async function restoreFromSession(sid: string, sessionData: any) {
    // Called when the user re-opens a project with existing collaboration state
    const collab = sessionData?.state_data?.collaboration
    if (!collab || collab.archived) return
    sessionId.value = sid
    docIds.value = collab.doc_ids || []
    autoMode.value = !!collab.auto_mode
    state.value = sessionData.current_state === 'collaboration_active' ? 'active' : 'off'
    if (state.value === 'active') {
      // Refresh snapshot on re-entry
      try {
        await refresh()
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
