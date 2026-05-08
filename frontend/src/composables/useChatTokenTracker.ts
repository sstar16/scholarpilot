import { ref, watch, type Ref } from 'vue'
import type { useSessionSSE } from './useSessionSSE'

export interface TurnTokenMeta {
  tokens: number
  input_tokens: number
  output_tokens: number
  model: string
  elapsed_ms: number
}

interface UseChatTokenTrackerOptions {
  /** 已经建立连接的 SSE 实例（由调用方负责 connect/disconnect） */
  chatSSE: ReturnType<typeof useSessionSSE>
  /** AI 是否还在思考；由 true → false 触发 onTurnEnd 后重置计数 */
  isAgentThinking: Ref<boolean>
  /** 一轮回复结束时回调，常用于把 token / model / elapsed 持久化到消息 metadata */
  onTurnEnd?: (meta: TurnTokenMeta) => void
}

/**
 * SSE 驱动的逐轮 token / model / 耗时追踪。
 * 监听 chatSSE 的 llm_call_start 起表，llm_usage_delta 累加，
 * isAgentThinking 由 true → false 时调用 onTurnEnd 持久化并重置。
 */
export function useChatTokenTracker(opts: UseChatTokenTrackerOptions) {
  const turnInputTokens = ref(0)
  const turnOutputTokens = ref(0)
  const turnTokens = ref(0)
  const turnModel = ref('')
  const turnStartTime = ref(0)
  const turnElapsed = ref(0)
  let elapsedTimer: ReturnType<typeof setInterval> | null = null

  opts.chatSSE.on('llm_call_start', () => {
    if (!turnStartTime.value) {
      turnStartTime.value = Date.now()
      elapsedTimer = setInterval(() => {
        turnElapsed.value = Date.now() - turnStartTime.value
      }, 100)
    }
  })

  // llm_usage_delta has flat {input_tokens, output_tokens, model};
  // llm_call_end nests them in usage（这里只关心 delta，足够实时计数）
  opts.chatSSE.on('llm_usage_delta', (data: any) => {
    const inp = data.input_tokens || 0
    const out = data.output_tokens || 0
    turnInputTokens.value += inp
    turnOutputTokens.value += out
    turnTokens.value += inp + out
    if (data.model) turnModel.value = data.model
  })

  // 回合结束时：把 token / model / elapsed 持久化（onTurnEnd），随后重置计数
  watch(opts.isAgentThinking, (thinking, was) => {
    if (was && !thinking && turnTokens.value > 0) {
      opts.onTurnEnd?.({
        tokens: turnTokens.value,
        input_tokens: turnInputTokens.value,
        output_tokens: turnOutputTokens.value,
        model: turnModel.value,
        elapsed_ms: turnElapsed.value,
      })
    }
    if (was && !thinking) {
      turnTokens.value = 0
      turnInputTokens.value = 0
      turnOutputTokens.value = 0
      turnModel.value = ''
      turnStartTime.value = 0
      turnElapsed.value = 0
      if (elapsedTimer) {
        clearInterval(elapsedTimer)
        elapsedTimer = null
      }
    }
  })

  return {
    turnInputTokens,
    turnOutputTokens,
    turnTokens,
    turnModel,
    turnElapsed,
  }
}
