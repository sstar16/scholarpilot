<template>
  <div class="rich-msg rich-msg--progress" :class="{
    'is-done': isDone,
    'is-collapsed': collapsed || isFinalized,
    'is-finalized': isFinalized,
  }">
    <div class="rich-msg__header" @click="!isFinalized && (collapsed = !collapsed)">
      <el-icon :size="18" :class="{ 'is-loading': !isDone }">
        <component :is="isFinalized ? CircleCheck : (isDone ? Collection : Search)" />
      </el-icon>
      <span class="title">第 {{ richData.round_number }} 轮 · {{ statusLabel }}</span>
      <el-tag :type="isDone ? 'success' : 'primary'" size="small" effect="dark">
        {{ isDone ? `${totalCount} 篇` : progressPercent + '%' }}
      </el-tag>
      <el-tag v-if="isDone && summaryCount" type="info" size="small">
        {{ summaryCount }} 份摘要
      </el-tag>
      <!-- 检索模式 badge（静态库 / API / 混合）— 让用户一眼看出本轮走哪条 -->
      <el-tooltip v-if="searchModeBadge" :content="searchModeBadge.tip" placement="top">
        <el-tag :type="searchModeBadge.type" size="small" effect="plain" class="mode-badge">
          {{ searchModeBadge.icon }} {{ searchModeBadge.label }}
        </el-tag>
      </el-tooltip>
      <div class="spacer"></div>
      <!-- Answer Now: 检索/评分/摘要中允许用户中断, 拿已有文献快速合成 best-effort 答案 -->
      <el-tooltip
        v-if="canTriggerAnswerNow && !answerNowRequested"
        content="基于已检索/评分的部分文献，立刻合成一份能用的答案"
        placement="top"
      >
        <el-button
          size="small"
          type="warning"
          plain
          :loading="answerNowLoading"
          class="answer-now-btn"
          @click.stop="triggerAnswerNow"
        >
          ⚡ 先看现有结果
        </el-button>
      </el-tooltip>
      <el-tag
        v-else-if="canTriggerAnswerNow && answerNowRequested"
        type="warning"
        size="small"
        effect="plain"
        class="answer-now-pending"
      >
        ⚡ 已受理 · 等本阶段...
      </el-tag>
      <!-- Mini progress bar when collapsed and still running -->
      <div v-if="collapsed && !isDone" class="mini-progress">
        <div class="mini-progress__fill" :style="{ width: progressPercent + '%' }"></div>
      </div>
      <el-button v-if="!isFinalized" size="small" text @click.stop="collapsed = !collapsed">
        {{ collapsed ? '展开' : '折叠' }}
        <el-icon><component :is="collapsed ? ArrowDown : ArrowUp" /></el-icon>
      </el-button>
    </div>

    <div class="rich-msg__body" v-show="!collapsed && !isFinalized">
      <!-- Task-lock hint: shown while round is in progress -->
      <div v-if="!isDone && isActive" class="task-lock-hint">
        <span class="lock-icon">🔒</span>
        任务进行中，无法取消；完成后可重新开始
        <span v-if="etaSeconds" class="eta">· 预计剩余 {{ etaSeconds }} 秒</span>
      </div>

      <!-- Searching phase: full original animation stack -->
      <template v-if="!isDone">
        <template v-if="isActive">
          <div class="processing-state-v2">
            <!-- A2: 显眼的整体进度条 —— 解决"看不到 X/Y 源完成"的反馈延迟 -->
            <div class="sources-progress">
              <div class="sources-progress__meta">
                <span class="sources-progress__label">
                  <el-icon class="is-loading" :size="12"><Loading /></el-icon>
                  已完成 <b>{{ sourcesDone }}</b> / {{ sourcesTotal || '?' }} 个数据源
                </span>
                <span class="sources-progress__percent">{{ progressPercent }}%</span>
              </div>
              <div class="sources-progress__bar">
                <div
                  class="sources-progress__fill"
                  :style="{ width: Math.max(2, progressPercent) + '%' }"
                ></div>
                <div class="sources-progress__shimmer"></div>
              </div>
            </div>

            <SearchingAnimation
              :status="currentRound?.status"
              :message="currentRound?.progress_message"
              :doc-count="streamingDocs.length"
              :summary-count="summaryReadyCount"
              :current-source="currentSearchingSource"
            />
            <DocumentStream :docs="streamingDocs" />
            <SourceProgressCompact ref="sourceProgressRef" />
          </div>

          <div
            v-if="searchStore.sourceStats && Object.keys(searchStore.sourceStats).length > 0"
            class="source-stats"
          >
            <span class="source-stats-label">数据源：</span>
            <el-tooltip
              v-for="(stat, sourceId) in searchStore.sourceStats"
              :key="sourceId"
              :content="getSourceTooltip(sourceId, stat)"
              placement="top"
            >
              <el-tag
                :type="(stat as any).status === 'ok' && (stat as any).count > 0 ? 'success' : (stat as any).status === 'error' ? 'danger' : 'info'"
                size="small"
                effect="plain"
                style="margin-right: 6px; margin-bottom: 4px; cursor: default"
              >
                {{ sourceId }}: {{ (stat as any).count ?? 0 }}篇
                <span v-if="(stat as any).status === 'error'" style="color: #f56c6c"> !</span>
              </el-tag>
            </el-tooltip>
          </div>
        </template>
        <div v-else class="snapshot-hint">
          <el-icon><Loading /></el-icon>
          本轮检索快照（历史消息）
        </div>
      </template>

      <!-- Done phase: full results UI (overrides the animation in-place) -->
      <template v-else>
        <RoundResultsMessage
          :rich-data="resultsRichData"
          :is-active="isActive"
          :finalizing="finalizing"
          @view-detail="$emit('view-detail', $event)"
          @finalize="$emit('finalize')"
        />
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { Search, Collection, Loading, ArrowUp, ArrowDown, CircleCheck } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useSearchStore } from '../../../stores/search'
import { useSSE } from '../../../composables/useSSE'
import { useProjectStore } from '../../../stores/project'
import { searchApi } from '../../../api/client'
import SearchingAnimation from '../../retrieval/SearchingAnimation.vue'
import DocumentStream from '../../retrieval/DocumentStream.vue'
import SourceProgressCompact from '../../retrieval/SourceProgressCompact.vue'
import RoundResultsMessage from './RoundResultsMessage.vue'

