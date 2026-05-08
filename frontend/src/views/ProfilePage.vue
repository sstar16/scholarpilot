<template>
  <div class="profile-page">
    <div class="pp-grid" aria-hidden="true" />

    <!-- Masthead -->
    <div class="pp-masthead">
      <div class="pp-masthead__left">
        <button class="pp-back" @click="router.push('/dashboard')">← BACK</button>
        <div class="pp-masthead__brand">SCHOLARPILOT</div>
      </div>
      <div class="pp-masthead__center">§ PROFILE · 研究者档案</div>
      <div class="pp-masthead__right">
        <button class="pp-gear" @click="router.push('/settings')" title="系统设置">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"/>
            <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>
          </svg>
          设置
        </button>
      </div>
    </div>

    <!-- Content -->
    <div class="pp-content">
      <!-- Left — portrait + signature card -->
      <div class="pp-left">
        <div class="pp-eyebrow">— PORTRAIT —</div>

        <div class="pp-avatar" :style="{ background: currentGradient }">
          <div class="pp-avatar__initial">{{ initialChar }}</div>
          <div class="pp-avatar__plate">PLATE · 001</div>
          <div class="pp-avatar__id">{{ plateTail }}</div>
        </div>

        <div class="pp-swatches">
          <button
            v-for="(grad, i) in GRADIENTS"
            :key="i"
            class="pp-swatch"
            :class="{ 'is-on': avatarIdx === i }"
            :style="{ background: grad }"
            @click="setAvatar(i)"
          />
        </div>

        <div class="pp-sigcard">
          <div class="pp-sigcard__name">{{ data.name || '未命名研究者' }}</div>
          <div class="pp-sigcard__handle">@{{ data.handle || handleFallback }}</div>
          <div v-if="data.role || data.org" class="pp-sigcard__role">
            <template v-if="data.role">{{ data.role }}</template>
            <template v-if="data.role && data.org"> · </template>
            <template v-if="data.org">{{ data.org }}</template>
          </div>
          <div v-if="data.fields.length" class="pp-sigcard__chips">
            <span v-for="f in data.fields" :key="f" class="pp-sigcard__chip">{{ f }}</span>
          </div>
          <div v-if="data.orcid" class="pp-sigcard__orcid">ORCID · {{ data.orcid }}</div>
        </div>

        <button class="pp-logout" @click="onLogout">
          <span>登 出</span>
        </button>
      </div>

      <!-- Right — editable fields -->
      <div class="pp-right">
        <div class="pp-eyebrow">— EDITORIAL · {{ todayLabel }} —</div>
        <h1 class="pp-title">档案<span class="pp-accent-dot">.</span></h1>
        <p class="pp-sub">—— 你的研究者身份会出现在论文笔记的署名中，也会用于订阅推荐的匹配。</p>

        <div class="pp-fields">
          <EditField
            v-for="(f, i) in editFields"
            :key="f.key"
            :label="f.label"
            :sub="f.sub"
            :value="String(data[f.key] ?? '')"
            :mono="f.mono"
            :idx="i + 1"
            @save="(v: string) => updateField(f.key, v)"
          />

          <!-- Fields (chips input) -->
          <div class="pp-ef" :style="{ animationDelay: `${0.15 + 6 * 0.05}s` }">
            <div class="pp-ef__num">§07</div>
            <div class="pp-ef__body">
              <div class="pp-ef__label">研究方向</div>
              <div class="pp-chips-wrap">
                <span
                  v-for="(f, i) in data.fields"
                  :key="f + i"
                  class="pp-chip"
                >
                  {{ f }}
                  <button class="pp-chip__x" @click="removeField(i)">×</button>
                </span>
                <input
                  v-model="fieldDraft"
                  class="pp-chip-input"
                  placeholder="+ 加一个方向，回车确认"
                  @keydown.enter.prevent="addField"
                />
              </div>
              <div class="pp-ef__sub">标签用于订阅推荐；最多 6 个</div>
            </div>
            <div class="pp-ef__actions" />
          </div>

          <!-- Password change -->
          <div class="pp-ef" :style="{ animationDelay: `${0.15 + 7 * 0.05}s` }">
            <div class="pp-ef__num">§08</div>
            <div class="pp-ef__body">
              <div class="pp-ef__label">密码</div>
              <div class="pp-ef__value">上次修改 —— <span class="pp-ef__dim">此功能即将开放</span></div>
              <div class="pp-ef__sub">后端暂未提供密码修改接口，保持登录状态即可</div>
            </div>
            <div class="pp-ef__actions">
              <button class="pp-btn pp-btn--ghost" disabled>修改密码 →</button>
            </div>
          </div>

          <!-- Danger zone -->
          <div class="pp-danger">
            <div>
              <div class="pp-danger__title">注销账号</div>
              <div class="pp-danger__sub">所有研究项目、订阅、笔记将在 30 天后彻底清除 —— 此操作不可恢复。</div>
            </div>
            <button class="pp-btn pp-btn--danger" @click="onDeleteAccount">注 销</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import EditField from '../components/auth/ProfileEditField.vue'

