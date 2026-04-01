<template>
  <div class="timeline">
    <div class="timeline-head">
      <span class="head-label">检索进度</span>
      <span class="head-count">{{ activeStep }}/{{ steps.length }}</span>
    </div>

    <div class="steps">
      <div
        v-for="(step, i) in steps"
        :key="i"
        class="step"
        :class="stepClass(i)"
      >
        <div class="step-indicator">
          <div class="step-dot">
            <svg v-if="getStepStatus(i) === 'finish'" width="10" height="10" viewBox="0 0 16 16" fill="currentColor"><path d="M13.485 1.929a1 1 0 0 1 .086 1.32l-.086.094-7.07 7.071a1 1 0 0 1-1.32.086l-.094-.086-3.536-3.535a1 1 0 0 1 1.32-1.497l.094.083L5.9 8.486l5.657-5.657a1 1 0 0 1 1.414 0l.514.1z"/></svg>
            <span v-else-if="getStepStatus(i) === 'process'" class="dot-active"></span>
            <span v-else class="dot-num">{{ i + 1 }}</span>
          </div>
          <div v-if="i < steps.length - 1" class="step-line" :class="{ filled: getStepStatus(i) === 'finish' }"></div>
        </div>
        <div class="step-content">
          <span class="step-title">{{ step.title }}</span>
          <span class="step-desc">{{ step.desc }}</span>
        </div>
      </div>
    </div>

    <div v-if="project?.status === 'monitoring'" class="monitor-badge">
      <el-icon><Bell /></el-icon>
      <span>每日监控中</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
const props = defineProps<{ project: any; rounds: any[] }>()

const DEFAULT_STEPS = [
  { title: '第1轮', desc: '近5年 · 中文优先' },
  { title: '第2轮', desc: '近10年 · 中文优先' },
  { title: '第3轮', desc: '近20年 · 中英双语' },
  { title: '第4轮', desc: '全时间 · 中英双语' },
  { title: '第5轮', desc: '全时间 · 全球多语言' },
]

function scopeLabel(s: string) {
  return ({ chinese_first:'中文优先', english_first:'英文优先', bilingual:'中英双语', international:'国际', global:'全球多语言' } as any)[s] || s
}

const steps = computed(() => {
  const max = props.project?.max_rounds || 5
  const cfg = props.project?.search_config
  if (cfg?.rounds) {
    return cfg.rounds.map((r: any, i: number) => ({
      title: `第${i+1}轮`,
      desc: `${r.years ? `近${r.years}年` : '全时间'} · ${scopeLabel(r.scope)}`,
    }))
  }
  return Array.from({ length: max }, (_, i) => DEFAULT_STEPS[i] || { title: `第${i+1}轮`, desc: '全时间' })
})

const activeStep = computed(() => props.project?.current_round ?? 0)

function getStepStatus(i: number) {
  const r = props.rounds.find((r: any) => r.round_number === i + 1)
  if (!r) return 'wait'
  if (r.status === 'complete') return 'finish'
  if (['searching','summarizing','awaiting_feedback'].includes(r.status)) return 'process'
  return 'wait'
}
function stepClass(i: number) {
  return { 'is-done': getStepStatus(i) === 'finish', 'is-active': getStepStatus(i) === 'process', 'is-wait': getStepStatus(i) === 'wait' }
}
</script>

<style scoped>
.timeline { padding: 20px 16px; }

.timeline-head {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 20px;
}
.head-label {
  font-size: 11px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.1em; color: var(--ink-400);
}
.head-count {
  font-size: 11px; font-weight: 600; color: var(--signal-teal);
  background: var(--signal-teal-bg); padding: 2px 8px; border-radius: var(--radius-full);
}

.steps { display: flex; flex-direction: column; }

.step { display: flex; gap: 12px; }

.step-indicator {
  display: flex; flex-direction: column; align-items: center;
  width: 24px; flex-shrink: 0;
}
.step-dot {
  width: 24px; height: 24px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; font-weight: 700;
  transition: all var(--duration-normal) var(--ease-out);
  flex-shrink: 0;
}
.is-done .step-dot { background: var(--signal-teal); color: #fff; }
.is-active .step-dot { background: var(--paper); border: 2px solid var(--signal-teal); color: var(--signal-teal); }
.is-wait .step-dot { background: var(--ink-50); border: 2px solid var(--ink-200); color: var(--ink-300); }

.dot-active {
  width: 8px; height: 8px; border-radius: 50%;
  background: var(--signal-teal);
  animation: pulse-dot 1.5s infinite;
}
.dot-num { font-family: var(--font-body); }

.step-line {
  width: 2px; flex: 1; min-height: 20px;
  background: var(--ink-100);
  margin: 4px 0;
  transition: background var(--duration-normal);
}
.step-line.filled { background: var(--signal-teal); }

.step-content { padding-bottom: 16px; min-width: 0; }
.step-title {
  display: block; font-size: 13px; font-weight: 600;
  color: var(--ink-700); line-height: 24px;
}
.is-active .step-title { color: var(--signal-teal); }
.is-wait .step-title { color: var(--ink-400); }
.step-desc {
  display: block; font-size: 11px; color: var(--ink-400);
  margin-top: 1px;
}

.monitor-badge {
  display: flex; align-items: center; gap: 6px; justify-content: center;
  margin-top: 16px; padding: 8px 12px; border-radius: var(--radius-md);
  background: var(--signal-emerald-bg); color: var(--signal-emerald);
  font-size: 12px; font-weight: 600;
}
</style>
