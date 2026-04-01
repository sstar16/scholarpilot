<template>
  <div class="source-progress">
    <div class="source-progress-header">
      <el-icon><Connection /></el-icon>
      <span>数据源检索进度</span>
      <span class="source-count">{{ completedCount }}/{{ totalCount }}</span>
    </div>
    <div class="source-items">
      <div
        v-for="(source, id) in sources"
        :key="id"
        class="source-item"
        :class="source.status"
      >
        <span class="source-dot" :class="'dot-' + source.status"></span>
        <span class="source-name">{{ id }}</span>
        <transition name="fade">
          <span v-if="source.status === 'searching'" class="source-searching">
            <el-icon class="is-loading"><Loading /></el-icon>
          </span>
          <span v-else-if="source.status === 'done'" class="source-result">
            {{ source.count }} 篇
          </span>
          <span v-else-if="source.status === 'error'" class="source-error">
            失败
          </span>
          <span v-else class="source-pending">等待中</span>
        </transition>
        <span v-if="source.timeMs" class="source-time">{{ source.timeMs }}ms</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive } from 'vue'

interface SourceState {
  status: 'pending' | 'searching' | 'done' | 'error'
  count?: number
  timeMs?: number
  query?: string
}

const sources = reactive<Record<string, SourceState>>({})

const completedCount = computed(() =>
  Object.values(sources).filter(s => s.status === 'done' || s.status === 'error').length
)
const totalCount = computed(() => Object.keys(sources).length)

function onSourceStarted(data: { source_id: string; query?: string }) {
  sources[data.source_id] = { status: 'searching', query: data.query }
}

function onSourceComplete(data: { source_id: string; count: number; time_ms: number }) {
  sources[data.source_id] = { status: 'done', count: data.count, timeMs: data.time_ms }
}

function onSourceError(data: { source_id: string; error: string }) {
  sources[data.source_id] = { status: 'error' }
}

function reset() {
  Object.keys(sources).forEach(k => delete sources[k])
}

defineExpose({ onSourceStarted, onSourceComplete, onSourceError, reset })
</script>

<style scoped>
.source-progress {
  background: #fff; border-radius: 8px; border: 1px solid #e4e7ed;
  padding: 16px; margin-bottom: 16px;
}
.source-progress-header {
  display: flex; align-items: center; gap: 8px;
  font-size: 14px; font-weight: 600; color: #303133;
  margin-bottom: 12px;
}
.source-count { margin-left: auto; font-size: 13px; color: #909399; font-weight: 400; }
.source-items { display: flex; flex-wrap: wrap; gap: 8px; }
.source-item {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 12px; border-radius: 20px;
  background: #f5f7fa; border: 1px solid #e4e7ed;
  font-size: 13px; transition: all 0.3s ease;
}
.source-item.done { background: #f0f9eb; border-color: #b3e19d; }
.source-item.error { background: #fef0f0; border-color: #fbc4c4; }
.source-item.searching { background: #ecf5ff; border-color: #b3d8ff; }
.source-dot { width: 6px; height: 6px; border-radius: 50%; }
.dot-pending { background: #c0c4cc; }
.dot-searching { background: #409eff; animation: pulse 1s infinite; }
.dot-done { background: #67c23a; }
.dot-error { background: #f56c6c; }
.source-name { font-weight: 500; color: #606266; }
.source-result { color: #67c23a; font-weight: 600; }
.source-error { color: #f56c6c; font-size: 12px; }
.source-searching { color: #409eff; }
.source-pending { color: #c0c4cc; font-size: 12px; }
.source-time { color: #909399; font-size: 11px; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