const props = defineProps<{
  richData: any
  isActive?: boolean
  finalizing?: boolean
  etaSeconds?: number
}>()

defineEmits<{
  'view-detail': [doc: any]
  finalize: []
}>()

const searchStore = useSearchStore()
const sse = useSSE()
const sourceProgressRef = ref<InstanceType<typeof SourceProgressCompact> | null>(null)
const summaryReadyCount = ref(0)
const currentSearchingSource = ref('')
const collapsed = ref(false)

const currentRound = computed(() => searchStore.currentRound)
const streamingDocs = computed(() => searchStore.streamingDocs)

// 本富消息是否对应 store 里 currentRound？只有匹配时才相信 currentRound.status，
// 否则就是历史快照（比如第 2 轮开始后，第 1 轮的 SearchProgressMessage）
const matchesCurrentRound = computed(() => {
  return (
    props.isActive &&
    !!currentRound.value &&
    currentRound.value.id === props.richData?.round_id
  )
})

const isDone = computed(() => {
  // 快照或 round_id 不匹配 → 一律视为已完成（不再显示 progress）
  if (!matchesCurrentRound.value) return true
  const st = currentRound.value?.status
  // partial_complete 也视为终态：Answer Now 触发后, partial 答案已落 DB, 不再 polling 进度
  return st === 'awaiting_feedback' || st === 'complete' || st === 'partial_complete'
})

// Answer Now: 哪些 status 允许触发"先看现有结果"
const ANSWER_NOW_STAGES = ['pending', 'searching', 'scoring', 'saving', 'summarizing']
const projectStore = useProjectStore()
const answerNowRequested = ref(false)
const answerNowLoading = ref(false)

const canTriggerAnswerNow = computed(() => {
  if (!matchesCurrentRound.value) return false
  if (isDone.value) return false
  const st = currentRound.value?.status
  return ANSWER_NOW_STAGES.includes(st || '')
})

async function triggerAnswerNow() {
  const pid = projectStore.current?.id
  const rid = props.richData?.round_id
  if (!pid || !rid) return
  answerNowLoading.value = true
  try {
    await searchApi.triggerAnswerNow(String(pid), String(rid))
    answerNowRequested.value = true
    ElMessage.success('已受理！当前阶段完成后立刻给你合成一份')
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.message || 'Answer Now 触发失败'
    ElMessage.error(typeof msg === 'string' ? msg : '触发失败')
  } finally {
    answerNowLoading.value = false
  }
}

