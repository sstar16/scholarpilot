<template>
  <div ref="cardRef" class="doc-card" :class="{
    rated: localFeedback !== null,
    [`fb-${localFeedback}`]: localFeedback !== null,
    'below-cutoff': doc.below_cutoff,
  }">
    <!-- Journal binding accent -->
    <div class="binding" :class="docType.accent"></div>

    <div class="card-inner">
      <!-- Row 1: Badges + date + AI score -->
      <div class="meta-row">
        <div class="badges">
          <span class="badge" :class="docType.accent">{{ docType.label }}</span>
          <span class="badge badge-outline">{{ doc.source }}</span>
          <span v-if="doc.agent_score != null" class="badge badge-score" :class="scoreClass">
            AI {{ doc.agent_score.toFixed(1) }}
          </span>
        </div>
        <div class="meta-right">
          <span v-if="doc.publication_date" class="date">{{ formatDate(doc.publication_date) }}</span>
          <transition name="pop">
            <span v-if="localFeedback !== null" class="fb-tag" :class="feedbackTag.cls">{{ feedbackTag.label }}</span>
          </transition>
        </div>
      </div>

      <!-- One-line summary (above title) -->
      <div class="one-liner-wrap" v-if="doc.one_line_summary || editingOneLiner">
        <p v-if="!editingOneLiner" class="one-liner">
          {{ doc.one_line_summary }}
          <span v-if="isEdited('one_line_summary')" class="edit-badge" title="你已手动编辑">✎</span>
          <button class="inline-edit-btn" @click="startEditOneLiner" title="编辑">✏️</button>
          <button
            v-if="isEdited('one_line_summary')"
            class="inline-edit-btn"
            title="重置为 AI 版"
            @click="resetField('one_line_summary')"
          >↺</button>
        </p>
        <div v-else class="edit-inline">
          <el-input
            v-model="editOneLinerText"
            size="small"
            :maxlength="300"
            @keydown.enter.prevent="saveOneLiner"
            @keydown.esc="cancelOneLiner"
          />
          <el-button size="small" type="primary" :loading="savingField === 'one_line_summary'" @click="saveOneLiner">保存</el-button>
          <el-button size="small" @click="cancelOneLiner">取消</el-button>
        </div>
      </div>

      <!-- Title -->
      <h3 class="title">
        <a :href="doc.url" target="_blank" rel="noopener noreferrer">{{ doc.title }}</a>
        <span v-if="doc.import_source === 'manual_upload'" class="upload-badge">📎 手动上传</span>
      </h3>

      <!-- Authors + Country flags -->
      <p v-if="doc.authors" class="authors">
        {{ formatAuthors(doc.authors) }}
        <span v-if="doc.countries?.length" class="country-flags">
          <span
            v-for="cc in doc.countries.slice(0, 5)"
            :key="cc"
            class="flag"
            :title="cc"
          >{{ countryFlag(cc) }}</span>
        </span>
      </p>

      <!-- AI Summary -->
      <div v-if="doc.ai_summary || !roundDone" class="summary-panel">
        <div class="summary-head">
          <span class="ai-badge">AI</span>
          <span class="summary-label">智能摘要</span>
          <span v-if="doc.ai_summary_source === 'from_abstract'" class="src-tag">原文摘要</span>
          <span v-else-if="doc.ai_summary_source === 'from_title'" class="src-tag src-tag-warn">标题推断</span>
          <span v-if="isEdited('ai_summary')" class="edit-badge" title="你已手动编辑">✎</span>
          <div class="spacer" />
          <button v-if="doc.ai_summary && !editingSummary" class="inline-edit-btn" @click="startEditSummary" title="编辑摘要">✏️</button>
          <button
            v-if="isEdited('ai_summary') && !editingSummary"
            class="inline-edit-btn"
            title="重置为 AI 版"
            @click="resetField('ai_summary')"
          >↺</button>
        </div>
        <template v-if="doc.ai_summary && !editingSummary">
          <p class="summary-body" :class="{ collapsed: !expanded }">{{ doc.ai_summary }}</p>
          <button v-if="doc.ai_summary.length > 180" class="btn-expand" @click="expanded = !expanded">
            {{ expanded ? '收起' : '展开全文' }}
          </button>
          <div class="key-points-wrap">
            <div v-if="doc.ai_key_points?.length || editingKeyPoints" class="kp-head">
              <span class="kp-label">关键点</span>
              <span v-if="isEdited('ai_key_points')" class="edit-badge" title="你已手动编辑">✎</span>
              <button v-if="!editingKeyPoints" class="inline-edit-btn" @click="startEditKeyPoints" title="编辑关键点">✏️</button>
              <button
                v-if="isEdited('ai_key_points') && !editingKeyPoints"
                class="inline-edit-btn"
                title="重置为 AI 版"
                @click="resetField('ai_key_points')"
              >↺</button>
            </div>
            <div v-if="doc.ai_key_points?.length && !editingKeyPoints" class="key-points">
              <span v-for="(pt, i) in doc.ai_key_points" :key="i" class="kp">{{ pt }}</span>
            </div>
            <div v-if="editingKeyPoints" class="kp-edit">
              <el-input
                v-model="editKeyPointsText"
                type="textarea"
                :rows="4"
                placeholder="一行一点"
                size="small"
                resize="vertical"
              />
              <div class="kp-edit-actions">
                <el-button size="small" type="primary" :loading="savingField === 'ai_key_points'" @click="saveKeyPoints">保存</el-button>
                <el-button size="small" @click="cancelKeyPoints">取消</el-button>
                <span class="edit-hint">每行一个关键点</span>
              </div>
            </div>
          </div>
          <p v-if="doc.ai_relevance_reason" class="relevance">{{ doc.ai_relevance_reason }}</p>
          <p v-if="doc.agent_rationale" class="agent-rationale">AI 评分理由: {{ doc.agent_rationale }}</p>
        </template>
        <div v-else-if="editingSummary" class="summary-edit">
          <el-input
            v-model="editSummaryText"
            type="textarea"
            :rows="6"
            :maxlength="4000"
            show-word-limit
            resize="vertical"
          />
          <div class="summary-edit-actions">
            <el-button size="small" type="primary" :loading="savingField === 'ai_summary'" @click="saveSummary">保存</el-button>
            <el-button size="small" @click="cancelSummary">取消</el-button>
          </div>
        </div>
        <div v-else-if="!roundDone" class="generating">
          <span class="dot-pulse"><span/><span/><span/></span>
          AI 正在分析...
        </div>
      </div>
      <p v-else-if="roundDone" class="no-summary">暂无摘要信息</p>

      <!-- Bucket classification + Full-text action -->
      <div class="feedback-bar">
        <BucketDropZone
          :doc-id="doc.id"
          :current-bucket="doc.bucket || null"
          :card-el="cardRef"
          @classify="onClassify"
        />

        <!-- 一个入口按钮，所有格式细节进 FulltextViewer 内部 tab 切换 -->
        <div class="fulltext-actions">
          <!-- 空态：下载全文 -->
          <button
            v-if="fulltextStage === 'idle'"
            :disabled="!canDownloadAny"
            class="pill pill-dl"
            @click="$emit('download-fulltext', 'auto')"
            :title="canDownloadAny ? '同时尝试下载 PDF 和 HTML 快照' : '无可用源'"
          >下载全文</button>

          <!-- 下载进行中 -->
          <button
            v-else-if="fulltextStage === 'downloading'"
            class="pill pill-dl pill-loading"
            disabled
          ><span class="spinner"></span>正在下载...</button>

          <!-- 已尝试过下载就让"查看全文"一直可点：内部 viewer 的空态会提供上传/重试 -->
          <button
            v-else-if="fulltextStage === 'done'"
            class="pill"
            :class="anyFulltextAvailable ? 'pill-view' : 'pill-view-empty'"
            @click="$emit('view-fulltext', 'auto')"
            :title="anyFulltextAvailable ? '查看已下载的全文（PDF/HTML 分 tab）' : '打开查看页面（可在内部上传或重试下载）'"
          >{{ anyFulltextAvailable ? '✓ 查看全文' : '查看全文' }}</button>

          <!-- PDF 通道兜底上传：只要 PDF 没成功就给 -->
          <button
            v-if="fulltextStage === 'done' && pdfStatus !== 'available'"
            class="pill pill-upload-sec"
            @click="triggerUpload('pdf')"
            title="手动上传 PDF 文件"
          >↑ 上传 PDF</button>

          <!-- HTML 通道兜底上传：只要 HTML 没成功就给 -->
          <button
            v-if="fulltextStage === 'done' && htmlStatus !== 'available'"
            class="pill pill-upload-sec"
            @click="triggerUpload('html')"
            title="手动上传 HTML 文件"
          >↑ 上传 HTML</button>

          <!-- 外链始终可点：在新窗口打开原文页面 -->
          <a
            v-if="externalLink"
            class="pill pill-link"
            :href="externalLink"
            target="_blank"
            rel="noopener noreferrer"
            title="在新窗口打开原文页面"
          >原文 ↗</a>
        </div>

        <!-- Hidden file input：accept 由 pendingUploadFormat 决定 -->
        <input
          ref="fileInputRef"
          type="file"
          :accept="pendingUploadFormat === 'html' ? '.html,.htm,.mhtml,text/html' : 'application/pdf'"
          style="display:none"
          @change="onFileChosen"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import BucketDropZone from './bucket/BucketDropZone.vue'
