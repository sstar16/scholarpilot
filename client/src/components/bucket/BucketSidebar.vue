<template>
  <aside class="bucket-sidebar">
    <h3 class="sidebar-title">文献库</h3>
    <p class="sidebar-sub">共 {{ bucketStore.total }} 篇</p>

    <div
      v-for="b in bucketDefs"
      :key="b.key"
      class="bucket-section"
      :class="{
        expanded: expandedBucket === b.key,
        'is-drop-target': dragging && dragging.bucket !== b.key,
      }"
      :data-bucket="b.key"
      @dragover.prevent="onSectionDragOver($event, b.key)"
      @dragenter.prevent="onSectionDragOver($event, b.key)"
      @drop="onDrop($event, b.key)"
    >
      <div class="bucket-header" @click="toggle(b.key)">
        <span class="bucket-dot" :style="{ background: b.color }"></span>
        <span class="bucket-name">{{ b.label }}</span>
        <span class="bucket-count" :style="{ background: b.color + '20', color: b.color }">
          {{ bucketStore.counts[b.key] }}
        </span>
        <el-button
          v-if="bucketStore.counts[b.key] > 0"
          text
          size="small"
          class="btn-graph"
          @click.stop="openGraph(b.key, b.label)"
          title="查看图谱"
        >
          <el-icon :size="14"><Share /></el-icon>
        </el-button>
        <span class="bucket-arrow">{{ expandedBucket === b.key ? '▾' : '▸' }}</span>
      </div>

      <transition name="slide">
        <div v-if="expandedBucket === b.key" class="bucket-docs">
          <div
            v-for="doc in bucketStore.buckets[b.key].slice(0, visibleCount)"
            :key="doc.document_id"
            class="bucket-doc"
            draggable="true"
            @dragstart="onDragStart($event, doc)"
            @dragend="onDragEnd"
          >
            <p class="doc-title">{{ doc.title || '(无标题)' }}</p>
            <p v-if="doc.one_line_summary" class="doc-summary">{{ doc.one_line_summary }}</p>
            <div class="doc-meta">
              <span class="doc-source">{{ doc.source }}</span>
              <span v-if="doc.agent_score" class="doc-score">AI {{ doc.agent_score.toFixed(1) }}</span>
            </div>
          </div>
          <button
            v-if="bucketStore.buckets[b.key].length > visibleCount"
            class="btn-more"
            @click.stop="visibleCount += 20"
          >
            还有 {{ bucketStore.buckets[b.key].length - visibleCount }} 篇...
          </button>
          <p v-if="bucketStore.buckets[b.key].length === 0" class="empty-hint">暂无文献</p>
        </div>
      </transition>

      <!-- Visible drop hint (整个 bucket-section 都接受 drop，这只是视觉提示) -->
      <div
        v-if="dragging && dragging.bucket !== b.key"
        class="drop-zone"
        :style="{ borderColor: b.color }"
      >
        拖到这里移入「{{ b.label }}」
      </div>
    </div>
    <!-- Knowledge Graph Dialog -->
    <KnowledgeGraphView
      v-if="graphBucket"
      v-model:visible="graphVisible"
      v-model:bucket="graphBucket"
      :project-id="props.projectId"
    />
  </aside>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useBucketStore, type BucketName, type BucketDoc } from '../../stores/bucket'
import KnowledgeGraphView from '../graph/KnowledgeGraphView.vue'

const props = defineProps<{ projectId: string }>()
const bucketStore = useBucketStore()

const expandedBucket = ref<BucketName | null>(null)
const visibleCount = ref(20)
const dragging = ref<BucketDoc | null>(null)

const bucketDefs = [
  { key: 'very_relevant' as BucketName, label: '核心', color: '#0d9488' },
  { key: 'relevant' as BucketName, label: '相关', color: '#2563eb' },
  { key: 'uncertain' as BucketName, label: '待定', color: '#64748b' },
  { key: 'irrelevant' as BucketName, label: '排除', color: '#dc2626' },
]

// Knowledge Graph
const graphVisible = ref(false)
const graphBucket = ref<string>('')

function openGraph(bucket: string, _label: string) {
  graphBucket.value = bucket
  graphVisible.value = true
}

function toggle(key: BucketName) {
  expandedBucket.value = expandedBucket.value === key ? null : key
  visibleCount.value = 20
}

function onDragStart(e: DragEvent, doc: BucketDoc) {
  dragging.value = doc
  if (e.dataTransfer) {
    e.dataTransfer.setData('text/plain', doc.document_id)
    e.dataTransfer.effectAllowed = 'move'
  }
}

