<template>
  <HomeJournalV2 v-if="isV2" />
  <div v-else class="home-journal">
    <!-- 细网格纸纹 -->
    <div class="hj-grid" aria-hidden="true" />

    <!-- Masthead -->
    <div class="hj-masthead">
      <div class="hj-masthead__brand">SCHOLARPILOT</div>
      <div class="hj-masthead__issue">{{ issueLabel }}</div>
      <div class="hj-masthead__icons">
        <button class="hj-variant-btn" title="切换到 V2 双栏目录" @click="toggleVariant">
          V2 <span class="hj-variant-btn__hint">· 目录</span>
        </button>
        <button class="hj-ibtn" title="记忆档案 (Markdown)" @click="router.push('/memory')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>
            <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>
          </svg>
        </button>
        <button class="hj-ibtn" title="系统设置" @click="router.push('/settings')">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>
          </svg>
        </button>
        <button
          class="hj-avatar"
          title="个人资料 / 登出"
          @click="onAvatarClick"
        >{{ userInitial }}</button>
      </div>
    </div>

    <!-- Hero -->
    <div class="hj-hero">
      <div class="hj-eyebrow">— EDITORIAL · {{ todayLabel }} —</div>
      <div class="hj-hero__row">
        <div>
          <h1 class="hj-hero__title">
            研究项目<span class="hj-hero__title-dot">.</span>
          </h1>
          <p class="hj-hero__sub">
            ——管理你的文献检索与情报追踪，每一个项目都是一期独立的刊号。
          </p>
        </div>
        <button class="hj-cta" @click="router.push('/projects/new')">
          + 新建项目
        </button>
      </div>
      <div class="hj-stats">
        <span><b class="hj-stats__teal">{{ pad2(activeCount) }}</b> ACTIVE PROJECTS</span>
        <span><b class="hj-stats__amber">{{ pad2(awaitingCount) }}</b> AWAITING</span>
        <span><b class="hj-stats__emerald">{{ pad2(recentCount) }}</b> RECENT</span>
        <span class="hj-stats__issn">ISSN 2026-{{ issnTail }}</span>
      </div>
    </div>

    <!-- Project grid -->
    <div class="hj-body">
      <div v-if="loading" class="hj-loading">
        <div v-for="i in 4" :key="i" class="hj-skel">
          <div class="hj-skel__strip" />
          <div class="hj-skel__title" />
          <div class="hj-skel__desc" />
          <div class="hj-skel__foot" />
        </div>
      </div>

      <div v-else-if="projects.length === 0" class="hj-empty">
        <div class="hj-empty__eyebrow">— EMPTY ISSUE —</div>
        <h2 class="hj-empty__title">尚无研究项目</h2>
        <p class="hj-empty__sub">创建你的第一个项目，开始一期独立的刊号</p>
        <button class="hj-cta" @click="router.push('/projects/new')">+ 新建项目</button>
      </div>

      <div v-else class="hj-grid-layout">
        <article
          v-for="(p, i) in projects"
          :key="p.id"
          class="hj-card"
          :style="{ animationDelay: `${0.3 + i * 0.08}s` }"
          @click="router.push(`/projects/${p.id}`)"
        >
          <div class="hj-card__strip">
            <span class="hj-card__status" :style="{ color: statusColor(p.status) }">
              ● {{ statusLabel(p.status) }}
            </span>
            <span class="hj-card__round">ROUND {{ pad2(p.current_round || 0) }}</span>
            <span class="hj-card__doi">{{ fakeDoi(p) }}</span>
          </div>
          <h3 class="hj-card__title">{{ p.title }}</h3>
          <p class="hj-card__desc">{{ truncate(p.description, 100) }}</p>
          <div class="hj-card__foot">
            <div class="hj-card__domains">
              <span
                v-for="d in getDomains(p).slice(0, 3)"
                :key="d"
                class="hj-domain-chip"
              >{{ domainLabel(d) }}</span>
            </div>
            <span class="hj-card__date">{{ formatDate(p.created_at) }}</span>
            <button
              class="hj-card__del"
              title="删除"
              @click.stop="onDelete(p)"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
                <polyline points="3 6 5 6 21 6"/>
                <path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"/>
                <path d="M10 11v6M14 11v6"/>
              </svg>
            </button>
          </div>
        </article>
      </div>
    </div>

    <FeedbackButton />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { projectApi } from '../api/client'
import { useAuthStore } from '../stores/auth'
import HomeJournalV2 from './HomeJournalV2.vue'
import FeedbackButton from '../components/FeedbackButton.vue'

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

const isV2 = computed(() => route.query.variant === 'v2')

function toggleVariant() {
  router.replace({ query: { ...route.query, variant: 'v2' } })
}

