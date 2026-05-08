<template>
  <div class="source-compact" v-if="Object.keys(sources).length > 0">
    <div class="compact-tags">
      <span
        v-for="(source, id) in sources"
        :key="id"
        class="compact-tag"
        :class="'tag-' + source.status"
      >
        <span class="tag-dot" :class="'dot-' + source.status"></span>
        <span class="tag-name">{{ id }}</span>
        <span v-if="source.status === 'done' && source.count !== undefined" class="tag-count">{{ source.count }}</span>
        <span v-if="source.status === 'searching'" class="tag-spinner"></span>
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive } from 'vue'

interface SourceState {
  status: 'pending' | 'searching' | 'done' | 'error'
  count?: number
  timeMs?: number
}

const sources = reactive<Record<string, SourceState>>({})

function onSourceStarted(data: { source_id: string }) {
  sources[data.source_id] = { status: 'searching' }
}

function onSourceComplete(data: { source_id: string; count: number; time_ms: number }) {
  sources[data.source_id] = { status: 'done', count: data.count, timeMs: data.time_ms }
}

function onSourceError(data: { source_id: string }) {
  sources[data.source_id] = { status: 'error' }
}

function reset() {
  Object.keys(sources).forEach(k => delete sources[k])
}

defineExpose({ onSourceStarted, onSourceComplete, onSourceError, reset })
</script>

<style scoped>
.source-compact {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #ebeef5;
}

.compact-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.compact-tag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 11px;
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  color: #606266;
  transition: all 0.3s ease;
}

.compact-tag.tag-searching {
  background: #ecf5ff;
  border-color: #b3d8ff;
  color: #409eff;
}

.compact-tag.tag-done {
  background: #f0f9eb;
  border-color: #c2e7b0;
  color: #67c23a;
}

.compact-tag.tag-error {
  background: #fef0f0;
  border-color: #fbc4c4;
  color: #f56c6c;
}

.tag-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
}

.dot-pending { background: #c0c4cc; }
.dot-searching { background: #409eff; animation: pulse 1s infinite; }
.dot-done { background: #67c23a; }
.dot-error { background: #f56c6c; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.tag-name {
  font-weight: 500;
}

.tag-count {
  font-weight: 700;
  font-size: 11px;
}

.tag-spinner {
  width: 10px;
  height: 10px;
  border: 1.5px solid #b3d8ff;
  border-top-color: #409eff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
