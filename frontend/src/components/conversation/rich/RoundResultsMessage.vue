<template>
  <div class="rich-msg rich-msg--results">
    <div class="rich-msg__header">
      <el-icon :size="18"><Collection /></el-icon>
      <span class="title">第 {{ richData.round_number }} 轮 · 检索结果</span>
      <el-tag type="success" size="small" effect="dark">{{ richData.total }} 篇</el-tag>
      <el-tag v-if="richData.summaries_done" type="info" size="small">
        {{ richData.summaries_done }} 份摘要
      </el-tag>
      <div class="spacer"></div>
      <el-button size="small" text @click="expanded = !expanded">
        {{ expanded ? '收起' : '展开' }}
        <el-icon><component :is="expanded ? ArrowUp : ArrowDown" /></el-icon>
      </el-button>
    </div>

    <div class="rich-msg__body" v-show="expanded">
      <!-- Round info -->
      <div class="round-meta">
        <span class="round-desc">{{ roundDesc }}</span>
        <el-tag :type="roundStatusType" effect="plain" size="small">
          {{ roundStatusLabel }}
        </el-tag>
      </div>

      <!-- Round history (if multiple rounds) -->
      <RoundHistory
        v-if="searchStore.rounds.length > 1"
        :rounds="searchStore.rounds"
        :active-round-id="richData.round_id"
      />

      <!-- Awaiting feedback alert -->
      <el-alert
        v-if="canFinalize"
        type="info"
        :closable="false"
        show-icon
        style="margin: 10px 0"
      >
        <template #title>
          请将文献分类到对应的桶中（点击文献下方的分类按钮），AI 将根据分类优化下一轮检索
        </template>
      </el-alert>

      <!-- Feedback progress + Finalize button -->
      <div v-if="canFinalize" class="feedback-progress">
        <span>已分类 {{ classifiedCount }} / {{ documents.length }} 篇</span>
        <el-button
          type="primary"
          size="small"
          :loading="finalizing"
          @click="$emit('finalize')"
        >
          结束本轮
        </el-button>
      </div>

      <!-- Cutoff slider (when agent scoring is on) -->
      <template v-if="hasAgentScores">
        <CutoffSlider v-model="scoringCutoff" :documents="documents" />
        <div v-if="filteredDocuments.length < documents.length" class="cutoff-toggle">
          <el-button text size="small" @click="showBelowCutoff = !showBelowCutoff">
            {{ showBelowCutoff ? '隐藏淘汰文献' : `显示全部 (含 ${documents.length - filteredDocuments.length} 篇淘汰)` }}
          </el-button>
        </div>
      </template>

      <!-- Document card list -->
      <div class="doc-list">
        <DocumentCard
          v-for="doc in filteredDocuments"
          :key="String(doc.id)"
          :doc="doc"
          :initial-feedback="searchStore.feedbackDrafts[String(doc.id)] ?? doc.user_feedback"
          :round-status="currentRound?.status"
          @feedback="(val: any) => searchStore.setFeedback(String(doc.id), val)"
          @classify="(bucket: string) => onDocClassify(String(doc.id), bucket)"
          @download-fulltext="(fmt: 'pdf'|'html'|'auto') => onDownloadFulltext(String(doc.id), fmt)"
          @upload-fulltext="(payload: { format: 'pdf'|'html'; file: File }) => onUploadFulltext(String(doc.id), payload)"
          @view-fulltext="(fmt: 'pdf'|'html'|'auto') => $emit('view-detail', { doc, format: fmt })"
        />
      </div>

      <!-- Empty fallback (richData docs only, when not actively loaded) -->
      <div v-if="!documents.length && (richData.docs || []).length" class="fallback-list">
        <p class="hint">本轮文献快照（{{ richData.docs.length }} 篇）：</p>
        <div
          v-for="doc in (richData.docs || []).slice(0, 20)"
          :key="doc.id"
          class="doc-row"
          @click="$emit('view-detail', doc)"
        >
          <div class="doc-row__title">{{ doc.title || '无标题' }}</div>
          <div class="doc-row__meta">
            <el-tag size="small" effect="plain">{{ doc.source }}</el-tag>
            <el-tag v-if="doc.has_summary" size="small" effect="plain" type="success">已摘要</el-tag>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Collection, ArrowUp, ArrowDown } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useSearchStore } from '../../../stores/search'
import { useBucketStore } from '../../../stores/bucket'
import { useProjectStore } from '../../../stores/project'
import { searchApi } from '../../../api/client'
import { downloadFulltextWithBudgetConfirm } from '../../../utils/patenthubBudget'
import DocumentCard from '../../DocumentCard.vue'
import CutoffSlider from '../../retrieval/CutoffSlider.vue'
import RoundHistory from '../../retrieval/RoundHistory.vue'

