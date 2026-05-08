import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { conversationApi } from '../api/client'
import { useRouter } from 'vue-router'

export interface ChatMessage {
  id?: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  metadata?: Record<string, any>
  rich_type?:
    | 'keyword_confirmation'
    | 'search_progress'
    | 'round_results'
    | 'round_complete'
    | 'document_snippet'
    | 'collaboration_scope'
    | 'collaboration_started'
    | 'collaboration_read_plan'
    | 'collaboration_answer'
    | 'collaboration_ended'
    | 'card_update_suggestion'
    | 'pdf_import_parsing'
    | 'pdf_import_editing'
    | 'pdf_import_scoring'
    | 'pdf_import_failed'
    | 'pdf_import_final_card'
    | 'pdf_import_cancelled'
    | 'skill_suggestion'
    | 'feature_gate_blocked'
    | 'feature_gate_allowed'
    | 'flow_exited'
  rich_data?: Record<string, any>
}

export interface ConfirmationEnvelope {
  confirmation_id: string
  agent_name: string
  action_type: string
  summary_zh: string
  details: Record<string, any>
  options: string[]
  auto_confirmable: boolean
}

export const useConversationStore = defineStore('conversation', () => {
  const sessionId = ref<string | null>(null)
  const currentState = ref<string>('idle')
  const messages = ref<ChatMessage[]>([])
  const pendingConfirmation = ref<ConfirmationEnvelope | null>(null)
  const searchMode = ref<string | null>(null)
  const projectId = ref<string | null>(null)
  const isAgentThinking = ref(false)
  const error = ref<string | null>(null)

  const hasSession = computed(() => !!sessionId.value)
  const isIdle = computed(() => currentState.value === 'idle')
  const isConfirming = computed(() =>
    ['intent_confirmation', 'search_mode_selection'].includes(currentState.value)
  )

  function addLocalMessage(role: ChatMessage['role'], content: string, metadata?: Record<string, any>) {
    messages.value.push({
      role,
      content,
      timestamp: new Date().toISOString(),
      metadata,
    })
  }

  /**
   * Append a message arriving from SSE (session_message_appended event).
   * Dedups by `id` so that if the same message is already in the store
   * (e.g. from API response polling or a double-SSE), we skip it.
   */
  function appendIncomingMessage(msg: ChatMessage) {
    if (msg.id) {
      const existing = messages.value.find((m) => m.id === msg.id)
      if (existing) return
    }
    messages.value.push(msg)
  }

  /** 更新最后一条 assistant 纯文本消息的 metadata（用于 token 追踪） */
  function updateLastAssistantMeta(patch: Record<string, any>) {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      const m = messages.value[i]
      if (m.role === 'assistant' && !m.rich_type) {
        m.metadata = { ...(m.metadata || {}), ...patch }
        return
      }
    }
  }

  async function startSession(existingProjectId?: string) {
    try {
      error.value = null
      const res = await conversationApi.start(
        existingProjectId ? { project_id: existingProjectId } : undefined
      )
      const session = res.data
      sessionId.value = session.id
      currentState.value = session.current_state
      messages.value = session.messages || []
      projectId.value = session.project_id
      searchMode.value = session.search_mode
    } catch (e: any) {
      error.value = e.response?.data?.detail || '创建对话失败'
      throw e
    }
  }

  async function restoreSession(sid: string) {
    try {
      error.value = null
      const res = await conversationApi.getSession(sid)
      const session = res.data
      sessionId.value = session.id
      currentState.value = session.current_state
      messages.value = session.messages || []
      projectId.value = session.project_id
      searchMode.value = session.search_mode
      // Restore pending confirmation from state_data
      if (session.state_data?.pending_envelope) {
        pendingConfirmation.value = session.state_data.pending_envelope
      }
    } catch (e: any) {
      error.value = '恢复对话失败'
      throw e
    }
  }

  async function sendMessage(content: string) {
    if (!sessionId.value || !content.trim()) return

    addLocalMessage('user', content)
    isAgentThinking.value = true
    error.value = null

    try {
      const res = await conversationApi.sendMessage(sessionId.value, content)
      const data = res.data
      currentState.value = data.state

      if (data.confirmation) {
        pendingConfirmation.value = data.confirmation
      } else {
        pendingConfirmation.value = null
      }

      // 只有后端明确返回 content 时才追加本地气泡。
      // 空 content 表示 handler 已通过 inject_rich_message + SSE 送达了气泡，
      // 前端通过 session_message_appended 事件已经 append 过了，不能重复。
      if (data.content) {
        addLocalMessage(data.role, data.content, {
          type: data.confirmation ? 'confirmation' : 'message',
        })
      } else {
        // SSE 可能因竞态/断连而漏掉气泡 — 从 DB 补偿
        await refreshMessages()
      }

      return data
    } catch (e: any) {
      error.value = e.response?.data?.detail || '发送消息失败'
      // 前端 axios timeout 常早于后端 LLM 实际响应 —— 后端可能已经通过
      // inject_rich_message 把 answer 写进 session.messages 了。
      // 先刷新确认真失败再报错，避免"明明成功却报 error 气泡"的误报。
      try { await refreshMessages() } catch { /* noop */ }
      throw e
    } finally {
      isAgentThinking.value = false
    }
  }

  async function confirmDecision(action: string, options?: {
    supplementText?: string
    edits?: Record<string, any>
    searchMode?: string
  }) {
    if (!sessionId.value || !pendingConfirmation.value) return

    isAgentThinking.value = true
    error.value = null

    try {
      const res = await conversationApi.confirm(sessionId.value, {
        confirmation_id: pendingConfirmation.value.confirmation_id,
        action,
        supplement_text: options?.supplementText,
        edits: options?.edits,
        search_mode: options?.searchMode,
      })

      const data = res.data
      currentState.value = data.state

      if (data.confirmation) {
        pendingConfirmation.value = data.confirmation
      } else {
        pendingConfirmation.value = null
      }

      // 与 sendMessage 保持一致：空 content 表示 bubbles 已通过 SSE 送达
      if (data.content) {
        addLocalMessage(data.role, data.content, { type: 'confirmation_response' })
      }

      // Extract project_id from message metadata if project was created
      if (data.state === 'search_mode_selection' || data.state === 'keyword_confirmation') {
        // Refresh session to get project_id
        const sessionRes = await conversationApi.getSession(sessionId.value)
        projectId.value = sessionRes.data.project_id
        searchMode.value = sessionRes.data.search_mode
      }

      return data
    } catch (e: any) {
      error.value = e.response?.data?.detail || '确认操作失败'
      throw e
    } finally {
      isAgentThinking.value = false
    }
  }

  async function selectSearchMode(mode: string) {
    return confirmDecision(mode, { searchMode: mode })
  }

  async function refreshMessages() {
    // 静默刷新 session messages — 用于轮询富消息更新（Celery worker 注入后）
    if (!sessionId.value) return
    try {
      const res = await conversationApi.getSession(sessionId.value)
      const s = res.data
      const incoming = s.messages || []
      // 只追加新消息，避免打断正在编辑的气泡
      if (incoming.length > messages.value.length) {
        // 保留本地 metadata（如 tokens/elapsed_ms）不被服务端覆盖
        const localMeta: Record<string, Record<string, any>> = {}
        for (const m of messages.value) {
          if (m.id && m.metadata?.tokens) localMeta[m.id] = m.metadata
        }
        for (const m of incoming) {
          if (m.id && localMeta[m.id]) m.metadata = { ...m.metadata, ...localMeta[m.id] }
        }
        messages.value = incoming
      }
      const stateChanged = s.current_state !== currentState.value
      if (stateChanged) {
        currentState.value = s.current_state
      }
      // state 变化时按服务端权威覆盖 pendingConfirmation（例如退出 keyword_confirmation 回退到
      // search_mode_selection 后，服务端会重建 mode 选择 envelope，前端要同步刷新）
      if (stateChanged) {
        pendingConfirmation.value = s.state_data?.pending_envelope || null
      } else if (s.state_data?.pending_envelope && !pendingConfirmation.value) {
        pendingConfirmation.value = s.state_data.pending_envelope
      }
    } catch { /* silent */ }
  }

  async function findOrCreateSession(forProjectId: string) {
    try {
      error.value = null
      const res = await conversationApi.getByProject(forProjectId)
      if (res.data?.session) {
        const s = res.data.session
        sessionId.value = s.id
        currentState.value = s.current_state
        messages.value = s.messages || []
        projectId.value = s.project_id
        searchMode.value = s.search_mode
        if (s.state_data?.pending_envelope) {
          pendingConfirmation.value = s.state_data.pending_envelope
        }
        return
      }
    } catch { /* no existing session */ }
    // Create new session linked to this project
    await startSession(forProjectId)
  }

  function reset() {
    sessionId.value = null
    currentState.value = 'idle'
    messages.value = []
    pendingConfirmation.value = null
    searchMode.value = null
    projectId.value = null
    isAgentThinking.value = false
    error.value = null
  }

  return {
    // State
    sessionId,
    currentState,
    messages,
    pendingConfirmation,
    searchMode,
    projectId,
    isAgentThinking,
    error,
    // Computed
    hasSession,
    isIdle,
    isConfirming,
    // Actions
    startSession,
    restoreSession,
    findOrCreateSession,
    sendMessage,
    confirmDecision,
    selectSearchMode,
    refreshMessages,
    appendIncomingMessage,
    updateLastAssistantMeta,
    reset,
  }
})
