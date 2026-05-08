<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import AppNav from '../components/AppNav.vue'
import { getLogs, deleteLogs, type LogEntry } from '../api/client'

// ─── 查询参数 ───
const level = ref<string>('')
const source = ref<string>('')
const category = ref<string>('')
const search = ref<string>('')
const roundId = ref<string>('')
const fromTs = ref<string>('')       // datetime-local 格式
const toTs = ref<string>('')

const page = ref(1)
const pageSize = ref(100)

const logs = ref<LogEntry[]>([])
const total = ref(0)
const loading = ref(false)
const errorMsg = ref('')

// 详情抽屉
const selected = ref<LogEntry | null>(null)

// 快捷时间按钮
const activePreset = ref<string>('24h')
const presets: Array<{ id: string; label: string; hours?: number }> = [
  { id: '1h', label: '最近 1 小时', hours: 1 },
  { id: '6h', label: '最近 6 小时', hours: 6 },
  { id: '24h', label: '最近 24 小时', hours: 24 },
  { id: '3d', label: '最近 3 天', hours: 72 },
  { id: '7d', label: '最近 7 天', hours: 168 },
  { id: 'custom', label: '自定义' },
]

function applyPreset(presetId: string) {
  activePreset.value = presetId
  const p = presets.find(x => x.id === presetId)
  if (!p) return
  if (p.id === 'custom') return
  if (typeof p.hours === 'number') {
    const to = new Date()
    const from = new Date(to.getTime() - p.hours * 3600_000)
    fromTs.value = toLocalIso(from)
    toTs.value = toLocalIso(to)
  }
  page.value = 1
  fetchLogs()
}

function toLocalIso(d: Date) {
  // YYYY-MM-DDTHH:mm (适配 <input type=datetime-local>)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`
}

function toApiIso(localValue: string): string | undefined {
  if (!localValue) return undefined
  try {
    // 本地时间串 → ISO（含时区偏移）
    const d = new Date(localValue)
    if (isNaN(d.getTime())) return undefined
    return d.toISOString()
  } catch {
    return undefined
  }
}

async function fetchLogs() {
  loading.value = true
  errorMsg.value = ''
  try {
    const { data } = await getLogs({
      level: level.value || undefined,
      source: source.value || undefined,
      category: category.value || undefined,
      search: search.value || undefined,
      round_id: roundId.value || undefined,
      from_ts: toApiIso(fromTs.value),
      to_ts: toApiIso(toTs.value),
      page: page.value,
      page_size: pageSize.value,
    })
    logs.value = data.items
    total.value = data.total
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || '查询失败'
  } finally {
    loading.value = false
  }
}

function doSearch() {
  page.value = 1
  fetchLogs()
}

function clearFilters() {
  level.value = ''
  source.value = ''
  category.value = ''
  search.value = ''
  roundId.value = ''
  applyPreset('24h')
}

async function clearOldLogs(hours: number) {
  const label = hours === 0 ? '所有日志' : `${hours}小时前的日志`
  if (!confirm(`确定清除${label}？此操作不可撤销。`)) return
  try {
    const { data } = await deleteLogs(hours)
    alert(`已删除 ${data.deleted} 条日志`)
    await fetchLogs()
  } catch {
    alert('删除失败')
  }
}

const pageMax = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

function prevPage() { if (page.value > 1) { page.value--; fetchLogs() } }
function nextPage() { if (page.value < pageMax.value) { page.value++; fetchLogs() } }

function openDetail(log: LogEntry) { selected.value = log }
function closeDetail() { selected.value = null }

function formatDt(iso?: string) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    const p = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
  } catch { return iso }
}

const contextJson = computed(() => {
  if (!selected.value?.context) return ''
  try { return JSON.stringify(selected.value.context, null, 2) } catch { return String(selected.value.context) }
})

onMounted(() => {
  applyPreset('24h')   // 默认 24h 并自动查一次
})
</script>

