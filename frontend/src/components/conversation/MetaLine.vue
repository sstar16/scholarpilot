<template>
  <div class="meta-line">
    <span class="meta-line__time">{{ formattedTime }}</span>
    <template v-if="model || inputTokens || outputTokens || elapsedMs">
      <template v-if="model">
        <span class="meta-line__sep">·</span>
        <span class="meta-line__model">{{ model }}</span>
      </template>
      <template v-if="inputTokens != null || outputTokens != null">
        <span class="meta-line__sep">·</span>
        <span class="meta-line__val">↑{{ inputTokens ?? 0 }} ↓{{ outputTokens ?? 0 }}</span>
      </template>
      <template v-if="elapsedMs">
        <span class="meta-line__sep">·</span>
        <span class="meta-line__val">{{ formattedElapsed }}</span>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  timestamp?: string
  model?: string
  inputTokens?: number | null
  outputTokens?: number | null
  elapsedMs?: number | null
}>()

const formattedTime = computed(() => {
  if (!props.timestamp) return ''
  const d = new Date(props.timestamp)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
})

const formattedElapsed = computed(() => {
  const ms = props.elapsedMs
  // 只对 null / 负数隐藏；0ms 是合法的（LLM cached hit），保留显示为 "0ms"
  if (ms == null || ms < 0) return ''
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
})
</script>

<style scoped>
.meta-line {
  font-family: var(--font-mono);
  font-size: var(--type-micro-size);
  color: var(--ink-400);
  display: flex;
  align-items: center;
  gap: var(--space-1);
  letter-spacing: 0.02em;
}
.meta-line__time { color: var(--ink-400); }
.meta-line__sep { color: var(--ink-200); }
.meta-line__model { color: var(--signal-blue); font-weight: 500; }
.meta-line__val { color: var(--ink-500); }
</style>
