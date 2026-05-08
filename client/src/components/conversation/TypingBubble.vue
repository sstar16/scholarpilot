<template>
  <div class="typing-bubble">
    <div class="typing-bubble__avatar">
      <CatAvatar :size="36" />
    </div>
    <div class="typing-bubble__body">
      <div class="typing-bubble__stage">
        <span class="typing-bubble__stage-text">{{ currentStage }}</span>
      </div>
      <div class="typing-bubble__dots">
        <span class="tb-dot" />
        <span class="tb-dot" />
        <span class="tb-dot" />
      </div>
      <div v-if="showMeta" class="typing-bubble__meta">
        <span v-if="model" class="tb-meta-item">{{ model }}</span>
        <span v-if="tokens > 0" class="tb-meta-item">↑{{ inputTokens }} ↓{{ outputTokens }}</span>
        <span v-if="elapsedMs > 0" class="tb-meta-item tb-meta-elapsed">{{ formatElapsed(elapsedMs) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from 'vue'
import CatAvatar from '../brand/CatAvatar.vue'

const props = withDefaults(
  defineProps<{
    /** 阶段场景：普通对话 / 协作研究 / 检索中 / 摘要生成 / 协作精读 */
    scene?: 'chat' | 'collaboration' | 'search' | 'summarize' | 'reading_deep'
    active?: boolean
    model?: string
    inputTokens?: number
    outputTokens?: number
    elapsedMs?: number
  }>(),
  { scene: 'chat', active: true, inputTokens: 0, outputTokens: 0, elapsedMs: 0 }
)

const STAGE_POOLS: Record<string, string[]> = {
  chat: [
    '正在读取上下文…',
    '组织回答思路…',
    '检索相关片段…',
    '撰写回复中…',
  ],
  collaboration: [
    '从文献库挑选相关证据…',
    '阅读候选文献摘要…',
    '对比关键论点与实验数据…',
    '整理参考与交叉引用…',
    '撰写带引用的回答…',
  ],
  reading_deep: [
    '打开文献 · 扫描全文结构…',
    '提取核心论点与实验数据…',
    '交叉对比不同来源结论…',
    '查找相关引用文献…',
    '筛选关键段落作为证据…',
    '合成带引用的分析…',
  ],
  search: [
    '并行访问数据源…',
    '解析返回条目…',
    'AI 评分并归桶…',
    '生成摘要中…',
  ],
  summarize: [
    '读取原文结构…',
    '提取关键论点…',
    '压缩要点…',
  ],
}

const stageIdx = ref(0)
let stageTimer: ReturnType<typeof setInterval> | null = null

const pool = computed(() => STAGE_POOLS[props.scene] || STAGE_POOLS.chat)
const currentStage = computed(() => pool.value[stageIdx.value % pool.value.length])
const tokens = computed(() => props.inputTokens + props.outputTokens)
const showMeta = computed(() => !!props.model || tokens.value > 0 || props.elapsedMs > 0)

function formatElapsed(ms: number): string {
  if (ms == null || ms < 0) return ''
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

watch(
  () => props.active,
  (on) => {
    if (stageTimer) clearInterval(stageTimer)
    if (!on) return
    stageIdx.value = 0
    // reading_deep 最慢（真·逐篇精读 + 查引用）；collaboration / search 次之
    const interval =
      props.scene === 'reading_deep'
        ? 4200
        : props.scene === 'collaboration'
          ? 3500
          : props.scene === 'search'
            ? 2800
            : 2000
    stageTimer = setInterval(() => {
      stageIdx.value += 1
    }, interval)
  },
  { immediate: true }
)

onUnmounted(() => {
  if (stageTimer) clearInterval(stageTimer)
})
</script>

<style scoped>
.typing-bubble {
  display: flex;
  gap: var(--space-3);
  margin: var(--space-3) 0 var(--space-4);
  max-width: 85%;
  margin-right: auto;
  transform-origin: bottom left;
  animation: aiEnter 620ms cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

.typing-bubble__avatar { flex-shrink: 0; }

.typing-bubble__body {
  padding: 12px 18px 10px;
  border-radius: var(--radius-lg);
  border-bottom-left-radius: 4px;
  background: linear-gradient(180deg, #fdfcf8, var(--paper-cool));
  border: 1px solid rgba(198, 172, 87, 0.35);
  box-shadow:
    0 2px 10px rgba(20, 20, 20, 0.04),
    0 0 0 3px rgba(198, 172, 87, 0.05);
  min-width: 220px;
  position: relative;
  /* 细微呼吸，提示"正在进行中" */
  animation: tb-breathe 2.6s ease-in-out infinite;
}
@keyframes tb-breathe {
  0%, 100% { box-shadow: 0 2px 10px rgba(20, 20, 20, 0.04), 0 0 0 3px rgba(198, 172, 87, 0.05); }
  50%      { box-shadow: 0 4px 16px rgba(198, 172, 87, 0.16), 0 0 0 5px rgba(198, 172, 87, 0.12); }
}

.typing-bubble__stage {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-800);
  font-family: var(--font-display);
  letter-spacing: 0.01em;
  line-height: 1.4;
  min-height: 18px;
}
.typing-bubble__stage-text {
  display: inline-block;
  animation: tb-stage-fade 0.3s ease-out;
}
@keyframes tb-stage-fade {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

.typing-bubble__dots {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-top: 8px;
}
.tb-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #c6ac57;
  animation: tb-pulse 1.2s ease-in-out infinite;
}
.tb-dot:nth-child(2) { animation-delay: 0.18s; }
.tb-dot:nth-child(3) { animation-delay: 0.36s; }
@keyframes tb-pulse {
  0%, 100% { opacity: 0.35; transform: scale(0.85); }
  50%      { opacity: 1;    transform: scale(1.15); }
}

.typing-bubble__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed rgba(20, 20, 20, 0.08);
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-500);
}
.tb-meta-elapsed { color: #c6ac57; font-weight: 600; }
</style>