// 切换 round 时重置 answer_now 状态（避免上一轮的"已受理"残留）
watch(() => props.richData?.round_id, () => {
  answerNowRequested.value = false
  answerNowLoading.value = false
})

// 已 finalize（用户点"结束本轮"后）— 整个大框折叠成单行摘要
// 让位给 RoundCompleteMessage 的 bucket 总结
const isFinalized = computed(() => {
  // 历史快照场景：richData 自带 finalized 标记 or round 整体已推进
  if (!matchesCurrentRound.value) {
    // 如果 store 里当前 round 比本条消息新，说明本条是已完成的历史轮
    if (currentRound.value && props.richData?.round_number != null &&
        currentRound.value.round_number > props.richData.round_number) {
      return true
    }
    return !!props.richData?.finalized
  }
  return currentRound.value?.status === 'complete'
})

// 检索模式 badge — 优先级：
//  1. richData.search_mode (后端注入时写的本轮 mode，最权威、零歧义)
//  2. 活跃且 round_id 匹配时看 store 的 sourceStats（fallback）
//  3. 都没有 → 不显示 badge
const searchModeBadge = computed(() => {
  const mode = props.richData?.search_mode
  if (mode === 'static_db') {
    return { icon: '📚', label: '本地库', type: 'success', tip: '本轮只从本地知识库检索，无外网 API 调用' }
  }
  if (mode === 'api') {
    return { icon: '🌐', label: 'API', type: 'primary', tip: '本轮走外部 API 实时检索' }
  }
  if (mode === 'hybrid') {
    return { icon: '⚡', label: '混合', type: 'warning', tip: '混合检索：本地知识库 + 外部 API' }
  }
  // 无 richData.search_mode：fallback 用 sourceStats（仅在 round_id 匹配时）
  if (!matchesCurrentRound.value) return null
  const stats: Record<string, any> = searchStore.sourceStats || {}
  const keys = Object.keys(stats)
  if (keys.length === 0) return null
  const onlyLocal = keys.length === 1 && keys[0] === 'local_kb'
  if (onlyLocal) {
    return { icon: '📚', label: '本地库', type: 'success', tip: '本轮只从本地知识库检索' }
  }
  const hasLocal = keys.includes('local_kb')
  if (hasLocal && keys.length > 1) {
    return { icon: '⚡', label: '混合', type: 'warning', tip: '混合检索' }
  }
  return { icon: '🌐', label: 'API', type: 'primary', tip: '外部 API 实时检索' }
})

// 缓动进度条：targetProgress 是后端推送的离散值（0.08, 0.15, 0.22, 0.38...），
// displayedProgress 在 ~600ms 内 ease 到目标。这样即使后端推得稀疏，
// 用户看到的进度也是平滑增长而不是跳变。
const targetProgress = computed(() => {
  return currentRound.value?.progress ?? props.richData.progress ?? 0.05
})
const displayedProgress = ref(targetProgress.value)
let easeRaf: number | null = null

function easeTo(target: number) {
  if (easeRaf !== null) cancelAnimationFrame(easeRaf)
  const start = displayedProgress.value
  if (target <= start) {
    // monotonic：单一 round 内进度只前进不后退
    return
  }
  const startTime = performance.now()
  const duration = 600 // ms
  const step = (now: number) => {
    const t = Math.min(1, (now - startTime) / duration)
    // ease-out cubic — 开始快、结尾慢
    const eased = 1 - Math.pow(1 - t, 3)
    displayedProgress.value = start + (target - start) * eased
    if (t < 1) {
      easeRaf = requestAnimationFrame(step)
    } else {
      easeRaf = null
    }
  }
  easeRaf = requestAnimationFrame(step)
}

watch(targetProgress, (val) => {
  // 单一 round 内：只允许前进，从不允许回退（杜绝 10→45→10 的怪异跳变）。
  // 真正的 round 切换由下面 watch(round_id) 处理。
  easeTo(val)
})

watch(() => props.richData?.round_id, () => {
  // 切换 round 时重置缓动状态，避免上一轮的进度残留
  if (easeRaf !== null) cancelAnimationFrame(easeRaf)
  displayedProgress.value = targetProgress.value
})

const progressPercent = computed(() => {
  return Math.round(displayedProgress.value * 100)
})

const totalCount = computed(() => {
  // When active, use live documents; otherwise fall back to richData
  if (props.isActive && searchStore.currentRound?.id === props.richData.round_id) {
    return searchStore.documents.length
  }
  return props.richData.total ?? 0
})

