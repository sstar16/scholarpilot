import { ref, onUnmounted } from 'vue'

export interface SSEEvent {
  event: string
  data: any
}

export function useSSE() {
  const connected = ref(false)
  const lastEvent = ref<SSEEvent | null>(null)
  let eventSource: EventSource | null = null
  const handlers = new Map<string, ((data: any) => void)[]>()

  function connect(roundId: string) {
    disconnect()
    const token = localStorage.getItem('urip_token')
    // SSE doesn't support custom headers, pass token as query param
    const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
    const url = `${baseUrl}/api/stream/rounds/${roundId}?token=${token}`

    eventSource = new EventSource(url)

    eventSource.onopen = () => {
      connected.value = true
    }

    eventSource.onerror = () => {
      connected.value = false
      // Auto-reconnect after 3s
      setTimeout(() => {
        if (eventSource?.readyState === EventSource.CLOSED) {
          connect(roundId)
        }
      }, 3000)
    }

    // Listen for all custom event types
    const eventTypes = [
      'connected', 'round_status', 'source_started', 'source_complete',
      'source_error', 'doc_arrived', 'summary_ready', 'agent_plan',
      'round_complete', 'round_failed', 'error'
    ]

    for (const type of eventTypes) {
      eventSource.addEventListener(type, (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data)
          lastEvent.value = { event: type, data }
          const typeHandlers = handlers.get(type)
          if (typeHandlers) {
            typeHandlers.forEach(h => h(data))
          }
        } catch {}
      })
    }
  }

  function on(eventType: string, handler: (data: any) => void) {
    if (!handlers.has(eventType)) {
      handlers.set(eventType, [])
    }
    handlers.get(eventType)!.push(handler)
  }

  function disconnect() {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    connected.value = false
  }

  onUnmounted(() => disconnect())

  return { connected, lastEvent, connect, disconnect, on }
}
