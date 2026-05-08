<template>
  <div class="stale-hint">
    <div class="stale-hint__body">
      <el-icon :size="14" class="stale-hint__icon"><AlarmClock /></el-icon>
      <span class="stale-hint__text">
        距上次检索 <b>{{ daysAgo }}</b> 天，文献库可能已经过时
      </span>
    </div>
    <div class="stale-hint__actions">
      <el-button
        size="small"
        type="primary"
        plain
        :loading="busy"
        @click="onStartRound"
      >开新一轮</el-button>
      <el-button
        size="small"
        link
        :disabled="busy"
        @click="onDismiss"
      >先不用</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { AlarmClock } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { projectApi, telemetryApi } from '../../../api/client'

const props = defineProps<{
  richData: any
  projectId?: string
}>()

const emit = defineEmits<{
  (e: 'start-round'): void
  (e: 'dismissed'): void
}>()

const busy = ref(false)
const daysAgo = computed(() => props.richData?.days_ago ?? '?')

async function onStartRound() {
  busy.value = true
  try {
    // 埋点：用户从 stale hint 入口开新一轮（不阻塞主流程，失败静默吞）
    telemetryApi.emit('stale_hint_clicked', props.projectId, {
      days_ago: props.richData?.days_ago,
    })
    emit('start-round')
  } finally {
    busy.value = false
  }
}

async function onDismiss() {
  if (!props.projectId) {
    emit('dismissed')
    return
  }
  busy.value = true
  try {
    await projectApi.staleDismiss(props.projectId)
    ElMessage.info('已忽略，7 天内不再提醒')
    emit('dismissed')
  } catch (err) {
    console.error('[StaleHint] dismiss failed', err)
    emit('dismissed')
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.stale-hint {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin: var(--space-3) auto;
  padding: 10px var(--space-4);
  font-size: var(--type-meta-size);
  color: var(--ink-700);
  background: var(--paper-warm, #fbf7ee);
  border: 1px dashed var(--ink-300);
  border-radius: var(--radius-md);
  max-width: 560px;
  animation: fadeUp var(--duration-normal) var(--ease-out) both;
}

.stale-hint__body {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  flex: 1 1 auto;
  min-width: 0;
}

.stale-hint__icon {
  color: var(--signal-amber, #c08a2b);
  flex-shrink: 0;
}

.stale-hint__text {
  color: var(--ink-700);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stale-hint__text b {
  color: var(--ink-900);
  font-weight: 600;
  margin: 0 2px;
}

.stale-hint__actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}
</style>
