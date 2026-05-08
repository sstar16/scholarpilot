<template>
  <div class="home-journal-v2">
    <div class="hj2-grid" aria-hidden="true" />

    <!-- Masthead (共享期刊风顶栏) -->
    <div class="hj2-masthead">
      <div class="hj2-masthead__brand">SCHOLARPILOT</div>
      <div class="hj2-masthead__center">目 录 · CONTENTS</div>
      <div class="hj2-masthead__icons">
        <button class="hj2-variant" title="切换到 V1 封面卡片" @click="toggleVariant">
          V1 <span class="hj2-variant__hint">· 封面</span>
        </button>
        <button
          v-if="auth.user?.is_admin"
          class="hj2-variant hj2-admin-btn"
          title="管理员控制台"
          @click="router.push('/admin/users')"
          data-testid="admin-entry"
        >
          ADMIN <span class="hj2-variant__hint">· 控制台</span>
        </button>
        <button class="hj2-ibtn" title="系统设置" @click="router.push('/settings')">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>
          </svg>
        </button>
        <button class="hj2-avatar" @click="router.push('/profile')" title="个人资料">{{ userInitial }}</button>
      </div>
    </div>

    <!-- Body -->
    <div class="hj2-body">
      <!-- ── Left: table of contents ── -->
      <div class="hj2-toc">
        <div class="hj2-eyebrow">— CONTENTS · {{ issueShort }} —</div>
        <h1 class="hj2-title">研究项目<span class="hj2-accent-dot">.</span></h1>
        <div class="hj2-intro">—— 本期收录 {{ String(projects.length).padStart(2, '0') }} 项研究</div>

        <div v-if="loading" class="hj2-loading">
          <div v-for="i in 3" :key="i" class="hj2-skel" />
        </div>

        <div v-else-if="projects.length === 0" class="hj2-empty">
          <div class="hj2-empty__eyebrow">— EMPTY ISSUE —</div>
          <div class="hj2-empty__sub">本期暂无研究项目</div>
          <button class="hj2-btn-dark" @click="router.push('/projects/new')">+ 新 建 项 目</button>
        </div>

        <div v-else>
          <div
            v-for="(p, i) in projects"
            :key="p.id"
            class="hj2-toc-row"
            :class="{ 'is-active': hoverId === p.id || (!hoverId && i === 0) }"
            :style="{ animationDelay: `${0.15 + i * 0.06}s` }"
            @mouseenter="hoverId = p.id"
            @click="router.push(`/projects/${p.id}`)"
          >
            <div class="hj2-toc-row__num">{{ pad2(i + 1) }}</div>
            <div class="hj2-toc-row__body">
              <h3 class="hj2-toc-row__title">{{ p.title }}</h3>
              <div class="hj2-toc-row__meta">
                <span class="hj2-toc-row__status" :style="{ color: statusColor(p.status) }">● {{ statusLabel(p.status) }}</span>
                <span class="hj2-toc-row__sep">·</span>
                <span>第 {{ p.current_round || 0 }} 轮</span>
                <template v-if="getDomains(p).length">
                  <span class="hj2-toc-row__sep">·</span>
                  <span
                    v-for="d in getDomains(p).slice(0, 3)"
                    :key="d"
                    class="hj2-toc-row__tag"
                  >{{ domainLabel(d) }}</span>
                </template>
              </div>
            </div>
            <div class="hj2-toc-row__date">· · · · {{ formatShortDate(p.created_at) }}</div>
            <div v-if="hoverId === p.id" class="hj2-toc-row__marker" />
          </div>

          <button class="hj2-btn-outline" @click="router.push('/projects/new')">+ 新 建 项 目</button>
        </div>
      </div>

      <!-- ── Right: preview (journal inside page) ── -->
      <div class="hj2-preview">
        <transition name="hj2-fade" mode="out-in">
          <div v-if="activeProject" :key="activeProject.id" class="hj2-preview__inner">
            <div class="hj2-preview__eyebrow" :style="{ color: statusColor(activeProject.status) }">
              —— NO. {{ pad2((projects.findIndex((p) => p.id === activeProject!.id) + 1) || 1) }} · FEATURE
            </div>
            <h2 class="hj2-preview__title">{{ activeProject.title }}</h2>
            <p class="hj2-preview__desc">{{ truncate(activeProject.description, 180) || '本项目暂无描述' }}</p>

            <div class="hj2-stats">
              <div class="hj2-stat">
                <div class="hj2-stat__n">{{ activeProject.current_round || 0 }}</div>
                <div class="hj2-stat__l">已进行轮次</div>
              </div>
              <div class="hj2-stat">
                <div class="hj2-stat__n">{{ daysSince(activeProject.created_at) }}</div>
                <div class="hj2-stat__l">创建天数</div>
              </div>
              <div class="hj2-stat">
                <div class="hj2-stat__n">{{ statusLabel(activeProject.status) }}</div>
                <div class="hj2-stat__l">当前状态</div>
              </div>
              <div class="hj2-stat">
                <div class="hj2-stat__n">{{ getDomains(activeProject).length }}</div>
                <div class="hj2-stat__l">研究领域</div>
              </div>
            </div>

            <div class="hj2-feature">
              <div class="hj2-feature__meta">
                <span class="hj2-feature__teal">{{ pad2(projects.findIndex((p) => p.id === activeProject!.id) + 1) }} / {{ pad2(projects.length) }}</span>
                <span>{{ formatFullDate(activeProject.created_at) }}</span>
              </div>
              <div class="hj2-feature__title">{{ activeProject.title }}</div>
              <div class="hj2-feature__sub">
                {{ getDomains(activeProject).map(domainLabel).join(' · ') || '—' }}
              </div>
            </div>

            <button class="hj2-enter-btn" @click="router.push(`/projects/${activeProject.id}`)">
              进入项目 →
            </button>
          </div>
          <div v-else class="hj2-preview__empty">
            <div class="hj2-empty__eyebrow">— NO FEATURE —</div>
            <div class="hj2-empty__sub">鼠标悬停左侧目录，预览会出现在这里</div>
          </div>
        </transition>
      </div>
    </div>

    <FeedbackButton />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'
