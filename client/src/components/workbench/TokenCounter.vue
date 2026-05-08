<template>
  <div class="token-counter" v-if="store.totalTokens > 0 || store.active">
    <div class="metric">
      <el-icon :size="11"><ArrowUp /></el-icon>
      <span class="num">{{ formatNum(store.cumulativeInputTokens) }}</span>
      <span class="label">in</span>
    </div>
    <div class="metric">
      <el-icon :size="11"><ArrowDown /></el-icon>
      <span class="num">{{ formatNum(store.cumulativeOutputTokens) }}</span>
      <span class="label">out</span>
    </div>
    <div class="metric cost" v-if="store.cumulativeCostUsd > 0">
      <span class="num">${{ store.cumulativeCostUsd.toFixed(4) }}</span>
    </div>
    <div v-if="store.lastModel" class="model">
      {{ store.lastModel }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ArrowUp, ArrowDown } from '@element-plus/icons-vue'
import { useWorkbenchStore } from '../../stores/workbench'

const store = useWorkbenchStore()

function formatNum(n: number): string {
  if (n < 1000) return String(n)
  if (n < 1_000_000) return (n / 1000).toFixed(1) + 'k'
  return (n / 1_000_000).toFixed(1) + 'M'
}
</script>

<style scoped>
.token-counter {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  color: var(--ink-400);
  font-variant-numeric: tabular-nums;
}
.metric {
  display: flex;
  align-items: center;
  gap: 3px;
}
.metric .num {
  font-weight: 600;
  color: var(--ink-700);
}
.metric .label {
  color: var(--ink-300);
  font-size: 10px;
}
.metric.cost .num {
  color: var(--signal-teal);
}
.model {
  margin-left: auto;
  color: var(--ink-300);
  font-family: var(--font-mono);
  font-size: 10px;
}
</style>
