<template>
  <div class="rich-msg rich-msg--answer">
    <div class="rich-msg__header">
      <el-icon :size="16"><ChatLineRound /></el-icon>
      <span class="title">协作研究回答</span>
      <el-tag v-if="richData.confidence" size="small" effect="plain">
        置信度 {{ Math.round(richData.confidence * 100) }}%
      </el-tag>
    </div>
    <div class="rich-msg__body">
      <div
        v-if="(richData.fulltext_picks || []).length"
        class="picks"
      >
        <div class="picks-head">
          <el-icon :size="14"><Reading /></el-icon>
          AI 精读了 {{ richData.fulltext_picks.length }} 篇全文
        </div>
        <div class="pick-list">
          <div
            v-for="(p, i) in richData.fulltext_picks"
            :key="p.doc_id || i"
            class="pick-item"
          >
            <span class="pick-idx">📖 #{{ i + 1 }}</span>
            <div class="pick-body">
              <div class="pick-title">{{ p.title || p.doc_id }}</div>
              <div v-if="p.reason" class="pick-reason">{{ p.reason }}</div>
            </div>
          </div>
        </div>
      </div>

      <div
        v-if="(richData.kg_used || []).length"
        class="kg-used"
      >
        <div class="kg-used-head">
          <el-icon :size="14"><Share /></el-icon>
          AI 查了 {{ richData.kg_used.length }} 个知识图谱实体
        </div>
        <div class="kg-list">
          <div
            v-for="(q, i) in richData.kg_used"
            :key="q.entity + i"
            class="kg-item"
          >
            <el-tag v-if="q.node_type" size="small" effect="plain">{{ q.node_type }}</el-tag>
            <span class="kg-label">{{ q.entity }}</span>
            <span v-if="q.reason" class="kg-reason">· {{ q.reason }}</span>
          </div>
        </div>
      </div>

      <div class="answer-text markdown-body" v-html="formatAnswer(richData.answer)" />

      <div v-if="(richData.citations || []).length" class="citations">
        <div class="citations-head">引用文献 ({{ richData.citations.length }})</div>
        <div class="citation-list">
          <div
            v-for="(c, i) in richData.citations"
            :key="i"
            class="citation-item"
          >
            <span class="cite-num">[{{ i + 1 }}]</span>
            <span class="cite-title">{{ c.title || '[未解析的引用]' }}</span>
            <span v-if="c.quote" class="cite-quote">{{ c.quote }}</span>
          </div>
        </div>
      </div>

      <div v-if="(richData.follow_up_suggestions || []).length" class="follow-ups">
        <div class="follow-head">建议的后续问题</div>
        <el-tag
          v-for="(s, i) in richData.follow_up_suggestions"
          :key="i"
          size="small"
          effect="plain"
          @click="$emit('follow-up', s)"
          style="cursor: pointer; margin: 4px 4px 0 0"
        >
          {{ s }}
        </el-tag>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ChatLineRound, Reading, Share } from '@element-plus/icons-vue'
import { renderMarkdown } from '../../../composables/useMarkdown'

defineProps<{ richData: any }>()
defineEmits<{ 'follow-up': [suggestion: string] }>()

function formatAnswer(text: string): string {
  if (!text) return ''
  return renderMarkdown(text)
}
</script>

<style scoped>
/* variant 色板（基础骨架见 design-system.css） */
.rich-msg {
  background: var(--paper);
  border: 1px solid var(--signal-purple-bg);
}
.rich-msg__header {
  color: var(--signal-purple);
  background: var(--signal-purple-bg);
  border-bottom: 1px solid var(--signal-purple-bg);
}
.answer-text {
  font-size: var(--type-body-size);
  line-height: 1.7;
  color: var(--ink-900);
}