<template>
  <div class="logs-view">
    <AppNav />

    <main class="content">
      <h2 class="page-title">历史日志查询</h2>

      <!-- Filter bar -->
      <div class="filter-card">
        <!-- Preset buttons -->
        <div class="preset-row">
          <span class="label">时间范围：</span>
          <button
            v-for="p in presets" :key="p.id"
            class="preset-btn" :class="{ active: activePreset === p.id }"
            @click="applyPreset(p.id)"
          >{{ p.label }}</button>
        </div>

        <!-- Custom datetime -->
        <div class="filter-row">
          <label>从
            <input v-model="fromTs" type="datetime-local" class="input" @change="activePreset = 'custom'" />
          </label>
          <label>到
            <input v-model="toTs" type="datetime-local" class="input" @change="activePreset = 'custom'" />
          </label>
        </div>

        <!-- Filters -->
        <div class="filter-row">
          <label>级别
            <select v-model="level" class="input">
              <option value="">全部</option>
              <option value="DEBUG">DEBUG</option>
              <option value="INFO">INFO</option>
              <option value="WARNING">WARNING</option>
              <option value="ERROR">ERROR</option>
              <option value="CRITICAL">CRITICAL</option>
            </select>
          </label>
          <label>Source
            <input v-model="source" placeholder="如 celery / api / harness" class="input" />
          </label>
          <label>Category
            <input v-model="category" placeholder="如 tool_call_end" class="input" />
          </label>
          <label>Round ID
            <input v-model="roundId" placeholder="UUID" class="input" />
          </label>
          <label class="grow">关键词
            <input v-model="search" @keyup.enter="doSearch" placeholder="搜消息正文" class="input" />
          </label>
        </div>

        <div class="action-row">
          <button class="btn btn-primary" @click="doSearch" :disabled="loading">
            {{ loading ? '查询中...' : '🔍 查询' }}
          </button>
          <button class="btn" @click="clearFilters">重置</button>
          <span class="stat">共 <b>{{ total }}</b> 条</span>

          <div class="clear-group">
            <span class="label-sm">清除：</span>
            <button class="btn-sm" @click="clearOldLogs(24)">24h 前</button>
            <button class="btn-sm" @click="clearOldLogs(72)">3d 前</button>
            <button class="btn-sm btn-danger" @click="clearOldLogs(0)">全部</button>
          </div>
        </div>
      </div>

      <div v-if="errorMsg" class="error-box">{{ errorMsg }}</div>

      <!-- Table -->
      <div class="table-wrapper">
        <table class="data-table">
          <thead>
            <tr>
              <th style="width: 165px">时间</th>
              <th style="width: 80px">级别</th>
              <th style="width: 110px">Source</th>
              <th style="width: 130px">Category</th>
              <th>消息</th>
              <th style="width: 70px">耗时</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading && !logs.length">
              <td colspan="6" class="loading">加载中...</td>
            </tr>
            <tr v-else-if="!logs.length">
              <td colspan="6" class="loading">没有匹配的日志</td>
            </tr>
            <tr
              v-for="lg in logs" :key="lg.id"
              class="log-row" :class="`log-${lg.level.toLowerCase()}`"
              @click="openDetail(lg)"
            >
              <td class="mono-sm">{{ formatDt(lg.created_at) }}</td>
              <td>
                <span class="log-level-badge" :class="`lv-${lg.level.toLowerCase()}`">{{ lg.level }}</span>
              </td>
              <td class="mono-sm">{{ lg.source }}</td>
              <td class="mono-sm">{{ lg.category || '—' }}</td>
              <td class="msg">{{ lg.message }}</td>
              <td class="mono-sm tc">{{ lg.duration_ms != null ? `${lg.duration_ms}ms` : '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="pager">
        <span>第 {{ page }} / {{ pageMax }} 页 · 共 {{ total }} 条</span>
        <label class="size-select">
          每页
          <select v-model.number="pageSize" @change="doSearch" class="input input-sm">
            <option :value="50">50</option>
            <option :value="100">100</option>
            <option :value="200">200</option>
            <option :value="500">500</option>
          </select>
        </label>
        <button class="btn-sm" :disabled="page <= 1" @click="prevPage">← 上一页</button>
        <button class="btn-sm" :disabled="page >= pageMax" @click="nextPage">下一页 →</button>
      </div>
    </main>

    <!-- ─── Detail Drawer ─── -->
    <div v-if="selected" class="drawer-mask" @click.self="closeDetail">
      <aside class="drawer">
        <header class="drawer-header">
          <div>
            <h3>日志详情 #{{ selected.id }}</h3>
            <p class="mono-sm sub">{{ formatDt(selected.created_at) }} · {{ selected.source }} · {{ selected.level }}</p>
          </div>
          <button class="btn-sm" @click="closeDetail">✕</button>
        </header>
        <div class="drawer-body">
          <h4>消息</h4>
          <pre class="code">{{ selected.message }}</pre>

          <div class="kv-grid">
            <div><span>Category</span><b class="mono">{{ selected.category || '—' }}</b></div>
            <div><span>Project ID</span><b class="mono">{{ selected.project_id || '—' }}</b></div>
            <div><span>Round ID</span><b class="mono">{{ selected.round_id || '—' }}</b></div>
            <div><span>Duration</span><b>{{ selected.duration_ms != null ? `${selected.duration_ms} ms` : '—' }}</b></div>
          </div>

          <template v-if="selected.context && Object.keys(selected.context).length">
            <h4>Context</h4>
            <pre class="code code-ctx">{{ contextJson }}</pre>
          </template>

          <template v-if="selected.error_trace">
            <h4>Error Trace</h4>
            <pre class="code code-err">{{ selected.error_trace }}</pre>
          </template>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.logs-view {
  min-height: 100vh;
  background: linear-gradient(135deg, #0a0a1a 0%, #1a1a2e 40%, #0f0f24 100%);
  color: #e0e0e0;
}
.content { padding: 20px 24px; max-width: 1700px; margin: 0 auto; }
.page-title { margin: 0 0 16px; font-size: 18px; color: #fff; font-weight: 700; }

/* Filter card */
.filter-card {
  background: rgba(19, 19, 43, 0.55);
  border: 1px solid rgba(42, 42, 74, 0.5);
  border-radius: 10px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 16px;
}
.preset-row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.label { font-size: 12px; color: #8888aa; }
.label-sm { font-size: 11px; color: #8888aa; }
.preset-btn {
  padding: 4px 12px;
  border: 1px solid rgba(74, 74, 107, 0.5);
  background: rgba(10, 10, 26, 0.5);
  color: #aaaacc;
  border-radius: 14px;
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s;
}
.preset-btn:hover { color: #c4b5fd; border-color: rgba(124, 58, 237, 0.35); }
.preset-btn.active { color: #c4b5fd; background: rgba(124, 58, 237, 0.2); border-color: rgba(124, 58, 237, 0.6); }

.filter-row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.filter-row label { display: flex; flex-direction: column; gap: 4px; font-size: 11px; color: #8888aa; }
.filter-row .grow { flex: 1; min-width: 200px; }

.input {
  padding: 6px 10px;
  border: 1px solid rgba(74, 74, 107, 0.5);
  background: rgba(10, 10, 26, 0.6);
  color: #e0e0e0;
  border-radius: 6px;
  font-size: 12px;
  outline: none;
}
.input:focus { border-color: rgba(124, 58, 237, 0.6); }
.input-sm { padding: 3px 8px; font-size: 11px; }

.action-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.stat { font-size: 12px; color: #8888aa; }
.stat b { color: #c4b5fd; font-size: 14px; }

.btn, .btn-primary, .btn-sm {
  padding: 6px 14px;
  border: 1px solid rgba(74, 74, 107, 0.5);
  background: rgba(19, 19, 43, 0.6);
  color: #e0e0e0;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.btn:hover, .btn-sm:hover { background: rgba(124, 58, 237, 0.12); border-color: rgba(124, 58, 237, 0.35); }
.btn-primary {
  background: rgba(124, 58, 237, 0.18);
  border-color: rgba(124, 58, 237, 0.5);
  color: #c4b5fd;
}
.btn-primary:hover { background: rgba(124, 58, 237, 0.3); }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-sm { padding: 3px 10px; font-size: 11px; }
.btn-sm:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-danger { color: #f87171; border-color: rgba(248, 113, 113, 0.4); }
.btn-danger:hover { background: rgba(248, 113, 113, 0.18); }

.clear-group { display: flex; gap: 6px; align-items: center; margin-left: auto; }

.error-box {
  margin-bottom: 12px;
  padding: 10px 14px;
  background: rgba(248, 113, 113, 0.1);
  border: 1px solid rgba(248, 113, 113, 0.35);
  border-radius: 6px;
  color: #f87171;
  font-size: 12px;
}

/* Table */
.table-wrapper {
  border: 1px solid rgba(42, 42, 74, 0.4);
  border-radius: 10px;
  overflow: auto;
  background: rgba(19, 19, 43, 0.3);
  max-height: calc(100vh - 340px);
  min-height: 300px;
}
.data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.data-table th {
  padding: 8px 10px;
  text-align: left;
  background: rgba(10, 10, 26, 0.8);
  position: sticky;
  top: 0;
  color: #8888aa;
  font-weight: 600;
  font-size: 10px;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  border-bottom: 1px solid rgba(42, 42, 74, 0.6);
  z-index: 1;
}
.data-table td {
  padding: 7px 10px;
  border-bottom: 1px solid rgba(42, 42, 74, 0.2);
  vertical-align: top;
}
.log-row { cursor: pointer; transition: background 0.1s; }
.log-row:hover { background: rgba(124, 58, 237, 0.06); }
.log-error { background: rgba(248, 113, 113, 0.03); }
.log-warning, .log-warn { background: rgba(251, 191, 36, 0.03); }

.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.mono-sm { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; color: #aaaacc; }
.tc { text-align: center; }
.msg {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11.5px;
  color: #e0e0e0;
  max-width: 800px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.log-error .msg { color: #fca5a5; }

.log-level-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 700;
  min-width: 55px;
  text-align: center;
}
.lv-debug { background: rgba(74, 74, 107, 0.35); color: #9999bb; }
.lv-info { background: rgba(100, 180, 255, 0.15); color: #93c5fd; }
.lv-warning, .lv-warn { background: rgba(251, 191, 36, 0.2); color: #fbbf24; }
.lv-error { background: rgba(248, 113, 113, 0.2); color: #f87171; }
.lv-critical { background: #f87171; color: #fff; }

.loading {
  padding: 50px 12px;
  text-align: center;
  color: #8888aa;
  font-size: 12px;
}

.pager {
  display: flex;
  gap: 14px;
  align-items: center;
  justify-content: flex-end;
  font-size: 12px;
  color: #8888aa;
  margin-top: 12px;
}
.size-select { display: flex; gap: 6px; align-items: center; }

/* Drawer */
.drawer-mask {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(4px);
  z-index: 200;
  display: flex; justify-content: flex-end;
}
.drawer {
  width: min(700px, 100vw);
  height: 100%;
  background: rgba(10, 10, 26, 0.98);
  border-left: 1px solid rgba(124, 58, 237, 0.25);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.drawer-header {
  padding: 16px 20px;
  display: flex; justify-content: space-between; align-items: center;
  border-bottom: 1px solid rgba(42, 42, 74, 0.5);
}
.drawer-header h3 { margin: 0; font-size: 14px; color: #fff; }
.sub { margin: 4px 0 0; font-size: 11px; color: #8888aa; }
.drawer-body { overflow-y: auto; padding: 16px 20px; flex: 1; }
.drawer-body h4 { font-size: 11px; color: #c4b5fd; text-transform: uppercase; letter-spacing: 1px; margin: 16px 0 6px; }
.drawer-body h4:first-child { margin-top: 0; }

.code {
  background: rgba(19, 19, 43, 0.7);
  border: 1px solid rgba(42, 42, 74, 0.5);
  border-radius: 6px;
  padding: 10px 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11.5px;
  color: #e0e0e0;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 240px;
  overflow: auto;
}
.code-ctx { color: #c4b5fd; }
.code-err { color: #fca5a5; max-height: 400px; }

.kv-grid {
  display: grid; grid-template-columns: repeat(2, 1fr);
  gap: 10px;
  margin-top: 8px;
}
.kv-grid > div {
  padding: 8px 12px;
  background: rgba(19, 19, 43, 0.5);
  border-radius: 6px;
  border: 1px solid rgba(42, 42, 74, 0.4);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.kv-grid span { font-size: 10px; color: #8888aa; text-transform: uppercase; letter-spacing: 0.5px; }
.kv-grid b { font-weight: 600; color: #e0e0e0; font-size: 12px; }
</style>
