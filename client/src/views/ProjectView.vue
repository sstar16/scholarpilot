<template>
  <div class="project-view">
    <template v-if="projectStore.loading">
      <el-skeleton :rows="5" animated style="padding:24px" />
    </template>

    <template v-else-if="project">
      <!-- Top bar -->
      <div class="project-topbar">
        <div class="topbar-left">
          <el-button text @click="router.push('/dashboard')"><el-icon><ArrowLeft /></el-icon></el-button>
          <div>
            <h2 class="project-title" v-if="!editingTitle" @dblclick="startEditTitle" :title="'双击编辑标题'">
              {{ project.title }}
              <el-icon class="edit-hint" @click="startEditTitle"><Edit /></el-icon>
            </h2>
            <div v-else class="inline-edit">
              <el-input v-model="editTitleValue" size="small" @keyup.enter="saveTitle" @keyup.escape="editingTitle = false" ref="titleInputRef" />
              <el-button size="small" type="primary" @click="saveTitle">保存</el-button>
              <el-button size="small" @click="editingTitle = false">取消</el-button>
            </div>
            <span class="project-domain" v-if="!editingDesc" @dblclick="startEditDesc" :title="'双击编辑描述'">
              {{ (project.domains || [project.domain]).join(' · ') }}
              <el-icon class="edit-hint" @click="startEditDesc"><Edit /></el-icon>
            </span>
            <div v-else class="inline-edit">
              <el-input v-model="editDescValue" type="textarea" :rows="3" size="small" />
              <el-button size="small" type="primary" @click="saveDesc">保存</el-button>
              <el-button size="small" @click="editingDesc = false">取消</el-button>
            </div>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:10px">
          <el-button size="small" @click="openSettings"><el-icon><Setting /></el-icon> 搜索设置</el-button>
          <el-tag :type="statusType(project.status)" size="large">{{ statusLabel(project.status) }}</el-tag>
        </div>
      </div>

      <!-- Settings dialog -->
      <el-dialog v-model="settingsVisible" title="数据源设置" width="480px" :close-on-click-modal="false">
        <p style="font-size:13px;color:#909399;margin:0 0 12px">默认全部开启；关闭的数据源在下一轮检索中生效</p>
        <div class="settings-source-grid">
          <div v-for="src in ALL_SOURCES" :key="src.id" class="settings-source-item">
            <el-switch :model-value="!settingsForm.disabledSources.includes(src.id)" @update:model-value="toggleSettingsSource(src.id, $event)" size="small" />
            <div>
              <span class="settings-source-label">{{ src.label }}</span>
              <span class="settings-source-desc">{{ src.desc }}</span>
            </div>
          </div>
        </div>
        <template #footer>
          <el-button @click="settingsVisible = false">取消</el-button>
          <el-button type="primary" :loading="savingSettings" @click="saveSettings">保存</el-button>
        </template>
      </el-dialog>

      <!-- Collaboration mode banner (shows above body when active) -->
      <CollaborationBanner
        v-if="collabStore.isActive"
        @manage-docs="bucketOpen = true"
        @view-graph="openGraphDialog"
      />

      <!-- 项目级笔记本（AI 多页决策，协作内外均可用） -->
      <NotebookDrawer />

      <div class="project-body">
        <!-- Cards / Library views: 两个并存 —— cards 是期刊风瀑布流，library 是 markdown workspace -->
        <template v-if="currentView === 'cards'">
          <main class="cards-main">
            <div class="chat-main__header">
              <div class="chat-main__title">
                <el-icon :size="18"><Grid /></el-icon>
                <span>卡片视图 · 按桶分组</span>
              </div>
              <div class="chat-main__actions">
                <el-button size="small" class="back-to-chat" @click="backToChat">
                  ← 回到对话流
                </el-button>
                <ViewSwitcher
                  :model-value="chatViewMode"
                  @update:model-value="onViewModeChange"
                  @open-notebook="openNotebook"
                />
              </div>
            </div>
            <BucketCardView
              :project-id="String(project.id)"
              @view-doc="onSideViewDoc"
            />
          </main>
        </template>
        <template v-else-if="currentView === 'library'">
          <main class="library-main">
            <LibraryBrowser :project-id="String(project.id)" @back="backToChat" />
          </main>
        </template>

        <!-- Default: chat workspace + optional bucket aside -->
        <template v-else>
          <main class="chat-main">
            <div class="chat-main__header">
              <div class="chat-main__title">
                <el-icon :size="18"><ChatDotRound /></el-icon>
                <span>项目对话</span>
              </div>
              <div class="chat-main__actions">
                <!-- ViewSwitcher: chat / cards / graph 三态 segmented + 笔记本 -->
                <ViewSwitcher
                  :model-value="chatViewMode"
                  @update:model-value="onViewModeChange"
                  @open-notebook="openNotebook"
                />
                <!-- 右侧文献库折叠开关（默认展开） -->
                <el-button
                  size="small"
                  :type="bucketOpen ? 'primary' : ''"
                  :plain="!bucketOpen"
                  class="aside-toggle"
                  @click="bucketOpen = !bucketOpen"
                >
                  <el-icon><Folder /></el-icon>
                  <span class="btn-label">{{ bucketOpen ? '收起' : '文献库' }}</span>
                  <span v-if="bucketStore.total > 0" class="header-badge badge-default">
                    {{ bucketStore.total }}
                  </span>
                </el-button>
              </div>
            </div>
            <div class="chat-main__body">
              <ChatPanel :project-id="String(project.id)" @view-doc="openFulltext" />
            </div>
          </main>

          <!-- Right aside: 协作模式 → CollaborationDocList；普通模式 → LibrarySidePanel（期刊风右栏） -->
          <template v-if="bucketOpen">
            <aside v-if="collabStore.isActive" class="bucket-aside">
              <CollaborationDocList
                :project-id="String(project.id)"
                @view="openFulltext"
                @manage="onManageCollabDocs"
              />
            </aside>
            <LibrarySidePanel
              v-else
              :project-id="String(project.id)"
              @view-doc="onSideViewDoc"
              @open-library="toggleLibraryView"
            />
          </template>
        </template>
      </div>

      <!-- Drawer: 全文查看 -->
      <el-drawer
        v-model="fulltextDrawerOpen"
        direction="rtl"
        size="70%"
        :with-header="false"
        destroy-on-close
      >
        <FulltextViewer
          :doc="currentFulltextDoc"
          :project-id="String(project.id)"
          :initial-format="currentFulltextFormat"
          @updated="onFulltextDocUpdated"
        />
      </el-drawer>

      <!-- Knowledge Graph Dialog (顶部入口 + 协作 banner 共享) -->
      <KnowledgeGraphView
        v-model:visible="kgVisible"
        v-model:bucket="kgBucket"
        :project-id="String(project.id)"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, computed, ref, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '../stores/project'
