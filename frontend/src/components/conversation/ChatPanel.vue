<template>
  <div class="chat-panel" ref="panelRef">
    <div class="chat-panel__messages" ref="scrollRef">
      <!-- Welcome message (only when no project / no messages) -->
      <div v-if="messages.length === 0" class="chat-panel__welcome">
        <div class="chat-panel__welcome-eyebrow">— ScholarPilot · 对话 —</div>
        <CatAvatar :size="72" class="chat-panel__welcome-cat" />
        <p>用自然语言描述您的研究需求</p>
        <p class="sub">例如："我想研究 Transformer 推理加速"或"全固态锂电池正极界面"</p>
      </div>

      <!-- Messages -->
      <!-- v-for key 用复合 key (msg.id 优先, fallback 到 rich_type+round_id+idx)
           确保多轮的同 rich_type 富消息不会被 Vue 错误地复用 DOM —— 这是
           "第二轮开始时第一轮 RoundComplete 错位"bug 的根因 -->
      <template v-for="(msg, i) in messages" :key="messageKey(msg, i)">
        <!-- Assistant meta: model + ↑↓tokens + elapsed (above every assistant message) -->
        <div v-if="msg.role === 'assistant'" class="chat-meta-line-wrapper">
          <MetaLine
            v-if="isAgentThinking && isLastAssistant(i) && turnTokens > 0"
            :timestamp="msg.timestamp"
            :model="turnModel"
            :input-tokens="turnInputTokens"
            :output-tokens="turnOutputTokens"
            :elapsed-ms="turnElapsed"
          />
          <MetaLine
            v-else-if="msg.metadata?.tokens"
            :timestamp="msg.timestamp"
            :model="msg.metadata?.model"
            :input-tokens="msg.metadata?.input_tokens || 0"
            :output-tokens="msg.metadata?.output_tokens || 0"
            :elapsed-ms="msg.metadata?.elapsed_ms"
          />
          <MetaLine v-else :timestamp="msg.timestamp" />
        </div>

        <!-- Rich messages dispatcher (16 类 rich_type 的渲染分支已下沉到 dispatcher 内部) -->
        <RichMessageDispatcher
          v-if="msg.rich_type"
          :msg="msg"
          :idx="i"
          :messages="messages"
          :current-state="store.currentState"
          :project-id="props.projectId"
          :finalizing="finalizingRound"
          :completed-scoring-job-ids="completedScoringJobIds"
          :dismissed-stale-hints="dismissedStaleHints"
          @confirm-keywords="onKeywordsConfirmed"
          @view-doc="onViewDoc"
          @finalize="onFinalizeRound"
          @start-next-round="onStartNextRound"
          @start-collaboration="onStartCollaboration"
          @cancel-collaboration="onCancelCollaboration"
          @deep-read-start="onDeepReadStart"
          @pdf-import-confirmed="onPdfImportConfirmed"
          @pdf-import-cancel="onPdfImportCancel"
          @pdf-import-bucketed="onPdfImportBucketed"
          @suggested-action="onSuggestedAction"
          @stale-hint-start="onStaleHintStart"
          @stale-hint-dismissed="onStaleHintDismissed"
        />

        <!-- ExitButton: inline below exitable rich bubbles -->
        <ExitButton
          v-if="shouldShowExit(msg)"
          :session-id="store.sessionId || ''"
          :current-state="currentExitState(msg)"
          :cleanup-hint="cleanupHintFor(msg)"
          class="exit-btn-inline"
          @exited="onExited"
        />

        <!-- Plain text messages（注意：上面 ExitButton 用了 v-if，导致 v-else 绑的是
             ExitButton 而不是 rich_type 的 template；必须显式排除 rich_type，否则
             协作模式的 rich 消息 content 会和 rich 组件同时渲染导致重复气泡） -->
        <ChatMessage
          v-if="!msg.rich_type"
          :msg="msg"
        >
          <!-- Inline "start first round" button on the last assistant message
               when project has no rounds yet -->
          <template v-if="showStartCard && i === lastAssistantIndex && msg.role === 'assistant'" #actions>
            <div class="msg-inline-actions">
              <el-button
                type="primary"
                size="default"
                :loading="searchStore.isStarting"
                @click="startNewRound"
              >
                <el-icon><Search /></el-icon>
                开始首轮检索
              </el-button>
              <span class="msg-inline-actions__hint">或直接输入「帮我开始检索」也可触发</span>
            </div>
          </template>
        </ChatMessage>

        <!-- Search mode selector (takes precedence over generic confirmation) -->
        <SearchModeSelector
          v-if="!msg.rich_type && pendingConfirmation?.action_type === 'search_mode' && i === lastConfirmationIndex"
          @select="onSearchMode"
        />

        <!-- Confirmation bubble (only for non-search-mode confirmations) -->
        <ConfirmationBubble
          v-else-if="!msg.rich_type && pendingConfirmation && i === lastConfirmationIndex"
          :envelope="pendingConfirmation"
          @confirm="onConfirm"
          @cancel="onCancel"
          @supplement="onSupplement"
        />
      </template>

      <!-- Typing bubble: AI 思考中的气泡（阶段文字轮播 + 三点脉动 + token 实时） -->
      <TypingBubble
        v-if="isAgentThinking || isReadingDeep"
        :scene="typingScene"
        :active="isAgentThinking || isReadingDeep"
        :model="turnModel"
        :input-tokens="turnInputTokens"
        :output-tokens="turnOutputTokens"
        :elapsed-ms="turnElapsed"
      />
    </div>

    <!-- Function Dock: 始终显示；无 projectId 时按钮提示"请先创建项目" -->
    <FunctionDock
      :project-id="props.projectId"
      :session-id="store.sessionId ?? ''"
      ref="dockRef"
      @triggered="onFeatureTriggered"
      @pdf-upload="onPdfUploadClick"
    />

    <!-- 定时推送配置 dialog -->
    <el-dialog
      v-model="showMonitoringDialog"
      title="📡 定时推送 / 每日监控"
      width="560px"
      destroy-on-close
    >
      <MonitoringPanel v-if="props.projectId" :project-id="props.projectId" />
      <div v-else class="m-empty">未绑定项目</div>
    </el-dialog>

    <!-- 新检索模式选择 dialog（点"新检索"按钮时弹出，让用户每轮重选模式） -->
    <el-dialog
      v-model="showNewRoundModeDialog"
      title="🔍 新检索 · 选择模式"
      width="600px"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <SearchModeSelector @select="onNewRoundModeSelected" />
    </el-dialog>

    <!-- Input -->
    <ChatComposer
      :disabled="isAgentThinking || isSearchInProgress"
      :placeholder="inputPlaceholder"
      :busy="isSearchInProgress"
      :confirming="isConfirming"
      @send="onComposerSend"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useConversationStore } from '../../stores/conversation'
