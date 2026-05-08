<template>
  <div class="fulltext-viewer">
    <div v-if="!doc" class="placeholder">
      <el-icon :size="48" color="#c0c4cc"><Document /></el-icon>
      <p>未选择文献</p>
    </div>

    <template v-else>
      <header class="ft-head">
        <div class="ft-badges">
          <span class="ft-badge">{{ doc.source || '未知源' }}</span>
          <span v-if="doc.doc_type" class="ft-badge ft-badge-outline">{{ doc.doc_type }}</span>
          <span v-if="doc.publication_date" class="ft-date">{{ formatDate(doc.publication_date) }}</span>
          <span v-if="doc.fulltext_status === 'available'" class="ft-badge ft-badge-ok">全文可用</span>
        </div>
        <h2 class="ft-title">{{ doc.title }}</h2>
        <p v-if="doc.authors" class="ft-authors">{{ formatAuthors(doc.authors) }}</p>
        <div class="ft-links">
          <a v-if="doc.url" :href="doc.url" target="_blank" rel="noopener" class="ft-link">
            <el-icon><Link /></el-icon> 原文页面
          </a>
          <a v-if="pdfUrl" :href="pdfUrl" target="_blank" rel="noopener" class="ft-link">
            <el-icon><Download /></el-icon> 打开 PDF
          </a>
          <a v-if="doc.doi" :href="`https://doi.org/${doc.doi}`" target="_blank" rel="noopener" class="ft-link">
            DOI: {{ doc.doi }}
          </a>
        </div>
      </header>

      <div class="ft-body">
        <!-- Tabs: PDF 全文 | HTML | AI 摘要 + 关键点 | 原始摘要
             PDF/HTML tab 只要"有源"就显示，内容区在已下载时 iframe，未下载时显示重试按钮 -->
        <div class="ft-tabs">
          <button
            :class="{ active: viewMode === 'pdf' }"
            @click="viewMode = 'pdf'"
          >📄 PDF 全文 <span v-if="pdfStatus !== 'available'" class="tab-badge">{{ tabBadge(pdfStatus) }}</span></button>
          <button
            :class="{ active: viewMode === 'html' }"
            @click="viewMode = 'html'"
          >🌐 HTML <span v-if="htmlStatus !== 'available'" class="tab-badge">{{ tabBadge(htmlStatus) }}</span></button>
          <button
            :class="{ active: viewMode === 'summary' }"
            @click="viewMode = 'summary'"
          >AI 摘要 + 关键点</button>
          <button
            v-if="doc.abstract"
            :class="{ active: viewMode === 'abstract' }"
            @click="viewMode = 'abstract'"
          >原始摘要</button>

          <div class="ft-tabs-right">
            <el-button size="small" type="primary" plain @click="showRegenerateDialog = true">
              <el-icon><Refresh /></el-icon>
              让 AI 重新分析
            </el-button>
          </div>
        </div>

        <!-- PDF tab 内容 -->
        <div v-if="viewMode === 'pdf'" class="ft-pdf">
          <div v-if="pdfUrl" class="ft-pdf-inner">
            <iframe :src="pdfUrl" frameborder="0" class="ft-iframe" />
            <p class="ft-hint">
              如 PDF 无法加载，请
              <a :href="pdfUrl" target="_blank" rel="noopener">点此新窗口打开</a>
            </p>
          </div>
          <div v-else class="ft-empty">
            <div class="ft-empty__icon">📄</div>
            <div class="ft-empty__text">{{ statusText(pdfStatus, 'PDF') }}</div>
            <div class="ft-empty__actions">
              <el-button
                type="primary"
                :loading="retrying === 'pdf'"
                :disabled="!canDownloadPdf"
                @click="retryDownload('pdf')"
              >
                {{ pdfStatus === 'failed' ? '重试下载 PDF' : '下载 PDF' }}
              </el-button>
              <el-button
                :loading="uploading === 'pdf'"
                @click="triggerUpload('pdf')"
                title="本地选择一个 PDF 文件作为兜底"
              >↑ 上传 PDF</el-button>
            </div>
            <p class="ft-empty__hint">下载失败或没有可用源时，可手动上传一份 PDF 兜底</p>
          </div>
        </div>

        <!-- HTML tab 内容 —— 和 PDF 并列 tab -->
        <div v-else-if="viewMode === 'html'" class="ft-pdf">
          <div v-if="htmlUrl" class="ft-pdf-inner">
            <iframe :src="htmlUrl" frameborder="0" class="ft-iframe" />
            <p class="ft-hint">
              HTML 快照来自原文 landing page。
              <a :href="htmlUrl" target="_blank" rel="noopener">新窗口打开</a>
            </p>
          </div>
          <div v-else class="ft-empty">
            <div class="ft-empty__icon">🌐</div>
            <div class="ft-empty__text">{{ statusText(htmlStatus, 'HTML') }}</div>
            <div class="ft-empty__actions">
              <el-button
                type="primary"
                :loading="retrying === 'html'"
                :disabled="!canDownloadHtml"
                @click="retryDownload('html')"
              >
                {{ htmlStatus === 'failed' ? '重试下载 HTML' : '下载 HTML' }}
              </el-button>
              <el-button
                :loading="uploading === 'html'"
                @click="triggerUpload('html')"
                title="本地选择一个 HTML 文件作为兜底"
              >↑ 上传 HTML</el-button>
            </div>
            <p class="ft-empty__hint">下载失败或没有可用源时，可手动上传一份 HTML 兜底</p>
          </div>
        </div>

        <!-- AI summary (editable) -->
        <div v-else-if="viewMode === 'summary'" class="ft-summary-area">
          <!-- 一句话总结 -->
          <div class="ft-sec">
            <div class="ft-sec-head">
              <h4>一句话总结</h4>
              <button v-if="!editing.one_liner" class="ft-btn-edit" @click="startEdit('one_liner')">编辑</button>
            </div>
            <p v-if="!editing.one_liner" class="ft-sec-content">
              {{ doc.one_line_summary || '（暂无）' }}
            </p>
            <div v-else class="ft-edit-area">
              <el-input v-model="editValues.one_liner" size="small" />
              <div class="ft-edit-actions">
                <el-button size="small" @click="cancelEdit('one_liner')">取消</el-button>
                <el-button size="small" type="primary" :loading="saving.one_liner" @click="saveEdit('one_liner')">保存</el-button>
              </div>
            </div>
          </div>

          <!-- AI 摘要 -->
          <div class="ft-sec">
            <div class="ft-sec-head">
              <h4>AI 智能摘要</h4>
              <span v-if="doc.ai_summary_source" class="ft-sec-tag">
                {{ summarySourceLabel }}
              </span>
              <button v-if="!editing.ai_summary" class="ft-btn-edit" @click="startEdit('ai_summary')">编辑</button>
            </div>
            <p v-if="!editing.ai_summary" class="ft-sec-content">
              {{ doc.ai_summary || '（暂无）' }}
            </p>
            <div v-else class="ft-edit-area">
              <el-input
                v-model="editValues.ai_summary"
                type="textarea"
                :rows="6"
                resize="vertical"
              />
              <div class="ft-edit-actions">
                <el-button size="small" @click="cancelEdit('ai_summary')">取消</el-button>
                <el-button size="small" type="primary" :loading="saving.ai_summary" @click="saveEdit('ai_summary')">保存</el-button>
              </div>
            </div>
          </div>

          <!-- Key points -->
          <div v-if="doc.ai_key_points?.length || editing.ai_key_points" class="ft-sec">
            <div class="ft-sec-head">
              <h4>关键点</h4>
              <button v-if="!editing.ai_key_points" class="ft-btn-edit" @click="startEdit('ai_key_points')">编辑</button>
            </div>
            <div v-if="!editing.ai_key_points" class="ft-kp">
              <span v-for="(pt, i) in doc.ai_key_points || []" :key="i" class="kp">{{ pt }}</span>
            </div>
            <div v-else class="ft-edit-area">
              <el-input
                v-model="editValues.ai_key_points"
                type="textarea"
                :rows="4"
                placeholder="每行一个关键点"
                resize="vertical"
              />
              <div class="ft-edit-actions">
                <el-button size="small" @click="cancelEdit('ai_key_points')">取消</el-button>
                <el-button size="small" type="primary" :loading="saving.ai_key_points" @click="saveEdit('ai_key_points')">保存</el-button>
              </div>
            </div>
          </div>

          <!-- Relevance reason -->
          <div v-if="doc.ai_relevance_reason" class="ft-sec">
            <div class="ft-sec-head"><h4>与项目相关性</h4></div>
            <p class="ft-sec-content ft-relevance">{{ doc.ai_relevance_reason }}</p>
          </div>
        </div>

        <!-- Raw abstract -->
        <div v-else-if="viewMode === 'abstract'" class="ft-summary-area">
          <div class="ft-sec">
            <h4>原始摘要（英文或原文）</h4>
            <p class="ft-sec-content">{{ doc.abstract || '（暂无）' }}</p>
          </div>
        </div>

        <!-- 隐藏 file input：accept 由 pendingUploadFormat 决定。放在所有 v-else-if 之后避免打断 if 链条 -->
        <input
          ref="ftUploadInputRef"
          type="file"
          :accept="pendingUploadFormat === 'html' ? '.html,.htm,.mhtml,text/html' : 'application/pdf'"
          style="display:none"
          @change="onFileChosen"
        />
      </div>
    </template>

    <!-- Regenerate dialog -->
    <el-dialog
      v-model="showRegenerateDialog"
      title="让 AI 重新分析"
      width="500px"
      :close-on-click-modal="false"
    >
      <p style="font-size:13px;color:#606266;margin:0 0 12px">
        AI 将基于<strong>{{ doc?.fulltext_text ? '已下载的全文' : '摘要' }}</strong>重新生成摘要和关键点。
        您可以给出方向提示，AI 会重点关注：
      </p>
      <el-input
        v-model="regenerateHint"
        type="textarea"
        :rows="3"
        placeholder="例如：重点关注实验方法和数据集规模，或留空让 AI 自由发挥"
      />
      <template #footer>
        <el-button @click="showRegenerateDialog = false">取消</el-button>
        <el-button type="primary" :loading="regenerating" @click="handleRegenerate">
          开始分析
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive } from 'vue'
import { Document, Link, Download, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { searchApi } from '../api/client'
import { downloadFulltextWithBudgetConfirm } from '../utils/patenthubBudget'
import { useSearchStore } from '../stores/search'

const searchStore = useSearchStore()

const props = defineProps<{
  doc: any
  projectId: string
  initialFormat?: 'pdf' | 'html' | 'auto'
}>()

const emit = defineEmits<{
  (e: 'updated', doc: any): void
}>()

const viewMode = ref<'pdf' | 'html' | 'summary' | 'abstract'>('summary')

// ── 双通道状态（优先读新字段，老数据按 fulltext_path 后缀 fallback）──
const pdfStatus = computed<string>(() => {
  if (!props.doc) return 'not_attempted'
  const s = props.doc.fulltext_pdf_status
  if (s && s !== 'not_attempted') return s
  const p = (props.doc.fulltext_path || '').toLowerCase()
  if (props.doc.fulltext_status === 'available' && p.endsWith('.pdf')) return 'available'
  return s || 'not_attempted'
})
const htmlStatus = computed<string>(() => {
  if (!props.doc) return 'not_attempted'
  const s = props.doc.fulltext_html_status
  if (s && s !== 'not_attempted') return s
  const p = (props.doc.fulltext_path || '').toLowerCase()
  if (props.doc.fulltext_status === 'available' && (p.endsWith('.html') || p.endsWith('.htm'))) return 'available'
  return s || 'not_attempted'
})

// 是否有源可下载
// patenthub 专利走后端三段式付费接口（详情→pdfList→PDF），凭 external_id 即可，
// 不需要 pdf_url / doi（搜索接口压根不返）
const canDownloadPdf = computed(() =>
  !!props.doc?.pdf_url
  || !!props.doc?.doi
  || (props.doc?.source === 'patenthub' && !!props.doc?.external_id)
)
const canDownloadHtml = computed(() => !!props.doc?.url || !!props.doc?.doi)

// 构造带 token + format query 的文件流 URL
function fileUrlFor(format: 'pdf' | 'html'): string | null {
  if (!props.doc?.id || !props.projectId) return null
  const token = localStorage.getItem('urip_token') || ''
  const qs = new URLSearchParams()
  qs.set('format', format)
  if (token) qs.set('token', token)
  return `/api/projects/${props.projectId}/documents/${props.doc.id}/file?${qs.toString()}`
}
const pdfUrl = computed(() => pdfStatus.value === 'available' ? fileUrlFor('pdf') : null)
const htmlUrl = computed(() => htmlStatus.value === 'available' ? fileUrlFor('html') : null)

const externalLink = computed(() => {
  if (!props.doc) return null
  return props.doc.url || props.doc.pdf_url || (props.doc.doi ? `https://doi.org/${props.doc.doi}` : null)
})

// tab 标签上的小徽标（失败/未下载/下载中）
function tabBadge(status: string): string {
  if (status === 'downloading') return '下载中'
  if (status === 'failed') return '失败'
  if (status === 'not_attempted') return '未下载'
  return ''
}
function statusText(status: string, kind: string): string {
  if (status === 'downloading') return `${kind} 正在下载中，稍候会自动刷新`
  if (status === 'failed') return `${kind} 之前下载失败，点击重试`
  return `本文献尚未下载 ${kind} 全文`
}

// 上传兜底 state
const ftUploadInputRef = ref<HTMLInputElement | null>(null)
const pendingUploadFormat = ref<'pdf' | 'html'>('pdf')
const uploading = ref<'pdf' | 'html' | ''>('')

function triggerUpload(format: 'pdf' | 'html') {
  pendingUploadFormat.value = format
  ftUploadInputRef.value?.click()
}

async function onFileChosen(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !props.doc?.id || !props.projectId) return
  const fmt = pendingUploadFormat.value
  uploading.value = fmt
  try {
    await searchApi.uploadFulltext(String(props.projectId), String(props.doc.id), file, fmt)
    ElMessage.success(`✓ ${fmt.toUpperCase()} 上传成功`)
    if (props.doc) {
      const statusField = fmt === 'pdf' ? 'fulltext_pdf_status' : 'fulltext_html_status'
      props.doc[statusField] = 'available'
      props.doc.fulltext_status = 'available'
    }
    // 刷新 store 拿到 path 字段，让 iframe 能立即指向新文件
    const roundId = searchStore.currentRound?.id
    if (roundId) {
      try {
        await searchStore.loadRoundResults(roundId)
        const fresh = searchStore.documents.find((d: any) => String(d.id) === String(props.doc.id)) as any
        if (fresh) Object.assign(props.doc, {
          fulltext_pdf_path: fresh.fulltext_pdf_path,
          fulltext_pdf_status: fresh.fulltext_pdf_status,
          fulltext_html_path: fresh.fulltext_html_path,
          fulltext_html_status: fresh.fulltext_html_status,
          fulltext_status: fresh.fulltext_status,
          fulltext_path: fresh.fulltext_path,
          fulltext_text: fresh.fulltext_text,
        })
      } catch { /* ignore */ }
    }
    viewMode.value = fmt
    emit('updated', props.doc)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || `${fmt.toUpperCase()} 上传失败`)
  } finally {
    uploading.value = ''
  }
}

