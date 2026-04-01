<template>
  <div class="doc-card" :class="{ rated: localFeedback !== null, [`fb-${localFeedback}`]: localFeedback !== null }">
    <!-- Journal binding accent -->
    <div class="binding" :class="docType.accent"></div>

    <div class="card-inner">
      <!-- Row 1: Badges + date -->
      <div class="meta-row">
        <div class="badges">
          <span class="badge" :class="docType.accent">{{ docType.label }}</span>
          <span class="badge badge-outline">{{ doc.source }}</span>
        </div>
        <div class="meta-right">
          <span v-if="doc.publication_date" class="date">{{ formatDate(doc.publication_date) }}</span>
          <transition name="pop">
            <span v-if="localFeedback !== null" class="fb-tag" :class="feedbackTag.cls">{{ feedbackTag.label }}</span>
          </transition>
        </div>
      </div>

      <!-- Title -->
      <h3 class="title">
        <a :href="doc.url" target="_blank" rel="noopener noreferrer">{{ doc.title }}</a>
      </h3>

      <!-- Authors -->
      <p v-if="doc.authors" class="authors">{{ formatAuthors(doc.authors) }}</p>

      <!-- AI Summary -->
      <div v-if="doc.ai_summary || !roundDone" class="summary-panel">
        <div class="summary-head">
          <span class="ai-badge">AI</span>
          <span class="summary-label">智能摘要</span>
          <span v-if="doc.ai_summary_source === 'from_abstract'" class="src-tag">原文摘要</span>
          <span v-else-if="doc.ai_summary_source === 'from_title'" class="src-tag src-tag-warn">标题推断</span>
        </div>
        <template v-if="doc.ai_summary">
          <p class="summary-body" :class="{ collapsed: !expanded }">{{ doc.ai_summary }}</p>
          <button v-if="doc.ai_summary.length > 180" class="btn-expand" @click="expanded = !expanded">
            {{ expanded ? '收起' : '展开全文' }}
          </button>
          <div v-if="doc.ai_key_points?.length" class="key-points">
            <span v-for="(pt, i) in doc.ai_key_points" :key="i" class="kp">{{ pt }}</span>
          </div>
          <p v-if="doc.ai_relevance_reason" class="relevance">{{ doc.ai_relevance_reason }}</p>
        </template>
        <div v-else-if="!roundDone" class="generating">
          <span class="dot-pulse"><span/><span/><span/></span>
          AI 正在分析...
        </div>
      </div>
      <p v-else-if="roundDone" class="no-summary">暂无摘要信息</p>

      <!-- Feedback -->
      <div class="feedback-bar">
        <span class="fb-label">相关度</span>
        <div class="pills">
          <button v-for="o in opts" :key="o.value" class="pill" :class="[o.cls, { active: localFeedback === o.value }]" @click="pick(o.value)">
            {{ o.label }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
const props = defineProps<{ doc: any; initialFeedback?: number | null; roundStatus?: string }>()
const emit = defineEmits<{ (e: 'feedback', v: number): void }>()
const roundDone = computed(() => ['awaiting_feedback', 'completed'].includes(props.roundStatus ?? ''))
const expanded = ref(false)
const localFeedback = ref<number | null>(props.initialFeedback ?? null)
watch(() => props.initialFeedback, v => { localFeedback.value = v ?? null })

const opts = [
  { label: '无关', value: -1, cls: 'p-neg' },
  { label: '不确定', value: 0, cls: 'p-mid' },
  { label: '相关', value: 1, cls: 'p-pos' },
  { label: '很相关', value: 2, cls: 'p-top' },
]
function pick(v: number) { localFeedback.value = v; emit('feedback', v) }

const docType = computed(() => {
  const m: Record<string, { label: string; accent: string }> = {
    paper: { label: '论文', accent: 'a-blue' }, preprint: { label: '预印本', accent: 'a-amber' },
    patent: { label: '专利', accent: 'a-teal' }, clinical_trial: { label: '临床试验', accent: 'a-coral' },
  }
  return m[props.doc.doc_type] ?? { label: props.doc.doc_type, accent: 'a-slate' }
})
const fbMap: Record<number, { label: string; cls: string }> = {
  [-1]: { label: '无关', cls: 'ft-neg' }, [0]: { label: '不确定', cls: 'ft-mid' },
  [1]: { label: '相关', cls: 'ft-pos' }, [2]: { label: '很相关', cls: 'ft-top' },
}
const feedbackTag = computed(() => localFeedback.value !== null ? fbMap[localFeedback.value] ?? { label: '', cls: '' } : { label: '', cls: '' })
function formatDate(d: string) { return d ? d.slice(0, 7) : '' }
function formatAuthors(a: any) {
  if (Array.isArray(a)) { const n = a.slice(0,3).map((x:any) => x.name||x).join(', '); return a.length > 3 ? n+` 等${a.length}人` : n }
  return String(a)
}
</script>

<style scoped>
.doc-card {
  position: relative; display: flex;
  background: var(--paper);
  border: 1px solid var(--ink-100);
  border-radius: var(--radius-lg);
  overflow: hidden;
  transition: all var(--duration-normal) var(--ease-out);
  animation: fadeUp var(--duration-slow) var(--ease-out) both;
}
.doc-card:hover {
  border-color: var(--ink-200);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}
.doc-card.fb--1 { opacity: 0.55; }
.doc-card.fb-2 { box-shadow: var(--shadow-glow-teal); border-color: rgba(13,148,136,0.25); }

/* ── Binding (left accent bar — like a journal spine) ── */
.binding { width: 4px; flex-shrink: 0; transition: width var(--duration-fast); }
.doc-card:hover .binding { width: 5px; }
.a-blue  { background: linear-gradient(180deg, #2563eb, #60a5fa); }
.a-amber { background: linear-gradient(180deg, #d97706, #fbbf24); }
.a-teal  { background: linear-gradient(180deg, var(--signal-teal), var(--signal-teal-light)); }
.a-coral { background: linear-gradient(180deg, #dc2626, #f87171); }
.a-slate { background: linear-gradient(180deg, #64748b, #94a3b8); }

.card-inner { flex: 1; padding: 18px 22px; min-width: 0; }

/* ── Meta row ── */
.meta-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; gap: 8px; }
.badges { display: flex; gap: 5px; flex-wrap: wrap; }
.badge {
  font-size: 10px; font-weight: 700; letter-spacing: 0.04em;
  padding: 2px 9px; border-radius: var(--radius-full); color: #fff;
}
.badge.a-blue { background: #2563eb; } .badge.a-amber { background: #d97706; color: #fff; }
.badge.a-teal { background: var(--signal-teal); } .badge.a-coral { background: #dc2626; }
.badge.a-slate { background: #64748b; }
.badge-outline {
  background: transparent; color: var(--ink-400);
  border: 1px solid var(--ink-200); font-weight: 500;
}
.meta-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.date { font-size: 11px; color: var(--ink-300); }

/* Feedback tag */
.fb-tag { font-size: 10px; font-weight: 700; padding: 2px 9px; border-radius: var(--radius-full); }
.ft-neg { background: var(--signal-coral-bg); color: var(--signal-coral); }
.ft-mid { background: var(--ink-50); color: var(--ink-400); }
.ft-pos { background: var(--signal-blue-bg); color: var(--signal-blue); }
.ft-top { background: var(--signal-teal-bg); color: var(--signal-teal); }

/* ── Title ── */
.title {
  font-family: var(--font-display); font-size: 16px; font-weight: 700;
  line-height: 1.55; margin: 0 0 4px; color: var(--ink-900);
}
.title a {
  color: inherit; text-decoration: none;
  transition: color var(--duration-fast);
}
.title a:hover { color: var(--signal-teal); }

.authors { font-size: 12px; color: var(--ink-400); margin: 0 0 12px; }

/* ── Summary panel ── */
.summary-panel {
  background: var(--paper-cool); border: 1px solid var(--ink-100);
  border-radius: var(--radius-md); padding: 14px 16px; margin-bottom: 12px;
}
.summary-head { display: flex; align-items: center; gap: 7px; margin-bottom: 8px; }
.ai-badge {
  width: 20px; height: 20px; border-radius: 5px;
  background: var(--signal-teal); color: #fff;
  font-size: 8px; font-weight: 800; letter-spacing: -0.5px;
  display: flex; align-items: center; justify-content: center;
}
.summary-label { font-size: 12px; font-weight: 600; color: var(--ink-600); }
.src-tag { font-size: 10px; padding: 1px 7px; border-radius: var(--radius-full); background: var(--signal-amber-bg); color: var(--signal-amber); }
.src-tag-warn { background: var(--signal-coral-bg); color: var(--signal-coral); }

.summary-body {
  font-size: 14px; line-height: 1.85; color: var(--ink-800); margin: 0;
  font-family: var(--font-body);
}
.summary-body.collapsed {
  display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden;
}
.btn-expand {
  background: none; border: none; cursor: pointer;
  color: var(--signal-teal); font-size: 12px; font-weight: 600;
  padding: 4px 0; margin-top: 4px;
  font-family: var(--font-body);
}
.btn-expand:hover { text-decoration: underline; }

.key-points { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; }
.kp {
  font-size: 11px; padding: 3px 10px; border-radius: var(--radius-full);
  background: var(--paper); border: 1px solid var(--ink-100);
  color: var(--ink-600);
}

.relevance {
  font-size: 12px; color: var(--signal-teal); margin: 10px 0 0;
  padding-top: 8px; border-top: 1px solid var(--ink-100);
  line-height: 1.5;
}
.no-summary { font-size: 13px; color: var(--ink-300); font-style: italic; margin: 0 0 12px; }

/* Generating dots */
.generating { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--signal-teal); }
.dot-pulse { display: flex; gap: 3px; }
.dot-pulse span {
  width: 5px; height: 5px; border-radius: 50%; background: var(--signal-teal);
  animation: pulse-dot 1.2s infinite ease-in-out;
}
.dot-pulse span:nth-child(2) { animation-delay: 0.15s; }
.dot-pulse span:nth-child(3) { animation-delay: 0.3s; }

/* ── Feedback bar ── */
.feedback-bar {
  display: flex; align-items: center; gap: 12px;
  padding-top: 12px; border-top: 1px solid var(--ink-100);
}
.fb-label { font-size: 12px; font-weight: 500; color: var(--ink-400); white-space: nowrap; }
.pills { display: flex; gap: 5px; }
.pill {
  padding: 4px 13px; border-radius: var(--radius-full);
  font-size: 12px; font-weight: 500; cursor: pointer;
  border: 1.5px solid var(--ink-200); background: var(--paper);
  color: var(--ink-500); font-family: var(--font-body);
  transition: all var(--duration-fast);
}
.pill:hover { border-color: var(--ink-300); background: var(--paper-hover); }
.pill.active.p-neg { background: var(--signal-coral-bg); border-color: rgba(220,38,38,0.3); color: var(--signal-coral); }
.pill.active.p-mid { background: var(--ink-50); border-color: var(--ink-300); color: var(--ink-600); }
.pill.active.p-pos { background: var(--signal-blue-bg); border-color: rgba(37,99,235,0.3); color: var(--signal-blue); }
.pill.active.p-top { background: var(--signal-teal-bg); border-color: rgba(13,148,136,0.3); color: var(--signal-teal); }

/* ── Transitions ── */
.pop-enter-active { animation: pop 0.2s var(--ease-spring); }
@keyframes pop { from { transform: scale(0.8); opacity: 0; } to { transform: scale(1); opacity: 1; } }
</style>
