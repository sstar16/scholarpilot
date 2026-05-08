<template>
  <el-config-provider :locale="zhCn">
    <div class="floating-indicators">
      <OfflineIndicator />
    </div>
    <router-view />
  </el-config-provider>
</template>

<script setup lang="ts">
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import OfflineIndicator from '@/components/common/OfflineIndicator.vue'
</script>

<style scoped>
.floating-indicators {
  position: fixed;
  top: 8px;
  right: 12px;
  z-index: 9999;
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
