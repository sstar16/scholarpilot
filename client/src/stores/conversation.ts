/**
 * Conversation store —— C5：对话历史 / session 走本地 SQLite。
 *
 * 之前：`conversationApi.start/sendMessage/confirm/getSession/getByProject`，全 backend，
 * Celery worker 通过 SSE 注入富消息。
 * 现在：
 *   - sessions / messages CRUD：conversationRepo（conversation_sessions / messages 表）
 *   - LLM 文本响应：客户端 LLMManager（assistant 普通回答）
 *   - 富消息（keyword_confirmation / round_complete / collaboration_*）：由具体 phase /
 *     skill 触发后通过 eventBus 注入；store 提供 `appendIncomingMessage` 入口
 *   - 状态机（intent / search_mode / collaboration）：state 字段保留，转移由调用方决定
 *
 * 不再依赖：backend 任何 conversationApi。`projectId` 仍由 view 传入。
 */
import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

import {
  appendMessage,
  getActiveSessionForProject,
  getSession,
  listMessages,
  setSessionActive,
  upsertMessage,
  upsertSession,
} from '@/data/sqlite/repos/conversationRepo'
import { upsertProject } from '@/data/sqlite/repos/projectRepo'
import { llmManager } from '@/data/llm/manager'
import { IntentAgent, type IntentResult } from '@/data/agents/intentAgent'
import { loadPrompt } from '@/data/agents/promptLoader'
import type { LLMManagerLike } from '@/data/agents/types'
import type { LocalMessage, LocalConversationSession, LocalProject } from '@/types/local'

export interface ChatMessage {
  id?: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  metadata?: Record<string, unknown>
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
  rich_data?: Record<string, unknown>
}

export interface ConfirmationEnvelope {
  confirmation_id: string
  agent_name: string
  action_type: string
  summary_zh: string
  details: Record<string, unknown>
  options: string[]
  auto_confirmable: boolean
}

function _genId(): string {
  return `local-${crypto.randomUUID()}`
}

function _localToChat(m: LocalMessage): ChatMessage {
  const richData = m.rich_data
  const richType =
    richData && typeof richData === 'object' && 'type' in richData
      ? (richData as { type?: string }).type
      : undefined
  return {
    id: m.id,
    role: m.role,
    content: m.content_md,
    timestamp: new Date(m.created_at).toISOString(),
    metadata: (richData ?? null) as Record<string, unknown> | undefined,
    rich_type: richType as ChatMessage['rich_type'] | undefined,
    rich_data: (richData ?? null) as Record<string, unknown> | undefined,
  }
}

