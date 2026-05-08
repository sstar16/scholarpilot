<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  DataZoomComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, DataZoomComponent])

const props = defineProps<{
  sparkline: Array<{ time: string; count: number }>
}>()

const option = computed(() => {
  const times = props.sparkline.map((d) => d.time)
  const counts = props.sparkline.map((d) => d.count)

  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(19, 19, 43, 0.95)',
      borderColor: '#2a2a4a',
      textStyle: { color: '#e0e0e0', fontSize: 12 },
      formatter: (params: any) => {
        const p = params[0]
        return `<div style="font-family:monospace">${p.axisValue}<br/><span style="color:#4ade80;font-weight:bold">${p.value}</span> requests</div>`
      },
    },
    grid: {
      left: 50,
      right: 20,
      top: 20,
      bottom: 30,
    },
    xAxis: {
      type: 'category',
      data: times,
      axisLine: { lineStyle: { color: '#2a2a4a' } },
      axisLabel: { color: '#8888aa', fontSize: 10 },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: 'rgba(42, 42, 74, 0.4)' } },
      axisLine: { show: false },
      axisLabel: { color: '#8888aa', fontSize: 10 },
    },
    series: [
      {
        type: 'line',
        data: counts,
        smooth: true,
        showSymbol: false,
        lineStyle: {
          color: '#4ade80',
          width: 2,
        },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(74, 222, 128, 0.25)' },
              { offset: 1, color: 'rgba(74, 222, 128, 0.02)' },
            ],
          },
        },
        emphasis: {
          lineStyle: { width: 3 },
        },
      },
    ],
  }
})
</script>

<template>
  <div class="chart-container">
    <h3 class="chart-title">Request Volume</h3>
    <v-chart
      v-if="sparkline.length > 0"
      :option="option"
      autoresize
      class="chart"
    />
    <div v-else class="empty-state">No request data yet</div>
  </div>
</template>

<style scoped>
.chart-container {
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
