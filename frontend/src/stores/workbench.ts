import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface WorkbenchPhase {
  id: number
  agent: string
  phase: string
  description: string
  timestamp: number
}

export interface WorkbenchToolCall {
  call_id: string
  tool_name: string
  agent: string
  args?: any
  result_preview?: string
  duration_ms: number
  status: 'running' | 'ok' | 'error'
  error?: string
  startedAt: number
}

export interface WorkbenchLLMCall {
  call_id: string
  provider: string
  model: string
  input_tokens: number
  output_tokens: number
  cost_usd: number
  latency_ms: number
  agent: string
  timestamp: number
}

const IDLE_TIMEOUT_MS = 15000

export const useWorkbenchStore = defineStore('workbench', () => {
  // ── State ───────────────────────────────────────────────
  const phases = ref<WorkbenchPhase[]>([])
  const toolCalls = ref<WorkbenchToolCall[]>([])
  const llmCalls = ref<WorkbenchLLMCall[]>([])

  const cumulativeInputTokens = ref(0)
  const cumulativeOutputTokens = ref(0)
  const cumulativeCostUsd = ref(0)
  const lastModel = ref<string>('')

  const currentAgent = ref<string>('')
  const currentPhase = ref<string>('')
  const currentDescription = ref<string>('')

  const active = ref(false)
  const lastEventAt = ref<number>(0)
  let idleTimer: ReturnType<typeof setTimeout> | null = null
  let phaseIdCounter = 0

  // ── Getters ─────────────────────────────────────────────
  const totalTokens = computed(() => cumulativeInputTokens.value + cumulativeOutputTokens.value)
  const phaseHistory = computed(() => phases.value.slice(-10)) // last 10
  const activeToolCalls = computed(() => toolCalls.value.filter((t) => t.status === 'running'))
  const completedToolCalls = computed(() => toolCalls.value.filter((t) => t.status !== 'running').slice(-8))

  // ── Actions ─────────────────────────────────────────────
  function _touchActive() {
    active.value = true
    lastEventAt.value = Date.now()
    if (idleTimer) clearTimeout(idleTimer)
    idleTimer = setTimeout(() => {
      // After idle timeout, fade to inactive (but keep data for quick re-show)
      active.value = false
    }, IDLE_TIMEOUT_MS)
  }

  function applyPhase(data: { agent_name: string; from_phase?: string; to_phase: string; description?: string }) {
    phases.value.push({
      id: ++phaseIdCounter,
      agent: data.agent_name || 'Agent',
      phase: data.to_phase,
      description: data.description || '',
      timestamp: Date.now(),
    })
    currentAgent.value = data.agent_name || ''
    currentPhase.value = data.to_phase
    currentDescription.value = data.description || ''
    _touchActive()
  }

  function applyLLMStart(data: { call_id: string; provider?: string; model?: string; agent_name?: string }) {
    // We don't add a record yet — wait for llm_call_end. Just touch active state.
    if (data.model) lastModel.value = data.model
    _touchActive()
  }

  function applyLLMEnd(data: {
    call_id: string
    provider?: string
    model?: string
    usage?: { input_tokens: number; output_tokens: number }
    cost_usd?: number
    latency_ms?: number
    agent_name?: string
    status?: string
  }) {
    const inp = data.usage?.input_tokens || 0
    const out = data.usage?.output_tokens || 0
    llmCalls.value.push({
      call_id: data.call_id,
      provider: data.provider || '',
      model: data.model || '',
      input_tokens: inp,
      output_tokens: out,
      cost_usd: data.cost_usd || 0,
      latency_ms: data.latency_ms || 0,
      agent: data.agent_name || '',
      timestamp: Date.now(),
    })
    if (data.model) lastModel.value = data.model
    _touchActive()
  }

  function applyLLMUsageDelta(data: { input_tokens?: number; output_tokens?: number; cost_usd?: number; model?: string }) {
    cumulativeInputTokens.value += data.input_tokens || 0
    cumulativeOutputTokens.value += data.output_tokens || 0
    cumulativeCostUsd.value += data.cost_usd || 0
    if (data.model) lastModel.value = data.model
    _touchActive()
  }

  function applyToolStart(data: { call_id: string; tool_name: string; args?: any; agent_name?: string }) {
    toolCalls.value.push({
      call_id: data.call_id,
      tool_name: data.tool_name,
      agent: data.agent_name || '',
      args: data.args,
      status: 'running',
      duration_ms: 0,
      startedAt: Date.now(),
    })
    _touchActive()
  }

  function applyToolEnd(data: {
    call_id: string
    tool_name: string
    args?: any
    result_preview?: string
    duration_ms?: number
    status?: string
    error?: string
    agent_name?: string
  }) {
    const existing = toolCalls.value.find((t) => t.call_id === data.call_id)
    if (existing) {
      existing.result_preview = data.result_preview
      existing.duration_ms = data.duration_ms || 0
      existing.status = (data.status || 'ok') as 'ok' | 'error'
      existing.error = data.error
    } else {
      // Tool call we never saw start for — create directly as completed
      toolCalls.value.push({
        call_id: data.call_id,
        tool_name: data.tool_name,
        agent: data.agent_name || '',
        args: data.args,
        result_preview: data.result_preview,
        duration_ms: data.duration_ms || 0,
        status: (data.status || 'ok') as 'ok' | 'error',
        error: data.error,
        startedAt: Date.now() - (data.duration_ms || 0),
      })
    }
    _touchActive()
  }

  function resetSession() {
    phases.value = []
    toolCalls.value = []
    llmCalls.value = []
    cumulativeInputTokens.value = 0
    cumulativeOutputTokens.value = 0
    cumulativeCostUsd.value = 0
    currentAgent.value = ''
    currentPhase.value = ''
    currentDescription.value = ''
    active.value = false
    if (idleTimer) {
      clearTimeout(idleTimer)
      idleTimer = null
    }
  }

  return {
    // state
    phases,
    toolCalls,
    llmCalls,
    cumulativeInputTokens,
    cumulativeOutputTokens,
    cumulativeCostUsd,
    lastModel,
    currentAgent,
    currentPhase,
    currentDescription,
    active,
    // getters
    totalTokens,
    phaseHistory,
    activeToolCalls,
    completedToolCalls,
    // actions
    applyPhase,
    applyLLMStart,
    applyLLMEnd,
    applyLLMUsageDelta,
    applyToolStart,
    applyToolEnd,
    resetSession,
  }
})