// 重试/首次下载某个通道
const retrying = ref<'pdf' | 'html' | ''>('')
async function retryDownload(format: 'pdf' | 'html') {
  if (!props.doc?.id || !props.projectId) return
  retrying.value = format
  try {
    await downloadFulltextWithBudgetConfirm(props.projectId, props.doc.id, format)
    ElMessage.info(`${format.toUpperCase()} 下载已加入队列`)
    const statusField = format === 'pdf' ? 'fulltext_pdf_status' : 'fulltext_html_status'
    const pathField = format === 'pdf' ? 'fulltext_pdf_path' : 'fulltext_html_path'
    if (props.doc) props.doc[statusField] = 'downloading'
    for (let i = 0; i < 40; i++) {
      await new Promise((r) => setTimeout(r, 3000))
      try {
        const roundId = searchStore.currentRound?.id
        if (!roundId) break
        await searchStore.loadRoundResults(roundId)
        const fresh = searchStore.documents.find((d: any) => String(d.id) === String(props.doc.id)) as any
        if (!fresh) continue
        Object.assign(props.doc, {
          [statusField]: fresh[statusField],
          [pathField]: fresh[pathField],
          fulltext_status: fresh.fulltext_status,
          fulltext_path: fresh.fulltext_path,
          fulltext_text: fresh.fulltext_text,
        })
        if (fresh[statusField] === 'available') {
          ElMessage.success(`${format.toUpperCase()} 下载完成`)
          emit('updated', props.doc)
          return
        }
        if (fresh[statusField] === 'failed') {
          ElMessage.error(`${format.toUpperCase()} 下载失败，可再次重试`)
          return
        }
      } catch { /* keep polling */ }
    }
    ElMessage.warning(`${format.toUpperCase()} 下载超时，后端仍在执行，请刷新查看`)
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    ElMessage.error(typeof detail === 'string' ? detail : `${format.toUpperCase()} 触发失败`)
  } finally {
    retrying.value = ''
  }
}

