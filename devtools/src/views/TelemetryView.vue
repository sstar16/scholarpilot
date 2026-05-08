<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import AppNav from '../components/AppNav.vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, LegendComponent, DataZoomComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { getTelemetry, type TelemetryResponse } from '../api/client'

use([BarChart, LineChart, GridComponent, TooltipComponent,
     LegendComponent, DataZoomComponent, CanvasRenderer])

const loading = ref(false)
const data = ref<TelemetryResponse | null>(null)
const days = ref(14)
const errorMsg = ref('')

let timer: ReturnType<typeof setInterval> | null = null

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await getTelemetry(days.value)
    data.value = res.data
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail || e?.message || 'load failed'
  } finally {
    loading.value = false
  }
}

const totals = computed(() => {
  const rows = data.value?.by_day || []
  return rows.reduce(
    (acc, r) => ({
      impr: acc.impr + r.impr,
      click: acc.click + r.click,
      dismiss: acc.dismiss + r.dismiss,
      ignore: acc.ignore + r.ignore,
    }),
    { impr: 0, click: 0, dismiss: 0, ignore: 0 },
  )
})

const overallCtr = computed(() =>
  totals.value.impr > 0
    ? ((totals.value.click / totals.value.impr) * 100).toFixed(1)
    : '0.0'
)

const overallDismiss = computed(() =>
  totals.value.impr > 0
    ? ((totals.value.dismiss / totals.value.impr) * 100).toFixed(1)
    : '0.0'
)

const overallIgnore = computed(() =>
  totals.value.impr > 0
    ? ((totals.value.ignore / totals.value.impr) * 100).toFixed(1)
    : '0.0'
)

const funnelChart = computed(() => {
  const rows = data.value?.by_day || []
  const dates = rows.map((r) => r.date)
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(19, 19, 43, 0.95)',
      borderColor: 'rgba(42, 42, 74, 0.8)',
      textStyle: { color: '#e2e2f0', fontSize: 12 },
    },
    legend: {
      data: ['Clicked', 'Dismissed', 'Ignored'],
      textStyle: { color: '#a8a8c2' },
      top: 4,
    },
    grid: { left: 50, right: 16, top: 36, bottom: 28 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLine: { lineStyle: { color: 'rgba(42, 42, 74, 0.6)' } },
      axisLabel: { color: '#8888aa', fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      name: 'unique users',
      nameTextStyle: { color: '#8888aa', fontSize: 11 },
      axisLine: { lineStyle: { color: 'rgba(42, 42, 74, 0.6)' } },
      splitLine: { lineStyle: { color: 'rgba(42, 42, 74, 0.3)' } },
      axisLabel: { color: '#8888aa', fontSize: 11 },
    },
    series: [
      {
        name: 'Clicked', type: 'bar', stack: 'funnel',
        data: rows.map((r) => r.click),
        itemStyle: { color: '#10b981' },
      },
      {
        name: 'Dismissed', type: 'bar', stack: 'funnel',
        data: rows.map((r) => r.dismiss),
        itemStyle: { color: '#f59e0b' },
      },
      {
        name: 'Ignored', type: 'bar', stack: 'funnel',
        data: rows.map((r) => r.ignore),
        itemStyle: { color: '#3f3f5e' },
      },
    ],
  }
})

const ctrLine = computed(() => {
  const rows = data.value?.by_day || []
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(19, 19, 43, 0.95)',
      borderColor: 'rgba(42, 42, 74, 0.8)',
      textStyle: { color: '#e2e2f0', fontSize: 12 },
      formatter: (params: any[]) => {
        const p = params[0]
        return `<span style="color:#8888aa">${p.name}</span><br/>` +
               `<span style="color:#10b981;font-weight:600">${(p.value).toFixed(1)}%</span> CTR`
      },
    },
    grid: { left: 50, right: 16, top: 16, bottom: 28 },
    xAxis: {
      type: 'category',
      data: rows.map((r) => r.date),
      axisLine: { lineStyle: { color: 'rgba(42, 42, 74, 0.6)' } },
      axisLabel: { color: '#8888aa', fontSize: 11 },
    },
    yAxis: {
      type: 'value', max: 100,
      axisLabel: { color: '#8888aa', formatter: '{value}%' },
      splitLine: { lineStyle: { color: 'rgba(42, 42, 74, 0.3)' } },
    },
    series: [
      {
        name: 'CTR', type: 'line', smooth: true,
        data: rows.map((r) => r.ctr),
        itemStyle: { color: '#10b981' },
        lineStyle: { width: 2 },
        areaStyle: { color: 'rgba(16, 185, 129, 0.12)' },
      },
    ],
  }
})