export const useConversationStore = defineStore('conversation', () => {
  const sessionId = ref<string | null>(null)
  const currentState = ref<string>('idle')
  const messages = shallowRef<ChatMessage[]>([])
  const pendingConfirmation = ref<ConfirmationEnvelope | null>(null)
  const searchMode = ref<string | null>(null)
  const projectId = ref<string | null>(null)
  const isAgentThinking = ref(false)
  const error = ref<string | null>(null)

  const hasSession = computed(() => !!sessionId.value)
  const isIdle = computed(() => currentState.value === 'idle')
  const isConfirming = computed(() =>
    ['intent_confirmation', 'search_mode_selection'].includes(currentState.value),
  )

  function _hydrateFromSession(s: LocalConversationSession, msgs: LocalMessage[]) {
    sessionId.value = s.id
    currentState.value = s.current_state
    projectId.value = s.project_id
    searchMode.value = s.search_mode
    messages.value = msgs.map(_localToChat)
    const sd = s.state_data as Record<string, unknown> | null
    if (sd && sd.pending_envelope) {
      pendingConfirmation.value = sd.pending_envelope as ConfirmationEnvelope
    } else {
      pendingConfirmation.value = null
    }
  }

  async function startSession(existingProjectId?: string): Promise<void> {
    const now = Date.now()
    const sid = _genId()
    const session: LocalConversationSession = {
      id: sid,
      project_id: existingProjectId ?? null,
      current_state: 'idle',
      state_data: null,
      search_mode: null,
      is_active: true,
      created_at: now,
      updated_at: now,
      last_synced_at: null,
    }
    await upsertSession(session)
    if (existingProjectId) {
      await setSessionActive(sid)
    }
    _hydrateFromSession(session, [])
  }

  async function restoreSession(sid: string): Promise<void> {
    const s = await getSession(sid)
    if (!s) {
      error.value = '会话不存在'
      throw new Error('session not found')
    }
    const msgs = await listMessages(sid)
    _hydrateFromSession(s, msgs)
  }

  function addLocalMessage(
    role: ChatMessage['role'],
    content: string,
    metadata?: Record<string, unknown>,
  ) {
    messages.value = [
      ...messages.value,
      {
        role,
        content,
        timestamp: new Date().toISOString(),
        metadata,
      },
    ]
  }

  /**
   * Append a message arriving from event bus / phase callback.
   * Dedups by id so that the same message arriving twice is a no-op.
   */
  function appendIncomingMessage(msg: ChatMessage) {
    if (msg.id) {
      const existing = messages.value.find((m) => m.id === msg.id)
      if (existing) return
    }
    messages.value = [...messages.value, msg]
  }

  function updateLastAssistantMeta(patch: Record<string, unknown>) {
    const arr = messages.value
    for (let i = arr.length - 1; i >= 0; i--) {
      const m = arr[i]
      if (m.role === 'assistant' && !m.rich_type) {
        const newMsg = { ...m, metadata: { ...(m.metadata || {}), ...patch } }
        const newArr = arr.slice()
        newArr[i] = newMsg
        messages.value = newArr
        return
      }
    }
  }

  async function _persistMessage(msg: ChatMessage): Promise<LocalMessage | null> {
    if (!sessionId.value) return null
    try {
      return await appendMessage({
        session_id: sessionId.value,
        role: msg.role,
        content_md: msg.content ?? '',
        rich_data: (msg.rich_data ?? msg.metadata ?? null) as Record<string, unknown> | null,
        created_at: msg.timestamp ? Date.parse(msg.timestamp) : Date.now(),
      })
    } catch (e) {
      console.warn('[conversation] persist message failed:', e)
      return null
    }
  }

  /**
   * 用户发消息 — 默认态走 IntentAgent 路由：
   *   - is_research_request → 直接创建 project + 转入 keyword_confirmation 让上层跳页
   *   - 否则 → 用 intent.reply（小猫文案）回；LLM 不再二次调用，避免双倍 token
   *
   * 已绑 project / 非 idle 状态：sendMessage 不路由，由具体流程态接管（phase / skill）；
   * 若未绑 phase 钩子，退化为普通 LLM 闲聊回答。
   *
   * 富消息（keyword_confirmation / round_complete / ...）走 `appendIncomingMessage`。
   */
  async function sendMessage(content: string): Promise<void> {
    if (!sessionId.value || !content.trim()) return
    isAgentThinking.value = true
    error.value = null

    const userMsg: ChatMessage = {
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
    }
    addLocalMessage(userMsg.role, userMsg.content)
    const userPersisted = await _persistMessage(userMsg)
    if (userPersisted) {
      const arr = messages.value.slice()
      arr[arr.length - 1] = { ...userMsg, id: userPersisted.id }
      messages.value = arr
    }

    try {
      // 路由：默认态（idle）+ 未绑 project → 意图分类
      if (currentState.value === 'idle' && !projectId.value) {
        const intent = await _runIntentAgent(content)
        const userIntent = intent?.intent ?? 'chat'

        if (userIntent === 'start_search' && intent?.is_research_request && intent.title) {
          await _startResearchFromIntent(intent)
          return
        }

        if (userIntent === 'start_collaboration') {
          const replyText = intent?.reply || '喵~协作研究模式需要先在已有项目里发起，请先进入一个项目再触发协作。'
          await _appendAssistantText(replyText)
          return
        }

        if (userIntent === 'start_pdf_import') {
          const replyText = intent?.reply || '喵~请点击聊天框上方的 PDF 上传按钮来导入文献。'
          await _appendAssistantText(replyText)
          return
        }

        if (userIntent === 'configure_push') {
          const replyText = intent?.reply || '喵~定时推送功能请进入项目后在右侧面板配置。'
          await _appendAssistantText(replyText)
          return
        }

        // chat / fallback
        const replyText = intent?.reply || (await _chatReply(content))
        await _appendAssistantText(replyText)
        return
      }

      // 已绑 project（有项目上下文）：也走 intent 路由
      if (currentState.value === 'idle' && projectId.value) {
        const intent = await _runIntentAgent(content)
        const userIntent = intent?.intent ?? 'chat'

        if (userIntent === 'start_search' && intent?.is_research_request && intent.title) {
          await _startResearchFromIntent(intent)
          return
        }

        if (userIntent === 'start_collaboration') {
          currentState.value = 'collaboration_active'
          const replyText = intent?.reply || '好的喵！进入协作研究模式，我们一起分析文献库~'
          await _appendAssistantText(replyText)
          return
        }

        if (userIntent === 'start_pdf_import') {
          const replyText = intent?.reply || '喵~请点击聊天框上方的 PDF 上传按钮来导入文献。'
          await _appendAssistantText(replyText)
          return
        }

        if (userIntent === 'configure_push') {
          const replyText = intent?.reply || '喵~定时推送功能请点击右上角的定时推送按钮配置。'
          await _appendAssistantText(replyText)
          return
        }

        // chat fallback
        const replyText = intent?.reply || (await _chatReply(content))
        await _appendAssistantText(replyText)
        return
      }

      // 非 idle：普通聊天回答（流程态由 phase 推进）
      const replyText = await _chatReply(content)
      await _appendAssistantText(replyText)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : '生成失败'
      error.value = msg
      addLocalMessage('assistant', `[错误] ${msg}`)
    } finally {
      isAgentThinking.value = false
      if (sessionId.value) {
        try {
          await upsertSession({
            id: sessionId.value,
            project_id: projectId.value,
            current_state: currentState.value,
            state_data: null,
            search_mode: searchMode.value,
            is_active: true,
            created_at: Date.now(),
            updated_at: Date.now(),
            last_synced_at: null,
          })
        } catch (err) {
          console.warn('[conversation] session upsert failed:', err)
        }
      }
    }
  }

  async function _runIntentAgent(userInput: string): Promise<IntentResult | null> {
    const agent = new IntentAgent(llmManager as unknown as LLMManagerLike)
    const supplementaryContext = `当前对话状态：${currentState.value}。若状态为 collaboration_active，用户多半在继续协作；若 idle 且无 project，多半是新研究方向。`
    return agent.analyze({ userInput, supplementaryContext })
  }

  async function _chatReply(content: string): Promise<string> {
    const pf = loadPrompt('agents/chat_system')
    const prompt = pf.render({ user_input: content })
    const temperature = Number(pf.get('temperature', 0.5)) || 0.5
    const result = await llmManager.generate(prompt, { temperature })
    const text = result && typeof result === 'object' && 'text' in result
      ? String((result as { text?: unknown }).text ?? '')
      : ''
    return text || '（LLM 未返回内容；请检查 BYOK 配置）'
  }

  async function _appendAssistantText(text: string): Promise<void> {
    const msg: ChatMessage = {
      role: 'assistant',
      content: text,
      timestamp: new Date().toISOString(),
    }
    addLocalMessage(msg.role, msg.content)
    const persisted = await _persistMessage(msg)
    if (persisted) {
      const arr = messages.value.slice()
      arr[arr.length - 1] = { ...msg, id: persisted.id }
      messages.value = arr
    }
  }

  async function _startResearchFromIntent(intent: IntentResult): Promise<void> {
    const now = Date.now()
    const pid = _genId()
    const project: LocalProject = {
      id: pid,
      title: (intent.title ?? '').slice(0, 100) || '未命名研究',
      description: intent.description ?? '',
      domain: intent.domains?.[0] ?? 'interdisciplinary',
      domains: intent.domains ?? null,
      search_config: {
        doc_types: intent.doc_types ?? 'literature',
        scope: intent.scope ?? 'international',
        year_focus: intent.year_focus ?? 'recent',
        suggested_sources: intent.suggested_sources ?? [],
        key_concepts: intent.key_concepts ?? [],
      },
      current_round: 0,
      max_rounds: 10,
      status: 'active',
      research_note_md: '',
      research_note_updated_at: null,
      research_note_updated_by: null,
      created_at: now,
      updated_at: now,
      last_synced_at: null,
    }
    await upsertProject(project)
    projectId.value = pid

    // 先把 session 绑到 project_id（让跳页后 ProjectView 能 findOrCreateSession 拿到）
    if (sessionId.value) {
      await upsertSession({
        id: sessionId.value,
        project_id: pid,
        current_state: 'idle',
        state_data: null,
        search_mode: searchMode.value,
        is_active: true,
        created_at: now,
        updated_at: now,
        last_synced_at: null,
      })
      await setSessionActive(sessionId.value)
    }

    // 先持久化 summary（必须在切 currentState 触发跳页前完成，否则跨页会丢）
    const summary
      = `✓ 已为你建立研究项目「${project.title}」\n`
      + `  · 学科：${(intent.domains ?? []).join(' / ') || 'interdisciplinary'}\n`
      + `  · 文献类型：${intent.doc_types ?? 'literature'}\n`
      + `  · 范围：${intent.scope ?? 'international'}\n`
      + `\nAI 正在为首轮检索生成关键词方案，预计 10-30 秒。生成后会弹出关键词确认气泡，你可以编辑后开始检索。`
    await _appendAssistantText(summary)

    // 最后切状态触发 ConversationCreate watcher 跳页（此时 summary 已写入 SQLite）
    currentState.value = 'keyword_confirmation'
    if (sessionId.value) {
      await upsertSession({
        id: sessionId.value,
        project_id: pid,
        current_state: 'keyword_confirmation',
        state_data: null,
        search_mode: searchMode.value,
        is_active: true,
        created_at: now,
        updated_at: Date.now(),
        last_synced_at: null,
      })
    }
  }

  async function confirmDecision(
    action: string,
    options?: {
      supplementText?: string
      edits?: Record<string, unknown>
      searchMode?: string
    },
  ): Promise<{ state: string; action: string; supplementText?: string }> {
    if (!sessionId.value || !pendingConfirmation.value) {
      return { state: currentState.value, action }
    }
    isAgentThinking.value = true
    error.value = null
    try {
      // C5：本地不再调 backend confirm；只清 envelope，留 state 给上层 phase 接管
      const cur = pendingConfirmation.value
      pendingConfirmation.value = null
      const summary = `[确认] ${cur.summary_zh} → ${action}`
      addLocalMessage('user', summary, { type: 'confirmation_response', action })
      if (options?.searchMode) {
        searchMode.value = options.searchMode
      }
      return { state: currentState.value, action, supplementText: options?.supplementText }
    } finally {
      isAgentThinking.value = false
    }
  }

  async function selectSearchMode(mode: string) {
    return confirmDecision(mode, { searchMode: mode })
  }

  async function refreshMessages(): Promise<void> {
    if (!sessionId.value) return
    try {
      const msgs = await listMessages(sessionId.value)
      messages.value = msgs.map(_localToChat)
    } catch (e) {
      console.warn('[conversation] refreshMessages failed:', e)
    }
  }

  async function findOrCreateSession(forProjectId: string): Promise<void> {
    error.value = null
    const existing = await getActiveSessionForProject(forProjectId)
    if (existing) {
      const msgs = await listMessages(existing.id)
      _hydrateFromSession(existing, msgs)
      return
    }
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

  // 公开给富消息 / phase 显式持久化用（一般不直接用）
  async function persistAssistantMessage(content: string, richData?: Record<string, unknown>): Promise<ChatMessage | null> {
    if (!sessionId.value) return null
    const msg: ChatMessage = {
      role: 'assistant',
      content,
      timestamp: new Date().toISOString(),
      rich_data: richData,
    }
    const persisted = await _persistMessage(msg)
    if (persisted) {
      const final: ChatMessage = { ...msg, id: persisted.id }
      appendIncomingMessage(final)
      return final
    }
    return null
  }

  // 维持兼容：旧 view 调过 upsertMessage —— 暴露但不让外部直接用
  void upsertMessage

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
    persistAssistantMessage,
    reset,
  }
})