// 初始 viewMode：按 initialFormat 显式意图 → 已下载的格式 → 默认 PDF tab（即使空态也展示上传/重试）
const initViewMode = () => {
  const fmt = props.initialFormat
  if (fmt === 'pdf') { viewMode.value = 'pdf'; return }
  if (fmt === 'html') { viewMode.value = 'html'; return }
  if (pdfUrl.value) viewMode.value = 'pdf'
  else if (htmlUrl.value) viewMode.value = 'html'
  else viewMode.value = 'pdf'  // 双失败也默认进 PDF tab，让用户看到空态 + 上传按钮
}
initViewMode()

const summarySourceLabel = computed(() => {
  const m: Record<string, string> = {
    from_fulltext: '基于全文',
    from_abstract: '基于摘要',
    from_title: '仅标题推断',
  }
  return m[props.doc?.ai_summary_source] || props.doc?.ai_summary_source || ''
})

// ── Edit state ──
type EditField = 'one_liner' | 'ai_summary' | 'ai_key_points'
const editing = reactive<Record<EditField, boolean>>({
  one_liner: false,
  ai_summary: false,
  ai_key_points: false,
})
const editValues = reactive<Record<EditField, string>>({
  one_liner: '',
  ai_summary: '',
  ai_key_points: '',
})
const saving = reactive<Record<EditField, boolean>>({
  one_liner: false,
  ai_summary: false,
  ai_key_points: false,
})