import { useSearchStore } from '../../stores/search'
import { useCollaborationStore } from '../../stores/collaboration'
import { useProjectStore } from '../../stores/project'
import { useBucketStore } from '../../stores/bucket'
import ChatMessage from './ChatMessage.vue'
import CatAvatar from '../brand/CatAvatar.vue'
import TypingBubble from './TypingBubble.vue'
import MetaLine from './MetaLine.vue'
import ConfirmationBubble from './ConfirmationBubble.vue'
import SearchModeSelector from './SearchModeSelector.vue'
import RichMessageDispatcher from './RichMessageDispatcher.vue'
import ChatComposer from './ChatComposer.vue'
import MonitoringPanel from '../monitoring/MonitoringPanel.vue'
import FunctionDock from './FunctionDock.vue'
import ExitButton from './ExitButton.vue'
import { featuresApi, uploadApi, collaborationApi } from '../../api/client'
import { useSessionSSE } from '../../composables/useSessionSSE'
import { useChatTokenTracker } from '../../composables/useChatTokenTracker'

const props = defineProps<{
  projectId?: string
}>()

const emit = defineEmits<{
  'view-doc': [doc: any]
}>()

const store = useConversationStore()
const searchStore = useSearchStore()
const collabStore = useCollaborationStore()
const projectStore = useProjectStore()
const bucketStore = useBucketStore()
const scrollRef = ref<HTMLElement | null>(null)
const finalizingRound = ref(false)
const startingNewRound = ref(false)  // 防止新检索按钮重复点击导致 finalize/prepare 双触发
const showMonitoringDialog = ref(false)  // 定时推送 dialog 开关（FunctionDock 的 schedule 按钮触发）
const showNewRoundModeDialog = ref(false) // 新检索模式选择 dialog（FunctionDock 的 new_round 按钮触发）
let pollTimer: any = null

