<template>
  <div class="auth-form" :style="cardStyle">
    <div class="af-head">
      <div class="af-title">{{ title }}</div>
      <button
        v-if="mode !== 'login'"
        class="af-back"
        type="button"
        @click="setMode('login')"
      >← 返回登录</button>
    </div>

    <!-- Login tabs: 邮箱 / 手机号 / 微信 (only in login mode, match design prototype) -->
    <div v-if="mode === 'login'" class="af-tabs">
      <button
        v-for="t in tabs"
        :key="t.value"
        type="button"
        class="af-tab"
        :class="{ 'is-active': tab === t.value }"
        :style="tab === t.value ? activeTabStyle : {}"
        @click="setTab(t.value)"
      >{{ t.label }}</button>
    </div>

    <!-- Email tab (also used for register / forgot) -->
    <template v-if="mode !== 'login' || tab === 'email'">
      <div class="af-field">
        <div class="af-label">EMAIL</div>
        <input
          v-model="email"
          class="af-input"
          type="email"
          placeholder="your@email.com"
          autocomplete="email"
          :disabled="loading"
          @focus="onFieldFocus"
          @blur="onFieldBlur"
        />
      </div>

      <div v-if="mode === 'register'" class="af-field">
        <div class="af-label">NAME</div>
        <input
          v-model="name"
          class="af-input"
          type="text"
          placeholder="你的名字"
          autocomplete="name"
          :disabled="loading"
          @focus="onFieldFocus"
          @blur="onFieldBlur"
        />
      </div>

      <div v-if="mode !== 'forgot'" class="af-field">
        <div class="af-label">PASSWORD</div>
        <div class="af-pwd-wrap">
          <input
            v-model="pwd"
            class="af-input af-input--pwd"
            :type="showPwd ? 'text' : 'password'"
            placeholder="至少 6 位"
            :autocomplete="mode === 'register' ? 'new-password' : 'current-password'"
            :disabled="loading"
            @keydown="onKeyDown"
            @focus="onFieldFocus"
            @blur="onFieldBlur"
          />
          <button
            type="button"
            class="af-pwd-toggle"
            tabindex="-1"
            @click="showPwd = !showPwd"
            :aria-label="showPwd ? '隐藏密码' : '显示密码'"
          >
            <svg v-if="showPwd" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 19c-6.5 0-10-7-10-7a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c6.5 0 10 7 10 7a18.5 18.5 0 0 1-2.16 3.19M1 1l22 22M14.12 14.12a3 3 0 1 1-4.24-4.24"/></svg>
            <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>
          </button>
        </div>
        <div v-if="capsOn" class="af-caps">
          <span class="af-caps-dot" />CAPS LOCK 已开启
        </div>
      </div>

      <div v-if="mode === 'register'" class="af-field">
        <div class="af-label">CONFIRM PASSWORD</div>
        <input
          v-model="pwd2"
          class="af-input"
          :type="showPwd ? 'text' : 'password'"
          placeholder="再输一次"
          autocomplete="new-password"
          :disabled="loading"
          @keydown="onKeyDown"
          @focus="onFieldFocus"
          @blur="onFieldBlur"
        />
      </div>
      <!-- 2026-05-08：客户端注册开放，邀请码字段已删除（后端 X-Client-Type=desktop 跳过校验） -->
    </template>

    <!-- Phone tab (login mode only) -->
    <template v-if="mode === 'login' && tab === 'phone'">
      <div class="af-field">
        <div class="af-label">PHONE</div>
        <input
          v-model="phone"
          class="af-input"
          type="tel"
          placeholder="+86 手机号"
          autocomplete="tel"
          :disabled="loading"
          @focus="onFieldFocus"
          @blur="onFieldBlur"
        />
      </div>
      <div class="af-field">
        <div class="af-label">SMS CODE</div>
        <div class="af-sms-row">
          <input
            v-model="smsCode"
            class="af-input af-sms-input"
            type="text"
            maxlength="6"
            inputmode="numeric"
            placeholder="6 位验证码"
            :disabled="loading"
            @focus="onFieldFocus"
            @blur="onFieldBlur"
          />
          <button
            type="button"
            class="af-sms-send"
            :class="{ 'is-cooling': countdown > 0 }"
            :style="smsBtnStyle"
            :disabled="countdown > 0 || loading"
            @click="sendSmsCode"
          >{{ countdown > 0 ? `${countdown}s` : '获取验证码' }}</button>
        </div>
      </div>
    </template>

    <!-- WeChat tab (login mode only) -->
    <template v-if="mode === 'login' && tab === 'wechat'">
      <div class="af-wechat">
        <div class="af-qr">
          <div class="af-qr__frame" />
          <span class="af-qr__hint">[ 微信扫码 ]</span>
        </div>
        <div class="af-wechat__tip">打开微信扫一扫</div>
      </div>
    </template>

    <div class="af-err-slot">
      <transition name="af-err">
        <div v-if="err" class="af-err">⚠ {{ err }}</div>
      </transition>
    </div>

    <!-- Submit CTA (hidden in wechat tab — scan to login, no button needed) -->
    <button
      v-if="!(mode === 'login' && tab === 'wechat')"
      class="af-cta"
      :style="ctaStyle"
      type="button"
      :disabled="loading"
      @click="submit"
    >
      <span v-if="loading" class="af-cta-loading">
        <svg class="af-spinner" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <circle cx="12" cy="12" r="9" stroke-opacity=".25"/>
          <path d="M12 3a9 9 0 0 1 9 9"/>
        </svg>
        验证中…
      </span>
      <span v-else>{{ ctaText }}</span>
    </button>

    <div v-if="mode === 'login'" class="af-links">
      <span @click="setMode('forgot')">忘记密码</span>
      <span @click="setMode('register')">注册新账号 →</span>
    </div>
    <div v-else-if="mode === 'register'" class="af-legal">
      注册即表示同意 <span class="af-legal-link" :style="{ color: accent }">用户协议</span> · <span class="af-legal-link" :style="{ color: accent }">隐私政策</span>
    </div>
    <div v-else class="af-links af-links--center">
      <span @click="setMode('login')">← 返回登录</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../../stores/auth'

