<template>
  <div class="document-stream" v-if="docs.length > 0">
    <div class="stream-header">
      <span class="stream-count">{{ docs.length }} 篇候选文献（去重筛选前）</span>
      <span class="stream-hint">实时推送中</span>
    </div>
    <div class="stream-container">
      <div class="stream-fade-top"></div>
      <div class="stream-list" ref="listRef">
        <TransitionGroup name="stream-item">
          <div
            v-for="(doc, idx) in docs"
            :key="doc.external_id + '-' + doc.source"
            class="stream-card"
            :style="{ transitionDelay: `${Math.min(idx * 50, 300)}ms` }"
          >
            <span class="source-dot" :style="{ background: sourceColor(doc.source) }"></span>
            <span class="source-tag" :style="{ color: sourceColor(doc.source), borderColor: sourceColor(doc.source) + '40' }">
              {{ sourceLabel(doc.source) }}
            </span>
            <div class="card-main">
              <span class="card-title">{{ doc.title }}</span>
              <span class="card-meta" v-if="doc.year || doc.authors">
                {{ doc.year ? doc.year + '' : '' }}{{ doc.authors ? ' · ' + truncAuthors(doc.authors) : '' }}
              </span>
            </div>
            <span class="summary-status">
              <span v-if="doc.has_summary" class="status-done" title="摘要已生成">✓</span>
              <span v-else class="status-pending" title="摘要生成中">
                <span class="mini-spinner"></span>
              </span>
            </span>
          </div>
        </TransitionGroup>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, watch, onUnmounted } from 'vue'

const props = defineProps<{
  docs: any[]
}>()

const listRef = ref<HTMLElement | null>(null)
const userScrolling = ref(false)
let lastScrollWasProgrammatic = false

function onScroll() {
  if (!listRef.value) return
  // Skip if this scroll was triggered by our auto-scroll code
  if (lastScrollWasProgrammatic) {
    lastScrollWasProgrammatic = false
    return
  }
  const el = listRef.value
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30
  // User scrolled up → pause auto-scroll; user scrolled back to bottom → resume
  userScrolling.value = !atBottom
}

// Attach scroll listener when listRef becomes available (it's inside v-if)
watch(listRef, (el, oldEl) => {
  oldEl?.removeEventListener('scroll', onScroll)
  el?.addEventListener('scroll', onScroll, { passive: true })
})

onUnmounted(() => {
  listRef.value?.removeEventListener('scroll', onScroll)
})

// Auto-scroll to bottom when new docs arrive (only if user hasn't scrolled up)
watch(() => props.docs.length, async () => {
  await nextTick()
  if (listRef.value && !userScrolling.value) {
    lastScrollWasProgrammatic = true
    listRef.value.scrollTop = listRef.value.scrollHeight
  }
})

const SOURCE_COLORS: Record<string, string> = {
  openalex: '#FF6B35',
  openalex_zh: '#FF8C5A',
  arxiv: '#B31B1B',
  crossref: '#2196F3',
  epo_ops: '#003DA5',
  europe_pmc: '#2E7D32',
  dblp: '#DAA520',
  biorxiv: '#7B1FA2',
  medrxiv: '#C62828',
  lens_patent: '#00695C',
  patenthub: '#D84315',
}

const SOURCE_LABELS: Record<string, string> = {
  openalex: 'OpenAlex',
  openalex_zh: 'OpenAlex中文',
  arxiv: 'arXiv',
  crossref: 'Crossref',
  epo_ops: 'EPO',
  europe_pmc: 'EuropePMC',
  dblp: 'DBLP',
  biorxiv: 'bioRxiv',
  medrxiv: 'medRxiv',
  lens_patent: 'Lens专利',
  patenthub: 'PatentHub',
}

function sourceColor(source: string): string {
  return SOURCE_COLORS[source] || '#909399'
}

function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] || source
}

function truncAuthors(authors: string | string[]): string {
  const str = Array.isArray(authors) ? authors.join(', ') : authors
  return str && str.length > 30 ? str.slice(0, 30) + '...' : (str || '')
}
</script>

<style scoped>
.document-stream {
  margin-top: 16px;
}

.stream-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  padding: 0 4px;
}

.stream-count {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-900);
}

.stream-hint {
  font-size: 12px;
  color: var(--ink-400);
  display: flex;
  align-items: center;
  gap: 6px;
}

.stream-hint::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--signal-emerald);
  animation: blink 1.5s infinite;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.stream-container {
  position: relative;
}

.stream-fade-top {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 40px;
  background: linear-gradient(to bottom, var(--paper), transparent);
  z-index: 2;
  pointer-events: none;
}

.stream-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 480px;
  overflow-y: auto;
  padding-top: 40px;
  padding-bottom: 8px;
  scroll-behavior: smooth;
  /* Thin subtle scrollbar */
  scrollbar-width: thin;
  scrollbar-color: var(--ink-200) transparent;
}
.stream-list::-webkit-scrollbar { width: 4px; }
.stream-list::-webkit-scrollbar-thumb { background: var(--ink-200); border-radius: 2px; }
.stream-list::-webkit-scrollbar-track { background: transparent; }

.stream-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: var(--paper);
  border-radius: 8px;
  border: 1px solid var(--ink-200);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  min-height: 48px;
  transition: all 0.3s ease;
}

.stream-card:hover {
  border-color: var(--ink-300);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.source-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.source-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 10px;
  border: 1px solid;
  flex-shrink: 0;
  white-space: nowrap;
  background: var(--paper);
}

.card-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.card-title {
  font-size: 13px;
  color: var(--ink-900);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-meta {
  font-size: 11px;
  color: var(--ink-400);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.summary-status {
  flex-shrink: 0;
  width: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.status-done {
  color: var(--signal-emerald);
  font-weight: 700;
  font-size: 14px;
}

.status-pending {
  display: flex;
  align-items: center;
  justify-content: center;
}

.mini-spinner {
  width: 14px;
  height: 14px;
  border: 2px solid var(--ink-200);
  border-top-color: var(--signal-blue-light);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* TransitionGroup animations */
.stream-item-enter-active {
  transition: all 0.45s cubic-bezier(0.23, 1, 0.32, 1);
}

.stream-item-leave-active {
  transition: all 0.3s ease-in;
}

.stream-item-enter-from {
  opacity: 0;
  transform: translateY(30px);
}

.stream-item-leave-to {
  opacity: 0;
  transform: translateY(-20px);
}

.stream-item-move {
  transition: transform 0.4s ease;
}
</style>
