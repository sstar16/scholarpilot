<template>
  <div class="cutoff-bar">
    <div class="cutoff-label">
      <span class="cutoff-icon">&#x2694;</span>
      <span>斩杀线</span>
    </div>
    <el-slider
      v-model="cutoff"
      :min="0"
      :max="10"
      :step="0.5"
      :show-tooltip="true"
      :format-tooltip="(v: number) => v.toFixed(1)"
      class="cutoff-slider"
      @change="onCutoffChange"
    />
    <div class="cutoff-stats">
      <span class="stat-above">{{ aboveCount }} 篇过线</span>
      <span class="stat-below">{{ belowCount }} 篇淘汰</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'

const props = defineProps<{
  modelValue: number
  documents: any[]
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: number): void
}>()

const cutoff = ref(props.modelValue)
watch(() => props.modelValue, v => { cutoff.value = v })

const aboveCount = computed(() =>
  props.documents.filter(d => d.agent_score != null && d.agent_score >= cutoff.value).length
)
const belowCount = computed(() =>
  props.documents.filter(d => d.agent_score != null && d.agent_score < cutoff.value).length
)

function onCutoffChange(v: number) {
  emit('update:modelValue', v)
}
</script>

<style scoped>
.cutoff-bar {
  display: flex; align-items: center; gap: 16px;
  padding: 10px 18px;
  background: var(--paper-cool);
  border: 1px solid var(--ink-100);
  border-radius: var(--radius-lg);
  margin-bottom: 12px;
}
.cutoff-label {
  display: flex; align-items: center; gap: 6px;
  font-size: 13px; font-weight: 600; color: var(--ink-600);
  white-space: nowrap;
}
.cutoff-icon { font-size: 16px; }
.cutoff-slider { flex: 1; }
.cutoff-stats {
  display: flex; gap: 12px; font-size: 12px; font-weight: 500; white-space: nowrap;
}
.stat-above { color: var(--signal-teal); }
.stat-below { color: var(--ink-300); }
</style>
