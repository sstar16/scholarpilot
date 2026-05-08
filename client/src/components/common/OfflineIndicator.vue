<script setup lang="ts">
// 仅在网络离线时显示。客户端无云同步业务，在线时不打扰 UI。
import { useOnlineStatus } from '@/composables/useOnlineStatus'

const { online, label } = useOnlineStatus()
</script>

<template>
  <span v-if="!online" class="offline-indicator tone-err">
    <span class="dot" />
    {{ label }}
  </span>
</template>

<style scoped>
.offline-indicator {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  cursor: pointer;
  user-select: none;
  background: var(--el-fill-color-light);
}
.offline-indicator .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.tone-ok .dot { background: #67c23a; }
.tone-warn .dot { background: #e6a23c; }
.tone-err .dot { background: #f56c6c; }
.tone-err { color: #f56c6c; }
</style>
