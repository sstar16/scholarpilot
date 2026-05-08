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
import { invoke, convertFileSrc } from '@tauri-apps/api/core'
import { searchApi } from '../api/client'
import { downloadFulltextWithBudgetConfirm } from '../utils/patenthubBudget'
import { downloadDocumentPdf } from '../data/sync/documentsSyncService'
import { useSearchStore } from '../stores/search'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()

const searchStore = useSearchStore()

// 候选路径用 slug + UUID legacy fallback 兼容已下载的旧文件
import { pdfFilename, htmlFilename, projectFolderName } from '@/utils/slug'
import { getProject } from '@/data/sqlite/repos/projectRepo'

// app_data_dir cache: convertFileSrc 需要绝对路径
const appDataDir = ref<string | null>(null)
invoke<{ app_data_dir: string }>('get_app_paths')
  .then((r) => { appDataDir.value = r.app_data_dir })
  .catch((e) => console.warn('[FulltextViewer] get_app_paths failed:', e))

// 项目 title fire-and-forget 从 SQLite 拉 (拼 slug 项目目录名)。setup 同步段
// 调 (props 还没初始化, 用 setTimeout 延后到 props ready)
setTimeout(() => {
  if (!props.projectId) return
  getProject(String(props.projectId))
    .then((p) => { _projectTitle.value = p?.title || null })
    .catch((e) => console.warn('[FulltextViewer] getProject failed:', e))
}, 0)

// 本地文件存在性 ref
const localPdfReady = ref(false)
const localHtmlReady = ref(false)
const _localPdfRelChosen = ref<string | null>(null)
const _localHtmlRelChosen = ref<string | null>(null)

// 项目 title cache (fire-and-forget 从 SQLite 拉, 用于拼 slug 项目目录名)
const _projectTitle = ref<string | null>(null)

const props = defineProps<{
  doc: any
  projectId: string
  initialFormat?: 'pdf' | 'html' | 'auto'
}>()

const emit = defineEmits<{
  (e: 'updated', doc: any): void
}>()

const viewMode = ref<'pdf' | 'html' | 'summary' | 'abstract'>('summary')

// 本地文件存在性检查: silentPdfReconciler 写到 projects/<pid>/pdfs/<...>.pdf,
// fs_exists 检查约定路径。fire-and-forget 模式 — 不挂 lifecycle, 不用 watch
// (避免 ElDrawer transition 期间 patch race 触发 'instance.update' 错)。
//
// 注意: 必须放在 defineProps 之后 (函数体引用 props), 否则 setup 同步段
// 调用时撞 TDZ -> 'Cannot access props before initialization'。
function _candidatePaths(format: 'pdf' | 'html'): string[] {
  const pid = props.projectId
  const did = props.doc?.id
  if (!pid || !did) return []
  const docTitle = props.doc?.title || ''
  const projTitle = _projectTitle.value
  const fname = format === 'pdf' ? pdfFilename(docTitle, did) : htmlFilename(docTitle, did)
  const fnameLegacy = `${did}.${format}`

  // 4 路径候选 (从最美观到最 legacy):
  // 1. <projslug>__<pid6>/<docslug>__<did6>.<ext>      — 全 slug, 用户看 fs 最美
  // 2. <UUID-pid>/<docslug>__<did6>.<ext>              — 项目老 UUID + 文档新 slug (PDF slug 改造期间产物)
  // 3. <projslug>__<pid6>/<UUID-did>.<ext>             — (理论可能, 实际不会出现, 占位)
  // 4. <UUID-pid>/<UUID-did>.<ext>                     — 全 UUID (2026-05-03 之前)
  const cands: string[] = []
  if (projTitle) {
    const projSlug = projectFolderName(projTitle, pid)
    cands.push(`projects/${projSlug}/pdfs/${fname}`)
    cands.push(`projects/${projSlug}/pdfs/${fnameLegacy}`)
  }
  cands.push(`projects/${pid}/pdfs/${fname}`)
  cands.push(`projects/${pid}/pdfs/${fnameLegacy}`)
  // 去重 (projTitle 缺失时可能有重复)
  return [...new Set(cands)]
}