/* Markdown rendering inside answer-text */
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 0.6em 0 0.3em;
  font-weight: 600;
  line-height: 1.3;
  color: var(--ink-900);
  font-family: var(--font-display);
}
.markdown-body :deep(h1) { font-size: 1.25em; }
.markdown-body :deep(h2) { font-size: 1.15em; }
.markdown-body :deep(h3) { font-size: 1.05em; }
.markdown-body :deep(p) { margin: 0.4em 0; }
.markdown-body :deep(p:first-child) { margin-top: 0; }
.markdown-body :deep(p:last-child) { margin-bottom: 0; }
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0.5em 0;
  padding-left: 1.4em;
}
.markdown-body :deep(li) { margin: 0.2em 0; }
.markdown-body :deep(code) {
  background: var(--signal-purple-bg);
  color: var(--signal-purple);
  padding: 1px 5px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 0.88em;
}
.markdown-body :deep(pre) {
  background: var(--ink-900);
  color: var(--ink-100);
  padding: 10px 12px;
  border-radius: var(--radius-md);
  overflow-x: auto;
  margin: 0.6em 0;
  font-size: 0.88em;
}
.markdown-body :deep(pre code) {
  background: none;
  color: inherit;
  padding: 0;
}
.markdown-body :deep(blockquote) {
  margin: 0.6em 0;
  padding: var(--space-1) var(--space-3);
  border-left: 3px solid var(--signal-purple);
  background: var(--signal-purple-bg);
  color: var(--ink-500);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
.markdown-body :deep(table) {
  border-collapse: collapse;
  margin: 0.6em 0;
  font-size: 0.95em;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid var(--ink-100);
  padding: var(--space-1) var(--space-3);
}
.markdown-body :deep(th) {
  background: var(--paper-cool);
  font-weight: 600;
}
.markdown-body :deep(a) {
  color: var(--signal-blue);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.markdown-body :deep(strong) { font-weight: 600; color: var(--ink-900); }
.markdown-body :deep(hr) {
  margin: 0.8em 0;
  border: none;
  border-top: 1px dashed var(--ink-200);
}
.citations {
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px dashed var(--ink-100);
}
.citations-head, .follow-head {
  font-size: var(--type-meta-size);
  font-weight: 600;
  color: var(--ink-400);
  margin-bottom: var(--space-2);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.citation-item {
  display: flex;
  gap: var(--space-2);
  font-size: var(--type-meta-size);
  color: var(--ink-500);
  padding: var(--space-1) 0;
}
.cite-num {
  color: var(--signal-blue);
  font-family: var(--font-mono);
  font-weight: 600;
  flex-shrink: 0;
}
.cite-title { font-weight: 500; }
.cite-quote {
  display: block;
  margin-top: 2px;
  font-style: italic;
  color: var(--ink-300);
}
.follow-ups { margin-top: var(--space-3); }
.picks {
  margin-bottom: var(--space-3);
  padding: 10px var(--space-3);
  background: var(--signal-amber-bg);
  border-radius: var(--radius-md);
  border: 1px solid var(--signal-amber-bg);
}
.picks-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--type-meta-size);
  font-weight: 600;
  color: var(--signal-amber);
  margin-bottom: var(--space-2);
}
.pick-list { display: flex; flex-direction: column; gap: var(--space-1); }
.pick-item {
  display: flex;
  gap: var(--space-2);
  padding: var(--space-1) 0;
  font-size: var(--type-sub-size);
}
.pick-idx {
  color: var(--signal-amber);
  font-weight: 600;
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}
.pick-body { flex: 1; min-width: 0; }
.pick-title {
  color: var(--ink-900);
  font-weight: 500;
  line-height: 1.3;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}
.pick-reason {
  color: var(--signal-amber);
  font-size: var(--type-meta-size);
  margin-top: 2px;
  font-style: italic;
}
.kg-used {
  margin-bottom: var(--space-3);
  padding: 10px var(--space-3);
  background: var(--signal-blue-bg);
  border-radius: var(--radius-md);
  border: 1px solid var(--signal-blue-bg);
}
.kg-used-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--type-meta-size);
  font-weight: 600;
  color: var(--signal-blue);
  margin-bottom: var(--space-2);
}
.kg-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-3);
}
.kg-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--type-sub-size);
  color: var(--ink-900);
}
.kg-label { font-weight: 500; color: var(--signal-blue); }
.kg-reason { color: var(--ink-400); font-size: var(--type-meta-size); }
</style>