// A2: 计算 "已完成 X/Y 数据源" —— 多层 fallback 避免 "0/?"
//  - status === 'ok' / 'error' 都算完成（error 源不再处理，视为完成）
//  - total 优先级：sourceStats 已收到事件 > richData 携带 > keywordPlan 的 enabled 源
const sourcesDone = computed(() => {
  const stats: Record<string, any> = searchStore.sourceStats || {}
  return Object.values(stats).filter((s: any) => s?.status === 'ok' || s?.status === 'error').length
})
const sourcesTotal = computed(() => {
  const stats: Record<string, any> = searchStore.sourceStats || {}
  const statKeys = Object.keys(stats).length
  if (statKeys > 0) return statKeys
  // fallback 1: richData 里后端若有注入
  const planned = props.richData?.source_plans || props.richData?.sources
  if (Array.isArray(planned) && planned.length > 0) return planned.length
  // fallback 2: store.keywordPlan 里用户刚确认的 enabled 源（最可靠，SSE 未到前可用）
  const kp = (searchStore.keywordPlan as any)?.source_plans
  if (Array.isArray(kp)) {
    const enabled = kp.filter((p: any) => p?.enabled !== false)
    if (enabled.length > 0) return enabled.length
  }
  return 0
})

const summaryCount = computed(() => {
  if (props.isActive && searchStore.currentRound?.id === props.richData.round_id) {
    return searchStore.documents.filter((d: any) => d.ai_summary).length
  }
  return props.richData.summaries_done ?? 0
})

// Build results-style richData so RoundResultsMessage can render
const resultsRichData = computed(() => ({
  round_id: props.richData.round_id,
  round_number: props.richData.round_number,
  total: totalCount.value,
  summaries_done: summaryCount.value,
  docs: props.richData.docs || [],
}))

const statusLabel = computed(() => {
  const st = currentRound.value?.status
  if (!props.isActive) return '检索快照'
  if (st === 'searching') return '检索中'
  if (st === 'scoring') return '评分中'
  if (st === 'saving') return '保存中'
  if (st === 'summarizing') return '生成摘要'
  if (st === 'awaiting_feedback') return '等待您评分'
  if (st === 'complete') return '已完成'
  return '处理中'
})

// Auto-collapse when transitioning to done (so the results open cleanly)
watch(isDone, (done, wasDone) => {
  if (done && !wasDone) {
    // keep expanded so user sees results immediately
    collapsed.value = false
  }
})

// SSE setup
function setupSSE(roundId: string) {
  summaryReadyCount.value = 0
  currentSearchingSource.value = ''
  sourceProgressRef.value?.reset()
  sse.on('round_status', (data: any) => searchStore.handleSSEEvent('round_status', data))
  sse.on('doc_arrived', (data: any) => searchStore.handleSSEEvent('doc_arrived', data))
  sse.on('summary_ready', (data: any) => {
    searchStore.handleSSEEvent('summary_ready', data)
    summaryReadyCount.value++
  })
  sse.on('round_complete', (data: any) => {
    searchStore.handleSSEEvent('round_complete', data)
    sse.disconnect()
  })
  sse.on('source_started', (data: any) => {
    sourceProgressRef.value?.onSourceStarted(data)
    currentSearchingSource.value = data.source_id || ''
  })
  sse.on('source_complete', (data: any) => {
    sourceProgressRef.value?.onSourceComplete(data)
    currentSearchingSource.value = ''
  })
  sse.on('source_error', (data: any) => sourceProgressRef.value?.onSourceError(data))
  sse.connect(roundId)
}

onMounted(() => {
  if (props.isActive && props.richData?.round_id && !isDone.value) {
    setupSSE(props.richData.round_id)
  }
})

onBeforeUnmount(() => {
  sse.disconnect()
  if (easeRaf !== null) cancelAnimationFrame(easeRaf)
})

const SOURCE_HINTS: Record<string, string> = {
  pubmed: '国内访问受限（TLS超时），用 Europe PMC 替代',
  lens_patent: '需在 .env 配置 LENS_API_TOKEN',
  epo_ops: '需在 .env 配置 EPO_CONSUMER_KEY + EPO_CONSUMER_SECRET',
  patenthub: '需在 .env 配置 PATENTHUB_API_TOKEN',
  semantic_scholar: '频率限制（429），已降低优先级',
  arxiv: '国内访问受限',
  openalex_zh: '中文论文专用（chinese_first 自动启用）',
  dblp: 'CS顶会/期刊',
}

