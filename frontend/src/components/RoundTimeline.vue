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

const YEAR_STRATEGY_LABELS: Record<string, (i: number) => string> = {
  progressive: (i) => ['近5年', '近10年', '近20年', '全时间', '全时间'][i] ?? '全时间',
  last5:  () => '近5年',
  last10: () => '近10年',
  last20: () => '近20年',
  all:    () => '全时间',
}

function scopeLabel(scope: string) {
  const map: Record<string, string> = {
    chinese_first: '中文优先',
    english_first: '英文优先',
    bilingual:     '中英双语',
    international: '国际',
    global:        '全球多语言',
  }
  return map[scope] || scope
}

const steps = computed(() => {
  const maxRounds = props.project?.max_rounds || 5
  const config = props.project?.search_config

  // per-round 自定义配置
  if (config?.rounds) {
    return config.rounds.map((r: any, i: number) => ({
      title: `第${i + 1}轮`,
      desc: `${r.years ? `近${r.years}年` : '全时间'} · ${scopeLabel(r.scope)} · ${r.max_results ? `Top ${r.max_results}` : '全部'}`,
    }))
  }

  // 全局配置
  const yearStrategy = config?.year_strategy || 'progressive'
  const langLabel = scopeLabel(config?.language_scope || 'chinese_first')
  const topKLabel = config?.top_k === null ? '全部' : `Top ${config?.top_k ?? 10}`
  const yearFn = YEAR_STRATEGY_LABELS[yearStrategy] ?? YEAR_STRATEGY_LABELS.progressive

  return Array.from({ length: maxRounds }, (_, i) => ({
    title: `第${i + 1}轮`,
    desc: `${yearFn(i)} · ${langLabel} · ${topKLabel}`,
  }))
})

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
