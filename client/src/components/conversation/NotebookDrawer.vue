<template>
  <el-drawer
    :model-value="store.panelOpen"
    direction="rtl"
    size="70%"
    :with-header="false"
    :close-on-click-modal="true"
    :close-on-press-escape="true"
    @update:model-value="onToggle"
    @open="onOpen"
  >
    <div class="notebook">
      <!-- 浮动关闭按钮（任何状态可见） -->
      <button class="notebook-close" @click="onClose" title="关闭（Esc）">
        <el-icon :size="18"><Close /></el-icon>
      </button>
      <!-- Left aside: pages list -->
      <aside class="pages">
        <header class="pages-head">
          <el-icon :size="16"><Notebook /></el-icon>
          <span class="title">项目笔记</span>
          <span class="count">{{ store.pages.length }} 页</span>
          <div class="spacer" />
          <el-button
            size="small"
            :disabled="!store.pages.length"
            :title="store.pages.length ? '导出全部笔记为 Markdown' : '笔记本为空'"
            @click="onExport"
          >
            <el-icon><Download /></el-icon>
          </el-button>
          <el-button size="small" type="primary" @click="onNewPage">
            <el-icon><Plus /></el-icon>
          </el-button>
        </header>
        <div class="pages-list">
          <div
            v-for="p in store.pages"
            :key="p.id"
            class="page-item"
            :class="{
              active: p.id === store.currentPageId,
              'ai-ping': p.id === store.lastAiUpdate?.page_id,
            }"
            @click="selectWithCheck(p.id)"
          >
            <div class="pi-title">{{ p.title || '未命名' }}</div>
            <div class="pi-meta">
              <span v-if="p.updated_by === 'ai'" class="pi-tag ai">AI</span>
              <span v-else-if="p.updated_by === 'user'" class="pi-tag user">你</span>
              <span class="pi-time">{{ formatTime(p.updated_at) }}</span>
            </div>
          </div>
          <div v-if="!store.pages.length && !store.loading" class="pages-empty">
            <p>笔记本空</p>
            <el-button size="small" @click="onNewPage">新建第一页</el-button>
          </div>
        </div>
      </aside>

      <!-- Right: editor -->
      <main class="editor">
        <div v-if="store.lastAiUpdate && store.currentPageId === store.lastAiUpdate.page_id" class="ai-banner">
          <el-icon><MagicStick /></el-icon>
          <span>AI 刚刚 <strong>{{ modeLabel(store.lastAiUpdate.mode) }}</strong> 了本页</span>
          <span v-if="store.lastAiUpdate.reason" class="reason">· {{ store.lastAiUpdate.reason }}</span>
          <span class="delta">{{ store.lastAiUpdate.prev_len }} → {{ store.lastAiUpdate.new_len }}</span>
          <el-button size="small" text @click="store.dismissAiUpdate()">忽略</el-button>
        </div>

        <div v-if="store.currentPage" class="editor-wrap">
          <div class="editor-head">
            <el-input
              v-model="titleDraft"
              size="large"
              placeholder="页面标题"
              class="title-input"
              :maxlength="200"
            />
            <el-segmented
              v-model="mode"
              :options="[
                { label: '编辑', value: 'edit' },
                { label: '预览', value: 'preview' },
                { label: '并排', value: 'split' },
              ]"
              size="small"
            />
            <el-button size="small" :disabled="!dirty" @click="resetDraft">丢弃</el-button>
            <el-button size="small" type="primary" :loading="store.saving" :disabled="!dirty" @click="save">
              保存
            </el-button>
            <el-button size="small" type="danger" text @click="confirmDelete">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
          <div v-if="dirty" class="dirty-bar">● 有未保存的修改</div>
          <div class="editor-body" :class="{ 'is-split': mode === 'split' }">
            <textarea
              v-if="mode === 'edit' || mode === 'split'"
              v-model="bodyDraft"
              class="body-editor"
              placeholder="用 Markdown 记录本页的研究发现..."
              spellcheck="false"
            />
            <article
              v-if="mode === 'preview' || mode === 'split'"
              class="body-preview"
              v-html="rendered"
            />
          </div>
        </div>

        <div v-else class="editor-empty">
          <el-icon :size="36"><Notebook /></el-icon>
          <p>请在左侧选择或新建一个页面</p>
        </div>
      </main>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Notebook, Plus, Delete, MagicStick, Close, Download } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { useNotebookStore } from '../../stores/notebook'
