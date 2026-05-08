<template>
  <div v-if="store.toolCalls.length" class="tool-call-list">
    <div
      v-for="tc in store.toolCalls.slice().reverse()"
      :key="tc.call_id"
      class="tool-card"
      :class="{ running: tc.status === 'running', error: tc.status === 'error' }"
    >
      <div class="header" @click="toggle(tc.call_id)">
        <el-icon v-if="tc.status === 'running'" class="spinner" :size="12"><Loading /></el-icon>
        <el-icon v-else-if="tc.status === 'ok'" :size="12" color="#0d9488"><Check /></el-icon>
        <el-icon v-else :size="12" color="#dc2626"><Close /></el-icon>
        <span class="name">{{ tc.tool_name }}</span>
        <span class="agent">· {{ tc.agent }}</span>
        <span v-if="tc.duration_ms" class="duration">{{ tc.duration_ms }}ms</span>
        <el-icon :size="10" class="caret">
          <component :is="expanded.has(tc.call_id) ? ArrowDown : ArrowRight" />
        </el-icon>
      </div>
      <div v-if="expanded.has(tc.call_id)" class="body">
        <div v-if="tc.args && Object.keys(tc.args).length" class="section">
          <div class="label">Args</div>
          <pre>{{ JSON.stringify(tc.args, null, 2) }}</pre>
        </div>
        <div v-if="tc.result_preview" class="section">
          <div class="label">Result</div>
          <pre>{{ tc.result_preview }}</pre>
        </div>
        <div v-if="tc.error" class="section error-text">
          <div class="label">Error</div>
          <pre>{{ tc.error }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Loading, Check, Close, ArrowDown, ArrowRight } from '@element-plus/icons-vue'
import { useWorkbenchStore } from '../../stores/workbench'

const store = useWorkbenchStore()
const expanded = ref(new Set<string>())

function toggle(callId: string) {
  if (expanded.value.has(callId)) {
    expanded.value.delete(callId)
  } else {
    expanded.value.add(callId)
  }
}
</script>

<style scoped>
.tool-call-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tool-card {
  background: var(--paper-cool);
  border: 1px solid var(--ink-200);
  border-radius: 6px;
  overflow: hidden;
}
.tool-card.running {
  border-color: var(--signal-purple-light);
  background: var(--signal-purple-bg);
}
.tool-card.error {
  border-color: var(--signal-coral-bg);
  background: var(--signal-coral-bg);
}
.header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  font-size: 12px;
  cursor: pointer;
  user-select: none;
}
.header .spinner {
  color: var(--signal-purple-light);
  animation: spin 1s linear infinite;
}
.header .name {
  font-family: var(--font-mono);
  font-weight: 600;
  color: var(--ink-800);
}
.header .agent {
  color: var(--ink-300);
  font-size: 11px;
}
.header .duration {
  margin-left: auto;
  color: var(--ink-400);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.header .caret {
  color: var(--ink-300);
}
.body {
  padding: 8px 10px 10px;
  border-top: 1px solid var(--ink-200);
}
.body .section + .section {
  margin-top: 6px;
}
.body .label {
  font-size: 10px;
  font-weight: 600;
  color: var(--ink-400);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 2px;
}
.body pre {
  margin: 0;
  padding: 6px 8px;
  background: var(--paper);
  border: 1px solid var(--ink-200);
  border-radius: 4px;
  font-size: 11px;
  font-family: var(--font-mono);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
  color: var(--ink-700);
}
.body .error-text pre {
  color: var(--signal-coral);
  background: var(--signal-coral-bg);
  border-color: var(--signal-coral-bg);
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
