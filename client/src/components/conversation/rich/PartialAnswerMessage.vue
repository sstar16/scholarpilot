<template>
  <div class="rich-msg rich-msg--partial">
    <div class="rich-msg__header">
      <span class="icon">⚡</span>
      <span class="title">Answer Now · 部分结果</span>
      <el-tag size="small" effect="dark" type="warning">中断于 {{ stage }}</el-tag>
      <el-tag v-if="docCount > 0" size="small" effect="plain">基于 {{ docCount }} 篇</el-tag>
      <el-tag size="small" effect="plain" :type="confidenceType">
        置信度 {{ Math.round(confidence * 100) }}%
      </el-tag>
    </div>
    <div class="rich-msg__body">
      <el-alert
        v-if="disclaimer"
        :title="disclaimer"
        type="warning"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
      <div class="answer-md" v-html="renderedAnswer"></div>
      <div v-if="error" class="error-block">
        ⚠ LLM 错误: {{ error }}
      </div>
      <div v-if="docIdsCited.length" class="citations">
        <span class="citations-label">引用 ({{ docIdsCited.length }}):</span>
        <el-tag
          v-for="cid in docIdsCited"
          :key="cid"
          size="small"
          effect="plain"
          class="cite-tag"
        >📄 {{ cid }}</el-tag>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '../../../composables/useMarkdown'

const props = defineProps<{ richData: any }>()

// rich_data 来自后端 deliver_partial_answer：{round_id, partial_answer: {...}}
const partial = computed(() => props.richData?.partial_answer || {})
const stage = computed(() => partial.value.interrupted_at_stage || '—')
const docCount = computed(() => partial.value.doc_count_used ?? 0)
const confidence = computed(() => partial.value.confidence ?? 0)
const disclaimer = computed(() => partial.value.disclaimer || '')
const error = computed(() => partial.value.error)
const docIdsCited = computed<string[]>(() => partial.value.doc_ids_cited || [])

const confidenceType = computed(() => {
  const c = confidence.value
  if (c >= 0.7) return 'success'
  if (c >= 0.4) return 'warning'
  return 'danger'
})

const renderedAnswer = computed(() => renderMarkdown(partial.value.answer_markdown || ''))
</script>

<style scoped>
.rich-msg--partial {
  background: #fffbeb;
  border: 1.5px solid var(--signal-amber, #f59e0b);
  border-radius: 12px;
  margin: 14px 0;
  overflow: hidden;
}
.rich-msg__header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  font-weight: 600;
  font-size: 13px;
  color: #92400e;
  background: linear-gradient(180deg, #fef3c7 0%, #fffbeb 100%);
  border-bottom: 1px solid #fde68a;
}
.rich-msg__header .icon { font-size: 16px; }
.rich-msg__header .title { margin-right: auto; }
.rich-msg__body { padding: 14px; }
.answer-md { line-height: 1.6; font-size: 14px; color: #1f2937; }
.answer-md :deep(h1) { font-size: 18px; margin: 14px 0 8px; }
.answer-md :deep(h2) { font-size: 16px; margin: 12px 0 6px; color: #92400e; }
.answer-md :deep(h3) { font-size: 14px; margin: 10px 0 4px; }
.answer-md :deep(ul), .answer-md :deep(ol) { padding-left: 22px; margin: 6px 0; }
.answer-md :deep(li) { margin: 2px 0; }
.answer-md :deep(strong) { color: #b45309; }
.answer-md :deep(code) {
  background: #fef3c7;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: var(--font-mono, monospace);
  font-size: 12.5px;
}
.answer-md :deep(p) { margin: 6px 0; }
.error-block {
  margin-top: 12px;
  padding: 10px;
  background: #fef2f2;
  color: #b91c1c;
  border-radius: 6px;
  font-size: 13px;
}
.citations {
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed #fde68a;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.citations-label {
  font-size: 12px;
  color: #92400e;
  margin-right: 4px;
}
.cite-tag { font-family: var(--font-mono, monospace); }
</style>