const recentRows = computed(() =>
  (data.value?.recent_events || [])
    .slice()
    .reverse()
    .slice(0, 20),
)

function eventColor(event: string): string {
  if (event.endsWith('_clicked')) return '#10b981'
  if (event.endsWith('_dismissed')) return '#f59e0b'
  if (event.endsWith('_impression')) return '#60a5fa'
  return '#8888aa'
}

onMounted(() => {
  load()
  timer = setInterval(load, 30_000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="page">
    <AppNav>
      <template #actions>
        <select v-model="days" @change="load" class="day-picker">
          <option :value="7">7 days</option>
          <option :value="14">14 days</option>
          <option :value="30">30 days</option>
          <option :value="90">90 days</option>
        </select>
        <button class="refresh-btn" @click="load" :disabled="loading">
          {{ loading ? '…' : '↻' }}
        </button>
      </template>
    </AppNav>

    <main class="content">
      <div v-if="errorMsg" class="error-bar">
        {{ errorMsg }}
      </div>

      <div v-if="!data?.available" class="empty">
        <p>📭 没有 telemetry 数据</p>
        <p class="hint">
          jsonl 文件路径：<code>{{ data?.path || '/app/data/telemetry.jsonl' }}</code>
          <br />
          会在第一条 stale_hint 触发后自动出现。
        </p>
      </div>

      <template v-else>
        <!-- KPI strip -->
        <section class="kpis">
          <div class="kpi">
            <div class="kpi-label">Impressions</div>
            <div class="kpi-value">{{ totals.impr.toLocaleString() }}</div>
            <div class="kpi-sub">unique user-days · {{ days }}d</div>
          </div>
          <div class="kpi success">
            <div class="kpi-label">CTR</div>
            <div class="kpi-value">{{ overallCtr }}%</div>
            <div class="kpi-sub">{{ totals.click.toLocaleString() }} clicked</div>
          </div>
          <div class="kpi warn">
            <div class="kpi-label">Dismiss</div>
            <div class="kpi-value">{{ overallDismiss }}%</div>
            <div class="kpi-sub">{{ totals.dismiss.toLocaleString() }} dismissed</div>
          </div>
          <div class="kpi muted">
            <div class="kpi-label">Ignore</div>
            <div class="kpi-value">{{ overallIgnore }}%</div>
            <div class="kpi-sub">{{ totals.ignore.toLocaleString() }} no action</div>
          </div>
        </section>

        <!-- Charts -->
        <section class="charts">
          <div class="chart-card">
            <h3>每日漏斗（按 unique user-day 计）</h3>
            <VChart class="chart" :option="funnelChart" autoresize />
          </div>
          <div class="chart-card">
            <h3>CTR 趋势</h3>
            <VChart class="chart" :option="ctrLine" autoresize />
          </div>
        </section>

        <!-- Recent events feed -->
        <section class="feed">
          <h3>最近事件 (top 20)</h3>
          <table class="evt-table">
            <thead>
              <tr>
                <th>time</th>
                <th>event</th>
                <th>project</th>
                <th>extra</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, i) in recentRows" :key="i">
                <td class="mono">{{ (r.ts || '').slice(11, 19) }}</td>
                <td>
                  <span class="evt-pill" :style="{ color: eventColor(r.event), borderColor: eventColor(r.event) }">
                    {{ r.event }}
                  </span>
                </td>
                <td class="mono dim">{{ (r.project_id || '').slice(0, 8) }}</td>
                <td class="dim">
                  <template v-if="r.days_ago != null">days_ago={{ r.days_ago }}</template>
                  <template v-if="r.threshold != null"> · thr={{ r.threshold }}</template>
                  <template v-if="r.mute_days != null"> · mute={{ r.mute_days }}d</template>
                </td>
              </tr>
              <tr v-if="recentRows.length === 0">
                <td colspan="4" class="dim center">— no events in window —</td>
              </tr>
            </tbody>
          </table>
        </section>
      </template>
    </main>
  </div>
</template>

<style scoped>
.page { min-height: 100vh; background: #0a0a1a; color: #e2e2f0; font-family: 'Inter', system-ui, sans-serif; }
.content { padding: 20px 24px 40px; max-width: 1200px; margin: 0 auto; }

.day-picker {
  background: rgba(19, 19, 43, 0.8);
  border: 1px solid rgba(42, 42, 74, 0.6);
  color: #e2e2f0;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
}
.refresh-btn {
  background: rgba(19, 19, 43, 0.8);
  border: 1px solid rgba(42, 42, 74, 0.6);
  color: #e2e2f0;
  width: 28px; height: 28px;
  border-radius: 6px;
  cursor: pointer;
}
.refresh-btn:disabled { opacity: 0.5; }

.error-bar { background: rgba(239, 68, 68, 0.15); border: 1px solid #ef4444; border-radius: 6px; padding: 8px 12px; margin-bottom: 16px; color: #fca5a5; font-size: 13px; }

.empty { padding: 80px 20px; text-align: center; color: #8888aa; }
.empty .hint { font-size: 13px; opacity: 0.8; margin-top: 12px; }
.empty code { background: rgba(42, 42, 74, 0.4); padding: 2px 8px; border-radius: 4px; font-size: 12px; }

.kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }
.kpi {
  background: rgba(19, 19, 43, 0.6);
  border: 1px solid rgba(42, 42, 74, 0.4);
  border-radius: 8px; padding: 14px 16px;
}
.kpi-label { font-size: 11px; color: #8888aa; text-transform: uppercase; letter-spacing: 1px; }
.kpi-value { font-size: 28px; font-weight: 700; margin-top: 4px; }
.kpi-sub { font-size: 11px; color: #6a6a85; margin-top: 4px; }
.kpi.success .kpi-value { color: #10b981; }
.kpi.warn .kpi-value { color: #f59e0b; }
.kpi.muted .kpi-value { color: #6a6a85; }

.charts { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }
.chart-card { background: rgba(19, 19, 43, 0.6); border: 1px solid rgba(42, 42, 74, 0.4); border-radius: 8px; padding: 16px; }
.chart-card h3 { font-size: 13px; margin: 0 0 12px; color: #a8a8c2; font-weight: 500; }
.chart { width: 100%; height: 240px; }

.feed { background: rgba(19, 19, 43, 0.6); border: 1px solid rgba(42, 42, 74, 0.4); border-radius: 8px; padding: 16px; }
.feed h3 { font-size: 13px; margin: 0 0 12px; color: #a8a8c2; font-weight: 500; }
.evt-table { width: 100%; font-size: 12px; border-collapse: collapse; }
.evt-table th { text-align: left; color: #6a6a85; font-weight: 500; padding: 6px 8px; border-bottom: 1px solid rgba(42, 42, 74, 0.4); }
.evt-table td { padding: 6px 8px; border-bottom: 1px solid rgba(42, 42, 74, 0.2); }
.evt-pill { font-size: 11px; padding: 2px 8px; border-radius: 3px; border: 1px solid; background: rgba(255,255,255,0.02); }
.mono { font-family: 'JetBrains Mono', monospace; }
.dim { color: #6a6a85; }
.center { text-align: center; }

@media (max-width: 900px) {
  .kpis { grid-template-columns: repeat(2, 1fr); }
  .charts { grid-template-columns: 1fr; }
}
</style>
