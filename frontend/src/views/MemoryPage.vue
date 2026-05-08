<template>
  <div class="mem-page">
    <div class="paper-grid" aria-hidden="true" />

    <!-- Masthead -->
    <header class="mem-masthead">
      <button class="mem-back" @click="router.push('/dashboard')">← 返回首页</button>
      <div class="mem-brand">SCHOLARPILOT</div>
      <div class="mem-issue">MEMORY · {{ todayLabel }}</div>
    </header>

    <div class="mem-hero">
      <div class="mem-eyebrow">— EDITORIAL · YOUR MEMORY —</div>
      <h1 class="mem-title">记忆档案<span class="mem-title__dot">.</span></h1>
      <p class="mem-sub">
        —— 像 Claude Code 一样，用 Markdown 管理你的身份和项目记忆。<b>用户级</b> 跨项目共享（身份/职业/偏好），
        <b>项目级</b> 只作用于当前项目（研究方向/子问题）。AI 检索时两份一起喂给 agent，互不污染。
      </p>
    </div>

    <div class="mem-body">
      <!-- Left nav -->
      <nav class="mem-nav">
        <button
          class="mem-nav__item"
          :class="{ 'is-active': scope === 'user' }"
          @click="scope = 'user'"
        >
          <span class="mem-nav__num">01</span>
          <span class="mem-nav__label">
            <span class="mem-nav__title">用户档案</span>
            <span class="mem-nav__hint">跨项目 · 身份/偏好</span>
          </span>
        </button>
        <button
          class="mem-nav__item"
          :class="{ 'is-active': scope === 'project' }"
          @click="scope = 'project'"
          :disabled="projects.length === 0"
        >
          <span class="mem-nav__num">02</span>
          <span class="mem-nav__label">
            <span class="mem-nav__title">项目记忆</span>
            <span class="mem-nav__hint">
              {{ projects.length === 0 ? '尚无项目' : `共 ${projects.length} 个项目` }}
            </span>
          </span>
        </button>
        <button
          class="mem-nav__item"
          :class="{ 'is-active': scope === 'recipe' }"
          @click="scope = 'recipe'"
          :disabled="projects.length === 0"
        >
          <span class="mem-nav__num">03</span>
          <span class="mem-nav__label">
            <span class="mem-nav__title">项目食谱</span>
            <span class="mem-nav__hint">自动 · 4 桶反馈归纳</span>
          </span>
        </button>
        <div class="mem-nav__sep" />
        <div class="mem-nav__info">
          <div class="mem-nav__info-t">记忆模型</div>
          <p class="mem-nav__info-p">
            Markdown 是权威层，人工编辑优先；<br />
            <b>🪄 从对话提炼</b> 会在你已有内容基础上叠加增补，不会推翻手写部分。
          </p>
        </div>
      </nav>

      <!-- Main -->
      <section class="mem-main">
        <!-- Project picker (only when scope=project | recipe) -->
        <div v-if="scope === 'project' || scope === 'recipe'" class="mem-picker">
          <div class="mem-picker__label">当前项目</div>
          <el-select
            v-model="selectedProjectId"
            placeholder="选择一个项目"
            size="large"
            style="width: 100%; max-width: 420px"
            @change="onProjectChange"
          >
            <el-option
              v-for="p in projects"
              :key="p.id"
              :value="p.id"
              :label="p.title"
            />
          </el-select>
        </div>

        <!-- Toolbar -->
        <div class="mem-toolbar">
          <div class="mem-toolbar__meta">
            <span class="mem-toolbar__eyebrow">— {{ scopeEyebrow }} —</span>
            <span v-if="updatedAtLabel" class="mem-toolbar__time">
              上次更新 · {{ updatedAtLabel }}
            </span>
          </div>
          <div class="mem-toolbar__actions">
            <!-- Recipe: read-only + 重新生成按钮 -->
            <template v-if="scope === 'recipe'">
              <el-tag size="small" effect="plain" type="info">read-only · auto</el-tag>
              <el-button
                size="small"
                :icon="MagicStick"
                :loading="regenerating"
                :disabled="!selectedProjectId"
                @click="regenerateRecipe"
              >重新生成</el-button>
            </template>
            <template v-else>
              <el-button
                size="small"
                :icon="View"
                :type="mode === 'read' ? 'primary' : 'default'"
                @click="mode = 'read'"
              >阅读</el-button>
              <el-button
                size="small"
                :icon="EditPen"
                :type="mode === 'edit' ? 'primary' : 'default'"
                @click="mode = 'edit'"
              >编辑</el-button>
              <el-button
                size="small"
                :icon="MagicStick"
                :loading="refining"
                :disabled="refining || !canRefine"
                @click="refineFromChat"
              >🪄 从对话提炼</el-button>
              <el-button
                v-if="mode === 'edit'"
                size="small"
                type="success"
                :loading="saving"
                :disabled="!dirty"
                @click="save"
              >保存</el-button>
              <el-button
                v-if="mode === 'edit' && dirty"
                size="small"
                @click="resetDraft"
              >撤销</el-button>
            </template>
          </div>
        </div>

        <!-- Content -->
        <div class="mem-content" v-loading="loading">
          <div v-if="mode === 'read'" class="mem-md markdown-body" v-html="renderedHtml" />
          <el-input
            v-else
            v-model="draft"
            type="textarea"
            :rows="28"
            class="mem-editor"
            resize="vertical"
            placeholder="用 Markdown 写下你的记忆…"
            spellcheck="false"
          />
        </div>

        <div class="mem-footnote">
          <b>隐私</b>：这份 Markdown 只对你自己可见，AI 检索时注入到 prompt，不会发给其他用户。<br />
          <b>反污染</b>：用户级和项目级严格分离，不同项目之间不会串扰研究方向。
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { View, EditPen, MagicStick } from '@element-plus/icons-vue'
import { memoryApi, projectApi } from '../api/client'
import { renderMarkdown } from '../composables/useMarkdown'