import { useSearchStore } from '../stores/search'
import { useConversationStore } from '../stores/conversation'
import { projectApi } from '../api/client'
import { useBucketStore } from '../stores/bucket'
import BucketSidebar from '../components/bucket/BucketSidebar.vue'
import LibrarySidePanel from '../components/conversation/LibrarySidePanel.vue'
import ViewSwitcher, { type ViewMode } from '../components/conversation/ViewSwitcher.vue'
import ChatPanel from '../components/conversation/ChatPanel.vue'
import CollaborationBanner from '../components/conversation/CollaborationBanner.vue'
import NotebookDrawer from '../components/conversation/NotebookDrawer.vue'
import { useNotebookStore } from '../stores/notebook'
import CollaborationDocList from '../components/conversation/CollaborationDocList.vue'
import { useCollaborationStore } from '../stores/collaboration'
import FulltextViewer from '../components/FulltextViewer.vue'
import LibraryBrowser from '../components/library/LibraryBrowser.vue'
// PRD §C8: 删 hydrateProject，客户端 SQLite 直读，PDF 仍走 pdfReconciler
// TODO(C5): 如要拉云端 round/owned-doc 元数据，改走 sp-api 直查接口
import BucketCardView from '../components/conversation/BucketCardView.vue'
import KnowledgeGraphView from '../components/graph/KnowledgeGraphView.vue'
import { useLibraryStore } from '../stores/library'
import { Folder, Collection, Share, Notebook, Grid, ChatDotRound } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const searchStore = useSearchStore()
const bucketStore = useBucketStore()
const convStore = useConversationStore()
const collabStore = useCollaborationStore()
const libraryStore = useLibraryStore()

