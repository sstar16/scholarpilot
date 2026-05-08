<script setup lang="ts">
import SearchingAnimation from '@/components/retrieval/SearchingAnimation.vue'

defineProps<{
  payload: {
    job_id: string
    doc_id: string
    filename?: string
  }
}>()
</script>

<template>
  <div class="pdf-scoring">
    <div class="pdf-scoring__head">
      <span class="title">📄 {{ payload.filename || '已上传文档' }}</span>
      <span class="tag">生成摘要 + 评分中</span>
    </div>
    <SearchingAnimation message="ScholarPilot 正在分析这篇文献..." />
    <div class="pdf-scoring__hint">完成后会自动生成文献卡片</div>
  </div>
</template>

<style scoped>
.pdf-scoring {
  border: 1px solid var(--ink-200);
  border-radius: 10px;
  padding: 14px 16px;
  background: linear-gradient(180deg, var(--signal-blue-bg) 0%, var(--paper) 60%);
  margin: 4px 0 16px 46px;
  max-width: calc(85% - 46px);
  box-sizing: border-box;
}
.pdf-scoring__head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
  font-size: 14px;
  color: var(--ink-900);
}
.pdf-scoring__head .title { font-weight: 600; }
.pdf-scoring__head .tag {
  font-size: 12px;
  color: var(--signal-blue-light);
  background: var(--signal-blue-bg);
  border: 1px solid var(--signal-blue-bg);
  border-radius: 10px;
  padding: 2px 8px;
}
.pdf-scoring__hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--ink-400);
  text-align: center;
}
</style>
