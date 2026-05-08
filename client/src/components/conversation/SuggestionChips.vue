<script setup lang="ts">
/**
 * 默认态引导气泡（CLAUDE.md 核心框架第 39 行：
 * 「默认态做一定的引导气泡，每个引导气泡是 AI 认为的能触发功能的自然语言，
 * 用户可以直接点击即发送对应自然语言来触发功能。」）
 *
 * 当前 P1.1：仅在 welcome 态显示（messages.length === 0）。
 * 后续 P1.2 跟场景判断（current_round + 文献库非空）联动，
 * idle 态也按 ConversationSession.current_state 显示对应 chip。
 */

defineProps<{
  chips: readonly string[]
  variant?: 'welcome' | 'inline'
}>()

const emit = defineEmits<{
  (e: 'select', chip: string): void
}>()

function onSelect(chip: string) {
  emit('select', chip)
}
</script>

<template>
  <div class="suggestion-chips" :class="[`variant-${variant ?? 'welcome'}`]">
    <button
      v-for="chip in chips"
      :key="chip"
      class="suggestion-chip"
      type="button"
      @click="onSelect(chip)"
    >
      {{ chip }}
    </button>
  </div>
</template>

<style scoped>
.suggestion-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 16px;
  animation: chipsFadeIn 0.6s 0.15s var(--ease-out, cubic-bezier(0.4, 0, 0.2, 1)) both;
}

.suggestion-chip {
  padding: 8px 14px;
  background: rgba(20, 20, 20, 0.04);
  border: 1px solid rgba(20, 20, 20, 0.12);
  border-radius: 999px;
  font-size: 13px;
  color: var(--ink-700, #444);
  cursor: pointer;
  font-family: inherit;
  font-weight: 500;
  letter-spacing: 0.01em;
  transition: all 0.15s ease;
  white-space: nowrap;
}

.suggestion-chip:hover {
  background: rgba(198, 172, 87, 0.12);
  border-color: rgba(198, 172, 87, 0.5);
  color: var(--ink-900, #1a1a1a);
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(198, 172, 87, 0.15);
}

.suggestion-chip:active {
  transform: scale(0.97);
}

.variant-welcome {
  margin-top: 24px;
  max-width: 680px;
}

.variant-inline {
  margin-top: 8px;
  padding: 0 12px;
}

@keyframes chipsFadeIn {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