// 订阅 session SSE 的 session_message_appended 事件 —— 用于 inject_rich_message
// 推送的富消息（pdf_import / keyword_confirmation / search_progress / skill_suggestion
// 等）实时追达前端。AIWorkbench 组件内部也调 useSessionSSE，这里是独立实例。
const chatSSE = useSessionSSE()
chatSSE.on('session_message_appended', (data: any) => {
  store.appendIncomingMessage(data)
})

// Token / model / 耗时实时追踪（由 SSE 的 llm_call_start + llm_usage_delta 驱动；
// 回合结束时把 meta 持久化到最后一条 assistant 消息），逻辑封装到 composable
const isAgentThinking = computed(() => store.isAgentThinking)
const {
  turnInputTokens,
  turnOutputTokens,
  turnTokens,
  turnModel,
  turnElapsed,
} = useChatTokenTracker({
  chatSSE,
  isAgentThinking,
  onTurnEnd: (meta) => store.updateLastAssistantMeta(meta),
})

function isLastAssistant(idx: number): boolean {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i].role === 'assistant') return i === idx
  }
  return false
}

function formatMsgTime(ts: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function formatElapsed(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

watch(
  () => store.sessionId,
  (sid) => {
    if (sid) {
      chatSSE.connect(sid)
    } else {
      chatSSE.disconnect()
    }
  },
  { immediate: true }
)

const messages = computed(() => store.messages)
const pendingConfirmation = computed(() => store.pendingConfirmation)
// final_card 到达后，隐藏同 job_id 的 scoring 进度气泡
const completedScoringJobIds = computed(() => {
  const ids = new Set<string>()
  for (const m of messages.value) {
    if (m.rich_type === 'pdf_import_final_card' && m.rich_data?.job_id) {
      ids.add(m.rich_data.job_id)
    }
  }
  return ids
})

// 用户发新消息 → reset 工作台, 为新一轮腾出干净的 phase/tool 列表
watch(
  () => messages.value.length,
  (newLen, oldLen) => {
    if (newLen > oldLen) {
      // placeholder for future per-message hooks
    }
  }
)

// 检索进行中（包括等待关键词确认 / 各种 worker 阶段）— 此时禁止发消息
// awaiting_feedback 阶段允许（用户分类完后可继续与 agent 互动）
//
// 关键守卫：必须绑定到具体 projectId 才能被 round 状态影响。
// 避免 Dashboard 项目1 处于 awaiting_keywords → 切到新建项目页时
// （ConversationCreate 没传 projectId）输入框被项目1 的旧 round 状态锁住。
const isSearchInProgress = computed(() => {
  const round: any = searchStore.currentRound
  if (!round) return false
  if (!props.projectId) return false
  if (round.project_id && String(round.project_id) !== String(props.projectId)) return false
  const s = round.status
  return !!s && ['pending', 'awaiting_keywords', 'searching', 'scoring', 'saving', 'summarizing'].includes(s)
})
const isConfirming = computed(() => store.isConfirming)

// 协作精读 / 引用查证 阶段：从用户点 ReadPlanBubble 的"继续"开始，到 collaboration_answer 到达结束
// 期间后端在执行深度阅读 + 引用查找 + LLM 合成，前端用 TypingBubble(reading_deep) 陪伴
const isReadingDeep = ref(false)
function onDeepReadStart() {
  isReadingDeep.value = true
}
watch(messages, (ms) => {
  if (!isReadingDeep.value) return
  // 找最后一条 rich，如果是 collaboration_answer → 精读结束
  for (let i = ms.length - 1; i >= 0; i--) {
    const rt = ms[i].rich_type
    if (rt === 'collaboration_answer') {
      isReadingDeep.value = false
      return
    }
    if (rt === 'collaboration_read_plan') return // 还在等 answer 到来
  }
}, { deep: true })

// TypingBubble 场景：协作精读 > 协作答问 > 检索 > 普通
const typingScene = computed<'chat' | 'collaboration' | 'search' | 'summarize' | 'reading_deep'>(() => {
  if (isReadingDeep.value) return 'reading_deep'
  if (collabStore.isActive) return 'collaboration'
  if (isSearchInProgress.value) return 'search'
  return 'chat'
})

// Show "start first round" inline card when:
// - project is linked (we know its id)
// - no rounds exist yet
// - no active rich messages of search type
const showStartCard = computed(() => {
  if (!props.projectId) return false
  if (searchStore.rounds.length > 0) return false
  if (collabStore.isActive) return false
  // Hide if conversation has any rich keyword/progress/results message already
  const hasSearchRich = messages.value.some((m: any) =>
    ['keyword_confirmation', 'search_progress', 'round_results'].includes(m.rich_type)
  )
  return !hasSearchRich
})

// 复合 key：优先用后端给的 message id，否则用 rich_type+round_id+timestamp 保证唯一
// 数组下标做 key 会让 Vue 在 messages 重排时复用旧 DOM，污染下一轮的卡片
function messageKey(msg: any, idx: number): string {
  if (msg.id) return String(msg.id)
  const rt = msg.rich_type || msg.role || 'msg'
  const rid = msg.rich_data?.round_id || ''
  const ts = msg.timestamp || ''
  return `${rt}:${rid}:${ts}:${idx}`
}

const inputPlaceholder = computed(() => {
  if (isSearchInProgress.value) {
    const s = searchStore.currentRound?.status
    if (s === 'awaiting_keywords') return '请先在上方气泡里确认关键词方案...'
    return '检索进行中，请稍候...'
  }
  if (store.currentState === 'idle') return '描述您的研究需求...'
  if (store.currentState === 'intent_confirmation') return '补充说明，或按 Enter 确认...'
  if (store.currentState === 'search_mode_selection') return '选择检索模式...'
  return '输入消息...'
})

// Find the index of the last assistant message that should show a confirmation
const lastConfirmationIndex = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i].role === 'assistant') return i
  }
  return -1
})
// Alias used by inline action injection (e.g. "start first round" button)
const lastAssistantIndex = lastConfirmationIndex

