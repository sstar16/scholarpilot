<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useWebSocket, type WsLogEntry } from '../composables/useWebSocket'
import { getLogs, type LogQueryParams } from '../api/client'

const props = defineProps<{
  filterSource?: string
  filterLevel?: string
}>()

const {
  connected,
  logs: wsLogs,
  connect,
  disconnect,
  setFilter,
  pause,
  resume,
  clearLogs,
} = useWebSocket()

const isPaused = ref(false)
const searchQuery = ref('')
const searchResults = ref<WsLogEntry[]>([])
const isSearching = ref(false)
const expandedRow = ref<number | null>(null)
const scrollContainer = ref<HTMLElement | null>(null)

let searchTimer: ReturnType<typeof setTimeout> | null = null

// Displayed logs: either search results or live WS logs
const displayLogs = computed(() => {
  if (searchQuery.value.trim() && searchResults.value.length > 0) {
    return searchResults.value
  }
  return wsLogs.value
})

function togglePause() {
  isPaused.value = !isPaused.value
  if (isPaused.value) {
    pause()
  } else {
    resume()
  }
}

function toggleExpand(index: number) {
  expandedRow.value = expandedRow.value === index ? null : index
}

function levelClass(level: string) {
  const l = level.toUpperCase()
  if (l === 'ERROR' || l === 'CRITICAL') return 'level-error'
  if (l === 'WARNING') return 'level-warn'
  if (l === 'INFO') return 'level-info'
  if (l === 'DEBUG') return 'level-debug'
  return 'level-default'
}

function formatTime(ts: string) {
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('zh-CN', { hour12: false }) + '.' + String(d.getMilliseconds()).padStart(3, '0')
  } catch {
    return ts
  }
}