function getSourceTooltip(sourceId: string, stat: any): string {
  if (stat.status === 'error') return `错误：${stat.error || '未知错误'}`
  if (stat.count === 0 && SOURCE_HINTS[sourceId]) return SOURCE_HINTS[sourceId]
  if (stat.count > 0) return `成功返回 ${stat.count} 篇`
  return '本次查询无匹配结果'
}
</script>

<style scoped>
/* variant 色板（基础骨架见 design-system.css） */
.rich-msg {
  background: #eff6ff;
  border: 1.5px solid var(--signal-blue);
  transition: background var(--duration-normal) var(--ease-out);
}
.rich-msg.is-done {
  background: var(--paper);
  border-color: var(--signal-emerald);
  border-width: 1px;
}
.rich-msg__header {
  border-bottom: 1px solid var(--signal-blue-bg);
  cursor: pointer;
  user-select: none;
}
.rich-msg.is-done .rich-msg__header {
  color: var(--signal-emerald);
  background: #ecfdf5;
  border-bottom-color: var(--signal-emerald-bg);
}
.rich-msg.is-collapsed .rich-msg__header {
  border-bottom: none;
}
/* Finalized 态：整个框变成单行摘要 */
.rich-msg.is-finalized {
  background: #f0fdf4;
  border-color: var(--signal-emerald);
  border-width: 1px;
}
.rich-msg.is-finalized .rich-msg__header {
  cursor: default;
  padding: var(--space-2) var(--space-4);
  color: var(--signal-emerald);
}
.rich-msg__header .mode-badge {
  font-weight: 600;
  letter-spacing: 0.3px;
}
.processing-state-v2 {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.source-stats {
  margin-top: var(--space-3);
  padding-top: 10px;
  border-top: 1px dashed var(--ink-100);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
}
.source-stats-label {
  font-size: var(--type-meta-size);
  color: var(--ink-400);
  margin-right: var(--space-1);
}
.task-lock-hint {
  margin-top: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--signal-amber-bg);
  color: var(--signal-amber);
  font-size: var(--type-sub-size);
  border: 1px solid var(--signal-amber-bg);
  border-radius: var(--radius-sm);
}
.lock-icon { margin-right: var(--space-1); }
.eta { color: var(--ink-400); font-family: var(--font-mono); font-size: var(--type-micro-size); }
.snapshot-hint {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--type-sub-size);
  color: var(--ink-300);
  font-style: italic;
}
.mini-progress {
  width: 100px;
  height: 4px;
  background: var(--signal-blue-bg);
  border-radius: 2px;
  overflow: hidden;
  margin-right: var(--space-1);
}
.mini-progress__fill {
  height: 100%;
  background: var(--signal-blue);
  transition: width var(--duration-normal) var(--ease-out);
}

/* A2: 显眼的大进度条 */
.sources-progress {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: 10px var(--space-3);
  background: var(--signal-blue-bg);
  border: 1px solid var(--signal-blue-bg);
  border-radius: var(--radius-md);
}
.sources-progress__meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: var(--type-meta-size);
  color: var(--ink-700);
}
.sources-progress__label {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  font-weight: 500;
}
.sources-progress__label b {
  color: var(--signal-blue);
  font-weight: 700;
}
.sources-progress__percent {
  font-variant-numeric: tabular-nums;
  font-family: var(--font-mono);
  font-weight: 600;
  color: var(--signal-blue);
}
.sources-progress__bar {
  position: relative;
  height: 6px;
  background: var(--signal-blue-bg);
  border-radius: var(--radius-full);
  overflow: hidden;
}
.sources-progress__fill {
  position: absolute;
  inset: 0 auto 0 0;
  background: linear-gradient(90deg, var(--signal-blue), var(--signal-blue-light));
  border-radius: var(--radius-full);
  transition: width var(--duration-slow) var(--ease-out);
}
.sources-progress__shimmer {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.35) 50%,
    transparent 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.6s linear infinite;
  pointer-events: none;
}

/* When SearchProgressMessage embeds RoundResultsMessage, strip its outer chrome */
.rich-msg :deep(.rich-msg--results) {
  margin: 0;
  border: none;
  background: transparent;
}
.rich-msg :deep(.rich-msg--results .rich-msg__header) {
  display: none;
}
.rich-msg :deep(.rich-msg--results .rich-msg__body) {
  padding: 0;
}
</style>