// Auto-scroll to bottom
watch(messages, () => {
  nextTick(() => {
    if (scrollRef.value) {
      scrollRef.value.scrollTop = scrollRef.value.scrollHeight
    }
  })
}, { deep: true })

async function onComposerSend(text: string) {
  if (isAgentThinking.value) return
  if (isSearchInProgress.value) {
    ElMessage.warning('检索进行中，请等待本轮结束后再发送消息')
    return
  }
  try {
    await store.sendMessage(text)
  } catch {
    // Error already handled in store
  }
}

async function onConfirm(edits?: Record<string, any>, autoConfirm?: boolean) {
  const action = autoConfirm ? 'auto_confirm' : 'confirm'
  await store.confirmDecision(action, { edits })
}

function onCancel() {
  store.confirmDecision('cancel')
}

async function onSupplement(text: string) {
  await store.confirmDecision('supplement', { supplementText: text })
}

async function onSearchMode(mode: string) {
  await store.selectSearchMode(mode)
}

// ── Rich message handlers ──────────────────────────────────────

// RoundCompleteMessage 触发的"开始下一轮"带上用户选的 mode
async function onStartNextRound(payload?: { mode?: string }) {
  const mode = payload?.mode
  if (mode) {
    // 切换模式：先 PATCH project.search_config.search_mode 再走 prepareRound
    const pid = props.projectId || projectStore.current?.id
    if (!pid) {
      ElMessage.warning('未找到项目 ID')
      return
    }
    try {
      const { projectApi } = await import('../../api/client')
      const currentCfg = projectStore.current?.search_config || {}
      if (currentCfg.search_mode !== mode) {
        await projectApi.update(String(pid), {
          search_config: { ...currentCfg, search_mode: mode },
        })
        await projectStore.fetchProject(String(pid))
      }
    } catch (e: any) {
      ElMessage.error(e?.response?.data?.detail || '切换检索模式失败')
      return
    }
  }
  await startNewRound()
}