import { ElMessage } from 'element-plus'
import { searchApi } from '../api/client'
import { useProjectStore } from '../stores/project'

const props = defineProps<{
  doc: any
  initialFeedback?: number | null
  roundStatus?: string
}>()
type FulltextFormat = 'pdf' | 'html' | 'auto'
const emit = defineEmits<{
  (e: 'feedback', v: number): void
  (e: 'classify', bucket: string): void
  (e: 'download-fulltext', format: FulltextFormat): void
  (e: 'view-fulltext', format: FulltextFormat): void
  (e: 'upload-fulltext', payload: { format: 'pdf' | 'html'; file: File }): void
  (e: 'doc-updated', payload: { id: string; patch: Record<string, any> }): void
}>()

// —— 卡片字段编辑（双字段 _user/_ai 策略）——
const projectStore = useProjectStore()
const editingOneLiner = ref(false)
const editingSummary = ref(false)
const editingKeyPoints = ref(false)
const editOneLinerText = ref('')
const editSummaryText = ref('')
const editKeyPointsText = ref('')
const savingField = ref<string | null>(null)

function isEdited(field: string): boolean {
  const arr = props.doc.user_edited_fields
  return Array.isArray(arr) && arr.includes(field)
}

async function _patch(updates: Record<string, any>, fieldName: string) {
  const pid = projectStore.current?.id
  if (!pid) {
    ElMessage.error('未知项目上下文，无法保存')
    return
  }
  savingField.value = fieldName
  try {
    const res = await searchApi.updateDocument(String(pid), String(props.doc.id), updates)
    emit('doc-updated', { id: String(props.doc.id), patch: res.data })
    ElMessage.success('已保存')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    savingField.value = null
  }
}