function startEdit(field: EditField) {
  if (field === 'ai_key_points') {
    editValues[field] = (props.doc?.ai_key_points || []).join('\n')
  } else if (field === 'one_liner') {
    editValues[field] = props.doc?.one_line_summary || ''
  } else {
    editValues[field] = props.doc?.[field] || ''
  }
  editing[field] = true
}

function cancelEdit(field: EditField) {
  editing[field] = false
  editValues[field] = ''
}

async function saveEdit(field: EditField) {
  if (!props.doc || !props.projectId) return
  saving[field] = true
  try {
    let updates: Record<string, any> = {}
    if (field === 'ai_key_points') {
      updates.ai_key_points = editValues[field].split('\n').map(s => s.trim()).filter(Boolean)
    } else if (field === 'one_liner') {
      updates.one_line_summary = editValues[field]
    } else {
      updates[field] = editValues[field]
    }
    const res = await searchApi.updateDocument(props.projectId, props.doc.id, updates)
    // 本地同步（乐观更新）
    Object.assign(props.doc, updates)
    editing[field] = false
    ElMessage.success('已保存')
    emit('updated', props.doc)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving[field] = false
  }
}

// ── Regenerate ──
const showRegenerateDialog = ref(false)
const regenerateHint = ref('')
const regenerating = ref(false)

