import { ref, onUnmounted } from 'vue'

export interface SSEEvent {
  event: string
  data: any
}

/**
 * SSE composable for session-scoped workbench events.
 * Subscribes to /api/stream/sessions/{sessionId}?token=... and dispatches
 * typed events to registered handlers.
 */
export function useSessionSSE() {
  const connected = ref(false)
  const lastEvent = ref<SSEEvent | null>(null)
  let eventSource: EventSource | null = null
  let currentSessionId: string | null = null
  const handlers = new Map<string, ((data: any) => void)[]>()

  const EVENT_TYPES = [
    'connected',
    'session_message_appended',
    'llm_call_start',
    'llm_call_end',
    'llm_usage_delta',
    'tool_call_start',
    'tool_call_end',
    'agent_phase',
    'agent_message_delta',
    'error',
  ]

  function connect(sessionId: string) {
    if (currentSessionId === sessionId && eventSource && eventSource.readyState !== EventSource.CLOSED) {
      return // already connected to this session
    }
    disconnect()
    currentSessionId = sessionId
    const token = localStorage.getItem('urip_token')
    const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
    const url = `${baseUrl}/api/stream/sessions/${sessionId}?token=${token}`

    eventSource = new EventSource(url)

    eventSource.onopen = () => {
      connected.value = true
    }
    eventSource.onerror = () => {
      connected.value = false
      setTimeout(() => {
        if (currentSessionId && eventSource?.readyState === EventSource.CLOSED) {
          connect(currentSessionId)
        }
      }, 3000)
    }

    for (const type of EVENT_TYPES) {
      eventSource.addEventListener(type, (e: MessageEvent) => {
        try {
          const data = JSON.parse((e as any).data)
          lastEvent.value = { event: type, data }
          const typeHandlers = handlers.get(type)
          if (typeHandlers) typeHandlers.forEach((h) => h(data))
        } catch {
          /* ignore parse errors */
        }
      })
    }
  }

  function on(eventType: string, handler: (data: any) => void) {
    if (!handlers.has(eventType)) handlers.set(eventType, [])
    handlers.get(eventType)!.push(handler)
  }

  function disconnect() {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    connected.value = false
    currentSessionId = null
  }

  onUnmounted(() => disconnect())

  return { connected, lastEvent, connect, on, disconnect }
}
