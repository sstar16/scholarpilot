<template>
  <div class="view-switcher">
    <button
      v-for="opt in options"
      :key="opt.value"
      class="vs-btn"
      :class="{ 'vs-btn--active': modelValue === opt.value }"
      :title="opt.title"
      @click="$emit('update:modelValue', opt.value)"
    >
      <span class="vs-btn__glyph">{{ opt.glyph }}</span>
      <span class="vs-btn__label">{{ opt.label }}</span>
    </button>
    <div v-if="showExtras" class="vs-divider" />
    <button
      v-if="showExtras"
      class="vs-btn vs-btn--ghost"
      title="项目笔记本"
      @click="$emit('open-notebook')"
    >
      <span class="vs-btn__glyph">📓</span>
      <span class="vs-btn__label">笔记本</span>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

export type ViewMode = 'chat' | 'cards' | 'graph'

const props = withDefaults(
  defineProps<{
    modelValue: ViewMode
    showExtras?: boolean
  }>(),
  { showExtras: true }
)

defineEmits<{
  'update:modelValue': [v: ViewMode]
  'open-notebook': []
}>()

const options = computed<{ value: ViewMode; label: string; glyph: string; title: string }[]>(() => [
  { value: 'chat',  label: '对话流',  glyph: '💬', title: '回到对话流（默认）' },
  { value: 'cards', label: '卡片视图', glyph: '⊞',  title: '按桶分组的文献卡片' },
  { value: 'graph', label: '知识图谱', glyph: '◉',  title: '力导向知识图谱' },
])
</script>

<style scoped>
.view-switcher {
  display: flex;
  gap: 2px;
  background: var(--paper-hover);
  padding: 4px;
  border-radius: var(--radius-md);
  align-items: center;
}

.vs-btn {
  padding: 6px 14px;
  background: transparent;
  color: var(--ink-400);
  border: none;
  border-radius: var(--radius-sm);
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
  transition: all var(--duration-fast) var(--ease-out);
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.vs-btn:hover { color: var(--ink-700); }
.vs-btn--active {
  background: var(--paper);
  color: var(--signal-teal);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.vs-btn__glyph {
  font-size: 13px;
  line-height: 1;
}
.vs-btn__label {
  font-family: var(--font-body);
}

.vs-divider {
  width: 1px;
  background: var(--ink-200);
  margin: 4px 4px;
  align-self: stretch;
}

.vs-btn--ghost:hover {
  background: var(--paper);
  color: var(--ink-700);
}

@media (max-width: 720px) {
  .vs-btn__label { display: none; }
}
</style>
