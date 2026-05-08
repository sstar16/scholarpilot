<template>
  <div class="login-scene" :style="{ '--accent': accent } as any">
    <!-- Dark hero layer (shown during login + success) -->
    <template v-if="showHeroLayer">
      <ParticleField
        :focus-point="focusPoint"
        :accelerate="btnHover"
        :density-mult="1.1"
        :glow-color="accent"
      />
      <!-- Darkness veil + glow orbs -->
      <div class="scene-veil" />
      <div class="orb orb--teal" :style="{ background: `radial-gradient(circle, ${accent}33, transparent 60%)` }" />
      <div class="orb orb--blue" />

      <!-- Top bar -->
      <header class="scene-topbar">
        <div class="scene-mark" :class="{ 'is-breathing': pwdFocused }">
          S<span class="scene-mark__dot" :style="{ color: accent }">.</span>P
        </div>
        <div class="scene-topbar__right">
          <span>EN / 中文</span>
          <span>DEV 3.0</span>
        </div>
      </header>

      <!-- Hero content -->
      <div class="scene-hero">
        <div class="scene-eyebrow" :style="{ color: `${accent}cc` }">— SCHOLARPILOT · EST. 2026 —</div>
        <h1 class="scene-title">
          <template v-for="(line, i) in taglineLines" :key="i">
            <span v-for="(part, j) in splitThink(line)" :key="j">
              <em
                v-if="part === '思考'"
                class="scene-title__think"
                :class="{ 'is-breathing': pwdFocused }"
                :style="{ background: `linear-gradient(135deg, ${accent}, #5eead4)`, WebkitBackgroundClip: 'text', backgroundClip: 'text' }"
              >{{ part }}</em>
              <template v-else>{{ part }}</template>
            </span>
            <br v-if="i < taglineLines.length - 1" />
          </template>
        </h1>
        <p class="scene-sub">全领域科研情报检索平台</p>

        <div
          class="auth-wrap"
          @mouseenter="btnHover = true"
          @mouseleave="btnHover = false"
        >
          <AuthForm
            :accent="accent"
            :initial-mode="initialMode"
            @focus-field="onFocusField"
            @mode-change="onModeChange"
            @login-success="onLoginSuccess"
          />
        </div>

        <div class="scene-footer-tags">
          <span>VIBE</span>
          <span>KNOWLEDGE GRAPH</span>
          <span>NOTEBOOK</span>
          <span>INFORM</span>
        </div>
      </div>
    </template>

    <!-- Success transition overlay: 纸张羽毛飞 -->
    <PaperFeatherTransition v-if="phase === 'success'" @done="onTransitionDone" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ParticleField from '../components/auth/ParticleField.vue'
import AuthForm from '../components/auth/AuthForm.vue'
import PaperFeatherTransition from '../components/auth/PaperFeatherTransition.vue'

type Phase = 'login' | 'success'
type Mode = 'login' | 'register' | 'forgot'

const route = useRoute()
const router = useRouter()

const accent = '#c6ac57'
const phase = ref<Phase>('login')
const btnHover = ref(false)
const focusPoint = ref<{ x: number; y: number } | null>(null)
const pwdFocused = ref(false)

const initialMode = computed<Mode>(() => {
  const q = route.query.mode
  if (q === 'register' || q === 'forgot') return q
  return 'login'
})

const taglineLines = ['让科研人员把时间', '花在 思考 上']

const showHeroLayer = computed(() => phase.value === 'login' || phase.value === 'success')

function splitThink(line: string): string[] {
  return line.split(/(思考)/g).filter((s) => s.length > 0)
}

function onFocusField(p: { x: number; y: number } | null) {
  focusPoint.value = p
  // Detect password focus (for breathing title animation)
  const ae = document.activeElement as HTMLInputElement | null
  pwdFocused.value = ae?.type === 'password'
}

function onModeChange(_m: Mode) {
  // Keep URL in sync so refresh preserves mode
  const q = _m === 'login' ? {} : { mode: _m }
  router.replace({ query: q })
}

function onLoginSuccess() {
  phase.value = 'success'
}

function onTransitionDone() {
  router.push('/dashboard')
}

onMounted(() => {
  // If user is already authed, skip to dashboard
  // (leave as-is; router guard should have handled it)
})
</script>

<style scoped>
.login-scene {
  position: fixed;
  inset: 0;
  background: radial-gradient(ellipse at 30% 20%, #0f2a2a 0%, #0a1420 55%, #05080d 100%);
  overflow: hidden;
  color: #fff;
  font-family: var(--font-body);
}

.scene-veil {
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse at center, transparent 20%, rgba(5, 8, 13, 0.92) 100%);
  pointer-events: none;
}

.orb {
  position: absolute;
  pointer-events: none;
  filter: blur(60px);
}
.orb--teal {
  top: -25%; right: -15%;
  width: 700px; height: 700px;
}
.orb--blue {
  bottom: -25%; left: -15%;
  width: 600px; height: 600px;
  background: radial-gradient(circle, rgba(37, 99, 235, 0.18), transparent 60%);
}

.scene-topbar {
  position: absolute;
  top: 0; left: 0; right: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 22px 44px;
  z-index: 3;
}
.scene-mark {
  font-family: var(--font-body);
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -0.5px;
}
.scene-mark.is-breathing {
  animation: scene-breathe 2.2s ease-in-out infinite;
}
.scene-topbar__right {
  display: flex;
  gap: 24px;
  font-size: var(--type-micro-size);
  color: rgba(255, 255, 255, 0.5);
  letter-spacing: 0.15em;
  font-family: var(--font-mono);
}

.scene-hero {
  position: relative;
  z-index: 2;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 90px 40px 40px;
  text-align: center;
}

.scene-eyebrow {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.45em;
  margin-bottom: 22px;
}

.scene-title {
  font-family: var(--font-display);
  font-size: 58px;
  font-weight: 900;
  line-height: 1.12;
  text-align: center;
  margin: 0 0 16px;
  letter-spacing: -1.2px;
  max-width: 760px;
  color: #fff;
}
.scene-title__think {
  font-style: italic;
  font-weight: 900;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  -webkit-background-clip: text;
}
.scene-title__think.is-breathing {
  animation: scene-breathe 2.2s ease-in-out infinite;
}

.scene-sub {
  font-size: 13.5px;
  color: rgba(255, 255, 255, 0.5);
  max-width: 480px;
  line-height: 1.7;
  margin: 0 0 40px;
  font-family: var(--font-display);
}

.auth-wrap { display: flex; justify-content: center; }

.scene-footer-tags {
  margin-top: 38px;
  display: flex;
  gap: 24px;
  font-size: 10px;
  color: rgba(255, 255, 255, 0.3);
  letter-spacing: 0.15em;
  font-family: var(--font-mono);
}

@keyframes scene-breathe {
  0%, 100% { text-shadow: 0 0 0 transparent; }
  50% { text-shadow: 0 0 30px var(--accent, #c6ac57); }
}

/* Responsive: shrink hero on small screens */
@media (max-width: 720px) {
  .scene-title { font-size: 40px; }
  .scene-hero { padding: 60px 20px 30px; }
  .scene-topbar { padding: 16px 20px; }
  .scene-footer-tags { gap: 14px; font-size: 9px; flex-wrap: wrap; justify-content: center; }
}
</style>
