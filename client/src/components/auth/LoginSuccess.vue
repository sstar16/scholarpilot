<template>
  <div class="login-success">
    <div class="ls-page-left" />
    <div class="ls-page-right" />
    <div class="ls-welcome">
      <div class="ls-welcome-eyebrow">— WELCOME BACK —</div>
      <div class="ls-welcome-title">
        欢迎回到<em>&nbsp;思考</em>
      </div>
      <div class="ls-welcome-sub">正在为你打开文献库 ···</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount } from 'vue'

const props = withDefaults(
  defineProps<{ durationMs?: number }>(),
  { durationMs: 2600 }
)

const emit = defineEmits<{ done: [] }>()

let timer: ReturnType<typeof setTimeout> | null = null
onMounted(() => {
  timer = setTimeout(() => emit('done'), props.durationMs)
})
onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<style scoped>
.login-success {
  position: absolute;
  inset: 0;
  z-index: 50;
  pointer-events: none;
  perspective: 1800px;
}

.ls-page-left {
  position: absolute;
  top: 0;
  left: 0;
  width: 50%;
  height: 100%;
  background: linear-gradient(90deg, rgba(10, 14, 20, 0.95), rgba(10, 14, 20, 0.85));
  border-right: 1px solid rgba(198, 172, 87, 0.3);
  animation: ls-page-l 1.8s var(--ease-out) forwards;
}

.ls-page-right {
  position: absolute;
  top: 0;
  left: 50%;
  width: 50%;
  height: 100%;
  background: linear-gradient(270deg, rgba(10, 14, 20, 0.95), rgba(10, 14, 20, 0.7));
  transform-origin: left center;
  animation: ls-page-r 1.8s var(--ease-out) forwards;
  box-shadow: inset 20px 0 40px -10px rgba(0, 0, 0, 0.5);
}

.ls-welcome {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  animation: ls-welcome-fade 2.6s var(--ease-out) forwards;
  color: #fff;
  text-align: center;
}

.ls-welcome-eyebrow {
  font-family: var(--font-mono);
  font-size: var(--type-micro-size);
  letter-spacing: 0.4em;
  color: #c6ac57;
  margin-bottom: 14px;
}

.ls-welcome-title {
  font-family: var(--font-display);
  font-size: 48px;
  font-weight: 900;
  letter-spacing: -1px;
  line-height: 1.1;
}
.ls-welcome-title em {
  font-style: italic;
  background: linear-gradient(135deg, #c6ac57, #5eead4);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.ls-welcome-sub {
  font-size: var(--type-sub-size);
  color: rgba(255, 255, 255, 0.5);
  margin-top: var(--space-3);
  font-family: var(--font-display);
}

@keyframes ls-page-l {
  0% { transform: translateX(0); }
  100% { transform: translateX(-100%); }
}
@keyframes ls-page-r {
  0% { transform: rotateY(0deg); }
  60% { transform: rotateY(-165deg); }
  100% { transform: rotateY(-180deg); opacity: 0; }
}
@keyframes ls-welcome-fade {
  0%, 20% { opacity: 0; transform: scale(0.96); }
  40%, 70% { opacity: 1; transform: scale(1); }
  100% { opacity: 0; transform: scale(1.02); }
}
</style>
