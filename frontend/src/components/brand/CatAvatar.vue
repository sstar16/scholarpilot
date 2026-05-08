<template>
  <div class="cat-avatar" :style="{ width: `${size}px`, height: `${size}px` }">
    <svg
      :width="size * 0.72"
      :height="size * 0.72"
      viewBox="0 0 40 40"
      class="cat-avatar__svg"
    >
      <path class="cat-ear cat-ear--left" d="M10 12 L13 4 L18 11 Z" />
      <path class="cat-ear cat-ear--right" d="M22 11 L27 4 L30 12 Z" />
      <path class="cat-ear-inner" d="M11.5 10.5 L13 6 L16 10 Z" />
      <path class="cat-ear-inner" d="M24 10 L27 6 L28.5 10.5 Z" />

      <ellipse class="cat-head" cx="20" cy="23" rx="12" ry="10.5" />

      <g class="cat-eyes">
        <ellipse class="cat-eye" cx="15.5" cy="22" rx="1.8" ry="2.4" />
        <ellipse class="cat-eye" cx="24.5" cy="22" rx="1.8" ry="2.4" />
        <ellipse class="cat-eye-glint" cx="15.8" cy="21.6" rx="0.5" ry="0.9" />
        <ellipse class="cat-eye-glint" cx="24.8" cy="21.6" rx="0.5" ry="0.9" />
      </g>

      <path class="cat-nose" d="M19 26 L21 26 L20 27.3 Z" />

      <path class="cat-mouth" d="M20 27.3 Q18.5 28.8 17 28" />
      <path class="cat-mouth" d="M20 27.3 Q21.5 28.8 23 28" />

      <line class="cat-whisker" x1="7" y1="24" x2="13" y2="24.5" />
      <line class="cat-whisker" x1="7" y1="26" x2="13" y2="26" />
      <line class="cat-whisker" x1="33" y1="24" x2="27" y2="24.5" />
      <line class="cat-whisker" x1="33" y1="26" x2="27" y2="26" />
    </svg>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ size?: number }>(), { size: 32 })
</script>

<style scoped>
.cat-avatar {
  flex-shrink: 0;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--paper-warm), #faf7f0);
  border: 1.5px solid rgba(20, 20, 20, 0.12);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--shadow-xs);
}
.cat-avatar__svg { overflow: visible; }

.cat-ear { fill: var(--ink-950); }
.cat-ear--left {
  transform-origin: 13px 11px;
  animation: cat-ear-flick 5s infinite;
}
.cat-ear--right {
  transform-origin: 27px 11px;
  animation: cat-ear-flick 5s 0.3s infinite;
}
.cat-ear-inner { fill: #c6ac57; opacity: 0.85; }
.cat-head { fill: var(--ink-950); }

.cat-eyes {
  transform-origin: 20px 22px;
  animation: cat-blink 4.5s infinite;
}
.cat-eye { fill: #c6ac57; }
.cat-eye-glint { fill: #fff; }

.cat-nose { fill: #f5b7a8; }
.cat-mouth {
  fill: none;
  stroke: #c6ac57;
  stroke-width: 0.8;
  stroke-linecap: round;
}
.cat-whisker {
  stroke: #fff;
  stroke-width: 0.5;
  opacity: 0.5;
}

@keyframes cat-blink {
  0%, 92%, 100% { transform: scaleY(1); }
  94%, 98% { transform: scaleY(0.1); }
}
@keyframes cat-ear-flick {
  0%, 90%, 100% { transform: rotate(0); }
  95% { transform: rotate(-8deg); }
}
</style>
