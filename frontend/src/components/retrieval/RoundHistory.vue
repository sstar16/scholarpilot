<template>
  <div class="round-history">
    <div class="rh-header" @click="expanded = !expanded">
      <h4 class="rh-title">检索历史</h4>
      <span class="rh-count">{{ rounds.length }} 轮</span>
      <span class="rh-arrow">{{ expanded ? '▾' : '▸' }}</span>
    </div>

    <transition name="slide">
      <div v-if="expanded" class="rh-list">
        <div
          v-for="r in sortedRounds"
          :key="r.id"
          class="rh-item"
          :class="{ active: r.id === activeRoundId, complete: r.status === 'complete' }"
          @click="$emit('select-round', r)"
        >
          <div class="rh-num">R{{ r.round_number }}</div>
          <div class="rh-info">
            <span class="rh-status" :class="'s-' + r.status">{{ statusLabel(r.status) }}</span>
            <span class="rh-docs">{{ r.selected_count || r.total_candidates || 0 }} 篇</span>
          </div>
          <span v-if="r.completed_at" class="rh-date">{{ formatDate(r.completed_at) }}</span>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  rounds: any[]
  activeRoundId?: string
}>()

defineEmits<{
  (e: 'select-round', round: any): void
}>()

const expanded = ref(false)

const sortedRounds = computed(() =>
  [...props.rounds].sort((a, b) => b.round_number - a.round_number)
)

function statusLabel(status: string): string {
  const m: Record<string, string> = {
    pending: '准备中', searching: '检索中', summarizing: '摘要中',
    awaiting_keywords: '等待确认', awaiting_feedback: '等待分类',
    complete: '已完成', failed: '失败',
  }
  return m[status] || status
}

function formatDate(d: string): string {
  return d ? new Date(d).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }) : ''
}
</script>

<style scoped>
.round-history {
  border: 1px solid var(--ink-100, #e2e8f0);
  border-radius: 10px;
  overflow: hidden;
  margin-bottom: 16px;
}
.rh-header {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px; cursor: pointer;
  background: var(--paper-cool, #f8fafc);
}
.rh-header:hover { background: var(--ink-50, #f1f5f9); }
.rh-title {
  font-size: 13px; font-weight: 700; margin: 0;
  color: var(--ink-700, #334155); flex: 1;
}
.rh-count {
  font-size: 11px; color: var(--ink-400, #94a3b8);
  background: var(--ink-100, #e2e8f0); padding: 1px 8px;
  border-radius: 10px;
}
.rh-arrow { font-size: 10px; color: var(--ink-300); }

.rh-list { padding: 4px 8px 8px; }

.rh-item {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 10px; border-radius: 8px;
  cursor: pointer; transition: background 0.15s;
}
.rh-item:hover { background: var(--ink-50, #f1f5f9); }
.rh-item.active { background: var(--signal-teal-bg, rgba(13,148,136,0.08)); }

.rh-num {
  font-size: 12px; font-weight: 800; color: var(--ink-500);
  width: 28px; text-align: center;
}
.rh-info { flex: 1; display: flex; gap: 8px; align-items: center; }
.rh-status {
  font-size: 11px; font-weight: 600; padding: 1px 8px;
  border-radius: 10px;
}
.s-complete { background: var(--signal-emerald-bg); color: var(--signal-emerald); }
.s-searching, .s-summarizing { background: var(--signal-blue-bg); color: var(--signal-blue); }
.s-awaiting_feedback, .s-awaiting_keywords { background: var(--signal-amber-bg); color: var(--signal-amber); }
.s-failed { background: var(--signal-coral-bg); color: var(--signal-coral); }
.s-pending { background: var(--ink-100); color: var(--ink-500); }

.rh-docs { font-size: 11px; color: var(--ink-400); }
.rh-date { font-size: 10px; color: var(--ink-300); }

.slide-enter-active { transition: all 0.2s ease-out; }
.slide-leave-active { transition: all 0.15s ease-in; }
.slide-enter-from, .slide-leave-to { opacity: 0; max-height: 0; }
.slide-enter-to, .slide-leave-from { opacity: 1; max-height: 600px; }
</style>