// 上一轮卡在 awaiting_feedback 时，弹确认框让用户一键结束本轮
async function handlePendingRoundGate(err: any, onAfterFinalize: () => Promise<any>): Promise<boolean> {
  const detail = err?.response?.data?.detail
  if (err?.response?.status !== 409 || !detail || detail.code !== 'PENDING_ROUND_AWAITING_FEEDBACK') {
    return false
  }
  try {
    await ElMessageBox.confirm(
      detail.message || '喵~上一轮还在等你收尾呢',
      `第 ${detail.pending_round_number ?? ''} 轮还没结束`,
      {
        confirmButtonText: '直接结束本轮',
        cancelButtonText: '稍后处理',
        distinguishCancelAndClose: true,
        type: 'warning',
      },
    )
  } catch {
    return true  // 用户取消，不做事但也不再报错
  }
  const pid = store.projectId
  if (!pid) return true
  try {
    await searchStore.finalizeRound(pid)
    ElMessage.success('喵~上一轮已收尾，这就帮你开新一轮！')
    await onAfterFinalize()
  } catch (finErr: any) {
    ElMessage.error(finErr?.response?.data?.detail || '结束本轮失败')
  }
  return true
}

async function startNewRound() {
  const pid = props.projectId || projectStore.current?.id
  if (!pid) {
    ElMessage.warning('未找到项目 ID')
    return
  }
  if (startingNewRound.value) return
  startingNewRound.value = true

  // 内部：单次 prepare → fallback startRound 的尝试
  async function attemptOnce(): Promise<{ ok: boolean; error?: any }> {
    try {
      await searchStore.prepareRound(String(pid))
      await projectStore.fetchProject(String(pid))
      await store.refreshMessages()
      return { ok: true }
    } catch (prepareErr: any) {
      // 400 = "feature disabled" / "需要补充描述" → fallback 到 legacy startRound
      // 但是"需要补充描述"应该让用户看到，不要静默 fallback
      const detail = prepareErr?.response?.data?.detail
      const isClarificationNeeded =
        typeof detail === 'string' && detail.includes('补充描述')
      if (prepareErr.response?.status === 400 && !isClarificationNeeded) {
        try {
          const round = await searchStore.startRound(String(pid))
          await projectStore.fetchProject(String(pid))
          await store.refreshMessages()
          if (round?.id) ElMessage.success('检索已开始')
          return { ok: true }
        } catch (legacyErr) {
          return { ok: false, error: legacyErr }
        }
      }
      return { ok: false, error: prepareErr }
    }
  }

  // Try once，失败时静默重试一次（解决"第一次点击 LLM timeout, 第二次成功"的体验问题）
  let result = await attemptOnce()
  if (!result.ok) {
    const err: any = result.error
    const status = err?.response?.status
    const detail = err?.response?.data?.detail
    // 上一轮 awaiting_feedback → 走 pending round gate
    if (await handlePendingRoundGate(err, () => attemptOnce().then(r => { result = r }))) return
    // 用户描述需要补充时，直接给出明确错误，不重试（避免重复消息）
    const isClarificationNeeded =
      typeof detail === 'string' && detail.includes('补充描述')
    if (isClarificationNeeded) {
      ElMessage.warning(detail)
      return
    }
    // 409 = 模式互斥，拦截器已弹小猫提示，别再重试也别再弹
    if (status === 409) return
    // 静默重试一次
    await new Promise((r) => setTimeout(r, 400))
    result = await attemptOnce()
  }

  if (!result.ok) {
    const err: any = result.error
    if (err?.__handledByInterceptor) { startingNewRound.value = false; return }
    const detail = err?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : '启动检索失败，请重试')
  }
  startingNewRound.value = false
}