function onDragEnd() {
  // 单一文档 drag 结束时清空 — 比依赖全局 dragend 监听更可靠
  dragging.value = null
}

function onSectionDragOver(e: DragEvent, bucket: BucketName) {
  // 必须在 dragover/dragenter 上 preventDefault 才能让浏览器接受 drop
  if (!dragging.value || dragging.value.bucket === bucket) return
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
}

async function onDrop(e: DragEvent, toBucket: BucketName) {
  e.preventDefault()
  if (!dragging.value) return
  if (dragging.value.bucket === toBucket) {
    dragging.value = null
    return
  }
  try {
    await bucketStore.move(props.projectId, dragging.value.document_id, toBucket)
  } catch (err) {
    console.warn('[BucketSidebar] move failed:', err)
  } finally {
    dragging.value = null
  }
}
</script>

<style scoped>
.bucket-sidebar {
  width: 260px;
  min-height: 100%;
  padding: 20px 16px;
  background: var(--paper-cool, #f8fafc);
  border-right: 1px solid var(--ink-100, #e2e8f0);
  overflow-y: auto;
}
.sidebar-title {
  font-size: 15px; font-weight: 700; color: var(--ink-800, #1e293b);
  margin: 0 0 2px;
}
.sidebar-sub {
  font-size: 11px; color: var(--ink-400, #94a3b8); margin: 0 0 16px;
}

/* ── Bucket section ── */
.bucket-section {
  margin-bottom: 4px;
  border-radius: 8px;
  transition: background 0.2s;
}
.bucket-section:hover { background: var(--ink-50, #f1f5f9); }
.bucket-section.is-drop-target {
  background: rgba(13, 148, 136, 0.06);
  outline: 2px dashed rgba(13, 148, 136, 0.4);
  outline-offset: -2px;
}

.bucket-header {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 10px; cursor: pointer;
  border-radius: 8px;
}
.bucket-dot {
  width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0;
}
.bucket-name {
  font-size: 13px; font-weight: 600; color: var(--ink-700, #334155);
  flex: 1;
}
.bucket-count {
  font-size: 11px; font-weight: 700; padding: 1px 7px;
  border-radius: 10px; min-width: 22px; text-align: center;
}
.bucket-arrow {
  font-size: 10px; color: var(--ink-300, #cbd5e1);
}

/* ── Doc list ── */
.bucket-docs {
  padding: 4px 10px 8px 26px;
}
.bucket-doc {
  padding: 6px 8px; margin-bottom: 4px;
  border-radius: 6px; cursor: grab;
  border: 1px solid transparent;
  transition: all 0.15s;
}
.bucket-doc:hover {
  background: var(--paper, #fff);
  border-color: var(--ink-200, #e2e8f0);
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
.doc-title {
  font-size: 12px; font-weight: 600; color: var(--ink-700, #334155);
  margin: 0; line-height: 1.4;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.doc-summary {
  font-size: 11px; color: var(--ink-400, #94a3b8); margin: 2px 0 0;
  display: -webkit-box; -webkit-line-clamp: 1; -webkit-box-orient: vertical; overflow: hidden;
}
.doc-meta {
  display: flex; gap: 6px; margin-top: 3px;
}
.doc-source {
  font-size: 10px; color: var(--ink-300, #cbd5e1);
}
.doc-score {
  font-size: 10px; font-weight: 700; color: var(--signal-teal, #0d9488);
}

.btn-more {
  background: none; border: none; cursor: pointer;
  font-size: 11px; color: var(--signal-teal, #0d9488);
  padding: 4px 0; font-weight: 500;
}
.btn-more:hover { text-decoration: underline; }
.empty-hint { font-size: 11px; color: var(--ink-300); margin: 4px 0; }

/* ── Drop zone ── */
.drop-zone {
  margin: 2px 10px 2px 26px; padding: 8px;
  border: 2px dashed var(--ink-200);
  border-radius: 8px; text-align: center;
  font-size: 11px; color: var(--ink-400);
  transition: all 0.2s;
}
.drop-zone:hover {
  background: rgba(13, 148, 136, 0.05);
}

/* ── Transitions ── */
.slide-enter-active { transition: all 0.2s ease-out; }
.slide-leave-active { transition: all 0.15s ease-in; }
.slide-enter-from, .slide-leave-to { opacity: 0; max-height: 0; overflow: hidden; }
.slide-enter-to, .slide-leave-from { opacity: 1; max-height: 800px; }
</style>