function formatJson(obj: any): string {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

// Debounced search
watch(searchQuery, (val) => {
  if (searchTimer) clearTimeout(searchTimer)
  if (!val.trim()) {
    searchResults.value = []
    return
  }
  searchTimer = setTimeout(async () => {
    isSearching.value = true
    try {
      const params: LogQueryParams = { search: val.trim(), page_size: 50 }
      if (props.filterSource) params.source = props.filterSource
      if (props.filterLevel) params.level = props.filterLevel
      const { data } = await getLogs(params)
      searchResults.value = data.items.map((item) => ({
        id: item.id,
        created_at: item.created_at,
        level: item.level,
        source: item.source,
        category: item.category,
        message: item.message,
        round_id: item.round_id,
        context: item.context,
        duration_ms: item.duration_ms,
        error_trace: item.error_trace,
      }))
    } catch {
      searchResults.value = []
    } finally {
      isSearching.value = false
    }
  }, 400)
})

// Apply filters from parent via WS
watch(
  () => [props.filterSource, props.filterLevel],
  () => {
    setFilter({
      source: props.filterSource,
      level: props.filterLevel,
    })
  },
)

// Auto-scroll to bottom
watch(
  () => wsLogs.value.length,
  () => {
    if (!isPaused.value && scrollContainer.value) {
      nextTick(() => {
        const el = scrollContainer.value
        if (el) el.scrollTop = el.scrollHeight
      })
    }
  },
)

onMounted(() => {
  connect()
})

onUnmounted(() => {
  disconnect()
  if (searchTimer) clearTimeout(searchTimer)
})
</script>

<template>
  <div class="log-stream-panel">
    <!-- Toolbar -->
    <div class="stream-toolbar">
      <div class="toolbar-left">
        <div class="connection-dot" :class="{ online: connected }"></div>
        <span class="toolbar-label">{{ connected ? 'LIVE' : 'OFFLINE' }}</span>
        <span class="log-count mono">{{ displayLogs.length }}</span>
      </div>

      <div class="toolbar-center">
        <el-input
          v-model="searchQuery"
          placeholder="Search logs..."
          size="small"
          clearable
          :loading="isSearching"
          class="search-input"
        >
          <template #prefix>
            <span style="color: #555577">&#x1F50D;</span>
          </template>
        </el-input>
      </div>

      <div class="toolbar-right">
        <button class="tool-btn" :class="{ active: isPaused }" @click="togglePause">
          {{ isPaused ? '&#9654; Resume' : '&#9646;&#9646; Pause' }}
        </button>
        <button class="tool-btn" @click="clearLogs">Clear</button>
      </div>
    </div>

    <!-- Log entries -->
    <div ref="scrollContainer" class="stream-body">
      <TransitionGroup name="log-entry">
        <div
          v-for="(log, idx) in displayLogs"
          :key="log.id ?? `ws-${idx}`"
          class="log-row"
          :class="{
            'log-error': log.level.toUpperCase() === 'ERROR' || log.level.toUpperCase() === 'CRITICAL',
            expanded: expandedRow === idx,
          }"
          @click="toggleExpand(idx)"
        >
          <div class="log-main">
            <span class="log-time mono">{{ formatTime(log.created_at) }}</span>
            <span class="log-level-badge" :class="levelClass(log.level)">
              {{ log.level.toUpperCase().slice(0, 4) }}
            </span>
            <span class="log-source mono">{{ log.source }}</span>
            <span class="log-message">{{ log.message }}</span>
          </div>

          <!-- Expanded detail -->
          <div v-if="expandedRow === idx" class="log-detail" @click.stop>
            <!-- LLM 答案 preview（LLM_CALL_END 专用，优先展示避免用户翻 JSON 找） -->
            <div v-if="log.context?.text_preview" class="detail-section">
              <div class="detail-label">
                Answer
                <span class="detail-tag">{{ log.context.finish_reason || '' }}</span>
                <span v-if="log.context.cache === 'hit'" class="detail-tag detail-tag--cache">cache</span>
              </div>
              <pre class="detail-answer mono">{{ log.context.text_preview }}</pre>
            </div>
            <!-- 思维链（仅 deepseek-reasoner 等推理模型返回 reasoning_preview 时展示） -->
            <div v-if="log.context?.reasoning_preview" class="detail-section">
              <div class="detail-label detail-label--reasoning">
                Reasoning
                <span class="detail-tag">{{ log.context.reasoning_length }} chars</span>
              </div>
              <pre class="detail-reasoning mono">{{ log.context.reasoning_preview }}</pre>
            </div>
            <div v-if="log.context && Object.keys(log.context).length > 0" class="detail-section">
              <div class="detail-label">Context</div>
              <pre class="detail-json mono">{{ formatJson(log.context) }}</pre>
            </div>
            <div v-if="log.error_trace" class="detail-section">
              <div class="detail-label error-label">Error Trace</div>
              <pre class="detail-trace mono">{{ log.error_trace }}</pre>
            </div>
            <div v-if="log.round_id" class="detail-meta">
              Round #{{ log.round_id }}
            </div>
          </div>
        </div>
      </TransitionGroup>

      <div v-if="displayLogs.length === 0" class="empty-stream">
        <span v-if="searchQuery">No matching logs</span>
        <span v-else>Waiting for logs...</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.log-stream-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: rgba(19, 19, 43, 0.7);
  border: 1px solid rgba(42, 42, 74, 0.6);
  border-radius: 12px;
  overflow: hidden;
}

/* ─── Toolbar ─── */
.stream-toolbar {
  display: flex;
  align-items: center;
  padding: 10px 14px;
  border-bottom: 1px solid rgba(42, 42, 74, 0.6);
  gap: 12px;
  flex-wrap: wrap;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.connection-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ef4444;
  box-shadow: 0 0 6px rgba(239, 68, 68, 0.5);
  transition: all 0.3s;
}

.connection-dot.online {
  background: #4ade80;
  box-shadow: 0 0 6px rgba(74, 222, 128, 0.5);
  animation: dot-pulse 2s ease-in-out infinite;
}

@keyframes dot-pulse {
  0%, 100% { box-shadow: 0 0 4px rgba(74, 222, 128, 0.4); }
  50% { box-shadow: 0 0 10px rgba(74, 222, 128, 0.7); }
}

.toolbar-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1px;
  color: #8888aa;
}

.log-count {
  font-size: 11px;
  color: #555577;
  background: rgba(42, 42, 74, 0.5);
  padding: 2px 6px;
  border-radius: 4px;
}

.toolbar-center {
  flex: 1;
  min-width: 160px;
}

.search-input :deep(.el-input__wrapper) {
  background: rgba(10, 10, 26, 0.6) !important;
  box-shadow: 0 0 0 1px rgba(42, 42, 74, 0.5) inset !important;
  border-radius: 6px;
}

