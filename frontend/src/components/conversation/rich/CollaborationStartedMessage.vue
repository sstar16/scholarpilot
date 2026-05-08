<template>
  <div class="rich-msg rich-msg--started">
    <div class="pulse" />
    <div class="rich-msg__content">
      <el-icon :size="18"><MagicStick /></el-icon>
      <div>
        <div class="title">已进入协作研究模式</div>
        <div class="sub">{{ richData.doc_count }} 篇文献参与 · 您可以自由提问，AI 会基于这些文献回答</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { MagicStick } from '@element-plus/icons-vue'

defineProps<{ richData: any }>()
</script>

<style scoped>
.rich-msg {
  margin: 14px 0;
  padding: 12px 16px;
  border-radius: 12px;
  background: linear-gradient(135deg, #0d9488 0%, #2563eb 100%);
  color: #fff;
  position: relative;
  overflow: hidden;
}
.pulse {
  position: absolute;
  top: 50%;
  left: 12px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #34d399;
  box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.7);
  animation: pulse 2s infinite;
}
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.6); }
  70% { box-shadow: 0 0 0 10px rgba(52, 211, 153, 0); }
  100% { box-shadow: 0 0 0 0 rgba(52, 211, 153, 0); }
}
.rich-msg__content {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: 24px;
}
.title { font-weight: 600; font-size: 14px; }
.sub { font-size: 12px; opacity: 0.85; margin-top: 2px; }
</style>
