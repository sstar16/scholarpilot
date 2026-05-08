<script setup lang="ts">
import { computed, ref } from 'vue'
import type { SourceInfo } from '../api/client'

const props = defineProps<{
  sources: SourceInfo[]
  selectedId: string | null
}>()

const emit = defineEmits<{
  select: [sourceId: string]
}>()

const filterCategory = ref('')
const filterStatus = ref('')

const categoryOptions = [
  { label: 'All', value: '' },
  { label: 'Literature', value: 'literature' },
  { label: 'Patents', value: 'patents' },
  { label: 'Clinical', value: 'clinical' },
]

const statusOptions = [
  { label: 'All', value: '' },
  { label: 'Enabled', value: 'enabled' },
  { label: 'Disabled', value: 'disabled' },
]

const filtered = computed(() => {
  return props.sources.filter((s) => {
    if (filterCategory.value && s.category !== filterCategory.value) return false
    if (filterStatus.value === 'enabled' && !s.enabled) return false
    if (filterStatus.value === 'disabled' && s.enabled) return false
    return true
  })
})

function reliabilityColor(r: number) {
  if (r >= 0.9) return '#4ade80'
  if (r >= 0.7) return '#fbbf24'
  return '#f87171'
}

function categoryLabel(cat: string) {
  const map: Record<string, string> = { literature: 'LIT', patents: 'PAT', clinical: 'CLI' }
  return map[cat] || cat.toUpperCase()
}

function categoryColor(cat: string) {
  const map: Record<string, string> = {
    literature: '#60a5fa',
    patents: '#c084fc',
    clinical: '#4ade80',
  }
  return map[cat] || '#8888aa'
}
</script>

<template>
  <div class="source-table-wrap">
    <div class="table-filters">
      <select v-model="filterCategory" class="filter-select">
        <option v-for="o in categoryOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <select v-model="filterStatus" class="filter-select">
        <option v-for="o in statusOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
      </select>
      <span class="filter-count">{{ filtered.length }} / {{ sources.length }}</span>
    </div>

    <div class="table-scroll">
      <div
        v-for="s in filtered"
        :key="s.source_id"
        class="source-row"
        :class="{ selected: s.source_id === selectedId, disabled: !s.enabled }"
        @click="emit('select', s.source_id)"
      >
        <span class="status-dot" :class="{ on: s.enabled && s.has_fetcher, off: !s.enabled, noImpl: s.enabled && !s.has_fetcher }" />
        <div class="row-main">
          <span class="row-name">{{ s.name }}</span>
          <span class="row-id mono">{{ s.source_id }}</span>
        </div>
        <span class="cat-badge" :style="{ color: categoryColor(s.category), borderColor: categoryColor(s.category) }">
          {{ categoryLabel(s.category) }}
        </span>
        <span class="lang-badge">{{ s.language }}</span>
        <span class="reliability mono" :style="{ color: reliabilityColor(s.stats.reliability) }">
          {{ s.stats.total_invocations > 0 ? (s.stats.reliability * 100).toFixed(0) + '%' : '--' }}
        </span>
        <span class="latency mono">
          {{ s.stats.avg_latency_ms > 0 ? s.stats.avg_latency_ms + 'ms' : '--' }}
        </span>
      </div>

      <div v-if="filtered.length === 0" class="empty-msg">No sources match filters</div>
    </div>
  </div>
</template>

<style scoped>
.source-table-wrap {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.table-filters {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 12px 14px;
  border-bottom: 1px solid rgba(42, 42, 74, 0.6);
}
.filter-select {
  background: rgba(10, 10, 26, 0.6);
  color: #c4b5fd;
  border: 1px solid rgba(42, 42, 74, 0.8);
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 11px;
  outline: none;
}
.filter-select:focus { border-color: #7c3aed; }
.filter-count { font-size: 11px; color: #666; margin-left: auto; }

.table-scroll {
  flex: 1;
  overflow-y: auto;
}

.source-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid rgba(42, 42, 74, 0.3);
  cursor: pointer;
  transition: background 0.15s;
}
.source-row:hover { background: rgba(124, 58, 237, 0.06); }
.source-row.selected { background: rgba(124, 58, 237, 0.15); border-left: 3px solid #7c3aed; }
.source-row.disabled { opacity: 0.5; }

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.status-dot.on { background: #4ade80; box-shadow: 0 0 6px rgba(74, 222, 128, 0.4); }
.status-dot.off { background: #f87171; }
.status-dot.noImpl { background: #fbbf24; }

.row-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.row-name { font-size: 13px; font-weight: 600; color: #e2e2f0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.row-id { font-size: 10px; color: #666; }

.cat-badge {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 1px;
  border: 1px solid;
  border-radius: 4px;
  padding: 1px 5px;
  flex-shrink: 0;
}
.lang-badge { font-size: 10px; color: #8888aa; flex-shrink: 0; }
.reliability { font-size: 12px; width: 36px; text-align: right; flex-shrink: 0; }
.latency { font-size: 11px; color: #8888aa; width: 50px; text-align: right; flex-shrink: 0; }

.empty-msg { text-align: center; color: #666; font-size: 13px; padding: 30px; }

.mono { font-family: 'Fira Code', 'Cascadia Code', monospace; }
</style>
