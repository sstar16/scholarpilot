<script setup lang="ts">
import { ElIcon } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'

defineProps<{
  payload: { job_id: string; filename: string; doc_id?: string }
}>()

const emit = defineEmits<{
  (e: 'cancel', jobId: string): void
}>()
</script>

<template>
  <div class="pdf-parsing">
    <ElIcon class="is-loading spinner"><Loading /></ElIcon>
    <div class="body">
      <div class="filename">{{ payload.filename }}</div>
      <div class="status">AI 正在解析元数据…</div>
    </div>
    <button class="cancel-btn" title="取消" @click="emit('cancel', payload.job_id)">✕</button>
  </div>
</template>

<style scoped>
.pdf-parsing {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-radius: 10px;
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
}
.spinner { font-size: 20px; color: #409eff; }
.body { flex: 1; }
.filename { font-weight: 600; font-size: 14px; color: #303133; }
.status { font-size: 12px; color: #909399; margin-top: 2px; }
.cancel-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: #909399;
  font-size: 16px;
}
.cancel-btn:hover { color: #f56c6c; }
</style>
