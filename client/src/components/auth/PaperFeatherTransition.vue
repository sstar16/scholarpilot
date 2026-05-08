<template>
  <div class="pft">
    <!-- White paper wipe from center -->
    <div class="pft-wipe" />
    <!-- Feather shards -->
    <div
      v-for="s in shards"
      :key="s.id"
      class="pft-shard"
      :style="{
        left: `${s.x}%`,
        width: `${s.size}px`,
        height: `${s.size * 0.6}px`,
        animationDelay: `${s.delay}s`,
        animationDuration: `${s.dur}s`,
        '--rot': `${s.rot}deg`,
      } as any"
    />
    <!-- Masthead overlay (期刊 vol/issue + S.P wordmark) -->
    <div class="pft-masthead">
      <div class="pft-masthead__inner">
        <div class="pft-masthead__issue">VOL. II · ISSUE 04 · 2026</div>
        <div class="pft-masthead__title">ScholarPilot</div>
        <div class="pft-masthead__rule" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onBeforeUnmount } from 'vue'

const props = withDefaults(
  defineProps<{ durationMs?: number; shardCount?: number }>(),
  { durationMs: 2400, shardCount: 14 }
)

const emit = defineEmits<{ done: [] }>()

type Shard = { id: number; x: number; delay: number; rot: number; size: number; dur: number }

// 一次性生成，避免 re-render 重算破坏动画时序
const shards: Shard[] = Array.from({ length: props.shardCount }, (_, i) => ({
  id: i,
  x: Math.random() * 100,
  delay: Math.random() * 0.4,
  rot: (Math.random() - 0.5) * 80,
  size: 40 + Math.random() * 90,
  dur: 1.6 + Math.random() * 0.8,
}))

let timer: ReturnType<typeof setTimeout> | null = null
onMounted(() => {
  timer = setTimeout(() => emit('done'), props.durationMs)
})
onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<style scoped>
.pft {
  position: absolute;
  inset: 0;
  z-index: 60;
  pointer-events: none;
  overflow: hidden;
}

.pft-wipe {
  position: absolute;
  inset: 0;
  background: var(--paper-warm);
  animation: pft-wipe 1.4s var(--ease-out) forwards;
  clip-path: circle(0% at 50% 50%);
}

.pft-shard {
  position: absolute;
  top: 50%;
  background: linear-gradient(135deg, #fff, #f0ead8);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  border-radius: 2px;
  opacity: 0;
  animation-name: pft-feather-fly;
  animation-timing-function: var(--ease-out);
  animation-fill-mode: forwards;
}

.pft-masthead {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: pft-masthead-fade 2.4s ease-out forwards;
  opacity: 0;
}
.pft-masthead__inner { text-align: center; }
.pft-masthead__issue {
  font-family: var(--font-mono);
  font-size: var(--type-micro-size);
  letter-spacing: 0.5em;
  color: var(--signal-teal);
  margin-bottom: 14px;
}
.pft-masthead__title {
  font-family: var(--font-display);
  font-size: 58px;
  font-weight: 900;
  letter-spacing: -1.5px;
  color: var(--ink-950);
  line-height: 1;
}
.pft-masthead__rule {
  width: 80px;
  height: 2px;
  background: #c6ac57;
  margin: 16px auto 0;
}

@keyframes pft-wipe {
  0% { clip-path: circle(0% at 50% 50%); }
  100% { clip-path: circle(150% at 50% 50%); }
}

@keyframes pft-feather-fly {
  0% {
    opacity: 0;
    transform: translate(0, 0) rotate(0deg) scale(0.6);
  }
  20% { opacity: 1; }
  100% {
    opacity: 0;
    transform: translate(calc(var(--rot, 0deg) * 2px), -600px) rotate(var(--rot, 0deg)) scale(1);
  }
}

@keyframes pft-masthead-fade {
  0%, 40% { opacity: 0; transform: scale(0.96); }
  55%, 80% { opacity: 1; transform: scale(1); }
  100% { opacity: 0; transform: scale(1.02); }
}
</style>