// ── Knowledge graph dialog state ──
const kgVisible = ref(false)
const kgBucket = ref<string>('very_relevant')

function openKnowledgeGraph(bucket: string = 'very_relevant') {
  kgBucket.value = bucket
  kgVisible.value = true
}

// ── View mode 状态（通过 query.view 分发）──
// 'chat' (default) | 'cards' (期刊风瀑布流) | 'library' (markdown workspace，旧入口)
const currentView = computed<string>(() => (route.query.view as string) || 'chat')

function toggleLibraryView() {
  if (currentView.value === 'library') {
    const { view, slug, ...rest } = route.query
    router.replace({ query: rest })
    libraryStore.clearDetail()
  } else {
    router.replace({ query: { ...route.query, view: 'library' } })
  }
}

function backToChat() {
  const { view, slug, ...rest } = route.query
  router.replace({ query: rest })
  libraryStore.clearDetail()
}

// ── Right-aside state ──
const fulltextDrawerOpen = ref(false)
const currentFulltextDoc = ref<any>(null)
const currentFulltextFormat = ref<'pdf' | 'html' | 'auto'>('auto')
// 默认展开：原型风格右栏文献库（`LibrarySidePanel`）作为三栏布局中的常见态；
// 协作模式下 fallback 到 `CollaborationDocList`。窄屏可以折叠以释放宽度。
const bucketOpen = ref(true)

// ── ViewSwitcher 三态 chat / cards / graph ──
// cards = 期刊风瀑布流（BucketCardView）；library = markdown workspace（旧入口，通过右栏"全部 →"保留）
const chatViewMode = computed<ViewMode>(() => {
  const v = route.query.view as string
  if (v === 'cards' || v === 'library') return 'cards'
  return 'chat'
})

function onViewModeChange(v: ViewMode) {
  if (v === 'chat') {
    const { view, slug, ...rest } = route.query
    router.replace({ query: rest })
    libraryStore.clearDetail()
  } else if (v === 'cards') {
    router.replace({ query: { ...route.query, view: 'cards' } })
  } else if (v === 'graph') {
    // 2026-05-08：graph 入口改跳全屏路由 /projects/<id>/graph（基于客户端 GraphRepo + cytoscape，
    // 体验比 dialog 流畅）。Banner / BucketSidebar 仍可通过 KnowledgeGraphView dialog 走 bucket-aware
    // 后端 API；二者并存。
    if (project.value?.id) {
      router.push({ name: 'KnowledgeGraph', params: { projectId: String(project.value.id) } })
    }
  }
}

// LibrarySidePanel 点击 mini-card 时打开全文查看
function onSideViewDoc(doc: any) {
  // mini-card 只有 document_id；转换成 openFulltext 所需格式
  openFulltext({ doc: { id: doc.document_id, ...doc }, format: 'auto' })
}

function openFulltext(payload: any) {
  // 兼容两种签名：旧的直接 doc，新的 { doc, format } 对象（DocumentCard view-fulltext 带 format）
  if (payload && typeof payload === 'object' && 'doc' in payload) {
    currentFulltextDoc.value = payload.doc
    currentFulltextFormat.value = (payload.format || 'auto') as 'pdf' | 'html' | 'auto'
  } else {
    currentFulltextDoc.value = payload
    currentFulltextFormat.value = 'auto'
  }
  fulltextDrawerOpen.value = true
}

function openGraphDialog() {
  // 协作模式 banner 触发：默认打开 very_relevant 桶的图谱
  openKnowledgeGraph('very_relevant')
}

const notebookStore = useNotebookStore()
function openNotebook() {
  const pid = project.value?.id
  if (!pid) return
  notebookStore.openPanel(String(pid))
}

function onManageCollabDocs() {
  ElMessage.info('请在对话中说「加入/移除某某文献」让 AI 帮您调整协作范围')
}

function onFulltextDocUpdated(updatedDoc: any) {
  // FulltextViewer 内部已通过 Object.assign 更新 props.doc
  // 这里刷新桶和结果保证其他地方看到最新字段
  const roundId = searchStore.currentRound?.id
  if (roundId) {
    searchStore.loadRoundResults(roundId).catch(() => { /* ignore */ })
  }
}

// Inline edit title/description
const editingTitle = ref(false)
const editingDesc = ref(false)
const editTitleValue = ref('')
const editDescValue = ref('')
const titleInputRef = ref<any>(null)

