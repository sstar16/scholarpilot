<script setup lang="ts">
import { ref, computed } from 'vue'
import { ElTooltip, ElButton, ElMessage } from 'element-plus'
import { useFeatureGate } from '@/composables/useFeatureGate'
import { usePdfImport } from '@/composables/usePdfImport'
import { featuresApi } from '../../api/client'

const props = defineProps<{
  projectId?: string
  sessionId?: string
}>()

const emit = defineEmits<{
  (e: 'triggered', feature: string, result: any): void
  (e: 'pdfUpload'): void
}>()

const projectIdRef = computed(() => props.projectId ?? null)
const { results, refresh } = useFeatureGate(projectIdRef)

defineExpose({ refresh })

const features = [
  { key: 'new_round', icon: '🔍', label: '新检索' },
  { key: 'collaboration', icon: '🤝', label: '协作研究' },
  { key: 'schedule', icon: '⏰', label: '定时推送' },
] as const

const hasProject = computed(() => !!props.projectId)

const fileInputRef = ref<HTMLInputElement | null>(null)

const { uploadFiles } = usePdfImport(
  () => props.projectId,
  () => props.sessionId,
)

function triggerFileSelect() {
  if (!hasProject.value) {
    ElMessage.info('请先创建项目')
    return
  }
  fileInputRef.value?.click()
}

async function onFileSelected(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files?.length) return
  const files = Array.from(input.files)
  await uploadFiles(files)
  input.value = ''
  emit('pdfUpload')
}

async function onClick(featureKey: string) {
  // 定时推送功能暂未完善，统一拦截为"正在开发中"提示（恢复时删除这三行即可）
  if (featureKey === 'schedule') {
    ElMessage.info('⏰ 定时推送功能正在开发中，敬请期待')
    return
  }
  if (!hasProject.value) {
    ElMessage.info('请先在下方输入框描述您的研究需求，创建项目后即可使用')
    return
  }
  if (!props.sessionId) {
    ElMessage.info('会话尚未就绪，请稍候')
    return
  }
  try {
    const resp = await featuresApi.trigger(props.projectId!, featureKey, props.sessionId)
    emit('triggered', featureKey, resp.data)
    if (!resp.data.allowed) {
      ElMessage.info(resp.data.rich_message.reason ?? '功能不可用')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail ?? '触发失败')
  }
}

function tooltipText(featureKey: string): string {
  // 定时推送功能暂未完善，hover tooltip 同步显示"开发中"（恢复时删除这两行即可）
  if (featureKey === 'schedule') return '定时推送功能正在开发中，敬请期待'
  if (!hasProject.value) return '请先创建项目（在下方输入框描述研究需求）'
  const rv = results.value
  const r = rv?.[featureKey as keyof typeof rv]
  if (!r) return ''
  return r.allowed ? '' : r.reason ?? ''
}

function isAllowed(featureKey: string): boolean {
  if (!hasProject.value) return false
  const rv = results.value
  return rv?.[featureKey as keyof typeof rv]?.allowed ?? false
}
</script>

<template>
  <div class="function-dock">
    <ElTooltip v-for="f in features" :key="f.key"
      :content="tooltipText(f.key)"
      :disabled="isAllowed(f.key)"
      placement="top">
      <ElButton
        :type="isAllowed(f.key) ? 'primary' : 'default'"
        :disabled="!isAllowed(f.key) && !tooltipText(f.key)"
        @click="onClick(f.key)">
        {{ f.icon }} {{ f.label }}
      </ElButton>
    </ElTooltip>
    <label class="upload-wrapper">
      <ElTooltip
        content="支持 PDF / DOCX / PPTX / XLSX / HTML / Markdown / TXT / CSV"
        placement="top"
      >
        <ElButton type="info" plain :disabled="!hasProject" @click.stop="triggerFileSelect">
          📎 上传文档
        </ElButton>
      </ElTooltip>
      <input
        ref="fileInputRef"
        type="file"
        accept=".pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.csv,.html,.htm,.md,.markdown,.txt,.json,.xml,.epub,.msg"
        multiple
        hidden
        @change="onFileSelected"
      />
    </label>
  </div>
</template>

<style scoped>
.function-dock {
  display: flex;
  gap: 8px;
  padding: 8px 12px;
  border-top: 1px solid var(--el-border-color-lighter);
}
</style>
