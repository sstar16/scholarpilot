<template>
  <div class="phase-timeline">
    <div class="current-phase" v-if="store.currentAgent">
      <el-icon class="spinner" :size="14"><Loading /></el-icon>
      <span class="agent">{{ store.currentAgent }}</span>
      <el-icon :size="10"><ArrowRight /></el-icon>
      <span class="phase-label">{{ phaseLabel(store.currentPhase) }}</span>
      <span v-if="store.currentDescription" class="description">· {{ store.currentDescription }}</span>
    </div>
    <div class="phase-history" v-if="store.phaseHistory.length > 1">
      <span v-for="p in store.phaseHistory.slice(0, -1)" :key="p.id" class="phase-chip">
        {{ phaseLabel(p.phase) }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Loading, ArrowRight } from '@element-plus/icons-vue'
import { useWorkbenchStore } from '../../stores/workbench'

const store = useWorkbenchStore()

const PHASE_LABELS: Record<string, string> = {
  analyzing_intent: '理解意图',
  analyzing_intent_fallback: '基础意图分析',
  intent_ready: '意图就绪',
  creating_project: '创建项目',
  routing_intent: '路由中',
  answering_collab_question: '回答协作问题',
  collab_answer_ready: '协作回答就绪',
  answering_research_qa: '回答研究问题',
  research_answer_ready: '研究回答就绪',
}

function phaseLabel(key: string): string {
  return PHASE_LABELS[key] || key
}
</script>

<style scoped>
.phase-timeline {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.current-phase {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--ink-800);
  font-weight: 500;
}
.current-phase .spinner {
  color: var(--signal-purple-light);
  animation: spin 1s linear infinite;
}
.current-phase .agent {
  color: var(--signal-purple-light);
  font-weight: 600;
}
.current-phase .phase-label {
  color: var(--ink-700);
}
.current-phase .description {
  color: var(--ink-300);
  font-size: 12px;
}
.phase-history {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.phase-chip {
  padding: 1px 6px;
  background: var(--paper-hover);
  border-radius: 10px;
  font-size: 11px;
  color: var(--ink-400);
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