function startEditTitle() {
  editTitleValue.value = project.value?.title || ''
  editingTitle.value = true
  setTimeout(() => titleInputRef.value?.focus(), 50)
}

function startEditDesc() {
  editDescValue.value = project.value?.description || ''
  editingDesc.value = true
}

async function saveTitle() {
  if (!editTitleValue.value.trim()) return
  try {
    await projectApi.update(route.params.id as string, { title: editTitleValue.value.trim() })
    await projectStore.fetchProject(route.params.id as string)
    editingTitle.value = false
    ElMessage.success('标题已更新，下一轮检索将使用新标题生成关键词')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  }
}

async function saveDesc() {
  if (!editDescValue.value.trim()) return
  try {
    await projectApi.update(route.params.id as string, { description: editDescValue.value.trim() })
    await projectStore.fetchProject(route.params.id as string)
    editingDesc.value = false
    ElMessage.success('描述已更新，下一轮检索将使用新描述生成关键词')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  }
}

// SSE / 检索进度的全部订阅已下沉到 SearchProgressMessage 富消息组件内部 —
// 这里不再需要 ProjectView 级别的 SSE 监听，避免双重连接。

const ALL_SOURCES = [
  { id: 'openalex',         label: 'OpenAlex',            desc: '国际综合文献库' },
  { id: 'europe_pmc',       label: 'Europe PMC',          desc: '生物医学全文' },
  { id: 'crossref',         label: 'Crossref',            desc: '期刊引用数据' },
  { id: 'semantic_scholar', label: 'Semantic Scholar',    desc: 'AI语义检索' },
  { id: 'dblp',             label: 'DBLP',                desc: 'CS顶级会议/期刊（免费）' },
  { id: 'openalex_zh',      label: 'OpenAlex 中文',        desc: '中文论文（chinese_first 自动启用）' },
  { id: 'arxiv',            label: 'arXiv',               desc: '物理/CS/数学预印本' },
  { id: 'biorxiv',          label: 'bioRxiv',             desc: '生物预印本' },
  { id: 'medrxiv',          label: 'medRxiv',             desc: '医学预印本' },
  { id: 'lens_patent',      label: 'Lens.org 专利',       desc: '全球专利 CN/US/EP/WO（需 LENS_API_TOKEN）' },
  { id: 'epo_ops',          label: 'EPO OPS 专利',        desc: '欧洲专利局 EP/WO（需 EPO_CONSUMER_KEY）' },
  { id: 'patenthub',        label: 'PatentHub 中国专利',  desc: 'CN发明/实用新型 + PDF全文下载（需 PATENTHUB_API_TOKEN）' },
  { id: 'clinical_trials',  label: 'ClinicalTrials.gov',  desc: '临床试验注册' },
]

const settingsVisible = ref(false)
const savingSettings = ref(false)
const settingsForm = reactive({ disabledSources: [] as string[] })

function toggleSettingsSource(id: string, enabled: boolean) {
  if (enabled) {
    const idx = settingsForm.disabledSources.indexOf(id)
    if (idx !== -1) settingsForm.disabledSources.splice(idx, 1)
  } else {
    if (!settingsForm.disabledSources.includes(id)) settingsForm.disabledSources.push(id)
  }
}

function openSettings() {
  const cfg = (project.value?.search_config ?? {}) as Record<string, unknown>
  const disabled = Array.isArray(cfg.disabled_sources) ? (cfg.disabled_sources as string[]) : []
  settingsForm.disabledSources = [...disabled]
  settingsVisible.value = true
}

async function saveSettings() {
  savingSettings.value = true
  try {
    const id = route.params.id as string
    const cfg = { ...(project.value?.search_config ?? {}), disabled_sources: [...settingsForm.disabledSources] }
    await projectApi.update(id, { search_config: cfg })
    await projectStore.fetchProject(id)
    settingsVisible.value = false
    ElMessage.success('设置已保存，下一轮检索生效')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    savingSettings.value = false
  }
}

const project = computed(() => projectStore.current)

function statusLabel(s: string) {
  return ({ active: '进行中', monitoring: '监控中', archived: '已归档' } as any)[s] ?? s
}

