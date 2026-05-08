<script setup lang="ts">
import { ElButton } from 'element-plus'

defineProps<{
  payload: {
    feature: string
    scene: string
    reason: string
    suggested_action: { trigger: string; label: string } | null
  }
}>()

const emit = defineEmits<{
  (e: 'action', trigger: string): void
}>()
</script>

<template>
  <div class="gate-blocked">
    <div class="icon">🚫</div>
    <div class="body">
      <div class="reason">{{ payload.reason }}</div>
      <ElButton v-if="payload.suggested_action"
        type="primary" size="small"
        @click="emit('action', payload.suggested_action.trigger)">
        {{ payload.suggested_action.label }}
      </ElButton>
    </div>
  </div>
</template>

<style scoped>
.gate-blocked {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  background: var(--el-fill-color-light);
  border-left: 3px solid var(--el-color-warning);
  border-radius: 6px;
}
.icon { font-size: 20px; }
.body { flex: 1; }
.reason { color: var(--el-text-color-primary); margin-bottom: 8px; }
</style>
