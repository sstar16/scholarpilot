<script setup lang="ts">
import { ref } from 'vue'
import { ElButton, ElMessageBox, ElMessage } from 'element-plus'
import { Close } from '@element-plus/icons-vue'
import { featuresApi } from '../../api/client'

const props = defineProps<{
  sessionId: string
  currentState: string
  cleanupHint?: string
}>()

const emit = defineEmits<{
  (e: 'exited', fromState: string): void
}>()

const loading = ref(false)

async function onExit() {
  try {
    await ElMessageBox.confirm(
      props.cleanupHint ?? `将退出 ${props.currentState} 流程回到对话`,
      '确认退出',
      { confirmButtonText: '退出', cancelButtonText: '继续', type: 'warning' },
    )
  } catch {
    return
  }
  loading.value = true
  try {
    await featuresApi.exitSession(props.sessionId)
    emit('exited', props.currentState)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail?.hint ?? '退出失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <ElButton :icon="Close" circle size="small" :loading="loading" @click="onExit" />
</template>