import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()

const store = useNotebookStore()

const mode = ref<'edit' | 'preview' | 'split'>('split')
const titleDraft = ref('')
const bodyDraft = ref('')

const md = new MarkdownIt({ html: false, breaks: true, linkify: true, typographer: true })
const rendered = computed(() => md.render(bodyDraft.value || '_（空页）_'))

const dirty = computed(() => {
  const p = store.currentPage
  if (!p) return false
  return (titleDraft.value !== p.title) || (bodyDraft.value !== p.body_md)
})

function modeLabel(m: string): string {
  return { create_page: '新建', update_page: '覆盖', append_to_page: '追加' }[m] || m
}

function formatTime(iso: string | number | null): string {
  if (iso === null || iso === undefined || iso === '') return ''
  try {
    const d = new Date(iso)
    const diff = Date.now() - d.getTime()
    const min = Math.floor(diff / 60000)
    if (min < 1) return '刚刚'
    if (min < 60) return `${min} 分钟前`
    const h = Math.floor(min / 60)
    if (h < 24) return `${h} 小时前`
    return `${Math.floor(h / 24)} 天前`
  } catch {
    return ''
  }
}

function syncFromStore() {
  const p = store.currentPage
  titleDraft.value = p?.title || ''
  bodyDraft.value = p?.body_md || ''
}

// 换页 / store 刷新 → 重置 draft（dirty 时提示）
watch(
  () => store.currentPage,
  () => syncFromStore(),
)

watch(
  () => store.lastAiUpdate,
  (nu) => {
    if (!nu) return
    ElMessage.success({
      message: `AI 在「${nu.title}」做了${modeLabel(nu.mode)}（+${nu.new_len - nu.prev_len} 字符）`,
      duration: 3500,
    })
  },
)

async function onOpen() {
  if (store.projectId) await store.fetchPages(store.projectId)
  syncFromStore()
}

function onToggle(v: boolean) {
  if (!v) onClose()
}

function onClose() {
  if (dirty.value) ElMessage.warning('已关闭；未保存的修改仍保留本次会话')
  store.closePanel()
}

function selectWithCheck(id: string) {
  if (dirty.value) {
    ElMessageBox.confirm('当前页有未保存修改，确认切换？', '未保存提醒', {
      confirmButtonText: '切换（丢弃）',
      cancelButtonText: '取消',
      type: 'warning',
    })
      .then(() => {
        store.selectPage(id)
      })
      .catch(() => { /* stay */ })
  } else {
    store.selectPage(id)
  }
}

async function save() {
  try {
    await store.updateCurrentPage({
      title: titleDraft.value.trim() || '未命名',
      body_md: bodyDraft.value,
    })
    ElMessage.success('已保存')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  }
}

function resetDraft() {
  syncFromStore()
}

async function onNewPage() {
  try {
    const title = (await ElMessageBox.prompt('页面标题', '新建页面', {
      confirmButtonText: '创建',
      cancelButtonText: '取消',
      inputValue: '新页面',
    })).value || '新页面'
    await store.createPage(title, '')
  } catch {
    /* cancelled */
  }
}