const props = defineProps<{
  richData: any
  isActive?: boolean
  finalizing?: boolean
}>()

defineEmits<{
  'view-detail': [doc: any]
  finalize: []
}>()

const searchStore = useSearchStore()
const bucketStore = useBucketStore()
const projectStore = useProjectStore()

const expanded = ref(true)
const scoringCutoff = ref(7.0)
const showBelowCutoff = ref(false)

// Use live store documents when this is the active round, otherwise empty (snapshot from richData)
const documents = computed<any[]>(() => {
  const curr = searchStore.currentRound
  if (curr?.id === props.richData.round_id) return searchStore.documents
  return []
})

const currentRound = computed(() => {
  const curr = searchStore.currentRound
  if (curr?.id === props.richData.round_id) return curr
  return null
})

const canFinalize = computed(() => currentRound.value?.status === 'awaiting_feedback')

const classifiedCount = computed(() =>
  documents.value.filter((d: any) => d.bucket).length
)

const hasAgentScores = computed(() =>
  documents.value.some((d: any) => d.agent_score != null)
)

const filteredDocuments = computed(() => {
  if (!hasAgentScores.value || showBelowCutoff.value) return documents.value
  return documents.value.filter((d: any) => d.agent_score == null || d.agent_score >= scoringCutoff.value)
})

const ROUND_DESCS: Record<number, string> = {
  1: '近5年 · 中文优先 · Top 10',
  2: '近10年 · 中文优先 · Top 10',
  3: '近20年 · 中英双语 · Top 20',
  4: '全时间 · 中英双语 · 全部相关',
  5: '全时间 · 全球多语言 · AI中文摘要',
}

const roundDesc = computed(() => ROUND_DESCS[props.richData.round_number ?? 0] ?? '')

const roundStatusLabel = computed(() => {
  const s = currentRound.value?.status
  return ({
    pending: '待开始',
    awaiting_keywords: '确认查询词',
    searching: '检索中',
    summarizing: 'AI摘要生成中',
    awaiting_feedback: '等待您评分',
    complete: '已完成',
  } as any)[s ?? ''] ?? '历史'
})

const roundStatusType = computed(() => {
  const s = currentRound.value?.status
  return ({
    awaiting_keywords: 'warning',
    searching: 'warning',
    summarizing: 'warning',
    awaiting_feedback: 'primary',
    complete: 'success',
    pending: 'info',
  } as any)[s ?? ''] ?? 'info'
})

const projectId = computed(() => projectStore.current?.id)

