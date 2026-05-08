<template>
  <el-drawer
    :model-value="collabStore.notePanelOpen"
    direction="rtl"
    size="55%"
    :with-header="false"
    :close-on-click-modal="false"
    @update:model-value="onDrawerToggle"
    @open="onOpen"
  >
    <div class="note-panel">
      <header class="note-panel__header">
        <div class="note-panel__title">
          <el-icon :size="18"><Notebook /></el-icon>
          <span>共同研究笔记</span>
          <el-tag v-if="collabStore.note.updated_by === 'ai'" size="small" type="success" effect="plain">
            最近由 AI 更新
          </el-tag>
          <el-tag v-else-if="collabStore.note.updated_by === 'user'" size="small" effect="plain">
            最近由你编辑
          </el-tag>
          <span class="meta" v-if="collabStore.note.updated_at">
            · {{ formatTime(collabStore.note.updated_at) }}
          </span>
        </div>
        <div class="note-panel__actions">
          <el-segmented
            v-model="mode"
            :options="[
              { label: '编辑', value: 'edit' },
              { label: '预览', value: 'preview' },
              { label: '并排', value: 'split' },
            ]"
            size="small"
          />
          <el-button size="small" :disabled="!dirty || collabStore.noteSaving" @click="resetDraft">
            丢弃
          </el-button>
          <el-button
            size="small"
            type="primary"
            :loading="collabStore.noteSaving"
            :disabled="!dirty"
            @click="save"
          >
            保存
          </el-button>
          <el-button size="small" text @click="close">
            <el-icon><Close /></el-icon>
          </el-button>
        </div>
      </header>

      <div
        v-if="collabStore.lastAiNoteUpdate && collabStore.lastAiNoteUpdate.new_len > 0"
        class="ai-ping"
      >
        <el-icon><MagicStick /></el-icon>
        <div class="ai-ping__text">
          AI 刚才
          <strong>{{ modeLabel(collabStore.lastAiNoteUpdate.mode) }}</strong>
          了笔记
          <span class="ai-ping__reason" v-if="collabStore.lastAiNoteUpdate.reason">
            · {{ collabStore.lastAiNoteUpdate.reason }}
          </span>
          <span class="ai-ping__delta">
            · {{ collabStore.lastAiNoteUpdate.prev_len }} → {{ collabStore.lastAiNoteUpdate.new_len }} 字符
          </span>
        </div>
        <el-button size="small" text @click="reloadFromServer">重新载入</el-button>
        <el-button size="small" text @click="collabStore.dismissAiNoteUpdate()">忽略</el-button>
      </div>

      <div v-if="dirty" class="dirty-bar">
        ● 有未保存的修改
      </div>

      <div class="note-panel__body" :class="{ 'is-split': mode === 'split' }">
        <textarea
          v-if="mode === 'edit' || mode === 'split'"
          v-model="draft"
          class="note-editor"
          placeholder="在这里用 Markdown 记录研究发现。AI 在对话中若认为有值得沉淀的内容，也会主动补充到这里。"
          spellcheck="false"
        />
        <article
          v-if="mode === 'preview' || mode === 'split'"
          class="note-preview"
          v-html="rendered"
        />
      </div>

      <footer class="note-panel__footer">
        <span class="hint">
          支持 Markdown · 用户手动编辑保存时覆盖整份内容 · AI 只会追加/小范围替换
        </span>
      </footer>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Notebook, Close, MagicStick } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { useCollaborationStore } from '../../stores/collaboration'

const collabStore = useCollaborationStore()
const mode = ref<'edit' | 'preview' | 'split'>('split')
const draft = ref('')
const dirty = ref(false)

const md = new MarkdownIt({ html: false, breaks: true, linkify: true, typographer: true })
const rendered = computed(() => md.render(draft.value || '_（笔记为空）_'))

function syncFromStore() {
  draft.value = collabStore.note.content || ''
  dirty.value = false
}

watch(
  () => collabStore.note.content,
  (val) => {
    // AI/服务端更新后：若用户无未保存修改，自动同步；否则留给用户决定
    if (!dirty.value) draft.value = val || ''
  },
)