type Mode = 'login' | 'register' | 'forgot'
type Tab = 'email' | 'phone' | 'wechat'

const props = withDefaults(
  defineProps<{ accent?: string; initialMode?: Mode }>(),
  { accent: '#c6ac57', initialMode: 'login' }
)

const emit = defineEmits<{
  'focus-field': [point: { x: number; y: number } | null]
  'mode-change': [mode: Mode]
  'login-success': []
}>()

const router = useRouter()
const auth = useAuthStore()

const mode = ref<Mode>(props.initialMode)
const tab = ref<Tab>('email')
const tabs: Array<{ value: Tab; label: string }> = [
  { value: 'email', label: '邮箱' },
  { value: 'phone', label: '手机号' },
  { value: 'wechat', label: '微信' },
]

const email = ref('')
const name = ref('')
const pwd = ref('')
const pwd2 = ref('')
// 2026-05-08：邀请码字段已删除，desktop 客户端开放注册
const phone = ref('')
const smsCode = ref('')
const showPwd = ref(false)
const capsOn = ref(false)
const err = ref('')
const loading = ref(false)
const countdown = ref(0)
let countdownTimer: ReturnType<typeof setInterval> | null = null

watch(() => props.initialMode, (m) => { mode.value = m })

const title = computed(() => ({
  login: '登录',
  register: '创建账号',
  forgot: '重置密码',
}[mode.value]))

const ctaText = computed(() => {
  if (mode.value === 'register') return '注 册'
  if (mode.value === 'forgot') return '发送重置链接'
  if (tab.value === 'phone') return '登 录'
  return '登 录'
})

const cardStyle = computed(() => ({
  '--af-accent': props.accent,
}))

const ctaStyle = computed(() => ({
  background: `linear-gradient(135deg, ${props.accent}, ${props.accent}bb)`,
  boxShadow: `0 8px 24px ${props.accent}55, inset 0 1px 0 rgba(255,255,255,0.3)`,
}))

const activeTabStyle = computed(() => ({
  background: `linear-gradient(135deg, ${props.accent}, ${props.accent}dd)`,
}))

