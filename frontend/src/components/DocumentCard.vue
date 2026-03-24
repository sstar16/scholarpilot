<template>
  <el-card class="doc-card" shadow="never" :class="{ 'is-rated': localFeedback !== null }">
    <!-- Header -->
    <div class="doc-header">
      <div class="doc-meta">
        <el-tag size="small" :type="docTypeTag.type">{{ docTypeTag.label }}</el-tag>
        <el-tag size="small" type="info" effect="plain">{{ doc.source }}</el-tag>
        <span class="doc-date" v-if="doc.publication_date">{{ formatDate(doc.publication_date) }}</span>
      </div>
      <el-tag v-if="localFeedback !== null" :type="feedbackTag.type" size="small" effect="dark">
        {{ feedbackTag.label }}
      </el-tag>
    </div>

    <!-- Title -->
    <h3 class="doc-title">
      <a :href="doc.url" target="_blank" rel="noopener noreferrer" class="title-link">
        {{ doc.title }}
      </a>
    </h3>

    <!-- Authors -->
    <p v-if="doc.authors" class="doc-authors">{{ formatAuthors(doc.authors) }}</p>

    <!-- AI Summary -->
    <div class="summary-section">
      <div class="summary-label">
        <el-icon><MagicStick /></el-icon> AI 摘要
        <el-tag v-if="doc.ai_summary_source === 'from_abstract'" size="small" type="warning" effect="plain" style="margin-left:6px">来自原文摘要</el-tag>
      </div>

      <template v-if="doc.ai_summary">
        <p class="summary-text" :class="{ 'collapsed': !expanded }">{{ doc.ai_summary }}</p>
        <div v-if="doc.ai_key_points?.length" class="key-points">
          <span v-for="(pt, i) in doc.ai_key_points" :key="i" class="key-point">
            <el-icon><Right /></el-icon> {{ pt }}
          </span>
        </div>
        <div v-if="doc.ai_relevance_reason" class="relevance-reason">
          <el-icon><Link /></el-icon> {{ doc.ai_relevance_reason }}
        </div>
      </template>
      <template v-else>
        <el-skeleton :rows="3" animated />
      </template>
    </div>

    <el-button v-if="doc.ai_summary" text size="small" @click="expanded = !expanded" style="margin-top:4px">
      {{ expanded ? '收起' : '展开全文摘要' }}
    </el-button>

    <!-- Feedback -->
    <div class="feedback-section">
      <span class="feedback-label">相关度：</span>
      <el-segmented
        v-model="localFeedback"
        :options="feedbackOptions"
        size="small"
        @change="onFeedbackChange"
      />
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'

const props = defineProps<{
  doc: any
  initialFeedback?: number | null
}>()

const emit = defineEmits<{
  (e: 'feedback', value: number): void
}>()

const expanded = ref(false)
const localFeedback = ref<number | null>(props.initialFeedback ?? null)

watch(() => props.initialFeedback, (v) => {
  localFeedback.value = v ?? null
})

const feedbackOptions = [
  { label: '无关', value: -1 },
  { label: '不确定', value: 0 },
  { label: '相关', value: 1 },
  { label: '非常相关', value: 2 },
]

const docTypeTag = computed(() => {
  const map: Record<string, { label: string; type: string }> = {
    paper: { label: '期刊论文', type: 'primary' },
    preprint: { label: '预印本', type: 'warning' },
    patent: { label: '专利', type: 'success' },
  }
  return map[props.doc.doc_type] ?? { label: props.doc.doc_type, type: 'info' }
})

const feedbackTagMap: Record<number, { label: string; type: string }> = {
  [-1]: { label: '无关', type: 'danger' },
  [0]: { label: '不确定', type: 'info' },
  [1]: { label: '相关', type: 'primary' },
  [2]: { label: '非常相关', type: 'success' },
}

const feedbackTag = computed(() => {
  if (localFeedback.value === null) return { label: '', type: '' }
  return feedbackTagMap[localFeedback.value] ?? { label: '', type: '' }
})

function onFeedbackChange(val: number) {
  emit('feedback', val)
}

function formatDate(d: string) {
  return d ? d.slice(0, 7) : ''
}

function formatAuthors(authors: any) {
  if (Array.isArray(authors)) {
    const names = authors.slice(0, 3).map((a: any) => a.name || a).join(', ')
    return authors.length > 3 ? names + ` 等${authors.length}人` : names
  }
  return String(authors)
}
</script>

<style scoped>
.doc-card {
  border-left: 3px solid transparent;
  transition: border-color 0.2s;
}
.doc-card.is-rated {
  border-left-color: var(--el-color-primary);
}
.doc-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  flex-wrap: wrap;
  gap: 6px;
}
.doc-meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.doc-date { font-size: 12px; color: #909399; }
.doc-title { font-size: 15px; font-weight: 600; margin: 6px 0 4px; line-height: 1.5; }
.title-link { color: #303133; text-decoration: none; }
.title-link:hover { color: var(--el-color-primary); }
.doc-authors { font-size: 12px; color: #909399; margin: 0 0 10px; }

.summary-section { background: #f8f9fa; border-radius: 6px; padding: 12px; margin: 10px 0; }
.summary-label { font-size: 12px; font-weight: 600; color: #606266; display: flex; align-items: center; gap: 4px; margin-bottom: 8px; }

.summary-text { font-size: 14px; line-height: 1.8; color: #303133; margin: 0; }
.summary-text.collapsed { display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }

.key-points { margin-top: 10px; display: flex; flex-direction: column; gap: 4px; }
.key-point { font-size: 13px; color: #606266; display: flex; align-items: flex-start; gap: 4px; }

.relevance-reason { margin-top: 8px; font-size: 13px; color: var(--el-color-primary); display: flex; align-items: center; gap: 4px; }

.feedback-section { display: flex; align-items: center; gap: 12px; margin-top: 12px; padding-top: 12px; border-top: 1px solid #f0f0f0; }
.feedback-label { font-size: 13px; color: #606266; white-space: nowrap; }
</style>
