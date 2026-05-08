<script setup lang="ts">
defineProps<{
  stats: {
    error_count: number
    request_count: number
    llm_count: number
    celery_count: number
    avg_request_ms: number
  }
}>()

const cards = [
  { key: 'error_count', label: 'Errors', color: '#f87171', icon: '!' },
  { key: 'request_count', label: 'Requests', color: '#4ade80', icon: 'R' },
  { key: 'llm_count', label: 'LLM Calls', color: '#60a5fa', icon: 'L' },
  { key: 'celery_count', label: 'Celery Tasks', color: '#c084fc', icon: 'C' },
  { key: 'avg_request_ms', label: 'Avg Response', color: '#fbbf24', icon: 'T' },
] as const

function formatValue(key: string, value: number): string {
  if (key === 'avg_request_ms') {
    if (value >= 1000) return (value / 1000).toFixed(1) + 's'
    return Math.round(value) + 'ms'
  }
  if (value >= 10000) return (value / 1000).toFixed(1) + 'k'
  return String(value)
}
</script>

<template>
  <div class="stat-grid">
    <div
      v-for="card in cards"
      :key="card.key"
      class="stat-card"
      :style="{ '--glow-color': card.color }"
    >
      <div class="stat-icon" :style="{ color: card.color, borderColor: card.color + '33' }">
        {{ card.icon }}
      </div>
      <div class="stat-value">{{ formatValue(card.key, (stats as any)[card.key] ?? 0) }}</div>
      <div class="stat-label">{{ card.label }}</div>
      <div class="glow-ring"></div>
    </div>
  </div>
</template>

<style scoped>
.stat-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
}

@media (max-width: 1024px) {
  .stat-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 640px) {
  .stat-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

.stat-card {
  position: relative;
  padding: 20px;
  background: rgba(19, 19, 43, 0.7);
  border: 1px solid rgba(42, 42, 74, 0.6);
  border-radius: 12px;
  text-align: center;
  overflow: hidden;
  transition: all 0.3s ease;
}

.stat-card:hover {
  border-color: var(--glow-color);
  box-shadow: 0 0 24px color-mix(in srgb, var(--glow-color) 20%, transparent);
  transform: translateY(-2px);
}

.stat-icon {
  width: 36px;
  height: 36px;
  margin: 0 auto 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  border: 1px solid;
  font-weight: 800;
  font-size: 16px;
  font-family: var(--dt-mono);
  background: rgba(10, 10, 26, 0.5);
}

.stat-value {
  font-size: 32px;
  font-weight: 700;
  color: #fff;
  font-family: var(--dt-mono);
  line-height: 1.1;
}

.stat-label {
  margin-top: 6px;
  font-size: 12px;
  color: #8888aa;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.glow-ring {
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: radial-gradient(
    circle at center,
    color-mix(in srgb, var(--glow-color) 4%, transparent),
    transparent 50%
  );
  pointer-events: none;
  animation: glow-pulse 4s ease-in-out infinite;
}

@keyframes glow-pulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}
</style>
