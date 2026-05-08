<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { HeatmapChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent])

const props = defineProps<{
  data: Array<{
    source: string
    bucket: string | null
    avg_ms: number
    error_count: number
  }>
}>()

function shortTime(iso: string | null): string {
  if (!iso) return '?'
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
  } catch { return '?' }
}

const option = computed(() => {
  if (!props.data || props.data.length === 0) return null

  const sources = [...new Set(props.data.map((d) => d.source))].sort()
  const buckets = [...new Set(props.data.map((d) => d.bucket ?? ''))].sort()
  const bucketLabels = buckets.map((b) => shortTime(b))

  const heatData: Array<[number, number, number]> = []
  let maxVal = 0

  for (const item of props.data) {
    const xi = buckets.indexOf(item.bucket ?? '')
    const yi = sources.indexOf(item.source)
    const val = item.error_count > 0 ? -1 : item.avg_ms
    if (item.avg_ms > maxVal) maxVal = item.avg_ms
    heatData.push([xi, yi, val])
  }

  return {
    backgroundColor: 'transparent',
    tooltip: {
      backgroundColor: 'rgba(19, 19, 43, 0.95)',
      borderColor: '#2a2a4a',
      textStyle: { color: '#e0e0e0', fontSize: 12 },
      formatter: (params: any) => {
        const [xi, yi, val] = params.data
        const source = sources[yi]
        const time = bucketLabels[xi]
        if (val === -1) {
          return `<div style="font-family:monospace"><b>${source}</b> @ ${time}<br/><span style="color:#f87171">ERROR</span></div>`
        }
        return `<div style="font-family:monospace"><b>${source}</b> @ ${time}<br/><span style="color:#fbbf24">${Math.round(val)}ms</span></div>`
      },
    },
    grid: {
      left: 180,
      right: 40,
      top: 10,
      bottom: 40,
    },
    xAxis: {
      type: 'category',
      data: bucketLabels,
      axisLine: { lineStyle: { color: '#2a2a4a' } },
      axisLabel: { color: '#8888aa', fontSize: 10 },
      axisTick: { show: false },
      splitArea: { show: false },
    },
    yAxis: {
      type: 'category',
      data: sources,
      axisLine: { lineStyle: { color: '#2a2a4a' } },
      axisLabel: { color: '#8888aa', fontSize: 10, width: 160, overflow: 'truncate' },
      axisTick: { show: false },
      splitArea: { show: false },
    },
    visualMap: {
      min: 0,
      max: Math.max(maxVal, 500),
      calculable: false,
      show: false,
      inRange: {
        color: ['#065f46', '#4ade80', '#fbbf24', '#f97316', '#ef4444'],
      },
    },
    series: [
      {
        type: 'heatmap',
        data: heatData,
        itemStyle: {
          borderColor: '#0a0a1a',
          borderWidth: 2,
          borderRadius: 3,
        },
        emphasis: {
          itemStyle: {
            borderColor: '#fff',
            borderWidth: 2,
          },
        },
        label: {
          show: true,
          formatter: (params: any) => {
            const val = params.data[2]
            if (val === -1) return 'ERR'
            if (val >= 1000) return (val / 1000).toFixed(1) + 's'
            return Math.round(val) + ''
          },
          color: '#e0e0e0',
          fontSize: 10,
          fontFamily: 'monospace',
        },
      },
    ],
  }
})
</script>

<template>
  <div class="heatmap-container">
    <h3 class="chart-title">Source Latency Heatmap</h3>
    <v-chart
      v-if="option"
      :option="option"
      autoresize
      class="chart"
    />
    <div v-else class="empty-state">No latency data yet</div>
  </div>
</template>

<style scoped>
.heatmap-container {
  background: rgba(19, 19, 43, 0.7);
  border: 1px solid rgba(42, 42, 74, 0.6);
  border-radius: 12px;
  padding: 20px;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.chart-title {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
  color: #c0c0d0;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.chart {
  flex: 1;
  min-height: 240px;
}

.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #555577;
  font-size: 13px;
}
</style>