const smsBtnStyle = computed(() => {
  if (countdown.value > 0) return {}
  return {
    color: props.accent,
    borderColor: `${props.accent}55`,
    background: `${props.accent}22`,
  }
})

function setMode(m: Mode) {
  mode.value = m
  err.value = ''
  emit('mode-change', m)
}

function setTab(t: Tab) {
  tab.value = t
  err.value = ''
}

function onFieldFocus(e: FocusEvent) {
  const el = e.target as HTMLElement
  const r = el.getBoundingClientRect()
  emit('focus-field', { x: r.left + r.width / 2, y: r.top + r.height / 2 })
}

function onFieldBlur() {
  emit('focus-field', null)
}

function onKeyDown(e: KeyboardEvent) {
  capsOn.value = typeof e.getModifierState === 'function' && e.getModifierState('CapsLock')
}

function sendSmsCode() {
  err.value = ''
  if (!/^(\+?\d{1,3}[ -]?)?\d{10,11}$/.test(phone.value.replace(/\s/g, ''))) {
    err.value = '请输入有效的手机号'
    return
  }
  ElMessage.info('短信验证码登录暂未开放，请使用邮箱登录')
  countdown.value = 60
  countdownTimer = setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0 && countdownTimer) {
      clearInterval(countdownTimer)
      countdownTimer = null
    }
  }, 1000)
}

onUnmounted(() => {
  if (countdownTimer) clearInterval(countdownTimer)
})

async function submit() {
  err.value = ''

  if (mode.value === 'login' && tab.value === 'phone') {
    if (!/^(\+?\d{1,3}[ -]?)?\d{10,11}$/.test(phone.value.replace(/\s/g, ''))) {
      err.value = '请输入有效的手机号'
      return
    }
    if (smsCode.value.length !== 6) {
      err.value = '请输入 6 位验证码'
      return
    }
    ElMessage.warning('手机号登录暂未开放，请使用邮箱登录')
    return
  }

  if (mode.value === 'forgot') {
    if (!email.value.includes('@')) return (err.value = '请输入有效邮箱地址')
    loading.value = true
    await new Promise((r) => setTimeout(r, 600))
    loading.value = false
    ElMessage.info('重置功能尚未开放，请联系管理员')
    setMode('login')
    return
  }

  if (!email.value.includes('@')) return (err.value = '请输入有效邮箱地址')
  if (pwd.value.length < 6) return (err.value = '密码至少 6 位')

  if (mode.value === 'register') {
    if (!name.value.trim()) return (err.value = '请填写名字')
    if (pwd.value !== pwd2.value) return (err.value = '两次输入的密码不一致')
    // 2026-05-08：邀请码已废弃（desktop 客户端开放注册）
  }

  loading.value = true
  try {
    if (mode.value === 'login') {
      await auth.login(email.value.trim(), pwd.value)
    } else {
      await auth.register(
        email.value.trim(),
        name.value.trim(),
        pwd.value,
      )
    }
    emit('login-success')
  } catch (e: any) {
    err.value = e?.response?.data?.detail || (mode.value === 'login' ? '邮箱或密码错误' : '注册失败')
  } finally {
    loading.value = false
  }
}

defineExpose({ router })
</script>

<style scoped>
.auth-form {
  width: 380px;
  padding: 26px 28px 22px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.06);
  font-family: var(--font-body);
}
.af-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 18px;
}
.af-title {
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 0.02em;
}
.af-back {
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.5);
  font-size: var(--type-micro-size);
  cursor: pointer;
  font-family: inherit;
}
.af-back:hover { color: rgba(255, 255, 255, 0.8); }

.af-tabs {
  display: flex;
  gap: 2px;
  margin-bottom: 16px;
  padding: 3px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 8px;
}
.af-tab {
  flex: 1;
  padding: 7px 0;
  font-size: 12px;
  font-weight: 600;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-family: inherit;
  background: transparent;
  color: rgba(255, 255, 255, 0.55);
  transition: all 0.25s;
}
.af-tab.is-active {
  color: #0a0e14;
}