onMounted(async () => {
  try {
    const res = await projectApi.list()
    projects.value = res.data || []
  } catch (e) {
    ElMessage.error('项目加载失败')
  } finally {
    loading.value = false
  }
})

const userInitial = computed(() => {
  const name = auth.user?.name || auth.user?.email || '?'
  return name.charAt(0).toUpperCase()
})

// ── Masthead issue label: 基于当前日期生成 "VOL. N · ISSUE MM · MMM YYYY"
const now = new Date()
const MONTH_NAMES = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
const issueLabel = computed(() => {
  const year = now.getFullYear()
  const vol = Math.max(1, year - 2024) // 2025 → VOL I, 2026 → VOL II ...
  const issue = String(now.getMonth() + 1).padStart(2, '0')
  const monthName = MONTH_NAMES[now.getMonth()]
  const volRoman = toRoman(vol)
  return `VOL. ${volRoman} · ISSUE ${issue} · ${monthName} ${year}`
})
const issnTail = computed(() => {
  const mm = String(now.getMonth() + 1).padStart(2, '0')
  const dd = String(now.getDate()).padStart(2, '0')
  return `${mm}${dd}`
})
const todayLabel = computed(() => {
  const mm = String(now.getMonth() + 1).padStart(2, '0')
  const dd = String(now.getDate()).padStart(2, '0')
  return `${mm}.${dd}.${now.getFullYear()}`
})