type Scope = 'user' | 'project' | 'recipe'
type Mode = 'read' | 'edit'

const router = useRouter()

const scope = ref<Scope>('user')
const mode = ref<Mode>('read')
const loading = ref(false)
const saving = ref(false)
const refining = ref(false)
const regenerating = ref(false)

const original = ref('')
const draft = ref('')
const updatedAt = ref<string | null>(null)

const projects = ref<Array<{ id: string; title: string }>>([])
const selectedProjectId = ref<string>('')

const dirty = computed(() => draft.value !== original.value)
const canRefine = computed(
  () => scope.value === 'user' || (scope.value === 'project' && !!selectedProjectId.value)
)

const scopeEyebrow = computed(() => {
  if (scope.value === 'user') return 'USER · CROSS-PROJECT'
  if (scope.value === 'recipe') return 'AUTO RECIPE · MACHINE-GENERATED'
  return 'PROJECT · CURRENT-ONLY'
})

const updatedAtLabel = computed(() => {
  if (!updatedAt.value) return ''
  const d = new Date(updatedAt.value)
  return d.toLocaleString('zh-CN', { hour12: false })
})

const renderedHtml = computed(() => renderMarkdown(draft.value || original.value || '*(空)*'))

const todayLabel = computed(() => {
  const d = new Date()
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`
})

async function loadProjects() {
  try {
    const res = await projectApi.list()
    projects.value = (res.data || []).map((p: any) => ({ id: p.id, title: p.title }))
    if (!selectedProjectId.value && projects.value.length) {
      selectedProjectId.value = projects.value[0].id
    }
  } catch {
    projects.value = []
  }
}

async function loadUserMemory() {
  loading.value = true
  try {
    const res = await memoryApi.getUser()
    original.value = res.data.markdown_text || ''
    draft.value = original.value
    updatedAt.value = res.data.updated_at || null
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载用户记忆失败')
  } finally {
    loading.value = false
  }
}

async function loadProjectMemory() {
  if (!selectedProjectId.value) return
  loading.value = true
  try {
    const res = await memoryApi.getProject(selectedProjectId.value)
    original.value = res.data.markdown_text || ''
    draft.value = original.value
    updatedAt.value = res.data.updated_at || null
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载项目记忆失败')
  } finally {
    loading.value = false
  }
}

async function loadProjectRecipe() {
  if (!selectedProjectId.value) return
  loading.value = true
  try {
    const res = await memoryApi.getProjectRecipe(selectedProjectId.value)
    original.value = res.data.markdown_text || ''
    draft.value = original.value
    updatedAt.value = res.data.updated_at || null
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载项目食谱失败')
  } finally {
    loading.value = false
  }
}

async function regenerateRecipe() {
  if (!selectedProjectId.value) return
  regenerating.value = true
  try {
    const res = await memoryApi.regenerateProjectRecipe(selectedProjectId.value)
    original.value = res.data.markdown_text || ''
    draft.value = original.value
    updatedAt.value = new Date().toISOString()
    ElMessage.success(`食谱已更新（${res.data.stats?.total_classified ?? 0} 篇分类）`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '重新生成失败')
  } finally {
    regenerating.value = false
  }
}

async function onProjectChange() {
  if (scope.value === 'recipe') await loadProjectRecipe()
  else await loadProjectMemory()
}

async function save() {
  if (!dirty.value) return
  if (draft.value.length > 40000) {
    ElMessage.warning('记忆 Markdown 不能超过 40000 字符')
    return
  }
  saving.value = true
  try {
    const res = scope.value === 'user'
      ? await memoryApi.putUser(draft.value)
      : await memoryApi.putProject(selectedProjectId.value, draft.value)
    original.value = res.data.markdown_text || ''
    draft.value = original.value
    updatedAt.value = res.data.updated_at || null
    ElMessage.success('记忆已保存')
    mode.value = 'read'
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

function resetDraft() {
  draft.value = original.value
}

async function refineFromChat() {
  if (!canRefine.value) return
  if (dirty.value) {
    try {
      await ElMessageBox.confirm(
        '有未保存的手动编辑，提炼前会被覆盖。继续吗？',
        '提示',
        { type: 'warning', confirmButtonText: '继续', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  refining.value = true
  try {
    const res = scope.value === 'user'
      ? await memoryApi.refineUserFromChat()
      : await memoryApi.refineProjectFromChat(selectedProjectId.value)
    original.value = res.data.markdown_text || ''
    draft.value = original.value
    updatedAt.value = res.data.updated_at || null
    ElMessage.success('已从对话提炼并更新')
    mode.value = 'read'
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '提炼失败（LLM 可能未就绪）')
  } finally {
    refining.value = false
  }
}

watch(scope, async (s) => {
  mode.value = 'read'
  if (s === 'user') await loadUserMemory()
  else if (s === 'project' && selectedProjectId.value) await loadProjectMemory()
  else if (s === 'recipe' && selectedProjectId.value) await loadProjectRecipe()
})

onMounted(async () => {
  await loadProjects()
  await loadUserMemory()
})
</script>

<style scoped>
.mem-page {
  min-height: 100vh;
  background: var(--paper-cream, #fdfcf8);
  padding: 0 0 60px;
  color: var(--ink-900);
  font-family: var(--font-body);
  position: relative;
}
.paper-grid { z-index: 0; }

/* Masthead */
.mem-masthead {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 48px;
  border-bottom: 1px solid rgba(20, 20, 20, 0.14);
  z-index: 1;
  animation: fadeUp 0.5s var(--ease-out) both;
}
.mem-back {
  background: none;
  border: none;
  color: var(--ink-500);
  cursor: pointer;
  font-family: inherit;
  font-size: 13px;
  padding: 6px 12px;
  border-radius: var(--radius-sm);
  transition: all 0.15s;
}
.mem-back:hover { color: var(--ink-900); background: rgba(20, 20, 20, 0.05); }
.mem-brand {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 900;
  letter-spacing: 0.05em;
}
.mem-issue {
  font-family: var(--font-mono);
  font-size: 10px;
  color: rgba(20, 20, 20, 0.5);
  letter-spacing: 0.2em;
}

/* Hero */
.mem-hero {
  position: relative;
  padding: 48px 48px 24px;
  z-index: 1;
  animation: fadeUp 0.6s 0.1s var(--ease-out) both;
}
.mem-eyebrow {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.35em;
  color: var(--signal-teal);
  margin-bottom: 14px;
}
.mem-title {
  font-family: var(--font-display);
  font-size: 72px;
  font-weight: 900;
  line-height: 0.98;
  letter-spacing: -2px;
  margin: 0 0 16px;
  color: var(--ink-950);
}
.mem-title__dot { color: #c6ac57; }
.mem-sub {
  max-width: 780px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--ink-600);
  margin: 0;
}
.mem-sub b { color: var(--ink-900); }

/* Body */
.mem-body {
  position: relative;
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 32px;
  padding: 28px 48px 0;
  z-index: 1;
}

/* Nav */
.mem-nav {
  display: flex;
  flex-direction: column;
  gap: 6px;
  animation: fadeUp 0.6s 0.18s var(--ease-out) both;
}
.mem-nav__item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 14px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  transition: all 0.2s;
}
.mem-nav__item:hover:not(:disabled) {
  background: rgba(198, 172, 87, 0.06);
  border-color: rgba(198, 172, 87, 0.2);
}
.mem-nav__item:disabled { opacity: 0.45; cursor: not-allowed; }
.mem-nav__item.is-active {
  background: linear-gradient(180deg, #fdfcf8, rgba(198, 172, 87, 0.1));
  border-color: rgba(198, 172, 87, 0.5);
  box-shadow: 0 2px 10px rgba(198, 172, 87, 0.1);
}
.mem-nav__num {
  font-family: var(--font-mono);
  font-size: 20px;
  font-weight: 800;
  color: #c6ac57;
  line-height: 1;
}
.mem-nav__label { display: flex; flex-direction: column; gap: 4px; }
.mem-nav__title {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  color: var(--ink-900);
}
.mem-nav__hint {
  font-size: 11px;
  color: var(--ink-400);
  font-family: var(--font-mono);
  letter-spacing: 0.02em;
}
.mem-nav__sep {
  height: 1px;
  background: rgba(20, 20, 20, 0.1);
  margin: 14px 0 10px;
}
.mem-nav__info {
  padding: 12px 14px;
  background: rgba(20, 20, 20, 0.02);
  border-radius: var(--radius-sm);
  font-size: 11.5px;
  color: var(--ink-500);
}
.mem-nav__info-t {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.15em;
  color: var(--ink-700);
  margin-bottom: 6px;
}
.mem-nav__info-p { margin: 0; line-height: 1.6; }
.mem-nav__info-p b { color: var(--ink-900); }

/* Main */
.mem-main {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
  animation: fadeUp 0.6s 0.22s var(--ease-out) both;
}

.mem-picker {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 14px;
  border: 1px solid rgba(20, 20, 20, 0.1);
  border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.6);
}
.mem-picker__label {
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.15em;
  color: var(--ink-500);
  white-space: nowrap;
}

.mem-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 4px;
  border-bottom: 1px solid rgba(20, 20, 20, 0.08);
}
.mem-toolbar__meta { display: flex; flex-direction: column; gap: 4px; }
.mem-toolbar__eyebrow {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.25em;
  color: #c6ac57;
}
.mem-toolbar__time {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--ink-400);
}
.mem-toolbar__actions { display: flex; gap: 8px; }

.mem-content {
  padding: 20px 24px;
  border: 1px solid rgba(20, 20, 20, 0.1);
  border-radius: var(--radius-md);
  background: #fff;
  box-shadow: 0 2px 10px rgba(20, 20, 20, 0.04);
  min-height: 320px;
}

.mem-md {
  font-size: 14px;
  line-height: 1.75;
  color: var(--ink-800);
}

.mem-editor :deep(.el-textarea__inner) {
  font-family: var(--font-mono);
  font-size: 13.5px;
  line-height: 1.7;
  color: var(--ink-900);
  background: transparent;
  border: none;
  box-shadow: none;
  padding: 0;
  resize: vertical;
}
.mem-editor :deep(.el-textarea__inner:focus) { box-shadow: none; }

.mem-footnote {
  padding: 12px 14px;
  background: rgba(20, 20, 20, 0.02);
  border-left: 3px solid rgba(198, 172, 87, 0.6);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  font-size: 11.5px;
  color: var(--ink-500);
  line-height: 1.7;
}
.mem-footnote b { color: var(--ink-900); }

/* Responsive */
@media (max-width: 900px) {
  .mem-body { grid-template-columns: 1fr; padding: 20px; }
  .mem-hero { padding: 32px 20px 20px; }
  .mem-title { font-size: 48px; }
  .mem-masthead { padding: 16px 20px; }
}
</style>