async function onDocClassify(docId: string, bucket: string) {
  if (!projectId.value) return
  try {
    await searchStore.classifyDocument(String(projectId.value), docId, bucket)
    await bucketStore.fetchBuckets(String(projectId.value))
  } catch (e: any) {
    ElMessage.error('分类失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function promptRegenerate(docId: string, sourceLabel: string) {
  // 询问用户是否让 AI 基于新全文重新生成摘要 + 重新评分
  try {
    await ElMessageBox.confirm(
      '已成功获取全文。是否让 AI 基于全文重新生成摘要和重新评分？',
      `${sourceLabel}成功`,
      {
        confirmButtonText: '让 AI 重新分析',
        cancelButtonText: '暂不',
        type: 'success',
      },
    )
    // 用户同意 → 调 regenerate-analysis
    await searchApi.regenerateAnalysis(String(projectId.value), docId)
    ElMessage.success('AI 已基于全文重新分析完成')
    const roundId = searchStore.currentRound?.id
    if (roundId) await searchStore.loadRoundResults(roundId)
  } catch (e: any) {
    if (e === 'cancel' || e?.toString?.().includes('cancel')) {
      ElMessage.info('已保留原 AI 摘要，您可随时在全文查看页手动触发')
      return
    }
    ElMessage.error(e?.response?.data?.detail || 'AI 重新分析失败')
  }
}

async function onDownloadFulltext(docId: string, format: 'pdf' | 'html' | 'auto' = 'auto') {
  if (!projectId.value) return
  const roundId = searchStore.currentRound?.id
  const doc = documents.value.find((d: any) => String(d.id) === docId) as any
  if (!doc) return

  // 对应通道的 status 字段名
  const statusField = format === 'html' ? 'fulltext_html_status' : 'fulltext_pdf_status'
  const pathField = format === 'html' ? 'fulltext_html_path' : 'fulltext_pdf_path'
  const kindLabel = format === 'html' ? 'HTML 快照' : 'PDF'

  try {
    // 立即在按钮上显示"正在下载"特效（spinner + pulse）
    doc[statusField] = 'downloading'
    doc.fulltext_status = 'downloading'  // 聚合状态兼容
    await downloadFulltextWithBudgetConfirm(String(projectId.value), docId, format)

    if (!roundId) return

    // 轮询 60 次 × 3s = 3 分钟最长
    for (let i = 0; i < 60; i++) {
      await new Promise((r) => setTimeout(r, 3000))
      try {
        await searchStore.loadRoundResults(roundId)
        // 注意：loadRoundResults 重建了 documents 数组，需要重新 find
        const updated = documents.value.find((d: any) => String(d.id) === docId) as any
        if (!updated) continue

        if (updated[statusField] === 'available') {
          // 同步到原 doc 引用避免响应式漏更
          doc[statusField] = 'available'
          doc[pathField] = updated[pathField]
          doc.fulltext_status = updated.fulltext_status
          doc.fulltext_path = updated.fulltext_path
          ElMessage.success(`✓ ${kindLabel} 下载完成`)
          await promptRegenerate(docId, `下载 ${kindLabel}`)
          return
        }
        if (updated[statusField] === 'failed') {
          doc[statusField] = 'failed'
          doc.fulltext_status = updated.fulltext_status
          ElMessage.error(`${kindLabel} 下载失败，可手动上传或点击「原文 ↗」`)
          return
        }
      } catch { /* keep retrying */ }
    }
    ElMessage.warning(`${kindLabel} 下载超时，后端仍在执行，刷新页面查看`)
  } catch (e: any) {
    doc[statusField] = 'not_attempted'
    const detail = e.response?.data?.detail
    if (e.response?.status === 422 && typeof detail === 'object' && detail?.code === 'no_source') {
      ElMessage.warning(detail.message || '该文献无可用源，请手动上传')
    } else {
      ElMessage.error(typeof detail === 'string' ? detail : `${kindLabel} 下载失败`)
    }
  }
}

// Mount: 强制从后端拉一次 round results，
// 避免 store 里缓存的 doc 对象因为旧 schema 没有 fulltext_status 字段
onMounted(async () => {
  const rid = props.richData?.round_id
  if (!rid) return
  try {
    await searchStore.loadRoundResults(rid)
  } catch { /* ignore */ }
})

async function onUploadFulltext(
  docId: string,
  payload: { format: 'pdf' | 'html'; file: File },
) {
  if (!projectId.value) return
  const { format, file } = payload
  const doc = documents.value.find((d: any) => String(d.id) === docId) as any
  try {
    await searchApi.uploadFulltext(String(projectId.value), docId, file, format)
    ElMessage.success(`✓ ${format.toUpperCase()} 上传成功！`)
    if (doc) {
      doc.fulltext_status = 'available'
      if (format === 'pdf') doc.fulltext_pdf_status = 'available'
      else doc.fulltext_html_status = 'available'
    }
    const roundId = searchStore.currentRound?.id
    if (roundId) await searchStore.loadRoundResults(roundId)
    await promptRegenerate(docId, '上传')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || `${format.toUpperCase()} 上传失败`)
  }
}
</script>

<style scoped>
.rich-msg {
  margin: 14px 0;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #e2e8f0;
  overflow: hidden;
}
.rich-msg__header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  font-weight: 600;
  font-size: 13px;
  color: #065f46;
  background: linear-gradient(180deg, #ecfdf5 0%, #f0fdf4 100%);
  border-bottom: 1px solid #d1fae5;
}
.rich-msg__header .spacer { flex: 1; }
.rich-msg__body { padding: 14px; }
.round-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  color: #64748b;
  margin-bottom: 10px;
}
.feedback-progress {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 10px 0;
  font-size: 13px;
  color: #475569;
}
.cutoff-toggle { margin: 6px 0 10px; text-align: right; }
.doc-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 6px;
}
.fallback-list { padding-top: 10px; }
.fallback-list .hint { font-size: 12px; color: #94a3b8; margin: 0 0 8px; }
.doc-row {
  padding: 8px 10px;
  background: #f8fafc;
  border-radius: 6px;
  cursor: pointer;
  margin-bottom: 6px;
}
.doc-row:hover { background: #e0f2fe; }
.doc-row__title {
  font-size: 13px;
  color: #0f172a;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}
.doc-row__meta { display: flex; gap: 4px; margin-top: 4px; font-size: 12px; }
</style>