function toRoman(n: number): string {
  const map: [number, string][] = [
    [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I'],
  ]
  let out = ''
  let x = n
  for (const [val, sym] of map) {
    while (x >= val) { out += sym; x -= val }
  }
  return out || 'I'
}

// ── Stats ──
const activeCount = computed(() => projects.value.filter((p) => p.status === 'active').length)
const awaitingCount = computed(
  () => projects.value.filter((p) => p.status === 'awaiting' || p.status === 'awaiting_feedback').length
)
// "本周新增"：用最近 7 天创建的项目数做 best-effort
const recentCount = computed(() => {
  const weekAgo = Date.now() - 7 * 24 * 3600 * 1000
  return projects.value.filter((p) => new Date(p.created_at).getTime() > weekAgo).length
})

// ── Formatting ──
function pad2(n: number): string {
  return String(n).padStart(2, '0')
}
function truncate(s: string, max: number): string {
  if (!s) return ''
  return s.length > max ? s.slice(0, max) + '…' : s
}
function formatDate(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

const DOMAIN_LABELS: Record<string, string> = {
  biology: '生物医学', chemistry: '化学', materials: '材料科学',
  mechanical: '设备机械', cs: '计算机', physics: '物理学',
  economics: '经济学', environment: '环境科学', other: '其他',
}
function domainLabel(d: string): string {
  return DOMAIN_LABELS[d] || d
}
function getDomains(p: Project): string[] {
  if (p.domains && p.domains.length) return p.domains
  return p.domain ? [p.domain] : []
}

const STATUS_MAP: Record<string, { label: string; color: string }> = {
  active: { label: 'ACTIVE', color: 'var(--signal-teal)' },
  awaiting: { label: 'AWAITING', color: 'var(--signal-amber)' },
  awaiting_feedback: { label: 'AWAITING', color: 'var(--signal-amber)' },
  paused: { label: 'PAUSED', color: 'var(--ink-400)' },
  monitoring: { label: 'MONITORING', color: 'var(--signal-emerald)' },
  archived: { label: 'ARCHIVED', color: 'var(--ink-300)' },
}
function statusLabel(s: string): string {
  return STATUS_MAP[s]?.label || s.toUpperCase()
}
function statusColor(s: string): string {
  return STATUS_MAP[s]?.color || 'var(--ink-400)'
}

// 生成一个"DOI-like"刊号标识 —— 非真 DOI，仅作为期刊风视觉元素
function fakeDoi(p: Project): string {
  const yearShort = String(now.getFullYear()).slice(-2)
  const monthShort = String(now.getMonth() + 1).padStart(2, '0')
  const idHash = (p.id || '').slice(-3).toUpperCase() || '000'
  return `10.SP/${yearShort}${monthShort}.${idHash}`
}

async function onDelete(p: Project) {
  try {
    await ElMessageBox.confirm(`确认删除「${p.title}」？`, '删除项目', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    await projectApi.delete(p.id)
    projects.value = projects.value.filter((x) => x.id !== p.id)
    ElMessage.success('项目已删除')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

function onAvatarClick() {
  router.push('/profile')
}
</script>

<style scoped>
.home-journal {
  position: relative;
  min-height: 100vh;
  background: var(--paper-warm);
  color: var(--ink-950);
  font-family: var(--font-body);
  overflow-x: hidden;
}

/* 细网格纸纹 —— 视觉基础色的"期刊感" */
.hj-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(120, 100, 80, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(120, 100, 80, 0.05) 1px, transparent 1px);
  background-size: 32px 32px;
  pointer-events: none;
}

/* ── Masthead ── */
.hj-masthead {
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 48px;
  border-bottom: 1px solid rgba(20, 20, 20, 0.14);
  animation: hj-mod-in 0.6s 0.1s both var(--ease-out);
}
.hj-masthead__brand {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 900;
  letter-spacing: 0.05em;
}
.hj-masthead__issue {
  font-family: var(--font-mono);
  font-size: 10px;
  color: rgba(20, 20, 20, 0.5);
  letter-spacing: 0.2em;
}
.hj-masthead__icons {
  display: flex;
  align-items: center;
  gap: 10px;
}
.hj-variant-btn {
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
.hj-variant-btn__hint {
  color: rgba(20, 20, 20, 0.4);
  font-weight: 400;
}
.hj-variant-btn:hover {
  background: var(--ink-950);
  color: var(--paper-warm);
  border-color: var(--ink-950);
}
.hj-ibtn {
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
.hj-ibtn:hover {
  background: var(--ink-950);
  color: #c6ac57;
  border-color: var(--ink-950);
}
.hj-avatar {
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
.hj-avatar:hover { transform: scale(1.08); }

/* ── Hero ── */
.hj-hero {
  position: relative;
  padding: 56px 48px 40px;
  max-width: 1200px;
  margin: 0 auto;
  animation: hj-mod-in 0.7s 0.25s both var(--ease-out);
}
.hj-eyebrow {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.35em;
  color: var(--signal-teal);
  margin-bottom: 14px;
}
.hj-hero__row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 48px;
}
.hj-hero__title {
  font-family: var(--font-display);
  font-size: 76px;
  font-weight: 900;
  line-height: 0.98;
  letter-spacing: -2px;
  margin: 0 0 14px;
  color: var(--ink-950);
}
.hj-hero__title-dot { color: #c6ac57; }
.hj-hero__sub {
  font-family: var(--font-display);
  font-size: 16px;
  color: rgba(20, 20, 20, 0.55);
  max-width: 480px;
  font-style: italic;
  line-height: 1.6;
  margin: 0;
}
.hj-cta {
  padding: 14px 22px;
  background: var(--ink-950);
  color: var(--paper-warm);
  border: none;
  font-family: inherit;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.25em;
  cursor: pointer;
  white-space: nowrap;
  box-shadow: 0 6px 20px rgba(10, 10, 10, 0.2);
  transition: transform var(--duration-normal) var(--ease-out), box-shadow var(--duration-normal) var(--ease-out);
}
.hj-cta:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 28px rgba(10, 10, 10, 0.28);
}

.hj-stats {
  display: flex;
  gap: 32px;
  margin-top: 28px;
  padding-top: 20px;
  border-top: 1px solid rgba(20, 20, 20, 0.1);
  font-family: var(--font-mono);
  font-size: 11px;
  color: rgba(20, 20, 20, 0.55);
  letter-spacing: 0.1em;
  flex-wrap: wrap;
}
.hj-stats b { font-weight: 700; }
.hj-stats__teal { color: var(--signal-teal); }
.hj-stats__amber { color: var(--signal-amber); }
.hj-stats__emerald { color: var(--signal-emerald); }
.hj-stats__issn { margin-left: auto; color: rgba(20, 20, 20, 0.35); }

/* ── Body ── */
.hj-body {
  position: relative;
  padding: 0 48px 60px;
  max-width: 1200px;
  margin: 0 auto;
}

.hj-grid-layout {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 28px 32px;
}

.hj-card {
  position: relative;
  background: #fff;
  border: 1px solid rgba(20, 20, 20, 0.12);
  padding: 24px 26px;
  cursor: pointer;
  box-shadow:
    0 1px 0 rgba(20, 20, 20, 0.04),
    0 12px 24px -12px rgba(20, 20, 20, 0.08);
  transition: transform var(--duration-normal) var(--ease-out), box-shadow var(--duration-normal) var(--ease-out);
  animation: hj-mod-in 0.6s both var(--ease-spring);
}
.hj-card:hover {
  transform: translateY(-3px);
  box-shadow:
    0 1px 0 rgba(20, 20, 20, 0.04),
    0 20px 40px -16px rgba(20, 20, 20, 0.15);
}
.hj-card:hover .hj-card__del { opacity: 1; }

.hj-card__strip {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-family: var(--font-mono);
  font-size: 9.5px;
  letter-spacing: 0.2em;
  margin-bottom: 14px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(20, 20, 20, 0.08);
}
.hj-card__status { font-weight: 700; }
.hj-card__round { color: rgba(20, 20, 20, 0.4); }
.hj-card__doi { color: rgba(20, 20, 20, 0.4); }

.hj-card__title {
  font-family: var(--font-display);
  font-size: 22px;
  font-weight: 900;
  line-height: 1.25;
  letter-spacing: -0.3px;
  margin: 0 0 10px;
  color: var(--ink-950);
}
.hj-card__desc {
  font-family: var(--font-display);
  font-size: 13.5px;
  color: rgba(20, 20, 20, 0.6);
  line-height: 1.65;
  margin: 0 0 14px;
  font-style: italic;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.hj-card__foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 12px;
  border-top: 1px dashed rgba(20, 20, 20, 0.1);
  gap: var(--space-2);
}
.hj-card__domains {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  flex: 1;
  min-width: 0;
}
.hj-domain-chip {
  font-size: 10.5px;
  padding: 3px 8px;
  background: var(--paper-warm);
  border: 1px solid rgba(20, 20, 20, 0.1);
  color: rgba(20, 20, 20, 0.65);
  letter-spacing: 0.05em;
}
.hj-card__date {
  font-family: var(--font-mono);
  font-size: 10px;
  color: rgba(20, 20, 20, 0.4);
  letter-spacing: 0.1em;
  white-space: nowrap;
}
.hj-card__del {
  width: 24px;
  height: 24px;
  border: 1px solid transparent;
  background: transparent;
  color: rgba(20, 20, 20, 0.35);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity var(--duration-fast) var(--ease-out), all var(--duration-fast) var(--ease-out);
}
.hj-card__del:hover {
  background: var(--signal-coral-bg);
  color: var(--signal-coral);
  border-color: var(--signal-coral);
}

/* ── Empty ── */
.hj-empty {
  text-align: center;
  padding: 80px 40px;
  border: 1px dashed rgba(20, 20, 20, 0.2);
  background: #fff;
  animation: hj-mod-in 0.5s 0.35s both var(--ease-out);
}
.hj-empty__eyebrow {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.4em;
  color: rgba(20, 20, 20, 0.4);
  margin-bottom: 14px;
}
.hj-empty__title {
  font-family: var(--font-display);
  font-size: 36px;
  font-weight: 900;
  letter-spacing: -0.8px;
  margin: 0 0 8px;
  color: var(--ink-950);
}
.hj-empty__sub {
  font-family: var(--font-display);
  font-size: 14px;
  font-style: italic;
  color: rgba(20, 20, 20, 0.55);
  margin: 0 0 28px;
}

/* ── Loading skeleton ── */
.hj-loading {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 28px 32px;
}
.hj-skel {
  background: #fff;
  border: 1px solid rgba(20, 20, 20, 0.1);
  padding: 24px 26px;
  animation: hj-mod-in 0.5s both var(--ease-out);
}
.hj-skel__strip {
  height: 10px;
  width: 60%;
  background: linear-gradient(90deg, var(--ink-50), var(--ink-100), var(--ink-50));
  background-size: 400% 100%;
  animation: shimmer 1.8s infinite;
  margin-bottom: 18px;
}
.hj-skel__title {
  height: 22px;
  width: 80%;
  background: linear-gradient(90deg, var(--ink-50), var(--ink-100), var(--ink-50));
  background-size: 400% 100%;
  animation: shimmer 1.8s 0.1s infinite;
  margin-bottom: 10px;
}
.hj-skel__desc {
  height: 14px;
  width: 100%;
  background: linear-gradient(90deg, var(--ink-50), var(--ink-100), var(--ink-50));
  background-size: 400% 100%;
  animation: shimmer 1.8s 0.2s infinite;
  margin-bottom: 14px;
}
.hj-skel__foot {
  height: 12px;
  width: 50%;
  background: linear-gradient(90deg, var(--ink-50), var(--ink-100), var(--ink-50));
  background-size: 400% 100%;
  animation: shimmer 1.8s 0.3s infinite;
}

@keyframes hj-mod-in {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ── Responsive ── */
@media (max-width: 900px) {
  .hj-hero__title { font-size: 56px; }
  .hj-grid-layout, .hj-loading { grid-template-columns: 1fr; }
  .hj-hero { padding: 36px 24px 28px; }
  .hj-body { padding: 0 24px 40px; }
  .hj-masthead { padding: 14px 24px; }
  .hj-stats { gap: 16px; font-size: 10px; }
  .hj-stats__issn { display: none; }
}
@media (max-width: 600px) {
  .hj-hero__row { flex-direction: column; align-items: stretch; gap: 20px; }
  .hj-hero__title { font-size: 42px; }
  .hj-masthead__issue { display: none; }
}
</style>