.af-field { margin-bottom: var(--space-3); }
.af-label {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: rgba(255, 255, 255, 0.45);
  letter-spacing: 0.15em;
  margin-bottom: 6px;
}
.af-input {
  width: 100%;
  padding: 11px 14px;
  background: rgba(0, 0, 0, 0.28);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  color: #fff;
  font-size: 13.5px;
  outline: none;
  font-family: inherit;
  box-sizing: border-box;
  transition: border-color 0.2s, background 0.2s, box-shadow 0.2s;
}
.af-input::placeholder { color: rgba(255, 255, 255, 0.3); }
.af-input:focus {
  border-color: var(--af-accent);
  background: rgba(0, 0, 0, 0.4);
  box-shadow: 0 0 0 3px rgba(198, 172, 87, 0.13);
}
.af-input:disabled { opacity: 0.6; cursor: not-allowed; }

.af-pwd-wrap { position: relative; }
.af-input--pwd { padding-right: 40px; }
.af-pwd-toggle {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  padding: 4px;
  display: flex;
  align-items: center;
}
.af-pwd-toggle:hover { color: rgba(255, 255, 255, 0.85); }

.af-caps {
  font-size: 10.5px;
  color: var(--signal-amber-light);
  margin-top: 5px;
  letter-spacing: 0.05em;
  display: flex;
  align-items: center;
  gap: 5px;
}
.af-caps-dot {
  width: 6px;
  height: 6px;
  border-radius: 3px;
  background: var(--signal-amber-light);
  box-shadow: 0 0 8px var(--signal-amber-light);
}

.af-sms-row { display: flex; gap: 8px; }
.af-sms-input { flex: 1; }
.af-sms-send {
  padding: 0 14px;
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  font-size: 12px;
  cursor: pointer;
  font-family: inherit;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  transition: all 0.2s;
}
.af-sms-send.is-cooling { cursor: default; }
.af-sms-send:disabled { cursor: default; }

.af-wechat { padding: 20px 0 8px; text-align: center; }
.af-qr {
  width: 150px;
  height: 150px;
  margin: 0 auto 10px;
  background: rgba(255, 255, 255, 0.96);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #333;
  font-size: 11px;
  position: relative;
  overflow: hidden;
}
.af-qr__frame {
  position: absolute;
  inset: 20%;
  border: 1.5px dashed rgba(0, 0, 0, 0.15);
  border-radius: 4px;
}
.af-qr__hint {
  font-family: var(--font-mono);
  color: rgba(0, 0, 0, 0.4);
  position: relative;
  z-index: 1;
}
.af-wechat__tip {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.5);
}

.af-err-slot { min-height: 18px; margin-top: var(--space-1); }
.af-err {
  font-size: 11.5px;
  color: #fca5a5;
  letter-spacing: 0.02em;
  animation: af-shake 0.35s;
}
@keyframes af-shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-4px); }
  75% { transform: translateX(4px); }
}

.af-cta {
  width: 100%;
  padding: 13px 0;
  border: none;
  border-radius: 8px;
  color: #0a0e14;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.18em;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.2s var(--ease-out);
  position: relative;
  overflow: hidden;
}
.af-cta:hover:not(:disabled) { transform: translateY(-1px); }
.af-cta:disabled { cursor: default; opacity: 0.7; }
.af-cta-loading {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
}
.af-spinner { animation: af-spin 1s linear infinite; }
@keyframes af-spin { to { transform: rotate(360deg); } }

.af-links {
  display: flex;
  justify-content: space-between;
  margin-top: 14px;
  font-size: 11.5px;
  color: rgba(255, 255, 255, 0.5);
}
.af-links--center { justify-content: center; }
.af-links span { cursor: pointer; transition: color 0.15s; }
.af-links span:hover { color: var(--af-accent); }

.af-legal {
  margin-top: 14px;
  font-size: var(--type-micro-size);
  color: rgba(255, 255, 255, 0.45);
  text-align: center;
  line-height: 1.6;
}
.af-legal-link { cursor: pointer; }

.af-err-enter-active,
.af-err-leave-active { transition: opacity var(--duration-fast) var(--ease-out); }
.af-err-enter-from,
.af-err-leave-to { opacity: 0; }
</style>