import { projectApi } from '../api/client'

const toast = useToast()
// PRD §C8: 删 syncProjects / onSyncEvent —— 改成 projectApi.list 直接读 sp-api，写本地 SQLite
import { listProjects, upsertProject } from '@/data/sqlite/repos/projectRepo'
import type { LocalProject } from '@/types/local'
import FeedbackButton from '../components/FeedbackButton.vue'
import { useAuthStore } from '../stores/auth'

type Project = {
  id: string
  title: string
  description: string
  domain: string
  domains?: string[] | null
  status: string
  current_round: number
  created_at: string
}

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const projects = ref<Project[]>([])
const loading = ref(true)
const hoverId = ref<string | null>(null)

const activeProject = computed<Project | null>(() => {
  if (!projects.value.length) return null
  return projects.value.find((p) => p.id === hoverId.value) || projects.value[0]
})

function _localToView(p: LocalProject): Project {
  return {
    id: p.id,
    title: p.title,
    description: p.description,
    domain: p.domain,
    domains: p.domains,
    status: p.status,
    current_round: p.current_round,
    created_at: new Date(p.created_at).toISOString(),
  }
}

async function refreshFromLocal() {
  try {
    const local = await listProjects({ status: 'active' })
    projects.value = local.map(_localToView)
  } catch {
    /* 本地查询不破坏 — 沉默处理 */
  }
}

/**
 * PRD §C8 替代 syncProjects —— 直接 projectApi.list 拉云端 → upsert 本地 SQLite。
 * 不再走 sync orchestrator / event bus。
 */
async function _pullAndUpsertProjects(): Promise<void> {
  const res = await projectApi.list()
  const now = Date.now()
  for (const s of (res.data ?? []) as Array<Record<string, unknown>>) {
    const local: LocalProject = {
      id: String(s.id),
      title: String(s.title ?? ''),
      description: String(s.description ?? ''),
      domain: String(s.domain ?? ''),
      domains: (s.domains as string[] | null) ?? null,
      search_config: (s.search_config as Record<string, unknown> | null) ?? null,
      current_round: Number(s.current_round ?? 0),
      max_rounds: Number(s.max_rounds ?? 0),
      status: (s.status as LocalProject['status']) ?? 'active',
      research_note_md: String(s.research_note_md ?? ''),
      research_note_updated_at: s.research_note_updated_at
        ? Date.parse(String(s.research_note_updated_at))
        : null,
      research_note_updated_by: (s.research_note_updated_by as 'user' | 'ai' | null) ?? null,
      created_at: s.created_at ? Date.parse(String(s.created_at)) : now,
      updated_at: s.updated_at ? Date.parse(String(s.updated_at)) : now,
      last_synced_at: now,
    }
    await upsertProject(local)
  }
}

