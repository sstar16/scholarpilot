<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { getKBStats, type KBStats } from '../api/client'
import AppNav from '../components/AppNav.vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const loading = ref(false)
const stats = ref<KBStats | null>(null)

let refreshTimer: ReturnType<typeof setInterval> | null = null

// ─── Computed ───

const totalStorage = computed(() => {
  if (!stats.value?.file_sizes) return 0
  return Object.values(stats.value.file_sizes).reduce((a, b) => a + b, 0)
})

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`
}

function formatNum(n: number | undefined): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

const yearChartOption = computed(() => {
  const byYear = stats.value?.by_year ?? []
  const sorted = [...byYear].sort((a, b) => a.publication_year - b.publication_year)
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(19, 19, 43, 0.95)',
      borderColor: 'rgba(42, 42, 74, 0.8)',
      textStyle: { color: '#e2e2f0', fontSize: 12 },
      formatter: (params: any[]) => {
        const p = params[0]
        return `<span style="color:#8888aa">${p.name}</span><br/><span style="color:#60a5fa;font-weight:600">${p.value.toLocaleString()}</span> works`
      },
    },
    grid: { left: 48, right: 16, top: 16, bottom: 36 },
    xAxis: {
      type: 'category',
      data: sorted.map((d) => String(d.publication_year)),
      axisLine: { lineStyle: { color: 'rgba(42, 42, 74, 0.6)' } },
      axisTick: { show: false },
      axisLabel: { color: '#8888aa', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: 'rgba(42, 42, 74, 0.35)' } },
      axisLabel: { color: '#8888aa', fontSize: 10 },
    },
    series: [
      {
        type: 'bar',
        data: sorted.map((d) => d.count),
        itemStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: '#60a5fa' },
              { offset: 1, color: 'rgba(96, 165, 250, 0.3)' },
            ],
          },
          borderRadius: [3, 3, 0, 0],
        },
        emphasis: {
          itemStyle: { color: '#93c5fd' },
        },
      },
    ],
  }
})

const syncInfo = computed(() => {
  const s = stats.value?.sync_state
  if (!s) return null
  return s
})

// ─── Actions ───

async function fetchData() {
  loading.value = true
  try {
    const { data } = await getKBStats()
    stats.value = data
  } catch (e) {
    console.error('Failed to fetch KB stats:', e)
    stats.value = { available: false, message: 'Failed to reach API' }
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await fetchData()
  refreshTimer = setInterval(fetchData, 30_000)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})
</script>

<template>
  <div class="local-data-page">
    <AppNav>
      <template #actions>
        <button class="refresh-btn" :class="{ spinning: loading }" @click="fetchData">↻ Refresh</button>
      </template>
    </AppNav>

    <!-- Main content -->
    <main class="page-content">

      <!-- KB unavailable state -->
      <div v-if="stats && !stats.available" class="unavailable-card">
        <div class="unavail-icon">⚠</div>
        <div class="unavail-title">Local Knowledge Base Not Available</div>
        <div class="unavail-msg">{{ stats.message || 'The local KB is not configured or unreachable.' }}</div>
      </div>

      <!-- Loading skeleton -->
      <div v-else-if="loading && !stats" class="loading-state">
        <div class="loading-text">Loading knowledge base stats…</div>
      </div>

      <!-- Data loaded -->
      <template v-else-if="stats && stats.available">

        <!-- Overview cards -->
        <section class="overview-cards">
          <div class="stat-card">
            <div class="stat-icon" style="color: #60a5fa; background: rgba(96,165,250,0.1); border-color: rgba(96,165,250,0.2);">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
              </svg>
            </div>
            <div class="stat-body">
              <div class="stat-value">{{ formatNum(stats.total_works) }}</div>
              <div class="stat-label">Total Works</div>
            </div>
          </div>

          <div class="stat-card">
            <div class="stat-icon" style="color: #4ade80; background: rgba(74,222,128,0.1); border-color: rgba(74,222,128,0.2);">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="8"/>
                <line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
            </div>
            <div class="stat-body">
              <div class="stat-value">{{ formatNum(stats.fts_indexed) }}</div>
              <div class="stat-label">FTS Indexed</div>
            </div>
          </div>

          <div class="stat-card">
            <div class="stat-icon" style="color: #f59e0b; background: rgba(245,158,11,0.1); border-color: rgba(245,158,11,0.2);">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="8" y1="6" x2="21" y2="6"/>
                <line x1="8" y1="12" x2="21" y2="12"/>
                <line x1="8" y1="18" x2="21" y2="18"/>
                <line x1="3" y1="6" x2="3.01" y2="6"/>
                <line x1="3" y1="12" x2="3.01" y2="12"/>
                <line x1="3" y1="18" x2="3.01" y2="18"/>
              </svg>
            </div>
            <div class="stat-body">
              <div class="stat-value">{{ formatNum(stats.citation_count) }}</div>
              <div class="stat-label">Citations</div>
            </div>
          </div>

          <div class="stat-card">
            <div class="stat-icon" style="color: #c084fc; background: rgba(192,132,252,0.1); border-color: rgba(192,132,252,0.2);">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 12H2M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
                <circle cx="12" cy="12" r="10"/>
              </svg>
            </div>
            <div class="stat-body">
              <div class="stat-value">{{ formatBytes(totalStorage) }}</div>
              <div class="stat-label">Storage Size</div>
            </div>
          </div>
        </section>

        <!-- Year distribution chart -->
        <section class="card chart-card">
          <div class="card-header">
            <span class="card-title">Publications by Year</span>
            <span class="card-badge">{{ (stats.by_year ?? []).length }} years</span>
          </div>
          <div class="chart-wrap">
            <VChart
              v-if="stats.by_year && stats.by_year.length"
              :option="yearChartOption"
              autoresize
              style="height: 100%; width: 100%;"
            />
            <div v-else class="empty-state">No year data available</div>
          </div>
        </section>

        <!-- Breakdown grids -->
        <section class="breakdown-row">

          <!-- By Type -->
          <div class="card breakdown-card">
            <div class="card-header">
              <span class="card-title">By Type</span>
            </div>
            <div class="breakdown-list" v-if="stats.by_type && stats.by_type.length">
              <div
                v-for="item in stats.by_type"
                :key="item.type"
                class="breakdown-item"
              >
                <div class="breakdown-bar-wrap">
                  <div
                    class="breakdown-bar"
                    :style="{
                      width: `${Math.round((item.count / (stats.total_works || 1)) * 100)}%`,
                      background: 'rgba(96,165,250,0.3)',
                    }"
                  ></div>
                </div>
                <span class="breakdown-label">{{ item.type || '(unknown)' }}</span>
                <span class="breakdown-count">{{ formatNum(item.count) }}</span>
              </div>
            </div>
            <div v-else class="empty-state">No data</div>
          </div>

          <!-- By Language -->
          <div class="card breakdown-card">
            <div class="card-header">
              <span class="card-title">By Language</span>
            </div>
            <div class="breakdown-list" v-if="stats.by_language && stats.by_language.length">
              <div
                v-for="item in stats.by_language"
                :key="item.language"
                class="breakdown-item"
              >
                <div class="breakdown-bar-wrap">
                  <div
                    class="breakdown-bar"
                    :style="{
                      width: `${Math.round((item.count / (stats.total_works || 1)) * 100)}%`,
                      background: 'rgba(74,222,128,0.3)',
                    }"
                  ></div>
                </div>
                <span class="breakdown-label">{{ item.language || '(unknown)' }}</span>
                <span class="breakdown-count">{{ formatNum(item.count) }}</span>
              </div>
            </div>
            <div v-else class="empty-state">No data</div>
          </div>

          <!-- By Domain -->
          <div class="card breakdown-card">
            <div class="card-header">
              <span class="card-title">By Domain</span>
            </div>
            <div class="breakdown-list" v-if="stats.by_domain && stats.by_domain.length">
              <div
                v-for="item in stats.by_domain"
                :key="item.primary_domain_name"
                class="breakdown-item"
              >
                <div class="breakdown-bar-wrap">
                  <div
                    class="breakdown-bar"
                    :style="{
                      width: `${Math.round((item.count / (stats.total_works || 1)) * 100)}%`,
                      background: 'rgba(245,158,11,0.3)',
                    }"
                  ></div>
                </div>
                <span class="breakdown-label">{{ item.primary_domain_name || '(unknown)' }}</span>
                <span class="breakdown-count">{{ formatNum(item.count) }}</span>
              </div>
            </div>
            <div v-else class="empty-state">No data</div>
          </div>

        </section>

        <!-- Bottom row: Topics + Sync + Files -->
        <section class="bottom-row">

          <!-- Top Topics table -->
          <div class="card topics-card">
            <div class="card-header">
              <span class="card-title">Top Topics</span>
              <span class="card-badge">Top 20</span>
            </div>
            <el-table
              v-if="stats.top_topics && stats.top_topics.length"
              :data="stats.top_topics.slice(0, 20)"
              size="small"
              class="topics-table"
              :show-header="true"
            >
              <el-table-column label="#" type="index" width="44" />
              <el-table-column label="Topic" prop="primary_topic_name" min-width="200">
                <template #default="{ row }">
                  <span class="topic-name">{{ row.primary_topic_name }}</span>
                </template>
              </el-table-column>
              <el-table-column label="Count" prop="count" width="90" align="right">
                <template #default="{ row }">
                  <span class="topic-count">{{ formatNum(row.count) }}</span>
                </template>
              </el-table-column>
            </el-table>
            <div v-else class="empty-state">No topic data available</div>
          </div>

          <!-- Right column: Sync info + File sizes -->
          <div class="side-column">

            <!-- Sync Info -->
            <div class="card sync-card">
              <div class="card-header">
                <span class="card-title">Sync Info</span>
              </div>
              <div v-if="syncInfo" class="sync-grid">
                <template v-for="(val, key) in syncInfo" :key="key">
                  <span class="sync-key">{{ key }}</span>
                  <span class="sync-val mono">{{ val }}</span>
                </template>
              </div>
              <div v-else class="empty-state">No sync state available</div>
            </div>

            <!-- File Sizes -->
            <div class="card files-card">
              <div class="card-header">
                <span class="card-title">File Sizes</span>
              </div>
              <div v-if="stats.file_sizes && Object.keys(stats.file_sizes).length" class="files-list">
                <div
                  v-for="(size, filename) in stats.file_sizes"
                  :key="filename"
                  class="file-row"
                >
                  <span class="file-name mono">{{ filename }}</span>
                  <span class="file-size">{{ formatBytes(size) }}</span>
                </div>
                <div class="file-row total-row">
                  <span class="file-name">Total</span>
                  <span class="file-size total-size">{{ formatBytes(totalStorage) }}</span>
                </div>
              </div>
              <div v-else class="empty-state">No file size data</div>
            </div>

          </div>
        </section>

      </template>

    </main>

    <!-- Grid overlay -->
    <div class="grid-overlay"></div>
  </div>
</template>

<style scoped>
.local-data-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #0a0a1a 0%, #1a1a2e 40%, #0f0f24 100%);
  color: #e2e2f0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
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

/* ─── Refresh button ─── */
.refresh-btn {
  padding: 5px 14px;
  border: 1px solid rgba(74, 222, 128, 0.25);
  border-radius: 6px;
  background: rgba(74, 222, 128, 0.06);
  color: #4ade80;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
  display: inline-block;
}
.refresh-btn:hover { background: rgba(74, 222, 128, 0.12); border-color: rgba(74, 222, 128, 0.4); }
.refresh-btn.spinning { opacity: 0.7; }

/* ─── Page content ─── */
.page-content {
  position: relative;
  z-index: 1;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 1600px;
  margin: 0 auto;
}

/* ─── Unavailable / Loading ─── */
.unavailable-card {
  background: rgba(248, 113, 113, 0.05);
  border: 1px solid rgba(248, 113, 113, 0.2);
  border-radius: 12px;
  padding: 48px 32px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}
.unavail-icon { font-size: 36px; color: #f87171; }
.unavail-title { font-size: 18px; font-weight: 600; color: #f87171; }
.unavail-msg { font-size: 13px; color: #8888aa; }

.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 300px;
}
.loading-text { font-size: 13px; color: #8888aa; }

/* ─── Overview cards ─── */
.overview-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.stat-card {
  background: rgba(19, 19, 43, 0.7);
  border: 1px solid rgba(42, 42, 74, 0.6);
  border-radius: 12px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  transition: border-color 0.2s;
}
.stat-card:hover { border-color: rgba(124, 58, 237, 0.3); }

.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  border-width: 1px;
  border-style: solid;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-body { display: flex; flex-direction: column; gap: 4px; }
.stat-value {
  font-size: 28px;
  font-weight: 700;
  font-family: 'Fira Code', 'Cascadia Code', monospace;
  color: #f0f0ff;
  line-height: 1;
}
.stat-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: #8888aa;
}

/* ─── Generic card ─── */
.card {
  background: rgba(19, 19, 43, 0.7);
  border: 1px solid rgba(42, 42, 74, 0.6);
  border-radius: 12px;
  padding: 20px;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
}
.card-title {
  font-size: 13px;
  font-weight: 600;
  color: #c4b5fd;
  text-transform: uppercase;
  letter-spacing: 0.8px;
}
.card-badge {
  font-size: 10px;
  color: #8888aa;
  background: rgba(42, 42, 74, 0.6);
  border: 1px solid rgba(42, 42, 74, 0.8);
  padding: 1px 7px;
  border-radius: 10px;
}

/* ─── Year chart ─── */
.chart-card .chart-wrap {
  height: 220px;
}

/* ─── Breakdown row ─── */
.breakdown-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.breakdown-card { }

.breakdown-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.breakdown-item {
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 8px;
  position: relative;
}

.breakdown-bar-wrap {
  grid-column: 1 / -1;
  height: 3px;
  background: rgba(42, 42, 74, 0.4);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: -4px;
}
.breakdown-bar {
  height: 100%;
  border-radius: 2px;
  transition: width 0.4s ease;
}

.breakdown-label {
  font-size: 12px;
  color: #c0c0d8;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.breakdown-count {
  font-size: 12px;
  font-family: 'Fira Code', 'Cascadia Code', monospace;
  color: #8888aa;
  white-space: nowrap;
}

/* ─── Bottom row ─── */
.bottom-row {
  display: grid;
  grid-template-columns: 1fr 360px;
  gap: 16px;
  align-items: start;
}

.side-column {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ─── Topics table ─── */
.topics-card { overflow: hidden; }

.topics-table {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(42, 42, 74, 0.3);
  --el-table-border-color: rgba(42, 42, 74, 0.5);
  --el-table-text-color: #c0c0d8;
  --el-table-header-text-color: #8888aa;
  --el-table-row-hover-bg-color: rgba(124, 58, 237, 0.06);
  background: transparent;
}

.topic-name {
  font-size: 12px;
  color: #c0c0d8;
}
.topic-count {
  font-family: 'Fira Code', 'Cascadia Code', monospace;
  font-size: 12px;
  color: #60a5fa;
}

/* ─── Sync info ─── */
.sync-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 16px;
  align-items: baseline;
}
.sync-key {
  font-size: 11px;
  color: #8888aa;
  text-transform: capitalize;
  white-space: nowrap;
}
.sync-val {
  font-size: 11px;
  color: #c0c0d8;
  word-break: break-all;
}

/* ─── File sizes ─── */
.files-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.file-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 5px 8px;
  border-radius: 6px;
  background: rgba(42, 42, 74, 0.2);
}
.file-name {
  font-size: 11px;
  color: #8888aa;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 200px;
}
.file-size {
  font-size: 11px;
  font-family: 'Fira Code', 'Cascadia Code', monospace;
  color: #c4b5fd;
  white-space: nowrap;
  margin-left: 8px;
}
.total-row {
  background: rgba(124, 58, 237, 0.08);
  border: 1px solid rgba(124, 58, 237, 0.15);
  margin-top: 4px;
}
.total-row .file-name { color: #c4b5fd; font-weight: 600; font-family: inherit; }
.total-size { color: #c4b5fd; font-weight: 600; }

.empty-state {
  font-size: 12px;
  color: #8888aa;
  text-align: center;
  padding: 24px 0;
}

.mono { font-family: 'Fira Code', 'Cascadia Code', monospace; }

/* ─── Responsive ─── */
@media (max-width: 1100px) {
  .overview-cards { grid-template-columns: repeat(2, 1fr); }
  .breakdown-row { grid-template-columns: 1fr 1fr; }
  .breakdown-row > :last-child { grid-column: 1 / -1; }
  .bottom-row { grid-template-columns: 1fr; }
  .side-column { display: grid; grid-template-columns: 1fr 1fr; }
}

@media (max-width: 700px) {
  .overview-cards { grid-template-columns: 1fr 1fr; }
  .breakdown-row { grid-template-columns: 1fr; }
  .side-column { grid-template-columns: 1fr; }
}
</style>