watch(draft, (val) => {
  if ((collabStore.note.content || '') !== (val || '')) {
    dirty.value = true
  }
})

// AI 主动更新时给一个 toast
watch(
  () => collabStore.lastAiNoteUpdate,
  (nu) => {
    if (!nu) return
    ElMessage.success({
      message: `AI 更新了研究笔记（${modeLabel(nu.mode)} · ${nu.new_len - nu.prev_len >= 0 ? '+' : ''}${nu.new_len - nu.prev_len} 字符）`,
      duration: 3500,
    })
  },
)

function modeLabel(m: string): string {
  return { append: '追加', replace: '重写', patch: '局部修改' }[m] || m
}

function formatTime(iso: string | null): string {
  if (!iso) return ''
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

async function onOpen() {
  try {
    await collabStore.fetchNote()
  } finally {
    syncFromStore()
  }
}

function onDrawerToggle(v: boolean) {
  if (!v) close()
}

function close() {
  if (dirty.value) {
    // 不强拦，只是给个二次提示
    ElMessage.warning('已关闭笔记面板；未保存的改动仍保留在本次会话内')
  }
  collabStore.closeNotePanel()
}

async function save() {
  try {
    await collabStore.saveNote(draft.value)
    dirty.value = false
    ElMessage.success('已保存')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  }
}

function resetDraft() {
  syncFromStore()
}

async function reloadFromServer() {
  await collabStore.fetchNote()
  syncFromStore()
  collabStore.dismissAiNoteUpdate()
}
</script>

<style scoped>
.note-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--paper-warm);
}
.note-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
  background: linear-gradient(135deg, var(--signal-emerald-bg) 0%, var(--signal-teal-bg) 100%);
  border-bottom: 1px solid var(--ink-200);
}
.note-panel__title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-900);
}
.note-panel__title .meta {
  font-weight: 400;
  color: var(--ink-400);
  font-size: 12px;
}
.note-panel__actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.ai-ping {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  background: var(--signal-emerald-bg);
  border-bottom: 1px solid var(--signal-emerald-bg);
  color: var(--signal-emerald);
  font-size: 13px;
}
.ai-ping__text { flex: 1; }
.ai-ping__reason { color: var(--signal-emerald); }
.ai-ping__delta { color: var(--signal-teal); font-variant-numeric: tabular-nums; }
.dirty-bar {
  padding: 6px 18px;
  font-size: 12px;
  color: var(--signal-amber);
  background: var(--signal-amber-bg);
  border-bottom: 1px solid var(--signal-amber-bg);
}
.note-panel__body {
  flex: 1;
  min-height: 0;
  display: flex;
  overflow: hidden;
}
.note-panel__body.is-split > * {
  width: 50%;
  border-right: 1px solid var(--ink-200);
}
.note-panel__body.is-split > :last-child {
  border-right: 0;
}
.note-editor {
  flex: 1;
  padding: 16px 18px;
  border: 0;
  outline: 0;
  resize: none;
  background: transparent;
  font-family: var(--font-mono);
  font-size: 13.5px;
  line-height: 1.65;
  color: var(--ink-900);
  min-height: 100%;
}
.note-preview {
  flex: 1;
  overflow-y: auto;
  padding: 16px 22px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--ink-800);
  background: var(--paper);
}
.note-preview :deep(h1),
.note-preview :deep(h2),
.note-preview :deep(h3) {
  margin-top: 1.2em;
  margin-bottom: 0.4em;
}
.note-preview :deep(code) {
  background: var(--paper-hover);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12.5px;
}
.note-preview :deep(pre) {
  background: var(--ink-900);
  color: var(--ink-200);
  padding: 12px 14px;
  border-radius: 8px;
  overflow-x: auto;
}
.note-preview :deep(blockquote) {
  border-left: 3px solid var(--signal-teal-light);
  margin: 0.5em 0;
  padding: 0.2em 1em;
  color: var(--ink-600);
  background: var(--paper-cool);
}
.note-panel__footer {
  padding: 10px 18px;
  border-top: 1px solid var(--ink-200);
  font-size: 12px;
  color: var(--ink-300);
  background: var(--paper);
}
</style>