onMounted(async () => {
  // 1. 立刻读本地缓存 → render（不闪白屏）
  await refreshFromLocal()
  if (projects.value.length > 0) {
    loading.value = false
  }

  // 2. 后台拉云端 → 写本地 → 再 render
  try {
    await _pullAndUpsertProjects()
    await refreshFromLocal()
  } catch (e) {
    if (projects.value.length === 0) {
      toast.error('项目加载失败')
    } else {
      // 本地有缓存 → 静默
    }
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  /* PRD §C8 已删 sync event 订阅 */
})

const userInitial = computed(() =>
  (auth.user?.name || auth.user?.email || '?').charAt(0).toUpperCase()
)

const now = new Date()
const issueShort = `${now.getFullYear()}.${String(now.getMonth() + 1).padStart(2, '0')}`

function toggleVariant() {
  router.replace({ query: {} })
}

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}
function truncate(s: string, max: number): string {
  if (!s) return ''
  return s.length > max ? s.slice(0, max) + '…' : s
}
function daysSince(iso: string): number {
  if (!iso) return 0
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 0
  return Math.max(0, Math.floor((Date.now() - d.getTime()) / (24 * 3600 * 1000)))
}
function formatShortDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`
}
function formatFullDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`
}

const DOMAIN_LABELS: Record<string, string> = {
  biology: '生物医学', chemistry: '化学', materials: '材料科学',
  mechanical: '设备机械', cs: '计算机', physics: '物理学',
  economics: '经济学', environment: '环境科学', other: '其他',
}
function domainLabel(d: string): string { return DOMAIN_LABELS[d] || d }
function getDomains(p: Project): string[] {
  if (p.domains && p.domains.length) return p.domains
  return p.domain ? [p.domain] : []
}

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  active: { label: '进行中', color: 'var(--signal-teal)' },
  awaiting: { label: '待反馈', color: 'var(--signal-amber)' },
  awaiting_feedback: { label: '待反馈', color: 'var(--signal-amber)' },
  paused: { label: '已暂停', color: 'var(--ink-400)' },
  monitoring: { label: '监控中', color: 'var(--signal-emerald)' },
  archived: { label: '已归档', color: 'var(--ink-300)' },
}
function statusLabel(s: string): string { return STATUS_MAP[s]?.label || s }
function statusColor(s: string): string { return STATUS_MAP[s]?.color || 'var(--ink-400)' }
</script>

<style scoped>
.home-journal-v2 {
  position: relative;
  height: 100vh;
  background: var(--paper-warm);
  color: var(--ink-950);
  font-family: var(--font-body);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.hj2-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(120, 100, 80, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(120, 100, 80, 0.04) 1px, transparent 1px);
  background-size: 32px 32px;
  pointer-events: none;
}

/* ── Masthead ── */
.hj2-masthead {
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 48px;
  border-bottom: 1px solid rgba(20, 20, 20, 0.14);
  background: var(--paper-warm);
  z-index: 2;
  animation: hj2-mod-in 0.6s 0.1s both var(--ease-out);
}
.hj2-masthead__brand {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 900;
  letter-spacing: 0.05em;
}
.hj2-masthead__center {
  font-family: var(--font-mono);
  font-size: 10px;
  color: rgba(20, 20, 20, 0.5);
  letter-spacing: 0.2em;
}
.hj2-masthead__icons {
  display: flex;
  align-items: center;
  gap: 10px;
}
.hj2-variant {
  padding: 6px 12px;
  background: transparent;
  border: 1px solid rgba(20, 20, 20, 0.2);
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.2em;
  color: rgba(20, 20, 20, 0.6);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}
.hj2-variant__hint {
  color: rgba(20, 20, 20, 0.4);
  font-weight: 400;
}
.hj2-variant:hover {
  background: var(--ink-950);
  color: var(--paper-warm);
  border-color: var(--ink-950);
}
.hj2-ibtn {
  width: 34px;
  height: 34px;
  background: transparent;
  border: 1px solid rgba(20, 20, 20, 0.12);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ink-500);
  padding: 0;
  transition: all var(--duration-normal) var(--ease-out);
}
.hj2-ibtn:hover {
  background: var(--ink-950);
  color: #c6ac57;
  border-color: var(--ink-950);
}
.hj2-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, #c6ac57, var(--signal-teal));
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  border: 2px solid #fff;
  cursor: pointer;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 900;
  color: #fff;
  letter-spacing: -0.5px;
  transition: transform var(--duration-normal) var(--ease-out);
}
.hj2-avatar:hover { transform: scale(1.08); }

