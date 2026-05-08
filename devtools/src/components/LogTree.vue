<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  tree: Record<string, any>
}>()

const emit = defineEmits<{
  'filter-change': [filter: { source?: string; level?: string; category?: string }]
}>()

interface TreeNode {
  id: string
  label: string
  count?: number
  children?: TreeNode[]
}

const treeData = computed<TreeNode[]>(() => {
  if (!props.tree || Object.keys(props.tree).length === 0) {
    return [{ id: 'empty', label: 'No logs yet' }]
  }

  // Backend returns: { source: { total, levels: {}, categories: { cat: { total, levels } } } }
  return Object.entries(props.tree).map(([source, info]: [string, any]) => ({
    id: `src:${source}`,
    label: `${source} (${info.total ?? 0})`,
    count: info.total,
    children: Object.entries(info.categories ?? {}).map(([cat, catInfo]: [string, any]) => ({
      id: `cat:${source}:${cat}`,
      label: `${cat} (${catInfo.total ?? 0})`,
      count: catInfo.total,
      children: Object.entries(catInfo.levels ?? {}).map(([level, cnt]) => ({
        id: `lvl:${source}:${cat}:${level}`,
        label: `${level} (${cnt})`,
        count: cnt as number,
      })),
    })),
  }))
})

const defaultProps = {
  children: 'children',
  label: 'label',
}

function handleNodeClick(data: TreeNode) {
  const id = data.id
  if (id.startsWith('src:')) {
    emit('filter-change', { source: id.replace('src:', '') })
  } else if (id.startsWith('cat:')) {
    const parts = id.split(':')
    emit('filter-change', { source: parts[1], category: parts[2] })
  } else if (id.startsWith('lvl:')) {
    const parts = id.split(':')
    emit('filter-change', { source: parts[1], level: parts[3] })
  }
}

const quickFilters = [
  { label: 'ERROR', level: 'ERROR', color: '#f87171', bg: 'rgba(248,113,113,0.12)' },
  { label: 'WARN', level: 'WARNING', color: '#fbbf24', bg: 'rgba(251,191,36,0.12)' },
  { label: 'LLM', source: 'llm', color: '#c084fc', bg: 'rgba(192,132,252,0.12)' },
  { label: '慢请求', source: 'slow_request', color: '#60a5fa', bg: 'rgba(96,165,250,0.12)' },
]

function applyQuickFilter(f: typeof quickFilters[0]) {
  emit('filter-change', {
    level: f.level,
    source: f.source,
  })
}
</script>

<template>
  <div class="log-tree-panel">
    <div class="tree-header">
      <span class="tree-title">Log Explorer</span>
    </div>

    <div class="tree-scroll">
      <el-tree
        :data="treeData"
        :props="defaultProps"
        node-key="id"
        highlight-current
        @node-click="handleNodeClick"
      >
        <template #default="{ data }">
          <span class="tree-node-label">
            <span
              v-if="data.count !== undefined"
              class="node-badge"
              :class="{
                'badge-error': data.label.startsWith('ERROR'),
                'badge-warn': data.label.startsWith('WARNING'),
                'badge-info': data.label.startsWith('INFO'),
              }"
            >
              {{ data.count }}
            </span>
            <span>{{ data.label }}</span>
          </span>
        </template>
      </el-tree>
    </div>

    <div class="quick-filters">
      <div class="qf-label">Quick Filters</div>
      <div class="qf-tags">
        <button
          v-for="f in quickFilters"
          :key="f.label"
          class="qf-tag"
          :style="{ color: f.color, backgroundColor: f.bg, borderColor: f.color + '33' }"
          @click="applyQuickFilter(f)"
        >
          {{ f.label }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.log-tree-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: rgba(19, 19, 43, 0.7);
  border: 1px solid rgba(42, 42, 74, 0.6);
  border-radius: 12px;
  overflow: hidden;
}

.tree-header {
  padding: 14px 16px;
  border-bottom: 1px solid rgba(42, 42, 74, 0.6);
}

.tree-title {
  font-size: 13px;
  font-weight: 600;
  color: #c0c0d0;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.tree-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.tree-node-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #c0c0d0;
}

.node-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  font-size: 10px;
  font-weight: 700;
  font-family: var(--dt-mono);
  background: rgba(136, 136, 170, 0.15);
  color: #8888aa;
}

.badge-error {
  background: rgba(248, 113, 113, 0.15);
  color: #f87171;
}

.badge-warn {
  background: rgba(251, 191, 36, 0.15);
  color: #fbbf24;
}

.badge-info {
  background: rgba(74, 222, 128, 0.15);
  color: #4ade80;
}

.quick-filters {
  padding: 12px 16px;
  border-top: 1px solid rgba(42, 42, 74, 0.6);
}

.qf-label {
  font-size: 10px;
  color: #555577;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 8px;
}

.qf-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.qf-tag {
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  background: transparent;
  font-family: var(--dt-mono);
}

.qf-tag:hover {
  transform: translateY(-1px);
  filter: brightness(1.2);
}
</style>