async function handleRegenerate() {
  if (!props.doc || !props.projectId) return
  regenerating.value = true
  try {
    const res = await searchApi.regenerateAnalysis(props.projectId, props.doc.id, regenerateHint.value.trim() || undefined)
    // 合并返回到 doc
    Object.assign(props.doc, {
      ai_summary: res.data.ai_summary,
      ai_key_points: res.data.ai_key_points,
      ai_relevance_reason: res.data.ai_relevance_reason,
      ai_summary_source: res.data.ai_summary_source,
    })
    showRegenerateDialog.value = false
    regenerateHint.value = ''
    viewMode.value = 'summary'
    ElMessage.success('AI 分析已更新')
    emit('updated', props.doc)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || 'AI 重新分析失败')
  } finally {
    regenerating.value = false
  }
}

function formatDate(d: string) {
  return d ? d.slice(0, 10) : ''
}

function formatAuthors(a: any): string {
  if (Array.isArray(a)) {
    const names = a.slice(0, 5).map((x: any) => x.name || x).join(', ')
    return a.length > 5 ? `${names} 等 ${a.length} 人` : names
  }
  return String(a || '')
}
</script>

<style scoped>
.fulltext-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--paper);
}
.placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--ink-400);
}

/* ── Header ── */
.ft-head {
  padding: 20px 24px 14px;
  border-bottom: 1px solid var(--ink-200);
  flex-shrink: 0;
}
.ft-badges {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.ft-badge {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 10px;
  border-radius: 99px;
  background: var(--signal-teal);
  color: var(--paper);
}
.ft-badge-outline {
  background: transparent;
  color: var(--ink-500);
  border: 1px solid var(--ink-200);
}
.ft-badge-ok {
  background: var(--signal-emerald-bg);
  color: var(--signal-teal);
}
.ft-date { font-size: 12px; color: var(--ink-400); }
.ft-title {
  font-size: 20px;
  font-weight: 700;
  color: var(--ink-800);
  margin: 0 0 8px;
  line-height: 1.4;
}
.ft-authors {
  font-size: 13px;
  color: var(--ink-500);
  margin: 0 0 10px;
}
.ft-links {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}
.ft-link {
  font-size: 12px;
  color: var(--signal-teal);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.ft-link:hover { text-decoration: underline; }

/* ── Body ── */
.ft-body {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.ft-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 10px 24px 0;
  border-bottom: 1px solid var(--ink-200);
  flex-shrink: 0;
}
.ft-tabs button {
  background: none;
  border: none;
  padding: 10px 16px;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-500);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
}
.ft-tabs button:hover { color: var(--signal-teal); }
.ft-tabs button.active {
  color: var(--signal-teal);
  border-bottom-color: var(--signal-teal);
}
.ft-tabs-right {
  margin-left: auto;
  padding-bottom: 6px;
}

.ft-pdf {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 12px 24px;
  min-height: 0;
}
.ft-pdf-inner {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.ft-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 40px 20px;
  color: var(--ink-300);
  text-align: center;
}
.ft-empty__icon {
  font-size: 48px;
  opacity: 0.5;
}
.ft-empty__text {
  font-size: 14px;
  color: var(--ink-400);
  margin-bottom: 4px;
}
.ft-empty__actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
}
.ft-empty__hint {
  font-size: 11px;
  color: var(--ink-300);
  margin: 6px 0 0;
}
.tab-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 99px;
  background: var(--signal-coral-bg);
  color: var(--signal-coral);
  margin-left: 4px;
  font-weight: 500;
  vertical-align: middle;
}
.ft-iframe {
  flex: 1;
  width: 100%;
  border: 1px solid var(--ink-200);
  border-radius: 6px;
  background: var(--paper-cool);
}
.ft-hint {
  font-size: 11px;
  color: var(--ink-400);
  margin: 8px 0 0;
  text-align: center;
}
.ft-hint a { color: var(--signal-teal); }

.ft-summary-area {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px;
}
.ft-sec {
  margin-bottom: 20px;
  padding: 14px 16px;
  background: var(--paper-cool);
  border: 1px solid var(--ink-200);
  border-radius: 8px;
}
.ft-sec-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.ft-sec-head h4 {
  font-size: 13px;
  font-weight: 700;
  color: var(--ink-800);
  margin: 0;
}
.ft-sec-tag {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 99px;
  background: var(--signal-blue-bg);
  color: var(--signal-blue);
}
.ft-btn-edit {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--signal-teal);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  padding: 2px 6px;
}
.ft-btn-edit:hover { text-decoration: underline; }
.ft-sec-content {
  font-size: 14px;
  line-height: 1.85;
  color: var(--ink-600);
  margin: 0;
  white-space: pre-wrap;
}
.ft-relevance { color: var(--signal-teal); }

.ft-edit-area {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ft-edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

.ft-kp {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ft-kp .kp {
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 99px;
  background: var(--paper);
  border: 1px solid var(--ink-200);
  color: var(--ink-600);
}
</style>