async function onKeywordsConfirmed(payload: any) {
  if (!store.projectId) return
  const roundId = payload?.round_id || searchStore.currentRound?.id
  if (!roundId) return
  try {
    await searchStore.confirmKeywords(store.projectId, roundId, payload)
    ElMessage.success('关键词已确认，检索开始')
    // 立即刷新富消息（拉取 search_progress）
    await store.refreshMessages()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '确认失败')
  }
}

function onViewDoc(payload: any) {
  // 兼容两种签名：旧的直接 doc，新的 { doc, format } 对象
  emit('view-doc', payload)
}

async function onFinalizeRound() {
  if (!store.projectId || finalizingRound.value) return
  try {
    finalizingRound.value = true
    await searchStore.finalizeRound(store.projectId)
    ElMessage.success('本轮已结束')
    await store.refreshMessages()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '结束失败')
  } finally {
    finalizingRound.value = false
  }
}

async function onNewRoundModeSelected(mode: string) {
  showNewRoundModeDialog.value = false
  await onStartNextRound({ mode })
}

async function onStartCollaboration(docIds: string[]) {
  if (!store.sessionId) return
  try {
    await collabStore.startCollaboration(store.sessionId, docIds)
    await store.refreshMessages()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '进入协作失败')
  }
}

function onCancelCollaboration() {
  collabStore.clearPending()
}

// ── FunctionDock / FeatureGate / ExitButton ───────────────────

const dockRef = ref<InstanceType<typeof FunctionDock> | null>(null)

async function onFeatureTriggered(feature: string, result: any) {
  if (!result.allowed) {
    if (result.rich_message) {
      store.appendIncomingMessage(result.rich_message)
    }
    return
  }
  // allowed: dispatch to the corresponding existing flow
  if (feature === 'new_round') {
    const pid = props.projectId || projectStore.current?.id
    if (!pid) {
      ElMessage.warning('未选定项目')
      return
    }
    // 流程态分派：
    //  - 项目创建流程（intent_*）：未建项目前不允许开新检索
    //  - 检索准备态（search_mode_selection / keyword_confirmation）：允许"放弃并重选"
    //  - 检索执行态（searching / scoring / classification / round_finalize）：不允许中途新开
    //  - idle：直接弹模式选择
    const st = store.currentState
    if (st === 'intent_analysis' || st === 'intent_confirmation') {
      ElMessage.warning('请先完成「项目创建」再开始新检索')
      return
    }
    const runningStates = ['searching', 'scoring', 'classification', 'round_finalize']
    if (runningStates.includes(st || '')) {
      ElMessage.warning('本轮检索正在进行中，请等待本轮结束后再开始新检索')
      return
    }
    if (st === 'keyword_confirmation' || st === 'search_mode_selection') {
      try {
        await ElMessageBox.confirm(
          '将结束当前未完成的检索准备，并重新选择模式开启新检索。',
          '结束当前准备并重选模式？',
          { confirmButtonText: '结束并重选', cancelButtonText: '取消', type: 'warning' },
        )
      } catch { return }
      const sid = store.sessionId
      if (!sid) { ElMessage.warning('未找到会话'); return }
      try {
        await featuresApi.resetForNewRound(sid)
        await store.refreshMessages()
      } catch (e: any) {
        ElMessage.error(e?.response?.data?.detail?.hint || e?.response?.data?.detail || '重置失败')
        return
      }
    }
    // 每次新检索都重选模式，交互交给已有的 onStartNextRound(mode) 路径
    showNewRoundModeDialog.value = true
  } else if (feature === 'collaboration') {
    const state = store.currentState
    if (state === 'collaboration_active' || state === 'collaboration_selecting') {
      ElMessage.info('您已在协作研究模式中')
      return
    }
    const sid = store.sessionId
    if (!sid) { ElMessage.warning('未找到会话'); return }
    // 直接调用 suggest-scope 端点：成功由后端 inject 的 collaboration_scope 气泡承载；
    // 失败不再往对话里写消息，用 toast 提示（409 由 axios 拦截器弹；其他 status 在 catch 里处理）
    try {
      await collaborationApi.suggestScope(sid)
      await store.refreshMessages()
    } catch (e: any) {
      if (!e?.__handledByInterceptor) {
        const d = e?.response?.data?.detail
        ElMessage.warning(typeof d === 'string' ? d : '进入协作失败')
      }
    }
  } else if (feature === 'schedule') {
    // 定时推送功能待完善，暂时以 toast 提示。
    // 恢复：把下面这行替换回 `showMonitoringDialog.value = true`
    ElMessage.info('⏰ 定时推送功能正在开发中，敬请期待')
  }
  dockRef.value?.refresh()
}

