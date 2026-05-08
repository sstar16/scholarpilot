<template>
  <div class="rich-msg rich-msg--scope" :class="{ 'is-locked': !isActive }">
    <div class="rich-msg__header">
      <el-icon :size="18"><Stopwatch /></el-icon>
      <span class="title">协作研究模式 · 选择文献</span>
      <el-tag v-if="isActive" size="small" effect="dark" type="info">{{ selected.length }}/{{ candidates.length }} 篇已选</el-tag>
      <el-tag v-else size="small" effect="plain" type="success">已完成 · {{ selected.length }} 篇已选</el-tag>
    </div>

    <div v-if="isActive" class="rich-msg__body">
      <p class="intro">
        请选择本次协作要分析的文献（支持多选，默认勾选核心桶文献）：
      </p>

      <div class="bucket-sections">
        <div v-for="b in bucketsOrder" :key="b.key" v-show="grouped[b.key]?.length" class="bucket-section">
          <div class="bucket-head" @click="toggleSection(b.key)">
            <el-icon>
              <component :is="collapsed[b.key] ? ArrowRight : ArrowDown" />
            </el-icon>
            <strong>{{ b.label }}</strong>
            <span class="count">{{ grouped[b.key]?.length || 0 }} 篇</span>
            <div class="spacer" />
            <el-button
              size="small"
              text
              @click.stop="toggleBucketAll(b.key)"
            >
              {{ isAllSelectedInBucket(b.key) ? '取消全选' : '全选' }}
            </el-button>
          </div>
          <div v-if="!collapsed[b.key]" class="doc-list">
            <label
              v-for="doc in grouped[b.key]"
              :key="doc.id"
              class="doc-item"
              :class="{ selected: selected.includes(doc.id) }"
            >
              <el-checkbox :model-value="selected.includes(doc.id)" @change="toggleDoc(doc.id)" />
              <div class="doc-info">
                <div class="doc-title">{{ doc.title }}</div>
                <div class="doc-meta">
                  <el-tag size="small" effect="plain">{{ doc.source }}</el-tag>
                  <el-tag
                    v-if="doc.fulltext_status === 'available'"
                    size="small"
                    effect="plain"
                    type="success"
                  >全文</el-tag>
                  <span v-if="doc.one_line_summary" class="summary">{{ doc.one_line_summary }}</span>
                </div>
              </div>
            </label>
          </div>
        </div>
      </div>

      <div class="action-row">
        <el-button size="small" @click="$emit('cancel')">取消</el-button>
        <el-button
          type="primary"
          size="small"
          :disabled="!selected.length || !isActive"
          @click="confirmStart"
        >
          开始协作 ({{ selected.length }} 篇)
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onMounted } from 'vue'
import { Stopwatch, ArrowRight, ArrowDown } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const props = defineProps<{
  richData: any
  isActive?: boolean
}>()

const emit = defineEmits<{
  start: [docIds: string[]]
  cancel: []
}>()

const candidates = computed<any[]>(() => props.richData?.candidate_docs || [])
const selected = ref<string[]>([])

const bucketsOrder = [
  { key: 'very_relevant', label: '核心' },
  { key: 'relevant', label: '相关' },
  { key: 'uncertain', label: '待定' },
  { key: 'other', label: '其他' },
]

const collapsed = reactive<Record<string, boolean>>({
  very_relevant: false,
  relevant: false,
  uncertain: true,
  other: true,
})

const grouped = computed<Record<string, any[]>>(() => {
  const g: Record<string, any[]> = { very_relevant: [], relevant: [], uncertain: [], other: [] }
  for (const doc of candidates.value) {
    const key = ['very_relevant', 'relevant', 'uncertain'].includes(doc.bucket) ? doc.bucket : 'other'
    g[key].push(doc)
  }
  return g
})

function toggleSection(key: string) {
  collapsed[key] = !collapsed[key]
}

function toggleDoc(id: string) {
  const i = selected.value.indexOf(id)
  if (i >= 0) selected.value.splice(i, 1)
  else selected.value.push(id)
}

function isAllSelectedInBucket(key: string): boolean {
  const ids = (grouped.value[key] || []).map(d => d.id)
  return ids.length > 0 && ids.every(id => selected.value.includes(id))
}

function toggleBucketAll(key: string) {
  const ids = (grouped.value[key] || []).map(d => d.id)
  if (isAllSelectedInBucket(key)) {
    selected.value = selected.value.filter(id => !ids.includes(id))
  } else {
    const set = new Set(selected.value)
    ids.forEach(id => set.add(id))
    selected.value = Array.from(set)
  }
}

function confirmStart() {
  if (!selected.value.length) {
    ElMessage.warning('请至少选择一篇文献')
    return
  }
  emit('start', selected.value.slice())
}

onMounted(() => {
  // Default: select very_relevant + relevant
  const auto = candidates.value
    .filter(d => d.bucket === 'very_relevant' || d.bucket === 'relevant')
    .map(d => d.id)
  selected.value = auto
})
</script>

<style scoped>
/* variant 色板（基础骨架见 design-system.css） */
.rich-msg {
  background: var(--signal-purple-bg);
  border: 1.5px solid var(--signal-purple);
  transition: opacity var(--duration-normal) var(--ease-out);
}
.rich-msg.is-locked {
  opacity: 0.6;
  pointer-events: none;
  user-select: none;
}
.rich-msg__header {
  color: var(--signal-purple);
  border-bottom: 1px solid var(--signal-purple-bg);
}
.intro { font-size: var(--type-sub-size); color: var(--ink-500); margin: 0 0 var(--space-3); }
.bucket-sections { max-height: 340px; overflow-y: auto; }
.bucket-section { margin-bottom: var(--space-2); }
.bucket-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2);
  background: var(--paper);
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--type-sub-size);
  color: var(--ink-900);
}
.bucket-head .count { color: var(--ink-300); font-size: var(--type-meta-size); }
.bucket-head .spacer { flex: 1; }
.doc-list { margin: var(--space-2) 0 var(--space-2) var(--space-5); }
.doc-item {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}
.doc-item:hover { background: rgba(255, 255, 255, 0.6); }
.doc-item.selected { background: var(--signal-purple-bg); }
.doc-info { flex: 1; min-width: 0; }
.doc-title {
  font-size: var(--type-sub-size);
  color: var(--ink-900);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}
.doc-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  margin-top: 3px;
  font-size: var(--type-meta-size);
  color: var(--ink-400);
}
.doc-meta .summary {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--ink-300);
}
.action-row {
  margin-top: var(--space-3);
  display: flex;
  gap: var(--space-2);
  justify-content: flex-end;
}
</style>