async function confirmDelete() {
  const p = store.currentPage
  if (!p) return
  try {
    await ElMessageBox.confirm(
      `确认删除「${p.title}」？此操作不可撤销。`,
      '删除页面',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    await store.deletePage(p.id)
    ElMessage.success('已删除')
  } catch {
    /* cancelled */
  }
}

function onExport() {
  const pid = store.projectId
  if (!pid) {
    ElMessage.warning('未绑定项目')
    return
  }
  const token = auth.token
  const url = `/api/projects/${pid}/notebook/export.md${token ? `?token=${encodeURIComponent(token)}` : ''}`
  // 浏览器直接打开下载；Content-Disposition: attachment 会触发保存
  window.open(url, '_blank')
}
</script>

<style scoped>
.notebook {
  display: flex;
  height: 100%;
  background: var(--paper-warm);
  position: relative;
}
.notebook-close {
  position: absolute;
  top: 10px;
  right: 12px;
  z-index: 20;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 1px solid var(--ink-100);
  background: var(--paper);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--ink-400);
  transition: all var(--duration-fast) var(--ease-out);
}
.notebook-close:hover {
  background: var(--paper-hover);
  color: var(--ink-900);
  border-color: var(--ink-200);
}
.pages {
  width: 260px;
  flex-shrink: 0;
  border-right: 1px solid var(--ink-100);
  background: var(--paper);
  display: flex;
  flex-direction: column;
}
.pages-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--ink-100);
  font-weight: 600;
  font-size: var(--type-sub-size);
  color: var(--ink-900);
  background: var(--signal-teal-bg);
}
.pages-head .title { font-family: var(--font-display); }
.pages-head .count { color: var(--ink-400); font-weight: 400; font-size: var(--type-meta-size); }
.pages-head .spacer { flex: 1; }
.pages-list {
  flex: 1;
  overflow-y: auto;
}
.page-item {
  padding: 10px var(--space-4);
  border-bottom: 1px solid var(--paper-hover);
  cursor: pointer;
  transition: background var(--duration-fast) var(--ease-out);
}
.page-item:hover { background: var(--paper-cool); }
.page-item.active {
  background: var(--signal-teal-bg);
  border-left: 3px solid var(--signal-teal);
  padding-left: calc(var(--space-4) - 3px);
}
.page-item.ai-ping {
  animation: pi-pulse 1.8s ease-in-out infinite;
}
@keyframes pi-pulse {
  0%, 100% { background: var(--paper); }
  50% { background: var(--signal-amber-bg); }
}
.pi-title {
  font-size: 13.5px;
  font-weight: 500;
  color: var(--ink-900);
  line-height: 1.4;
  margin-bottom: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 1;
}
.pi-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--type-micro-size);
  color: var(--ink-300);
}
.pi-tag {
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
}
.pi-tag.ai { background: var(--signal-emerald-bg); color: var(--signal-emerald); }
.pi-tag.user { background: var(--signal-blue-bg); color: var(--signal-blue); }
.pages-empty {
  padding: 30px var(--space-4);
  text-align: center;
  color: var(--ink-300);
}

.editor {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.ai-banner {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-4);
  background: var(--signal-emerald-bg);
  border-bottom: 1px solid var(--signal-emerald);
  color: var(--signal-emerald);
  font-size: var(--type-sub-size);
}
.ai-banner .reason { color: var(--signal-emerald); opacity: 0.8; }
.ai-banner .delta {
  margin-left: auto;
  color: var(--signal-emerald);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  padding-right: var(--space-2);
}
.editor-wrap { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.editor-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--ink-100);
  background: var(--paper);
}
.title-input :deep(.el-input__wrapper) {
  box-shadow: none;
  padding: 0;
  background: transparent;
}
.title-input :deep(.el-input__inner) {
  font-size: 16px;
  font-weight: 600;
  color: var(--ink-900);
  font-family: var(--font-display);
}
.dirty-bar {
  padding: var(--space-2) var(--space-4);
  font-size: var(--type-meta-size);
  color: var(--signal-amber);
  background: var(--signal-amber-bg);
  border-bottom: 1px solid var(--signal-amber);
}
.editor-body {
  flex: 1;
  min-height: 0;
  display: flex;
  overflow: hidden;
}
.editor-body.is-split > * {
  width: 50%;
  border-right: 1px solid var(--ink-100);
}
.editor-body.is-split > :last-child { border-right: 0; }
.body-editor {
  flex: 1;
  padding: 18px 20px;
  border: 0;
  outline: 0;
  resize: none;
  background: transparent;
  font-family: var(--font-mono);
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--ink-900);
  min-height: 100%;
}
.body-preview {
  flex: 1;
  overflow-y: auto;
  padding: 18px 24px;
  font-size: var(--type-body-size);
  line-height: 1.7;
  color: var(--ink-800);
  background: var(--paper);
}
.body-preview :deep(h1), .body-preview :deep(h2), .body-preview :deep(h3) {
  margin-top: 1.2em;
  margin-bottom: 0.4em;
  font-family: var(--font-display);
}
.body-preview :deep(code) {
  background: var(--paper-hover);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-size: var(--type-code-size);
  font-family: var(--font-mono);
}
.body-preview :deep(pre) {
  background: var(--ink-900);
  color: var(--ink-100);
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  overflow-x: auto;
}
.body-preview :deep(blockquote) {
  border-left: 3px solid var(--signal-teal);
  margin: 0.5em 0;
  padding: 0.2em 1em;
  color: var(--ink-500);
  background: var(--paper-cool);
}

.editor-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  color: var(--ink-300);
}
</style>