async function onPdfUploadClick() {
  await store.refreshMessages()
}

async function onPdfImportCancel(jobId: string) {
  try {
    await uploadApi.cancelImport(jobId)
    await store.refreshMessages()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '取消失败')
  }
}

async function onPdfImportConfirmed(_docId: string) {
  await store.refreshMessages()
}

async function onPdfImportBucketed(_docId: string, _bucket: string) {
  await store.refreshMessages()
  // 手动上传卡片入桶后，刷新文献库 badge 计数
  const pid = props.projectId || projectStore.current?.id
  if (pid) {
    try { await bucketStore.fetchBuckets(String(pid)) } catch { /* noop */ }
  }
}

function onSuggestedAction(trigger: string) {
  if (!props.projectId || !store.sessionId) return
  featuresApi.trigger(props.projectId, trigger, store.sessionId).then(resp => {
    onFeatureTriggered(trigger, resp.data)
  }).catch(() => {})
}

async function onExited() {
  ElMessage.success('已退出流程')
  await store.refreshMessages()
  dockRef.value?.refresh()
}

const EXITABLE_RICH_TYPES = new Set<string>([
  // 检索流程一旦开启不可逆（keyword_confirmation 起不再可退，只能走到本轮结束）
  // collaboration_scope（选文献阶段）不提供 × 退出，用气泡内的取消按钮
  // collaboration_started（已进入协作）也不提供 × 退出，顶部 CollaborationBanner 已经有退出按钮
])

function shouldShowExit(msg: any): boolean {
  return EXITABLE_RICH_TYPES.has(msg.rich_type)
}

function currentExitState(msg: any): string {
  if (msg.rich_type === 'keyword_confirmation') return 'keyword_confirmation'
  if (msg.rich_type === 'collaboration_scope') return 'collaboration_selecting'
  if (msg.rich_type === 'collaboration_started') return 'collaboration_active'
  return 'idle'
}

function cleanupHintFor(msg: any): string {
  if (msg.rich_type === 'keyword_confirmation') return '将取消当前检索轮次，关键词草稿会丢失'
  if (msg.rich_type?.startsWith('collaboration')) return '将结束协作会话'
  return '将退出当前流程回到对话'
}

// ── Polling for rich-message updates ──────────────────────────

function shouldPoll(): boolean {
  // 只在有活跃 round（或关键词等待）时轮询
  const r = searchStore.currentRound
  if (!r) return false
  return ['pending', 'searching', 'scoring', 'saving', 'summarizing', 'awaiting_keywords', 'awaiting_feedback'].includes(r.status)
}

// Stale hint: 一次性触发 server-side 检测；后端有 24h 去重 + 7 天 dismiss 静音，
// 多次进项目不会被刷屏。dismiss 后本地隐藏 bubble（按 timestamp 去重，刷新页面也保持隐藏）。
const dismissedStaleHints = ref<Set<string>>(new Set())

function onStaleHintStart() {
  // 复用现有的"开新一轮"流程
  startNewRound()
}

function onStaleHintDismissed(msg: any) {
  if (msg?.timestamp) {
    dismissedStaleHints.value.add(msg.timestamp)
  }
}