const router = useRouter()
const auth = useAuthStore()

const PROFILE_KEY = 'sp_profile_v1'
const GRADIENTS = [
  'linear-gradient(135deg, #c6ac57, #0d9488)',
  'linear-gradient(135deg, #d97757, #f59e0b)',
  'linear-gradient(135deg, #605bec, #0d9488)',
  'linear-gradient(135deg, #0a0a0a, #c6ac57)',
  'linear-gradient(135deg, #dc2626, #d97706)',
]

type ProfileData = {
  name: string
  handle: string
  email: string
  org: string
  role: string
  orcid: string
  fields: string[]
  avatarIdx: number
}

function loadFromStorage(): Partial<ProfileData> {
  try {
    const raw = localStorage.getItem(PROFILE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

const stored = loadFromStorage()

const data = reactive<ProfileData>({
  // Name/email 优先从 auth store 拿（服务端真值），本地存储里的 handle/org/role/orcid/fields 是前端 draft
  name: stored.name ?? auth.user?.name ?? '',
  handle:
    stored.handle ??
    (auth.user?.email ? String(auth.user.email).split('@')[0] : ''),
  email: auth.user?.email ?? stored.email ?? '',
  org: stored.org ?? '',
  role: stored.role ?? '',
  orcid: stored.orcid ?? '',
  fields: Array.isArray(stored.fields) ? stored.fields : [],
  avatarIdx: typeof stored.avatarIdx === 'number' ? stored.avatarIdx : 0,
})

const avatarIdx = computed(() => data.avatarIdx)
const fieldDraft = ref('')

const editFields: { key: keyof ProfileData; label: string; sub: string; mono?: boolean }[] = [
  { key: 'name', label: '显示名称', sub: '中文姓名 / 常用署名' },
  { key: 'handle', label: '用户名', sub: '唯一 · 不含空格 · 用于主页链接 sp.co/@...', mono: true },
  { key: 'email', label: '邮箱', sub: '用于订阅摘要 · 协作邀请', mono: true },
  { key: 'org', label: '所属机构', sub: '院校 · 实验室 · 公司' },
  { key: 'role', label: '职位', sub: '例如：博士研究生 / 副教授 / 研究员' },
  { key: 'orcid', label: 'ORCID', sub: '开放研究者与贡献者身份标识符', mono: true },
]

const currentGradient = computed(() => GRADIENTS[data.avatarIdx] || GRADIENTS[0])

const initialChar = computed(() => (data.name || data.email || '?').charAt(0).toUpperCase())

const handleFallback = computed(() =>
  (data.email || '').split('@')[0] || 'researcher'
)

const plateTail = computed(() => {
  const src = data.orcid || data.handle || auth.user?.id?.toString() || ''
  return src.slice(-4).padStart(4, '0').toUpperCase()
})

const now = new Date()
const todayLabel = `${String(now.getMonth() + 1).padStart(2, '0')}.${String(now.getDate()).padStart(2, '0')}`

function saveToStorage() {
  localStorage.setItem(PROFILE_KEY, JSON.stringify({ ...data }))
}

watch(data, saveToStorage, { deep: true })

function setAvatar(i: number) {
  data.avatarIdx = i
}

function updateField(key: keyof ProfileData, v: string) {
  if (key === 'fields' || key === 'avatarIdx') return
  ;(data as any)[key] = v
  ElMessage.success('已保存到本地')
}

function addField() {
  const v = fieldDraft.value.trim()
  if (!v) return
  if (data.fields.length >= 6) {
    ElMessage.warning('最多 6 个研究方向')
    return
  }
  if (data.fields.includes(v)) {
    fieldDraft.value = ''
    return
  }
  data.fields.push(v)
  fieldDraft.value = ''
}

function removeField(i: number) {
  data.fields.splice(i, 1)
}

function onLogout() {
  auth.logout()
  router.push('/login')
}

async function onDeleteAccount() {
  try {
    await ElMessageBox.confirm(
      '注销账号是不可恢复的操作，后端暂未提供真实删除接口；点击"确认"仅会清除本地会话并退出。',
      '注销确认',
      {
        type: 'warning',
        confirmButtonText: '确认退出',
        cancelButtonText: '取消',
      }
    )
  } catch {
    return
  }
  localStorage.removeItem(PROFILE_KEY)
  auth.logout()
  ElMessage.info('已清除本地档案')
  router.push('/login')
}
</script>

<style scoped>
.profile-page {
  position: relative;
  min-height: 100vh;
  background: var(--paper-warm);
  color: var(--ink-950);
  font-family: var(--font-body);
  overflow-x: hidden;
}
.pp-grid {
  position: fixed;
  inset: 0;
  background-image:
    linear-gradient(rgba(120, 100, 80, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(120, 100, 80, 0.04) 1px, transparent 1px);
  background-size: 32px 32px;
  pointer-events: none;
}

/* ── Masthead ── */
.pp-masthead {
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 48px;
  border-bottom: 1px solid rgba(20, 20, 20, 0.14);
  background: var(--paper-warm);
  z-index: 2;
  animation: pp-mod-in 0.5s var(--ease-out) both;
}
.pp-masthead__left,
.pp-masthead__right {
  display: flex;
  align-items: center;
  gap: 16px;
}
.pp-masthead__brand {
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 900;
  letter-spacing: 0.05em;
}
.pp-masthead__center {
  font-family: var(--font-mono);
  font-size: 10px;
  color: rgba(20, 20, 20, 0.5);
  letter-spacing: 0.2em;
}
.pp-back,
.pp-gear {
  background: transparent;
  border: 1px solid rgba(20, 20, 20, 0.2);
  padding: 6px 14px;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.2em;
  color: var(--ink-950);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.pp-back:hover,
.pp-gear:hover {
  background: var(--ink-950);
  color: var(--paper-warm);
  border-color: var(--ink-950);
}

/* ── Content ── */
.pp-content {
  position: relative;
  max-width: 1200px;
  margin: 0 auto;
  padding: 48px 48px 80px;
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 56px;
  animation: pp-mod-in 0.6s 0.1s var(--ease-out) both;
}

.pp-eyebrow {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.4em;
  color: var(--signal-teal);
  margin-bottom: 14px;
}

/* ── Left: portrait ── */
.pp-avatar {
  position: relative;
  width: 100%;
  aspect-ratio: 1;
  margin-bottom: 16px;
  box-shadow: 0 12px 40px -16px rgba(20, 20, 20, 0.3);
  overflow: hidden;
}
.pp-avatar__initial {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-size: 120px;
  font-weight: 900;
  color: rgba(255, 255, 255, 0.9);
  letter-spacing: -4px;
  text-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
}
.pp-avatar__plate,
.pp-avatar__id {
  position: absolute;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.3em;
  color: rgba(255, 255, 255, 0.7);
}
.pp-avatar__plate { top: 12px; left: 12px; }
.pp-avatar__id { bottom: 12px; right: 12px; }

.pp-swatches {
  display: flex;
  gap: 8px;
  margin-bottom: 24px;
}
.pp-swatch {
  width: 36px;
  height: 36px;
  border: 1px solid rgba(20, 20, 20, 0.15);
  cursor: pointer;
  padding: 0;
  transition: all var(--duration-fast) var(--ease-out);
}
.pp-swatch.is-on {
  border: 2px solid var(--ink-950);
  transform: scale(1.1);
}

/* ── Signature card ── */
.pp-sigcard {
  background: var(--paper);
  border: 1px solid rgba(20, 20, 20, 0.12);
  padding: 20px 22px;
  box-shadow: 0 8px 24px -14px rgba(20, 20, 20, 0.18);
  margin-bottom: 16px;
}
.pp-sigcard__name {
  font-family: var(--font-display);
  font-size: 26px;
  font-weight: 900;
  letter-spacing: -0.5px;
  margin-bottom: 4px;
}
.pp-sigcard__handle {
  font-family: var(--font-mono);
  font-size: 11px;
  color: rgba(20, 20, 20, 0.5);
  letter-spacing: 0.1em;
  margin-bottom: 12px;
}
.pp-sigcard__role {
  font-family: var(--font-display);
  font-size: 13px;
  font-style: italic;
  color: rgba(20, 20, 20, 0.7);
  line-height: 1.6;
  border-top: 1px dashed rgba(20, 20, 20, 0.15);
  padding-top: 12px;
}
.pp-sigcard__chips {
  margin-top: 14px;
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.pp-sigcard__chip {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 3px 8px;
  background: var(--paper-warm);
  border: 1px solid rgba(20, 20, 20, 0.12);
  color: rgba(20, 20, 20, 0.6);
  letter-spacing: 0.05em;
}
.pp-sigcard__orcid {
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid rgba(20, 20, 20, 0.08);
  font-family: var(--font-mono);
  font-size: 9.5px;
  color: rgba(20, 20, 20, 0.4);
  letter-spacing: 0.2em;
}

.pp-logout {
  width: 100%;
  padding: 12px;
  background: transparent;
  color: var(--ink-950);
  border: 1px solid var(--ink-950);
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.25em;
  cursor: pointer;
  font-weight: 700;
  transition: all var(--duration-fast) var(--ease-out);
}
.pp-logout:hover {
  background: var(--ink-950);
  color: var(--paper-warm);
}

/* ── Right ── */
.pp-title {
  font-family: var(--font-display);
  font-size: 56px;
  font-weight: 900;
  letter-spacing: -1.2px;
  line-height: 1;
  margin: 0 0 8px;
}
.pp-accent-dot { color: #c6ac57; }
.pp-sub {
  font-family: var(--font-display);
  font-size: 15px;
  font-style: italic;
  color: rgba(20, 20, 20, 0.55);
  margin: 0 0 36px;
  line-height: 1.7;
}

.pp-fields {
  display: flex;
  flex-direction: column;
}

/* ── Edit field ── */
.pp-ef {
  display: grid;
  grid-template-columns: 110px 1fr auto;
  gap: 24px;
  align-items: center;
  padding: 20px 0;
  border-bottom: 1px solid rgba(20, 20, 20, 0.1);
  animation: pp-mod-in 0.4s var(--ease-spring) both;
}
.pp-ef__num {
  font-family: var(--font-mono);
  font-size: 10px;
  color: rgba(20, 20, 20, 0.55);
  letter-spacing: 0.25em;
}
.pp-ef__body { min-width: 0; }
.pp-ef__label {
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 800;
  letter-spacing: -0.2px;
  margin-bottom: 4px;
}
.pp-ef__value {
  font-family: var(--font-display);
  font-size: 15px;
  color: rgba(20, 20, 20, 0.85);
  font-style: italic;
}
.pp-ef__dim { color: rgba(20, 20, 20, 0.4); }
.pp-ef__sub {
  font-size: 11.5px;
  color: rgba(20, 20, 20, 0.5);
  font-style: italic;
  font-family: var(--font-display);
  margin-top: 5px;
}
.pp-ef__actions {
  display: flex;
  gap: 8px;
}

/* Chips input */
.pp-chips-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  margin-top: 6px;
}
.pp-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 4px 4px 4px 10px;
  background: var(--paper-warm);
  border: 1px solid rgba(20, 20, 20, 0.12);
  color: rgba(20, 20, 20, 0.75);
  letter-spacing: 0.05em;
}
.pp-chip__x {
  background: transparent;
  border: none;
  cursor: pointer;
  color: rgba(20, 20, 20, 0.4);
  font-size: 14px;
  padding: 0 4px;
  line-height: 1;
}
.pp-chip__x:hover { color: var(--signal-coral); }
.pp-chip-input {
  flex: 1;
  min-width: 180px;
  padding: 5px 8px;
  border: 1px dashed rgba(20, 20, 20, 0.2);
  background: transparent;
  outline: none;
  font-family: inherit;
  font-size: 12.5px;
  color: var(--ink-950);
}
.pp-chip-input:focus {
  border-color: var(--ink-950);
  border-style: solid;
}

/* ── Buttons ── */
.pp-btn {
  padding: 10px 18px;
  border: 1px solid;
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.2em;
  cursor: pointer;
  font-weight: 700;
  transition: all var(--duration-fast) var(--ease-out);
}
.pp-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.pp-btn--ghost {
  background: transparent;
  color: rgba(20, 20, 20, 0.55);
  border-color: rgba(20, 20, 20, 0.15);
}
.pp-btn--danger {
  background: transparent;
  color: var(--signal-coral);
  border-color: var(--signal-coral);
}
.pp-btn--danger:hover {
  background: var(--signal-coral);
  color: #fff;
}

/* ── Danger zone ── */
.pp-danger {
  margin-top: 40px;
  padding: 20px 22px;
  background: var(--paper);
  border: 1px solid rgba(220, 38, 38, 0.25);
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 24px;
  align-items: center;
}
.pp-danger__title {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 800;
  color: var(--signal-coral);
  letter-spacing: -0.2px;
}
.pp-danger__sub {
  font-size: 12px;
  color: rgba(20, 20, 20, 0.55);
  font-style: italic;
  font-family: var(--font-display);
  margin-top: 4px;
  line-height: 1.5;
}

@keyframes pp-mod-in {
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ── Responsive ── */
@media (max-width: 900px) {
  .pp-content {
    grid-template-columns: 1fr;
    padding: 28px 24px 48px;
    gap: 36px;
  }
  .pp-title { font-size: 42px; }
  .pp-masthead { padding: 14px 20px; }
  .pp-masthead__center { display: none; }
  .pp-ef {
    grid-template-columns: 40px 1fr;
    gap: 14px;
  }
  .pp-ef__actions {
    grid-column: 2;
    justify-self: start;
  }
}
</style>
