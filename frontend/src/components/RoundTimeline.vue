<template>
  <div class="round-timeline">
    <div class="timeline-title">检索进度</div>
    <el-steps direction="vertical" :active="activeStep" finish-status="success">
      <el-step
        v-for="(step, i) in steps"
        :key="i"
        :title="step.title"
        :description="step.desc"
        :status="getStepStatus(i)"
      />
    </el-steps>
    <div v-if="project?.status === 'monitoring'" class="monitoring-badge">
      <el-tag type="success" effect="dark" size="large">
        <el-icon><Bell /></el-icon> 监控中
      </el-tag>
      <p class="monitor-hint">每日自动推送新文献</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  project: any
  rounds: any[]
}>()

const DEFAULT_STEPS = [
  { title: '第1轮', desc: '近5年 · 中文优先 · Top 10' },
  { title: '第2轮', desc: '近10年 · 中文优先 · Top 10' },
  { title: '第3轮', desc: '近20年 · 中英双语 · Top 20' },
  { title: '第4轮', desc: '全时间 · 中英双语 · 全部' },
  { title: '第5轮', desc: '全时间 · 全球多语言 · AI摘要' },
]

const steps = computed(() => {
  const maxRounds = props.project?.max_rounds || 5
  const config = props.project?.search_config
  if (config?.rounds) {
    return config.rounds.map((r: any, i: number) => ({
      title: `第${i + 1}轮`,
      desc: `${r.years ? `近${r.years}年` : '全时间'} · ${scopeLabel(r.scope)} · Top ${r.max_results}`,
    }))
  }
  return DEFAULT_STEPS.slice(0, maxRounds)
})

function scopeLabel(scope: string) {
  return ({ chinese_first: '中文优先', international: '国际', global: '全球多语言' } as any)[scope] || scope
}

const activeStep = computed(() => {
  if (!props.project) return 0
  return props.project.current_round
})

function getStepStatus(index: number) {
  const roundNum = index + 1
  const round = props.rounds.find((r: any) => r.round_number === roundNum)
  if (!round) return 'wait'
  if (round.status === 'complete') return 'finish'
  if (['searching', 'summarizing', 'awaiting_feedback'].includes(round.status)) return 'process'
  return 'wait'
}
</script>

<style scoped>
.round-timeline {
  padding: 16px;
  min-width: 200px;
}
.timeline-title {
  font-size: 13px;
  font-weight: 600;
  color: #909399;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 20px;
}
.monitoring-badge {
  margin-top: 24px;
  text-align: center;
}
.monitor-hint {
  font-size: 12px;
  color: #909399;
  margin-top: 6px;
}
</style>
