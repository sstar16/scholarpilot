<template>
  <div class="rich-msg rich-msg--ended">
    <el-icon :size="18"><CircleClose /></el-icon>
    <div>
      <div class="title">协作模式已退出</div>
      <div class="sub">
        {{ richData.archived ? '本次协作已归档，不可重新进入' : '本次协作已保留，再次提问可刷新恢复' }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { CircleClose } from '@element-plus/icons-vue'

defineProps<{ richData: any }>()
</script>

<style scoped>
.rich-msg {
  margin: 14px 0;
  padding: 10px 14px;
  display: flex;
  align-items: center;
  gap: 10px;
  border-radius: 10px;
  background: #f1f5f9;
  border: 1px dashed #cbd5e1;
  color: #475569;
  font-size: 13px;
}
.title { font-weight: 600; color: #334155; }
.sub { font-size: 12px; color: #94a3b8; margin-top: 2px; }
</style>