function statusType(s: string) {
  return ({ active: 'primary', monitoring: 'success', archived: 'info' } as any)[s] ?? ''
}

// 检索流程（startRound / 关键词确认 / 文献分类 / 全文下载 / 上传 / monitoring 等）
// 已经全部下沉到 ChatPanel.vue 富消息流。ProjectView 只保留项目元信息编辑、
// 文献库 sidebar、协作模式 banner、全文查看 drawer。

// 防止进入项目页重复触发 prepareRound（单次 mount 生命周期内只触发一次）
const _autoPrepareTriggered = ref(false)

onMounted(async () => {
  const id = route.params.id as string
  // 切项目前先清零：防止旧项目的 currentState/messages/scope 残留到新项目
  convStore.reset()
  collabStore.reset()
  await projectStore.fetchProject(id)
  await Promise.all([
    searchStore.fetchRounds(id),
    bucketStore.fetchBuckets(id),
    convStore.findOrCreateSession(id),
  ])

  // 场景 1 自动化：项目刚创建（current_round === 0）且无已有轮次 → 自动 prepareRound
  if (
    !_autoPrepareTriggered.value
    && (projectStore.current?.current_round ?? 0) === 0
    && searchStore.rounds.length === 0
  ) {
    _autoPrepareTriggered.value = true
    try {
      await searchStore.prepareRound(id)
      await projectStore.fetchProject(id)
      await convStore.refreshMessages()
    } catch (err) {
      console.warn('[ProjectView] auto prepareRound failed:', err)
      ElMessage.warning('首轮关键词自动生成失败，请点底部「新检索」按钮手动触发')
    }
  }
  // PRD §C8 旧 hydrateProject 已删。PDF 自动批量下载现单独走 pdfReconciler.reconcileSilent
  // TODO(C5): 直接调 reconcileSilent(id) 或重新组合上层入口。当前先停（依赖 round/ownership
  // 同步链；ownership API 已撤；重启需配合后续设计）。
  void Promise.resolve()
  // Restore collaboration state if the session has it
  if (convStore.sessionId) {
    try {
      const { conversationApi } = await import('../api/client')
      const sessRes = await conversationApi.getSession(convStore.sessionId)
      await collabStore.restoreFromSession(convStore.sessionId, sessRes.data)
    } catch { /* ignore */ }
  }
  // 加载当前轮次结果（如果有），让文献库 sidebar 等组件看到最新数据
  if (searchStore.currentRound && searchStore.currentRound.round_number) {
    await searchStore.loadRoundResults(searchStore.currentRound.id)
  }
  // 页面刷新时，如果存在 active round，让 store 自己继续 polling；
  // SSE 连接由 SearchProgressMessage 富消息组件按 round_id 自动建立。
  if (searchStore.currentRound && ['searching', 'summarizing', 'running', 'pending'].includes(searchStore.currentRound.status)) {
    try {
      if (searchStore.documents.length > 0 && searchStore.streamingDocs.length === 0) {
        searchStore.streamingDocs = searchStore.documents.map((d: any) => ({
          external_id: d.external_id,
          source: d.source,
          title: d.title,
          year: d.year,
          authors: d.authors,
          has_summary: !!d.ai_summary,
          has_abstract: !!d.abstract,
        }))
      }
    } catch { /* round may not have results yet */ }
    searchStore.startPolling(id, searchStore.currentRound.id)
  }
})
</script>

<style scoped>
/* ═══════════════════════════════════════════════
   ProjectView — Ink & Signal theme
   ═══════════════════════════════════════════════ */

.project-view {
  min-height: calc(100vh - 52px);
  background: var(--paper-cool);
}

/* ── Top Bar ── */
.project-topbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 24px;
  background: var(--paper);
  border-bottom: 1px solid var(--ink-100);
}
.topbar-left { display: flex; align-items: center; gap: 12px; }
.project-title {
  margin: 0; font-family: var(--font-display);
  font-size: 19px; font-weight: 900; color: var(--ink-900);
  letter-spacing: -0.3px;
  cursor: default;
  display: flex;
  align-items: center;
  gap: 6px;
}
.project-title .edit-hint {
  font-size: 14px;
  color: var(--ink-300);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s;
}
.project-title:hover .edit-hint,
.project-domain:hover .edit-hint {
  opacity: 1;
}
.inline-edit {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 2px 0;
}
.inline-edit .el-input, .inline-edit .el-textarea {
  flex: 1;
}
.project-domain .edit-hint {
  font-size: 12px;
  color: var(--ink-300);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s;
  margin-left: 4px;
}
.project-domain {
  font-size: 11px; color: var(--ink-400);
  background: var(--ink-50); padding: 2px 10px;
  border-radius: var(--radius-full);
}