.toolbar-right {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

.tool-btn {
  padding: 4px 10px;
  border: 1px solid rgba(42, 42, 74, 0.6);
  border-radius: 6px;
  background: rgba(10, 10, 26, 0.4);
  color: #8888aa;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
  font-family: var(--dt-sans);
}

.tool-btn:hover {
  background: rgba(124, 58, 237, 0.15);
  border-color: rgba(124, 58, 237, 0.3);
  color: #c0c0d0;
}

.tool-btn.active {
  background: rgba(251, 191, 36, 0.12);
  border-color: rgba(251, 191, 36, 0.3);
  color: #fbbf24;
}

/* ─── Log body ─── */
.stream-body {
  flex: 1;
  overflow-y: auto;
  max-height: 500px;
}

.log-row {
  padding: 6px 14px;
  border-bottom: 1px solid rgba(42, 42, 74, 0.2);
  cursor: pointer;
  transition: background 0.15s;
  border-left: 3px solid transparent;
}

.log-row:hover {
  background: rgba(124, 58, 237, 0.04);
}

.log-row.log-error {
  border-left-color: #f87171;
  background: rgba(248, 113, 113, 0.03);
}

.log-row.log-error:hover {
  background: rgba(248, 113, 113, 0.06);
}

.log-row.expanded {
  background: rgba(124, 58, 237, 0.06);
}

.log-main {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 26px;
}

.log-time {
  font-size: 11px;
  color: #555577;
  flex-shrink: 0;
  width: 90px;
}

.log-level-badge {
  font-size: 10px;
  font-weight: 700;
  font-family: var(--dt-mono);
  padding: 1px 6px;
  border-radius: 3px;
  flex-shrink: 0;
  min-width: 36px;
  text-align: center;
}

.level-error {
  background: rgba(248, 113, 113, 0.15);
  color: #f87171;
}

.level-warn {
  background: rgba(251, 191, 36, 0.15);
  color: #fbbf24;
}

.level-info {
  background: rgba(74, 222, 128, 0.12);
  color: #4ade80;
}

.level-debug {
  background: rgba(136, 136, 170, 0.1);
  color: #8888aa;
}

.level-default {
  background: rgba(136, 136, 170, 0.1);
  color: #8888aa;
}

.log-source {
  font-size: 11px;
  color: #60a5fa;
  flex-shrink: 0;
  min-width: 70px;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.log-message {
  font-size: 12px;
  color: #c0c0d0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}

/* ─── Expanded detail ─── */
.log-detail {
  margin-top: 8px;
  padding: 10px 12px;
  background: rgba(10, 10, 26, 0.5);
  border-radius: 6px;
  border: 1px solid rgba(42, 42, 74, 0.4);
}

.detail-section {
  margin-bottom: 10px;
}

.detail-section:last-child {
  margin-bottom: 0;
}

.detail-label {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #555577;
  margin-bottom: 4px;
}

.error-label {
  color: #f87171;
}

.detail-json {
  font-size: 11px;
  line-height: 1.5;
  color: #a0a0c0;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}

.detail-answer {
  font-size: 11.5px;
  line-height: 1.5;
  color: #d4d4e8;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 240px;
  overflow-y: auto;
  background: rgba(30, 32, 56, 0.5);
  padding: 8px 10px;
  border-left: 2px solid rgba(100, 200, 180, 0.4);
}

.detail-reasoning {
  font-size: 11.5px;
  line-height: 1.5;
  color: #c8bae8;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 260px;
  overflow-y: auto;
  background: rgba(40, 28, 60, 0.5);
  padding: 8px 10px;
  border-left: 2px solid rgba(192, 132, 252, 0.5);
  font-style: italic;
}

.detail-label--reasoning {
  color: #c084fc;
}

.detail-tag {
  display: inline-block;
  font-family: monospace;
  font-size: 9.5px;
  padding: 1px 6px;
  margin-left: 6px;
  background: rgba(100, 200, 180, 0.15);
  color: #7ddfc8;
  border-radius: 2px;
  letter-spacing: 0.5px;
  text-transform: lowercase;
}

.detail-tag--cache {
  background: rgba(96, 165, 250, 0.15);
  color: #8bb8ff;
}

.detail-trace {
  font-size: 11px;
  line-height: 1.4;
  color: #f87171;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}

.detail-meta {
  font-size: 11px;
  color: #555577;
  margin-top: 6px;
}

.empty-stream {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 120px;
  color: #555577;
  font-size: 13px;
}

/* ─── Transition ─── */
.log-entry-enter-active {
  transition: all 0.3s ease;
}

.log-entry-enter-from {
  opacity: 0;
  transform: translateY(-6px);
  background: rgba(124, 58, 237, 0.08);
}
</style>