async function maybeFireStaleCheck() {
  if (!props.projectId) return
  try {
    const { projectApi } = await import('../../api/client')
    await projectApi.staleCheck(props.projectId)
    // SSE 会自动把新富消息推过来；这里不需要手动 refreshMessages
  } catch (err) {
    // 静默失败：staleCheck 不是关键路径
    console.debug('[StaleHint] staleCheck failed', err)
  }
}

onMounted(() => {
  pollTimer = setInterval(async () => {
    if (shouldPoll() || collabStore.state === 'selecting') {
      await store.refreshMessages()
    }
  }, 3000)
  maybeFireStaleCheck()
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
/* A2: Assistant meta line —— 默认半隐藏（opacity 0.22），hover 整行时显现 1.0。
   解决"每条 AI 消息上方冗余的 model/tokens/时长占一整行"的视觉噪音问题，
   同时保留调试可见性。过渡曲线与 design-system.css 的 --duration-normal 一致。 */
/* A2: Assistant meta wrapper —— 默认半隐藏（opacity 0.22），hover 整行时显现 1.0。
   避免每条 AI 消息上方冗余的 model/tokens/时长占满视觉注意力，同时保留调试可见性。 */
.chat-meta-line-wrapper {
  padding-left: 46px; /* align with message body (avatar 36px + gap 10px) */
  margin-bottom: 2px;
  opacity: 0.22;
  transition: opacity var(--duration-normal) var(--ease-out);
  user-select: none;
}
.chat-meta-line-wrapper:hover,
.chat-meta-line-wrapper:focus-within {
  opacity: 1;
}

.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  /* 期刊风纸色 + 细网格纸纹（和首页 HomeJournal 统一） */
  background:
    linear-gradient(rgba(120, 100, 80, 0.045) 1px, transparent 1px) 0 0 / 32px 32px,
    linear-gradient(90deg, rgba(120, 100, 80, 0.045) 1px, transparent 1px) 0 0 / 32px 32px,
    radial-gradient(ellipse at top, rgba(198, 172, 87, 0.06), transparent 60%),
    var(--paper-cream, #fdfcf8);
  /* 防御长富消息把父容器撑开横向滚动 */
  min-width: 0;
  overflow: hidden;
  position: relative;
}
.chat-panel::before {
  /* 顶部金色 hairline，对齐首页 masthead 风格 */
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, rgba(198, 172, 87, 0.4), transparent);
  pointer-events: none;
  z-index: 1;
}
.chat-panel__messages {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 28px 32px 20px;
  min-width: 0;
  position: relative;
  z-index: 1;
}
.chat-panel__messages > * {
  max-width: 100%;
}
.chat-panel__welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 100px 20px;
  color: var(--ink-400);
  animation: fadeUp var(--duration-slow) var(--ease-out) both;
}
.chat-panel__welcome-eyebrow {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.35em;
  color: #c6ac57;
  margin-bottom: 22px;
  text-transform: uppercase;
}
.chat-panel__welcome-cat {
  box-shadow: 0 8px 24px rgba(20, 20, 20, 0.08), 0 0 0 6px rgba(198, 172, 87, 0.08);
  animation: breathe-soft 3.6s ease-in-out infinite;
}
.chat-panel__welcome p {
  margin: 16px 0 0;
  font-size: 18px;
  font-family: var(--font-display);
  color: var(--ink-800);
  letter-spacing: -0.2px;
  font-weight: 600;
}
.chat-panel__welcome .sub {
  font-size: 13px;
  color: var(--ink-400);
  font-family: var(--font-body);
  font-style: italic;
  margin-top: 6px;
}

/* Inline action row injected into the last assistant message bubble */
.msg-inline-actions {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed #e2e8f0;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.msg-inline-actions__hint {
  font-size: 12px;
  color: #94a3b8;
}
/* Typing bubble 样式全部在 TypingBubble.vue 内，此处不再有 legacy rows */
/* 输入区相关样式已下沉到 ChatComposer.vue */
</style>
