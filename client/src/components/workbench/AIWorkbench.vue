<template>
  <transition name="fade">
    <div v-if="visible" class="ai-workbench">
      <div class="workbench-header">
        <div class="title">
          <el-icon :size="14" class="wb-title-icon"><MagicStick /></el-icon>
          <span>AI 正在工作</span>
        </div>
        <TokenCounter />
      </div>
      <div class="workbench-body">
        <PhaseTimeline />
        <ToolCallList />
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { MagicStick } from '@element-plus/icons-vue'
import PhaseTimeline from './PhaseTimeline.vue'
import ToolCallList from './ToolCallList.vue'
import TokenCounter from './TokenCounter.vue'
import { useWorkbenchStore } from '../../stores/workbench'
import { useSessionSSE } from '../../composables/useSessionSSE'

const props = defineProps<{
  sessionId: string | null
}>()

const store = useWorkbenchStore()
const { connect, on, disconnect } = useSessionSSE()

// Show only while active (2.5s idle timer auto-fades after last event)
const visible = computed(() => store.active)

// Wire SSE events to store actions
on('agent_phase', (data) => store.applyPhase(data))
on('llm_call_start', (data) => store.applyLLMStart(data))
on('llm_call_end', (data) => store.applyLLMEnd(data))
on('llm_usage_delta', (data) => store.applyLLMUsageDelta(data))
on('tool_call_start', (data) => store.applyToolStart(data))
on('tool_call_end', (data) => store.applyToolEnd(data))

watch(
  () => props.sessionId,
  (sid) => {
    if (sid) {
      connect(sid)
    } else {
      disconnect()
    }
  },
  { immediate: true }
)
</script>

<style scoped>
.ai-workbench {
  background: var(--signal-purple-bg);
  border: 1px solid var(--signal-purple-bg);
  border-radius: var(--radius-md);
  padding: 10px var(--space-3);
  margin: var(--space-2) var(--space-3) var(--space-3);
  box-shadow: var(--shadow-xs);
}
.workbench-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
  padding-bottom: var(--space-2);
  border-bottom: 1px dashed var(--signal-purple-bg);
}
.workbench-header .title {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--type-meta-size);
  font-weight: 600;
  color: var(--signal-purple);
}
.workbench-header .title .wb-title-icon { color: var(--signal-purple); }
.workbench-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease, max-height 0.3s ease;
  overflow: hidden;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  max-height: 0;
  margin: 0 12px;
}
.fade-enter-to,
.fade-leave-from {
  opacity: 1;
  max-height: 400px;
}
</style>
