<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { getStats, getLogTree, getSources, deleteLogs } from '../api/client'
import AppNav from '../components/AppNav.vue'
import StatCards from '../components/StatCards.vue'
import RequestChart from '../components/RequestChart.vue'
import LatencyHeatmap from '../components/LatencyHeatmap.vue'
import LogTree from '../components/LogTree.vue'
import LogStream from '../components/LogStream.vue'

// ─── State ───
const stats = ref({
  error_count: 0,
  request_count: 0,
  llm_count: 0,
  celery_count: 0,
  avg_request_ms: 0,
})

const sparkline = ref<Array<{ time: string; count: number }>>([])

const heatmapData = ref<
  Array<{ source: string; bucket: string | null; avg_ms: number; error_count: number }>
>([])

const logTree = ref<Record<string, any>>({})

const filterSource = ref<string | undefined>()
const filterLevel = ref<string | undefined>()

let refreshTimer: ReturnType<typeof setInterval> | null = null

// ─── Data fetching ───
async function fetchStats() {
  try {
    const { data } = await getStats()
    stats.value = {
      error_count: data.error_count ?? 0,
      request_count: data.request_count ?? 0,
      llm_count: data.llm_count ?? 0,
      celery_count: data.celery_count ?? 0,
      avg_request_ms: data.avg_request_ms ?? 0,
    }
    sparkline.value = data.sparkline ?? []
  } catch (e) {
    console.error('Failed to fetch stats:', e)
  }
}

async function fetchLogTree() {
  try {
    const { data } = await getLogTree()
    // Backend returns: { source: { total, levels: {}, categories: { cat: { total, levels } } } }
    logTree.value = data ?? {}
  } catch (e) {
    console.error('Failed to fetch log tree:', e)
  }
}

async function fetchHeatmapData() {
  try {
    const { data } = await getSources()
    heatmapData.value = data ?? []
  } catch (e) {
    console.error('Failed to fetch heatmap data:', e)
  }
}

function handleFilterChange(filter: { source?: string; level?: string }) {
  filterSource.value = filter.source
  filterLevel.value = filter.level
}

const clearOptions = [
  { label: '全部清除', value: 0 },
  { label: '1小时前', value: 1 },
  { label: '6小时前', value: 6 },
  { label: '24小时前', value: 24 },
  { label: '3天前', value: 72 },
]
const showClearMenu = ref(false)

async function handleClearLogs(hours: number) {
  showClearMenu.value = false
  const label = hours === 0 ? '所有日志' : `${hours}小时前的日志`
  if (!confirm(`确定清除${label}？此操作不可撤销。`)) return
  try {
    const { data } = await deleteLogs(hours)
    alert(`已删除 ${data.deleted} 条日志`)
    await Promise.all([fetchStats(), fetchLogTree(), fetchHeatmapData()])
  } catch (e) {
    alert('删除失败')
  }
}

async function refreshAll() {
  await Promise.all([fetchStats(), fetchLogTree(), fetchHeatmapData()])
}

onMounted(async () => {
  await Promise.all([fetchStats(), fetchLogTree(), fetchHeatmapData()])

  // Auto-refresh every 10s
  refreshTimer = setInterval(() => {
    fetchStats()
    fetchLogTree()
    fetchHeatmapData()
  }, 10_000)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<template>
  <div class="dashboard">
    <AppNav>
      <template #actions>
        <button class="refresh-btn" @click="refreshAll">↻ Refresh</button>
        <div class="clear-dropdown">
          <button class="clear-btn" @click="showClearMenu = !showClearMenu">Clear Logs ▾</button>
          <div v-if="showClearMenu" class="clear-menu">
            <button
              v-for="opt in clearOptions"
              :key="opt.value"
              class="clear-menu-item"
              @click="handleClearLogs(opt.value)"
            >{{ opt.label }}</button>
          </div>
        </div>
      </template>
    </AppNav>

    <!-- Main content -->
    <main class="dash-content">
      <!-- Stat cards row -->
      <section class="section-stats">
        <StatCards :stats="stats" />
      </section>

      <!-- Charts row -->
      <section class="section-charts">
        <div class="chart-left">
          <RequestChart :sparkline="sparkline" />
        </div>
        <div class="chart-right">
          <LatencyHeatmap :data="heatmapData" />
        </div>
      </section>

      <!-- Bottom: Tree + Stream -->
      <section class="section-logs">
        <div class="logs-tree">
          <LogTree :tree="logTree" @filter-change="handleFilterChange" />
        </div>
        <div class="logs-stream">
          <LogStream
            :filter-source="filterSource"
            :filter-level="filterLevel"
          />
        </div>
      </section>
    </main>

    <!-- Subtle grid overlay -->
    <div class="grid-overlay"></div>
  </div>
</template>

<style scoped>
.dashboard {
  min-height: 100vh;
  background: linear-gradient(135deg, #0a0a1a 0%, #1a1a2e 40%, #0f0f24 100%);
  position: relative;
}

.grid-overlay {
  position: fixed;
  inset: 0;
  background-image:
    linear-gradient(rgba(124, 58, 237, 0.015) 1px, transparent 1px),
    linear-gradient(90deg, rgba(124, 58, 237, 0.015) 1px, transparent 1px);
  background-size: 60px 60px;
  pointer-events: none;
  z-index: 0;
}

/* ─── Header action buttons ─── */
.refresh-btn {
  padding: 5px 14px;
  border: 1px solid rgba(74, 222, 128, 0.25);
  border-radius: 6px;
  background: rgba(74, 222, 128, 0.06);
  color: #4ade80;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.refresh-btn:hover {
  background: rgba(74, 222, 128, 0.12);
  border-color: rgba(74, 222, 128, 0.4);
}

.clear-dropdown {
  position: relative;
}

.clear-btn {
  padding: 5px 14px;
  border: 1px solid rgba(251, 191, 36, 0.25);
  border-radius: 6px;
  background: rgba(251, 191, 36, 0.06);
  color: #fbbf24;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.clear-btn:hover {
  background: rgba(251, 191, 36, 0.12);
  border-color: rgba(251, 191, 36, 0.4);
}

.clear-menu {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 4px;
  background: rgba(19, 19, 43, 0.95);
  border: 1px solid rgba(251, 191, 36, 0.25);
  border-radius: 6px;
  overflow: hidden;
  z-index: 200;
  min-width: 120px;
  backdrop-filter: blur(12px);
}

.clear-menu-item {
  display: block;
  width: 100%;
  padding: 8px 14px;
  border: none;
  background: transparent;
  color: #e0e0e0;
  font-size: 12px;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
}

.clear-menu-item:hover {
  background: rgba(251, 191, 36, 0.12);
  color: #fbbf24;
}

.clear-menu-item:first-child {
  color: #f87171;
}

/* ─── Content ─── */
.dash-content {
  position: relative;
  z-index: 1;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 1600px;
  margin: 0 auto;
}

.section-stats {
  /* full width stat cards */
}

.section-charts {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.chart-left,
.chart-right {
  min-height: 300px;
}

.section-logs {
  display: grid;
  grid-template-columns: 250px 1fr;
  gap: 20px;
  min-height: 400px;
}

.logs-tree {
  min-height: 400px;
}

.logs-stream {
  min-height: 400px;
}

/* ─── Responsive ─── */
@media (max-width: 1024px) {
  .section-charts {
    grid-template-columns: 1fr;
  }
  .section-logs {
    grid-template-columns: 1fr;
  }
}
</style>