/* ── Body ── */
.hj2-body {
  flex: 1;
  display: grid;
  grid-template-columns: 1.3fr 1fr;
  overflow: hidden;
  position: relative;
}

.hj2-eyebrow {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.35em;
  color: var(--signal-teal);
  margin-bottom: 12px;
}
.hj2-title {
  font-family: var(--font-display);
  font-size: 52px;
  font-weight: 900;
  letter-spacing: -1.2px;
  line-height: 1;
  margin: 0 0 6px;
}
.hj2-accent-dot { color: #c6ac57; }
.hj2-intro {
  font-family: var(--font-display);
  font-size: 14px;
  font-style: italic;
  color: rgba(20, 20, 20, 0.5);
  margin-bottom: 32px;
}

/* ── Left TOC ── */
.hj2-toc {
  padding: 40px 40px 40px 56px;
  overflow-y: auto;
  border-right: 1px solid rgba(20, 20, 20, 0.12);
  animation: hj2-mod-in 0.7s 0.2s both var(--ease-out);
}

.hj2-toc-row {
  display: grid;
  grid-template-columns: 38px 1fr auto;
  gap: 18px;
  align-items: baseline;
  padding: 18px 0;
  border-bottom: 1px solid rgba(20, 20, 20, 0.08);
  cursor: pointer;
  position: relative;
  animation: hj2-mod-in 0.5s var(--ease-spring) both;
  transition: background var(--duration-fast) var(--ease-out);
}

.hj2-toc-row__num {
  font-family: var(--font-mono);
  font-size: 13px;
  color: rgba(20, 20, 20, 0.35);
  font-weight: 600;
  transition: color var(--duration-fast) var(--ease-out);
}
.hj2-toc-row.is-active .hj2-toc-row__num { color: #c6ac57; }

.hj2-toc-row__title {
  margin: 0;
  font-family: var(--font-display);
  font-size: 21px;
  font-weight: 800;
  letter-spacing: -0.3px;
  color: rgba(20, 20, 20, 0.75);
  transition: color var(--duration-fast) var(--ease-out);
  line-height: 1.3;
}
.hj2-toc-row.is-active .hj2-toc-row__title { color: var(--ink-950); }

.hj2-toc-row__meta {
  display: flex;
  gap: 10px;
  margin-top: 8px;
  font-size: 11px;
  color: rgba(20, 20, 20, 0.5);
  align-items: center;
  flex-wrap: wrap;
}
.hj2-toc-row__status { font-weight: 600; }
.hj2-toc-row__sep { color: rgba(20, 20, 20, 0.3); }
.hj2-toc-row__tag {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.05em;
}

.hj2-toc-row__date {
  font-family: var(--font-mono);
  font-size: 11px;
  color: rgba(20, 20, 20, 0.4);
  letter-spacing: 0.1em;
  white-space: nowrap;
}

.hj2-toc-row__marker {
  position: absolute;
  left: -56px;
  top: 50%;
  width: 40px;
  height: 1px;
  background: #c6ac57;
  animation: hj2-line-in 0.25s var(--ease-out) both;
}

.hj2-btn-outline {
  margin-top: 28px;
  padding: 12px 20px;
  background: transparent;
  color: var(--ink-950);
  border: 1.5px solid var(--ink-950);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.25em;
  cursor: pointer;
  font-family: inherit;
  transition: all var(--duration-fast) var(--ease-out);
}
.hj2-btn-outline:hover {
  background: var(--ink-950);
  color: var(--paper-warm);
}

.hj2-btn-dark {
  padding: 12px 24px;
  background: var(--ink-950);
  color: var(--paper-warm);
  border: none;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.25em;
  cursor: pointer;
  font-family: inherit;
  margin-top: 18px;
}

/* ── Right preview ── */
.hj2-preview {
  padding: 40px 48px;
  overflow: hidden;
  position: relative;
  background: linear-gradient(180deg, var(--paper-warm), #f3ecdc);
  animation: hj2-mod-in 0.7s 0.35s both var(--ease-out);
  display: flex;
  flex-direction: column;
}
.hj2-preview__inner {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.hj2-preview__eyebrow {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.3em;
  margin-bottom: 10px;
}
.hj2-preview__title {
  font-family: var(--font-display);
  font-size: 36px;
  font-weight: 900;
  line-height: 1.1;
  letter-spacing: -0.8px;
  margin: 0 0 16px;
  color: var(--ink-950);
}
.hj2-preview__desc {
  font-family: var(--font-display);
  font-size: 15px;
  font-style: italic;
  color: rgba(20, 20, 20, 0.6);
  line-height: 1.7;
  margin: 0 0 22px;
}

.hj2-stats {
  display: flex;
  gap: 18px;
  padding: 14px 0;
  border-top: 1px solid rgba(20, 20, 20, 0.15);
  border-bottom: 1px solid rgba(20, 20, 20, 0.15);
  margin-bottom: 22px;
}
.hj2-stat { flex: 1; min-width: 0; }
.hj2-stat__n {
  font-family: var(--font-display);
  font-size: 24px;
  font-weight: 900;
  letter-spacing: -0.3px;
  line-height: 1.1;
  color: var(--ink-950);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hj2-stat__l {
  font-family: var(--font-mono);
  font-size: 9.5px;
  letter-spacing: 0.2em;
  color: rgba(20, 20, 20, 0.5);
  margin-top: 3px;
}

.hj2-feature {
  background: var(--paper);
  border: 1px solid rgba(20, 20, 20, 0.12);
  padding: 16px 18px;
  box-shadow: 0 8px 24px -12px rgba(20, 20, 20, 0.15);
  margin-bottom: 18px;
}
.hj2-feature__meta {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  font-family: var(--font-mono);
  letter-spacing: 0.15em;
  color: rgba(20, 20, 20, 0.5);
  margin-bottom: 8px;
}
.hj2-feature__teal {
  color: var(--signal-teal);
  font-weight: 700;
}
.hj2-feature__title {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 700;
  line-height: 1.4;
  margin-bottom: 6px;
  color: var(--ink-950);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.hj2-feature__sub {
  font-size: 11.5px;
  color: rgba(20, 20, 20, 0.55);
  line-height: 1.6;
}

.hj2-enter-btn {
  padding: 11px 22px;
  background: var(--ink-950);
  color: var(--paper-warm);
  border: none;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.25em;
  cursor: pointer;
  font-family: inherit;
  align-self: flex-start;
  transition: all var(--duration-fast) var(--ease-out);
  box-shadow: 0 6px 20px rgba(10, 10, 10, 0.2);
}
.hj2-enter-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 28px rgba(10, 10, 10, 0.28);
}

.hj2-preview__empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}

/* ── Loading / empty ── */
.hj2-loading { display: flex; flex-direction: column; gap: 14px; }
.hj2-skel {
  height: 56px;
  background: linear-gradient(90deg, rgba(20, 20, 20, 0.05), rgba(20, 20, 20, 0.1), rgba(20, 20, 20, 0.05));
  background-size: 400% 100%;
  animation: shimmer 1.8s infinite;
  border-radius: 4px;
}
.hj2-empty {
  padding: 40px 24px;
  text-align: center;
  border: 1px dashed rgba(20, 20, 20, 0.2);
  background: var(--paper);
}
.hj2-empty__eyebrow {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.4em;
  color: rgba(20, 20, 20, 0.4);
  margin-bottom: 12px;
}
.hj2-empty__sub {
  font-family: var(--font-display);
  font-size: 14px;
  font-style: italic;
  color: rgba(20, 20, 20, 0.55);
}

/* ── Transitions ── */
.hj2-fade-enter-active,
.hj2-fade-leave-active {
  transition: opacity var(--duration-fast) var(--ease-out), transform var(--duration-fast) var(--ease-out);
}
.hj2-fade-enter-from,
.hj2-fade-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

@keyframes hj2-mod-in {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes hj2-line-in {
  from { width: 0; opacity: 0; }
  to { width: 40px; opacity: 1; }
}

/* ── Responsive ── */
@media (max-width: 960px) {
  .hj2-body { grid-template-columns: 1fr; }
  .hj2-preview { display: none; }
  .hj2-toc { padding: 28px 28px 28px 48px; }
}
</style>