/* ── Layout (conversation-centric) ── */
.project-body {
  display: flex;
  height: calc(100vh - 120px);
  min-height: 600px;
  background: var(--paper-cool);
  /* min-width: 0 + overflow: hidden 是 flex 子项防止富消息长内容把父容器撑出
     横向滚动条的标准防御 */
  min-width: 0;
  overflow: hidden;
}

/* ── Chat main (primary workspace) ── */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  background: var(--paper);
}
.chat-main__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-bottom: 1px solid var(--ink-100);
  background: var(--paper);
  flex-shrink: 0;
}
.chat-main__title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 700;
  color: var(--ink-800, #1e293b);
}
.chat-main__actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.chat-main__actions .btn-label {
  margin-left: 4px;
}
.chat-main__body {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* ── Library main (markdown workspace) & Cards main (瀑布流) ── */
.library-main,
.cards-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  background: var(--paper-cool);
}
.back-to-chat :deep(.el-button),
.back-to-chat {
  border-color: rgba(198, 172, 87, 0.55);
  color: #8a7438;
  background: rgba(198, 172, 87, 0.08);
  font-weight: 600;
  transition: all var(--duration-fast);
}
.back-to-chat:hover {
  background: rgba(198, 172, 87, 0.18);
  color: #6d5a26;
  border-color: rgba(198, 172, 87, 0.8);
}

