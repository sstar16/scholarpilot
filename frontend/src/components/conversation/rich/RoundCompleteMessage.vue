<template>
  <div class="rich-msg rich-msg--complete">
    <div class="rich-msg__header">
      <el-icon :size="18"><CircleCheck /></el-icon>
      <span class="title">第 {{ richData.round_number }} 轮 · 已结束</span>
      <el-tag type="success" size="small" effect="dark">
        {{ richData.classified }}/{{ richData.total }} 已分类
      </el-tag>
    </div>

    <div class="rich-msg__body">
      <div class="bucket-grid">
        <div class="bucket-cell" :class="{ 'has-value': counts.very_relevant > 0 }">
          <div class="bucket-label">核心</div>
          <div class="bucket-count">{{ counts.very_relevant }}</div>
        </div>
        <div class="bucket-cell" :class="{ 'has-value': counts.relevant > 0 }">
          <div class="bucket-label">相关</div>
          <div class="bucket-count">{{ counts.relevant }}</div>
        </div>
        <div class="bucket-cell" :class="{ 'has-value': counts.uncertain > 0 }">
          <div class="bucket-label">待定</div>
          <div class="bucket-count">{{ counts.uncertain }}</div>
        </div>
        <div class="bucket-cell" :class="{ 'has-value': counts.irrelevant > 0 }">
          <div class="bucket-label">排除</div>
          <div class="bucket-count">{{ counts.irrelevant }}</div>
        </div>
      </div>

      <div v-if="richData.memory_updated" class="memory-note">
        <el-icon><Cpu /></el-icon>
        Memory Agent 已根据本轮反馈更新您的研究画像
      </div>

      <div class="next-round" :class="{ 'is-locked': nextRoundStarted }">
        <div class="mode-picker">
          <div class="mode-picker__label">
            下一轮检索模式
            <el-tooltip
              v-if="!nextRoundStarted"
              :content="recommendation.reason"
              placement="top"
            >
              <el-tag type="info" size="small" effect="plain" class="rec-tag">
                💡 推荐：{{ modeMeta[recommendation.mode].label }}
              </el-tag>
            </el-tooltip>
            <el-tag
              v-else
              type="success"
              size="small"
              effect="plain"
              class="rec-tag"
            >
              ✓ 已进入第 {{ (richData.round_number || 0) + 1 }} 轮
            </el-tag>
          </div>
          <el-radio-group
            v-model="selectedMode"
            size="small"
            class="mode-radios"
            :disabled="nextRoundStarted"
          >
            <el-radio-button
              v-for="m in MODE_ORDER"
              :key="m"
              :value="m"
            >
              {{ modeMeta[m].icon }} {{ modeMeta[m].label }}
            </el-radio-button>
          </el-radio-group>
        </div>
        <div class="next-actions">
          <el-button
            type="primary"
            size="small"
            :loading="searchStore.isStarting"
            :disabled="nextRoundStarted"
            @click="$emit('start-next-round', { mode: selectedMode })"
          >
            <el-icon><Search /></el-icon>
            {{ nextRoundStarted
              ? `已进入第 ${(richData.round_number || 0) + 1} 轮`
              : `开始第 ${(richData.round_number || 0) + 1} 轮` }}
          </el-button>
          <span v-if="!nextRoundStarted" class="hint">
            或直接对 AI 说"再来一轮"/"换成 API 模式重试"
          </span>
          <span v-else class="hint hint-locked">
            本轮模式已锁定 · 若要重选，请等下一轮结束后在对应 RoundComplete 卡片里切换
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { CircleCheck, Cpu, Search } from '@element-plus/icons-vue'
import { useSearchStore } from '../../../stores/search'

type SearchMode = 'static_db' | 'api' | 'hybrid'

const props = defineProps<{
  richData: any
}>()

defineEmits<{
  'start-next-round': [payload: { mode: SearchMode }]
}>()

const searchStore = useSearchStore()

const counts = computed(() => ({
  very_relevant: 0,
  relevant: 0,
  uncertain: 0,
  irrelevant: 0,
  ...(props.richData?.bucket_counts || {}),
}))

