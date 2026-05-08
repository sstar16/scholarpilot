import { ref, type Ref } from 'vue'

export interface WsLogEntry {
  id?: number
  created_at: string
  level: string
  source: string
  category?: string
  message: string
  round_id?: string
  project_id?: string
  duration_ms?: number
  error_trace?: string
  context?: Record<string, unknown>
}

export interface WsFilter {
  level?: string
  source?: string
}

const MAX_LOGS = 500
const BASE_RECONNECT_MS = 3_000
const MAX_RECONNECT_MS = 30_000

export function useWebSocket() {
  const connected = ref(false)
  const logs: Ref<WsLogEntry[]> = ref([])

  let ws: WebSocket | null = null
  let reconnectDelay = BASE_RECONNECT_MS
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let paused = false
  let intentionalClose = false

  function deriveWsUrl(): string {
    const base = import.meta.env.VITE_API_BASE
    const token = localStorage.getItem('devtools_token') || ''
    if (base) {
      const url = new URL(base)
      const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
      return `${protocol}//${url.host}/api/devtools/ws?token=${encodeURIComponent(token)}`
    }
    // Use current page origin (works behind nginx proxy)
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${location.host}/api/devtools/ws?token=${encodeURIComponent(token)}`
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return
    }
    intentionalClose = false
    const wsUrl = deriveWsUrl()
    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      connected.value = true
      reconnectDelay = BASE_RECONNECT_MS
    }

    ws.onmessage = (event) => {
      if (paused) return
      try {
        const entry: WsLogEntry = JSON.parse(event.data)
        logs.value.push(entry)
        if (logs.value.length > MAX_LOGS) {
          logs.value.splice(0, logs.value.length - MAX_LOGS)
        }
      } catch {
        // ignore malformed messages
      }
    }

    ws.onclose = () => {
      connected.value = false
      ws = null
      if (!intentionalClose) {
        scheduleReconnect()
      }
    }

    ws.onerror = () => {
      ws?.close()
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) return
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_MS)
      connect()
    }, reconnectDelay)
  }

  function disconnect() {
    intentionalClose = true
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    ws?.close()
    ws = null
    connected.value = false
  }

  function setFilter(filter: WsFilter) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ filter }))
    }
  }

  function pause() {
    paused = true
  }

  function resume() {
    paused = false
  }

  function clearLogs() {
    logs.value = []
  }

  return {
    connected,
    logs,
    connect,
    disconnect,
    setFilter,
    pause,
    resume,
    clearLogs,
  }
}