/* ── Header badge (for drawer buttons) ── */
.header-badge {
  display: inline-block;
  margin-left: 6px;
  padding: 0 6px;
  min-width: 18px;
  height: 16px;
  line-height: 16px;
  border-radius: 8px;
  font-size: 10px;
  font-weight: 700;
  text-align: center;
  background: #e4e7ed;
  color: #606266;
}
.header-badge.badge-warning { background: #faecd8; color: #d97706; }
.header-badge.badge-primary { background: #d9ecff; color: #409eff; }
.header-badge.badge-default { background: #f0f2f5; color: #606266; }

/* ── Bucket aside (right) ── */
.bucket-aside {
  width: 280px;
  flex-shrink: 0;
  border-left: 1px solid var(--ink-100);
  background: var(--paper-cool);
  overflow-y: auto;
}

/* ── Search workspace (drawer content) ── */
.search-workspace {
  padding: 4px 24px 24px;
  max-width: 100%;
}

/* Reused within drawer */
.main-content { padding: 0; }

.start-panel { display: flex; justify-content: center; padding: 80px 0; }

/* ── Round Header ── */
.round-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 20px; padding-bottom: 14px;
  border-bottom: 1px solid var(--ink-100);
}
.round-header h3 {
  margin: 0; font-family: var(--font-display);
  font-size: 20px; font-weight: 900; color: var(--ink-900);
}
.round-desc { color: var(--ink-400); font-size: 12px; margin: 3px 0 0; }

/* ── Processing (SSE v2) ── */
.processing-state-v2 {
  background: var(--paper); border-radius: var(--radius-lg);
  padding: 24px; border: 1px solid var(--ink-100);
  margin-bottom: 18px; box-shadow: var(--shadow-xs);
}

/* ── Feedback Progress ── */
.feedback-progress {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 18px; padding: 12px 18px;
  background: var(--signal-teal-bg); border-radius: var(--radius-md);
  border: 1px solid rgba(13,148,136,0.15);
  font-size: 13px; color: var(--signal-teal); font-weight: 600;
}

.doc-list { display: flex; flex-direction: column; gap: 12px; }
.cutoff-toggle { text-align: center; margin-bottom: 8px; }

/* ── Source Stats ── */
.source-stats {
  display: flex; flex-wrap: wrap; align-items: center;
  margin-bottom: 14px; padding: 8px 14px;
  background: var(--paper); border-radius: var(--radius-md);
  border: 1px solid var(--ink-100);
}
.source-stats-label { font-size: 12px; color: var(--ink-400); margin-right: 8px; white-space: nowrap; font-weight: 600; }

.next-round-panel { margin-top: 24px; }

.settings-source-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.settings-source-item { display: flex; align-items: center; gap: 8px; }
.settings-source-label { font-size: 13px; font-weight: 600; color: var(--ink-800); }
.settings-source-desc { font-size: 11px; color: var(--ink-400); }

/* ── Dev View Pipeline ── */
.dev-pipeline {
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 10px;
  padding: 18px 20px;
  margin-bottom: 16px;
  color: #c9d1d9;
  font-size: 13px;
}
.dev-pipeline-header {
  display: flex; align-items: center; gap: 8px;
  font-size: 14px; font-weight: 700; color: #58a6ff;
  margin-bottom: 18px; padding-bottom: 12px;
  border-bottom: 1px solid #21262d;
}

/* Step block */
.dev-step {
  display: flex; gap: 14px; align-items: flex-start;
  background: #161b22; border: 1px solid #21262d;
  border-radius: 8px; padding: 14px 16px;
}
.dev-step-num {
  width: 24px; height: 24px; border-radius: 50%;
  background: #1f6feb; color: #fff;
  font-size: 12px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; margin-top: 1px;
}
.dev-step-body { flex: 1; min-width: 0; }
.dev-step-title {
  font-size: 13px; font-weight: 600; color: #e6edf3;
  margin-bottom: 10px; display: flex; align-items: center; gap: 8px;
}
.dev-step-sub { font-size: 11px; font-weight: 400; color: #8b949e; }

/* Connector between steps */
.dev-connector {
  text-align: center; color: #8b949e;
  font-size: 11px; padding: 4px 0;
  display: flex; align-items: center; justify-content: center; gap: 6px;
}
.dev-connector span {
  background: #161b22; border: 1px solid #21262d;
  border-radius: 20px; padding: 2px 12px;
}

/* KV rows */
.dev-kv-list { display: flex; flex-direction: column; gap: 6px; }
.dev-kv { display: flex; align-items: flex-start; gap: 10px; }
.dev-k {
  font-size: 11px; color: #8b949e;
  min-width: 76px; flex-shrink: 0; padding-top: 2px;
}
.dev-v { color: #c9d1d9; flex: 1; }
.dev-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.dev-tag { font-family: monospace; }
.dev-source-tag { flex-shrink: 0; margin-left: 4px; }

/* Code */
.dev-code {
  font-family: 'Consolas', monospace; font-size: 12px;
  background: #0d1117; border: 1px solid #21262d;
  border-radius: 4px; padding: 2px 7px;
  color: #79c0ff;
}
.dev-code-primary { color: #a5f3c0; font-size: 13px; font-weight: 500; }
.dev-code-sm {
  font-family: 'Consolas', monospace; font-size: 11.5px;
  color: #79c0ff; word-break: break-all;
}

/* Source table */
.dev-src-table { width: 100%; }
.dev-src-thead, .dev-src-row {
  display: grid;
  grid-template-columns: 20px 120px 1fr 58px 68px;
  align-items: center;
}
.dev-src-thead {
  font-size: 11px; color: #8b949e; font-weight: 600;
  padding: 4px 8px 6px; border-bottom: 1px solid #21262d;
  text-transform: uppercase; letter-spacing: 0.05em;
}
.dev-src-block { border-bottom: 1px solid #21262d; }
.dev-src-block:last-child { border-bottom: none; }
.row-zero { opacity: 0.6; }
.row-err .dev-src-row { background: #160808; }
.dev-src-row {
  padding: 7px 8px;
  transition: background 0.12s;
}
.dev-src-row:hover { background: #1c2128; }

.c-exp { display: flex; align-items: center; justify-content: center; color: #8b949e; }
.c-src { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 500; color: #c9d1d9; }
.c-query { font-size: 12px; color: #8b949e; padding-right: 8px; overflow: hidden; }
.c-count { font-size: 12px; text-align: right; padding-right: 8px; }
.c-time { font-size: 11px; color: #8b949e; text-align: right; }
.cnt-ok { color: #3fb950; font-weight: 600; }
.cnt-zero { color: #8b949e; }

.src-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.dot-ok { background: #3fb950; }
.dot-zero { background: #484f58; }
.dot-err { background: #f85149; }
.dev-err-txt { font-size: 11px; color: #f85149; word-break: break-all; }

/* Expand icon */
.expand-icon { font-size: 11px; transition: transform 0.2s; }
.icon-open { transform: rotate(90deg); }

/* Expanded source doc list */
.dev-src-docs {
  padding: 6px 8px 10px 28px;
  border-top: 1px solid #21262d;
  background: #0d1117;
}
.dev-src-doc-row {
  display: grid;
  grid-template-columns: 28px 52px 1fr 58px;
  align-items: baseline;
  gap: 8px;
  padding: 4px 0;
  border-bottom: 1px solid #161b22;
  font-size: 12px;
}
.dev-src-doc-row:last-of-type { border-bottom: none; }
.doc-rank { color: #484f58; font-size: 11px; text-align: right; }
.doc-score { color: #8957e5; font-family: monospace; font-size: 11px; }
.doc-title-sm { color: #c9d1d9; line-height: 1.4; }
.doc-date-sm { color: #484f58; font-size: 11px; text-align: right; white-space: nowrap; }
.dev-src-note { font-size: 11px; color: #484f58; padding: 6px 0 2px; font-style: italic; }

/* LLM Step */
.dev-step-llm { background: #6e40c9 !important; font-size: 10px !important; }
.dev-toggle-btn {
  margin-left: auto; font-size: 11px; color: #58a6ff;
  cursor: pointer; padding: 2px 8px;
  border: 1px solid #1f6feb; border-radius: 10px;
  background: transparent;
  transition: background 0.15s;
  white-space: nowrap;
}
.dev-toggle-btn:hover { background: #1f3a5f; }

.dev-llm-list { display: flex; flex-direction: column; gap: 6px; }
.dev-llm-item {
  background: #0d1117; border: 1px solid #21262d;
  border-radius: 6px; overflow: hidden;
}
.dev-llm-title-row {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 10px; cursor: pointer;
  transition: background 0.12s;
}
.dev-llm-title-row:hover { background: #161b22; }
.dev-llm-doc-title {
  flex: 1; font-size: 12px; color: #c9d1d9;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.dev-llm-badge { font-size: 10px; white-space: nowrap; }
.badge-ok { color: #3fb950; }
.badge-title { color: #f59e0b; }
.badge-none { color: #484f58; }

.dev-llm-detail {
  display: grid; grid-template-columns: 1fr 24px 1fr;
  gap: 0; border-top: 1px solid #21262d;
}
.dev-llm-col { padding: 10px 12px; }
.dev-llm-arrow {
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; color: #8b949e;
  background: #0a0d12; border-left: 1px solid #21262d; border-right: 1px solid #21262d;
}
.dev-llm-col-label {
  font-size: 10px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.06em; color: #8b949e; margin-bottom: 6px;
}
.col-label-sub { font-weight: 400; text-transform: none; letter-spacing: 0; color: #484f58; }
.dev-llm-text { font-size: 12px; line-height: 1.6; }
.dev-llm-raw { color: #8b949e; font-style: italic; }
.dev-llm-ai { color: #79c0ff; }
.dev-llm-points {
  display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px;
}
.dev-llm-point {
  font-size: 11px; background: #1f3a5f; color: #79c0ff;
  padding: 2px 7px; border-radius: 10px;
}
.dev-llm-reason {
  font-size: 11px; color: #8b949e; margin-top: 6px;
  font-style: italic; border-top: 1px solid #21262d; padding-top: 6px;
}

/* Funnel */
.dev-funnel {
  display: flex; align-items: center; flex-wrap: wrap;
  gap: 8px; padding: 10px 0 4px;
}
.funnel-node {
  display: flex; flex-direction: column; align-items: center;
  background: #21262d; border-radius: 8px; padding: 8px 16px;
  min-width: 72px;
}
.funnel-final { background: #1a3d1f; border: 1px solid #238636; }
.funnel-num { font-size: 22px; font-weight: 700; color: #e6edf3; line-height: 1; }
.funnel-final .funnel-num { color: #3fb950; }
.funnel-label { font-size: 11px; color: #8b949e; margin-top: 3px; }
.funnel-op { font-size: 12px; color: #8b949e; white-space: nowrap; }

.dev-no-data { font-size: 12px; color: #484f58; padding: 6px 0; }
</style>