const MODE_ORDER: SearchMode[] = ['static_db', 'hybrid', 'api']
const modeMeta: Record<SearchMode, { icon: string; label: string }> = {
  static_db: { icon: '📚', label: '本地库' },
  hybrid: { icon: '⚡', label: '混合' },
  api: { icon: '🌐', label: 'API' },
}

// 基于上一轮效果推荐下一轮模式
// 简化启发式：
//  - 核心/相关太少（<3）→ 推荐 API（需要拉更多外部数据）
//  - 核心/相关充足（>=5）→ 推荐 static_db（复用已积累的本地库）
//  - 中等 → 推荐 hybrid
const recommendation = computed<{ mode: SearchMode; reason: string }>(() => {
  const quality = counts.value.very_relevant + counts.value.relevant
  const prevMode = (props.richData?.search_mode || null) as SearchMode | null
  if (quality < 3) {
    return {
      mode: 'api',
      reason: `上轮仅 ${quality} 篇高相关文献，建议走 API 拉更多外部数据`,
    }
  }
  if (quality >= 5) {
    return {
      mode: 'static_db',
      reason: `上轮有 ${quality} 篇高相关文献，本地库已足够，选静态库省 API 额度`,
    }
  }
  if (prevMode) {
    return { mode: prevMode, reason: '基于上轮设置，保持相同模式' }
  }
  return { mode: 'hybrid', reason: '中等质量，混合模式兼顾速度和覆盖' }
})

const selectedMode = ref<SearchMode>(recommendation.value.mode)

// 下一轮是否已经启动 — 判断依据：searchStore.rounds 里存在比本 round 大的轮次
// 一旦启动就锁住本卡片的 mode radio 和"开始"按钮，避免用户重复点击
const nextRoundStarted = computed(() => {
  const myRound = props.richData?.round_number ?? 0
  return searchStore.rounds.some((r: any) => (r.round_number ?? 0) > myRound)
})
</script>

<style scoped>
/* variant 色板（基础骨架见 design-system.css） */
.rich-msg {
  background: #f0fdf4;
  border: 1.5px solid var(--signal-emerald);
}
.rich-msg__header {
  border-bottom: 1px solid var(--signal-emerald-bg);
}
.bucket-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-2);
}
.bucket-cell {
  padding: var(--space-3) var(--space-2);
  background: var(--paper);
  border: 1px solid var(--ink-100);
  border-radius: var(--radius-md);
  text-align: center;
  transition: all var(--duration-fast) var(--ease-out);
}
.bucket-cell.has-value {
  border-color: var(--signal-emerald);
  background: var(--signal-emerald-bg);
}
.bucket-label {
  font-size: var(--type-micro-size);
  color: var(--ink-500);
  font-weight: 600;
  letter-spacing: 0.04em;
}
.bucket-count {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 900;
  color: var(--signal-emerald);
  margin-top: 2px;
  line-height: 1;
}
.bucket-cell:not(.has-value) .bucket-count { color: var(--ink-200); }
.memory-note {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--signal-emerald-bg);
  border: 1px dashed var(--signal-emerald);
  border-radius: var(--radius-sm);
  font-size: var(--type-meta-size);
  color: var(--signal-emerald);
}
.next-round {
  margin-top: var(--space-4);
  padding: var(--space-3);
  background: rgba(255, 255, 255, 0.5);
  border: 1px dashed var(--signal-emerald);
  border-radius: var(--radius-md);
  transition: opacity var(--duration-normal) var(--ease-out);
}
.next-round.is-locked {
  background: var(--paper-cool);
  border-color: var(--ink-100);
  border-style: solid;
  opacity: 0.75;
}
.next-round.is-locked .mode-picker__label {
  color: var(--ink-400);
}
.hint-locked {
  color: var(--ink-400) !important;
  font-style: italic;
}
.mode-picker__label {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--type-meta-size);
  font-weight: 600;
  color: var(--ink-700);
  margin-bottom: var(--space-2);
}
.mode-picker__label .rec-tag {
  font-weight: 500;
}
.mode-radios {
  margin-bottom: 10px;
}
.next-actions {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-wrap: wrap;
}
.next-actions .hint {
  font-size: var(--type-meta-size);
  color: var(--ink-300);
}
</style>