async function _checkOne(rel: string): Promise<boolean> {
  try { return await invoke<boolean>('fs_exists', { relPath: rel }) }
  catch { return false }
}

void (async () => {
  // setup 同步段 fire-and-forget. 顺序 check 候选路径, 第一个命中的就用。
  const pdfCands = _candidatePaths('pdf')
  for (const p of pdfCands) {
    if (await _checkOne(p)) {
      _localPdfRelChosen.value = p
      localPdfReady.value = true
      break
    }
  }
})()
void (async () => {
  const htmlCands = _candidatePaths('html')
  for (const p of htmlCands) {
    if (await _checkOne(p)) {
      _localHtmlRelChosen.value = p
      localHtmlReady.value = true
      break
    }
  }
})()

// ── 双通道状态（本地 fs 优先 → props.doc store → fulltext_path 后缀 fallback）──
//
// 之前只看 props.doc.fulltext_pdf_status (来自 backend HTTP search store), 但
// 客户端 silentPdfReconciler / downloadDocumentPdf 写本地后**不更新 store**,
// 导致 fs 已有 PDF 但 UI 显示 "未下载"。修: localPdfReady (fs_exists 异步
// check 结果) 真就当作 'available', UI 立刻能加载。
const pdfStatus = computed<string>(() => {
  // 1. 本地真有 -> available (无视 backend status, 它可能 stale)
  if (localPdfReady.value) return 'available'
  if (!props.doc) return 'not_attempted'
  // 2. props.doc 字段 (search store cache)
  const s = props.doc.fulltext_pdf_status
  if (s && s !== 'not_attempted') return s
  // 3. fallback: 老数据按 fulltext_path 后缀
  const p = (props.doc.fulltext_path || '').toLowerCase()
  if (props.doc.fulltext_status === 'available' && p.endsWith('.pdf')) return 'available'
  return s || 'not_attempted'
})
const htmlStatus = computed<string>(() => {
  if (localHtmlReady.value) return 'available'
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

// 构造文件流 URL: 客户端优先用本地 fs (convertFileSrc -> tauri://...),
// 拿不到本地副本时 fallback 到 backend HTTP (带 BASE_URL + token query)。
//
// 之前的 bug: 总是返回相对 URL '/api/...', 在 Tauri webview 里被解析成
// 'tauri://localhost/api/...' 死路 — 即便本地有 PDF, 也走不到 backend, iframe 永远空白。
function fileUrlFor(format: 'pdf' | 'html'): string | null {
  if (!props.doc?.id || !props.projectId) return null

  // 1. 本地优先: silentPdfReconciler 已经把 binary 下到了
  //    projects/<pid>/pdfs/<did>.pdf (paths.ts PATHS.pdfFile 约定),
  //    用 fs_exists check 是否真存在 (不依赖 props.doc 上不存在的 *_local_path 字段)。
  const ready = format === 'pdf' ? localPdfReady.value : localHtmlReady.value
  const rel = format === 'pdf' ? _localPdfRelChosen.value : _localHtmlRelChosen.value
  if (ready && rel && appDataDir.value) {
    // appDataDir 在 Windows 是 'C:\Users\...\Roaming\top.scholarpilot.client'
    const sep = appDataDir.value.includes('\\') ? '\\' : '/'
    const abs = `${appDataDir.value}${sep}${rel.replace(/\//g, sep)}`
    return convertFileSrc(abs)
  }

  // 2. fallback: backend HTTP (本地无副本; VITE_API_BASE_URL 桌面端是
  //    https://scholarpilot.top 走 Cloudflare Tunnel)
  const BASE = import.meta.env.VITE_API_BASE_URL || ''
  const token = auth.token
  const qs = new URLSearchParams()
  qs.set('format', format)
  if (token) qs.set('token', token)
  return `${BASE}/api/projects/${props.projectId}/documents/${props.doc.id}/file?${qs.toString()}`
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
          // 同步到客户端本地 fs (用户期望: 下载原文 = 本地有副本 + 云端有副本)
          // backend GET /file 拿 binary -> writeBytes 写本地 -> 更新 SQLite pdf_local_path
          // 然后 fs_exists check 触发 fileUrlFor 用本地 (tauri:// asset) 加载, 0 网络。
          if (format === 'pdf' && props.projectId && props.doc?.id) {
            try {
              const r = await downloadDocumentPdf(String(props.projectId), String(props.doc.id))
              if (r.status === 'available' || r.status === 'skipped') {
                // 重新 fs_exists check 触发 fileUrlFor recompute -> iframe 切换到 tauri://
                const cands = _candidatePaths('pdf')
                for (const p of cands) {
                  if (await _checkOne(p)) {
                    _localPdfRelChosen.value = p
                    localPdfReady.value = true
                    break
                  }
                }
              }
            } catch (e) {
              console.warn('[retryDownload] local sync failed (backend ok):', e)
            }
          }
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

// ── 自动下载: PDF tab 进入时如果还没下过, 后台 trigger 一次 ──────────────
// silentPdfReconciler 只下"用户 own 过的"PDF (0028 ownership 驱动)。新检索
// 出来的文献 (status='not_attempted') 不在自动下载列表 -> 用户点详情 PDF tab
// 永远空白, 必须手动点"下载 PDF"按钮。这里改成: 用户开抽屉默认进 PDF tab =
// 已经表达想看 PDF = 自动 trigger 一次下载。
//
// 安全性: setup 同步段 fire-and-forget retryDownload (async), Promise 内部
// 第一个 await 之后的代码在下个 microtask 跑, 跟 ElDrawer transition 完全
// 错开, 不会触发 instance.update race。
// 幂等性: backend POST /download-fulltext 同 doc 重复请求会去重 (Celery 任务级)。
// 自动下载: 不看 backend status (可能 'available' 但本地没文件 + iframe
// 加载 backend HTTPS 在 Tauri webview 失败 = 拒绝连接), 看**本地真的有没有**。
//
// 等 300ms 让 ElDrawer transition 稳定 + setup phase 早期 fs_exists check
// 完成, 再判断:
//   1. 本地有 -> 不动, fileUrlFor 自然走 tauri://本地
//   2. 本地没 + canDownloadPdf -> 直接调 downloadDocumentPdf:
//        - GET /file 拿 binary -> writeBytes 写本地 (backend 已有 PDF 时, 秒拿到)
//        - 404 -> POST /download-fulltext + 进 retryDownload polling
//   3. 都不行 -> 用户看到"未下载"空态 + 上传按钮
void (async () => {
  await new Promise((r) => setTimeout(r, 300))

  // 重新 fs_exists check 一次本地 (setup 早期 IIFE 可能还没完成)
  const cands = _candidatePaths('pdf')
  // debug: log 候选路径 + 每个的 fs_exists 结果, 帮诊断"fs 有但 UI 没找到"
  const checkResults: { path: string; exists: boolean }[] = []
  let hasLocal = false
  for (const p of cands) {
    const e = await _checkOne(p)
    checkResults.push({ path: p, exists: e })
    if (e && !hasLocal) {
      _localPdfRelChosen.value = p
      localPdfReady.value = true
      hasLocal = true
    }
  }
  invoke('log_webview_error', {
    level: 'warn',
    message: `fs_exists check doc=${props.doc?.id} title="${(props.doc?.title || '').slice(0, 40)}" hasLocal=${hasLocal} candidates=${JSON.stringify(checkResults)}`,
    source: 'FulltextViewer.fs-check',
  }).catch(() => {})

  if (viewMode.value !== 'pdf' || hasLocal || !canDownloadPdf.value) return

  // 本地没 + 能下 -> 直接 GET /file 拉 binary 写本地
  try {
    const r = await downloadDocumentPdf(String(props.projectId), String(props.doc.id))
    if (r.status === 'available' || r.status === 'skipped') {
      // backend 有 PDF, 已写本地 -> 重新 check 触发 fileUrlFor recompute
      for (const p of cands) {
        if (await _checkOne(p)) {
          _localPdfRelChosen.value = p
          localPdfReady.value = true
          break
        }
      }
    } else if (r.status === 'queued') {
      // backend 也没 -> 走 retryDownload polling (POST + 等 Celery)
      void retryDownload('pdf')
    }
  } catch (e) {
    console.warn('[FulltextViewer] auto-download direct failed:', e)
  }
})()

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
