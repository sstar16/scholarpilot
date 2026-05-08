<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElIcon } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import DocumentCard from '@/components/DocumentCard.vue'
import { documentApi, bucketApi } from '@/api/client'

const props = defineProps<{
  payload: {
    job_id: string
    doc_id: string
    slug?: string
    evaluation_skipped?: boolean
  }
  projectId: string
}>()

const emit = defineEmits<{
  (e: 'bucketed', docId: string, bucket: string): void
}>()

const doc = ref<any>(null)
const loading = ref(true)
const localBucket = ref<string | null>(null)

const BUCKET_LABELS: Record<string, string> = {
  very_relevant: '核心',
  relevant: '相关',
  uncertain: '待定',
  irrelevant: '排除',
}

onMounted(async () => {
  try {
    const resp = await documentApi.get(props.payload.doc_id)
    doc.value = resp.data
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载文献失败')
  } finally {
    loading.value = false
  }
})

async function onClassify(bucket: string) {
  try {
    await bucketApi.classify(props.projectId, props.payload.doc_id, { bucket })
    localBucket.value = bucket
    ElMessage.success(`已入 ${BUCKET_LABELS[bucket] || bucket} 桶`)
    emit('bucketed', props.payload.doc_id, bucket)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '入桶失败')
  }
}
</script>

<template>
  <div class="pdf-final">
    <div v-if="payload.evaluation_skipped" class="fresh-hint">
      ℹ️ 项目尚未建立画像，未生成 AI 评分；入桶后作为种子反馈用于下次检索
    </div>

    <div v-if="loading" class="loading-state">
      <ElIcon class="is-loading" :size="18"><Loading /></ElIcon>
      <span>加载文献卡片…</span>
    </div>

    <div v-else-if="doc" class="card-wrapper">
      <div v-if="localBucket" class="bucket-applied">
        ✓ 已入 <b>{{ BUCKET_LABELS[localBucket] }}</b> 桶
      </div>
      <DocumentCard
        :doc="doc"
        @classify="onClassify"
      />
    </div>

    <div v-else class="err-state">加载失败</div>
  </div>
</template>

<style scoped>
.pdf-final { margin: 8px 0; }
.fresh-hint {
  padding: 6px 10px; font-size: 12px;
  background: var(--signal-amber-bg); border: 1px solid var(--signal-amber-bg); color: var(--signal-amber);
  border-radius: 6px; margin-bottom: 8px;
}
.loading-state {
  display: flex; align-items: center; gap: 8px;
  padding: 20px; color: var(--ink-400); font-size: 13px;
  background: var(--ink-100); border-radius: 8px;
}
.bucket-applied {
  padding: 6px 12px; margin-bottom: 6px;
  background: var(--signal-emerald-bg); color: var(--signal-emerald);
  border-radius: 6px; font-size: 13px;
}
.err-state {
  padding: 12px; color: var(--signal-coral); font-size: 13px;
  background: var(--signal-coral-bg); border-radius: 6px;
}
</style>