function startEditOneLiner() {
  editOneLinerText.value = props.doc.one_line_summary || ''
  editingOneLiner.value = true
}
function cancelOneLiner() { editingOneLiner.value = false }
async function saveOneLiner() {
  const v = editOneLinerText.value.trim()
  await _patch({ one_line_summary: v }, 'one_line_summary')
  editingOneLiner.value = false
}

function startEditSummary() {
  editSummaryText.value = props.doc.ai_summary || ''
  editingSummary.value = true
}
function cancelSummary() { editingSummary.value = false }
async function saveSummary() {
  const v = editSummaryText.value.trim()
  await _patch({ ai_summary: v }, 'ai_summary')
  editingSummary.value = false
}

function startEditKeyPoints() {
  const arr = props.doc.ai_key_points || []
  editKeyPointsText.value = arr.join('\n')
  editingKeyPoints.value = true
}
function cancelKeyPoints() { editingKeyPoints.value = false }
async function saveKeyPoints() {
  const lines = editKeyPointsText.value
    .split('\n')
    .map((s) => s.trim())
    .filter((s) => s.length > 0)
  await _patch({ ai_key_points: lines }, 'ai_key_points')
  editingKeyPoints.value = false
}

async function resetField(field: 'one_line_summary' | 'ai_summary' | 'ai_key_points') {
  const resetPayload: Record<string, any> = {}
  // 空字符串 / 空数组 = 清 _user 回到 AI 版
  resetPayload[field] = field === 'ai_key_points' ? [] : ''
  await _patch(resetPayload, field)
}
const roundDone = computed(() => ['awaiting_feedback', 'completed'].includes(props.roundStatus ?? ''))
const expanded = ref(false)
const cardRef = ref<HTMLElement>()
const localFeedback = ref<number | null>(props.initialFeedback ?? null)
const fileInputRef = ref<HTMLInputElement | null>(null)

// PDF 通道可下载：有 pdf_url 或 DOI（后端会尝试解析 citation_pdf_url）；
// patenthub 专利走三段式付费接口，凭 external_id 即可（搜索接口不返 pdf_url/doi）
const canDownloadPdf = computed(() =>
  !!props.doc.pdf_url
  || !!props.doc.doi
  || (props.doc.source === 'patenthub' && !!props.doc.external_id)
)
// HTML 通道可下载：有 landing url 即可（doc.url 或 doi）
const canDownloadHtml = computed(() => !!props.doc.url || !!props.doc.doi)
// 任一源存在 → 可以点"下载全文"
const canDownloadAny = computed(() => canDownloadPdf.value || canDownloadHtml.value)

// 通道状态：优先读新字段，fallback 到旧聚合字段（老数据兼容）
const pdfStatus = computed<string>(() => {
  const s = props.doc.fulltext_pdf_status
  if (s && s !== 'not_attempted') return s
  // 老数据兼容：如果 fulltext_path 是 .pdf 且 status=available，视为 pdf available
  if (props.doc.fulltext_status === 'available'
      && (props.doc.fulltext_path || '').toLowerCase().endsWith('.pdf')) {
    return 'available'
  }
  return s || 'not_attempted'
})
const htmlStatus = computed<string>(() => {
  const s = props.doc.fulltext_html_status
  if (s && s !== 'not_attempted') return s
  const p = (props.doc.fulltext_path || '').toLowerCase()
  if (props.doc.fulltext_status === 'available' && (p.endsWith('.html') || p.endsWith('.htm'))) {
    return 'available'
  }
  return s || 'not_attempted'
})

// 聚合阶段：idle(两通道全 not_attempted) / downloading(任一通道在下载) / done(其它)
const fulltextStage = computed<'idle' | 'downloading' | 'done'>(() => {
  const p = pdfStatus.value
  const h = htmlStatus.value
  if (p === 'downloading' || h === 'downloading') return 'downloading'
  if (p === 'not_attempted' && h === 'not_attempted') return 'idle'
  return 'done'
})

// 任一通道可用 → 可以点"查看全文"
const anyFulltextAvailable = computed(
  () => pdfStatus.value === 'available' || htmlStatus.value === 'available'
)

// 兜底外链：DOI/原始 URL/PDF URL — 点击新窗口打开
// 手动上传（无 url/doi）→ 指向后端原始文件下载端点（含 token query）
const externalLink = computed<string | null>(() => {
  const d = props.doc
  if (d?.url) return d.url
  if (d?.pdf_url) return d.pdf_url
  if (d?.doi) return `https://doi.org/${d.doi}`
  if (d?.import_source === 'manual_upload' && d?.id) {
    const token = localStorage.getItem('urip_token') || ''
    return `/api/documents/${d.id}/original-pdf${token ? `?token=${encodeURIComponent(token)}` : ''}`
  }
  return null
})

const pendingUploadFormat = ref<'pdf' | 'html'>('pdf')
function triggerUpload(format: 'pdf' | 'html') {
  pendingUploadFormat.value = format
  fileInputRef.value?.click()
}

function onFileChosen(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) emit('upload-fulltext', { format: pendingUploadFormat.value, file })
  input.value = ''
}

watch(() => props.initialFeedback, v => { localFeedback.value = v ?? null })

function onClassify(bucket: string) {
  // 映射 bucket -> legacy feedback 值（兼容）
  const map: Record<string, number> = { very_relevant: 2, relevant: 1, uncertain: 0, irrelevant: -1 }
  localFeedback.value = map[bucket] ?? 0
  emit('classify', bucket)
  emit('feedback', map[bucket] ?? 0)
}

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
const scoreClass = computed(() => {
  const s = props.doc.agent_score
  if (s == null) return ''
  if (s >= 9) return 'score-top'
  if (s >= 7) return 'score-high'
  if (s >= 5) return 'score-mid'
  return 'score-low'
})
function formatDate(d: string) { return d ? d.slice(0, 7) : '' }
function formatAuthors(a: any) {
  if (Array.isArray(a)) { const n = a.slice(0,3).map((x:any) => x.name||x).join(', '); return a.length > 3 ? n+` 等${a.length}人` : n }
  return String(a)
}
function countryFlag(code: string): string {
  return code.toUpperCase().split('').map(c =>
    String.fromCodePoint(0x1F1E6 + c.charCodeAt(0) - 65)
  ).join('')
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
.doc-card.below-cutoff { opacity: 0.45; border-style: dashed; }

/* ── Binding (left accent bar — like a journal spine) ── */
.binding { width: 4px; flex-shrink: 0; transition: width var(--duration-fast); }
.doc-card:hover .binding { width: 5px; }
.a-blue  { background: linear-gradient(180deg, var(--signal-blue), var(--signal-blue-light)); }
.a-amber { background: linear-gradient(180deg, var(--signal-amber), var(--signal-amber-light)); }
.a-teal  { background: linear-gradient(180deg, var(--signal-teal), var(--signal-teal-light)); }
.a-coral { background: linear-gradient(180deg, var(--signal-coral), #f87171); }
.a-slate { background: linear-gradient(180deg, var(--ink-400), var(--ink-300)); }

.card-inner { flex: 1; padding: 18px 22px; min-width: 0; }

/* ── Meta row ── */
.meta-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; gap: 8px; }
.badges { display: flex; gap: 5px; flex-wrap: wrap; }
.badge {
  font-size: 10px; font-weight: 700; letter-spacing: 0.04em;
  padding: 2px 9px; border-radius: var(--radius-full); color: #fff;
}
.badge.a-blue { background: var(--signal-blue); } .badge.a-amber { background: var(--signal-amber); color: #fff; }
.badge.a-teal { background: var(--signal-teal); } .badge.a-coral { background: var(--signal-coral); }
.badge.a-slate { background: var(--ink-400); }
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

.authors { font-size: 12px; color: var(--ink-400); margin: 0 0 12px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.country-flags { display: inline-flex; gap: 2px; }
.flag { font-size: 14px; cursor: default; }

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

/* ── Agent score badge ── */
.badge-score { font-weight: 800; letter-spacing: 0; }
.score-top { background: var(--signal-teal); color: #fff; }
.score-high { background: #2563eb; color: #fff; }
.score-mid { background: #d97706; color: #fff; }
.score-low { background: var(--ink-300); color: #fff; }

/* ── One-line summary ── */
.one-liner {
  font-size: 13px; font-weight: 600; color: var(--signal-teal);
  margin: 0 0 4px; line-height: 1.5;
  padding: 4px 10px; border-radius: var(--radius-sm);
  background: var(--signal-teal-bg);
}

/* ── Agent rationale ── */
.agent-rationale {
  font-size: 12px; color: var(--ink-500); margin: 6px 0 0;
  font-style: italic;
}

/* ── Full-text action buttons ── */
/* 整组下载/查看按钮始终贴在文献卡片右侧 */
.fulltext-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.pill-dl {
  background: rgba(59,130,246,0.08); border-color: rgba(59,130,246,0.25);
  color: #3b82f6; font-size: 11px;
}
.pill-dl:hover { background: rgba(59,130,246,0.15); }
.pill-dl:disabled { opacity: 0.5; cursor: default; }
.pill-loading {
  display: inline-flex !important;
  align-items: center;
  gap: 6px;
  background: rgba(59,130,246,0.12) !important;
  border-color: rgba(59,130,246,0.35) !important;
  color: #1e40af !important;
  opacity: 0.95 !important;
  animation: pill-pulse 1.6s ease-in-out infinite;
}
.spinner {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(59,130,246,0.25);
  border-top-color: #3b82f6;
  border-radius: 50%;
  display: inline-block;
  animation: spinner-rotate 0.8s linear infinite;
  flex-shrink: 0;
}
@keyframes spinner-rotate {
  to { transform: rotate(360deg); }
}
@keyframes pill-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(59,130,246,0); }
  50% { box-shadow: 0 0 0 4px rgba(59,130,246,0.15); }
}
.pill-view {
  /* 不再 margin-left: auto — 统一由 .fulltext-actions 推到右边 */
  background: var(--signal-teal-bg); border-color: rgba(13,148,136,0.3);
  color: var(--signal-teal); font-weight: 600; font-size: 11px;
}
.pill-view:hover { background: rgba(13,148,136,0.15); }
.pill-view-empty {
  background: rgba(100,116,139,0.06); border-color: rgba(100,116,139,0.25);
  color: #64748b; font-size: 11px;
}
.pill-view-empty:hover { background: rgba(100,116,139,0.15); color: #1e293b; }
.pill-view-html {
  background: rgba(14,165,233,0.10); border-color: rgba(14,165,233,0.3);
  color: #0ea5e9;
}
.pill-view-html:hover { background: rgba(14,165,233,0.18); }
.pill-dl-html {
  background: rgba(14,165,233,0.06); border-color: rgba(14,165,233,0.25);
  color: #0ea5e9;
}
.pill-dl-html:hover { background: rgba(14,165,233,0.15); }
.pill-retry {
  background: rgba(220,38,38,0.08) !important;
  border-color: rgba(220,38,38,0.3) !important;
  color: #dc2626 !important;
}
.pill-retry:hover { background: rgba(220,38,38,0.15) !important; }
.pill-upload {
  background: rgba(168,85,247,0.08); border-color: rgba(168,85,247,0.3);
  color: #9333ea; font-weight: 600; font-size: 11px;
}
.pill-upload:hover { background: rgba(168,85,247,0.15); }
.pill-upload-sec {
  background: rgba(168,85,247,0.06); border-color: rgba(168,85,247,0.2);
  color: #9333ea; font-size: 11px;
}
.pill-upload-sec:hover { background: rgba(168,85,247,0.12); }
.pill-link {
  background: rgba(100,116,139,0.08); border: 1.5px solid rgba(100,116,139,0.3);
  color: #475569; font-size: 11px; text-decoration: none;
  display: inline-flex; align-items: center;
  padding: 4px 13px; border-radius: var(--radius-full);
  font-weight: 500; cursor: pointer;
  font-family: var(--font-body);
  transition: all var(--duration-fast);
}
.pill-link:hover {
  background: rgba(100,116,139,0.16); border-color: rgba(100,116,139,0.5);
  color: #1e293b;
}

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

/* ── 卡片字段编辑 UI ── */
.one-liner-wrap { margin: 0 0 4px; }
.one-liner .inline-edit-btn,
.summary-head .inline-edit-btn,
.kp-head .inline-edit-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 12px;
  opacity: 0.45;
  padding: 0 2px;
  transition: opacity 0.15s;
  line-height: 1;
}
.one-liner:hover .inline-edit-btn,
.summary-head:hover .inline-edit-btn,
.kp-head:hover .inline-edit-btn,
.inline-edit-btn:hover { opacity: 1; }
.edit-badge {
  display: inline-block;
  font-size: 10px;
  padding: 0 4px;
  border-radius: 3px;
  background: rgba(245, 158, 11, 0.18);
  color: #b45309;
  font-weight: 600;
  margin-left: 4px;
  vertical-align: middle;
}
.edit-inline {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 4px 0;
}
.edit-inline .el-input { flex: 1; }
.summary-edit { padding: 6px 0; }
.summary-edit-actions { margin-top: 6px; display: flex; gap: 6px; }
.kp-edit { margin-top: 6px; }
.kp-edit-actions {
  margin-top: 4px;
  display: flex;
  gap: 6px;
  align-items: center;
}
.edit-hint {
  font-size: 11px;
  color: var(--ink-400, #94a3b8);
  margin-left: auto;
  font-style: italic;
}
.kp-head {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 10px;
  margin-bottom: 2px;
}
.kp-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-500, #64748b);
}
.summary-head .spacer { flex: 1; }

/* ── Manual upload badge ── */
.upload-badge {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  background: #fef6ec;
  color: #b88230;
  border-radius: 10px;
  margin-left: 6px;
  font-weight: normal;
  vertical-align: middle;
}
</style>
