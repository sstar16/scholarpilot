<template>
  <div class="rich-msg rich-msg--complete rich-msg-enter">
    <div class="rich-msg__header">
      <el-icon :size="18"><CircleCheck /></el-icon>
      <span class="title">第 {{ richData.round_number }} 轮 · 已结束</span>
      <el-tag type="success" size="small" effect="dark">
        {{ richData.classified }}/{{ richData.total }} 已分类
      </el-tag>
    </div>

    <div class="rich-msg__body">
      <!-- Compact horizontal stat bar -->
      <div class="bucket-bar">
        <div class="bucket-stat" :class="{ 'has-value': counts.very_relevant > 0 }">
          <span class="bucket-stat__num">{{ counts.very_relevant }}</span>
          <span class="bucket-stat__label">核心</span>
        </div>
        <div class="bucket-stat" :class="{ 'has-value': counts.relevant > 0 }">
          <span class="bucket-stat__num">{{ counts.relevant }}</span>
          <span class="bucket-stat__label">相关</span>
        </div>
        <div class="bucket-stat" :class="{ 'has-value': counts.uncertain > 0 }">
          <span class="bucket-stat__num">{{ counts.uncertain }}</span>
          <span class="bucket-stat__label">待定</span>
        </div>
        <div class="bucket-stat" :class="{ 'has-value': counts.irrelevant > 0 }">
          <span class="bucket-stat__num">{{ counts.irrelevant }}</span>
          <span class="bucket-stat__label">排除</span>
        </div>
      </div>

      <div v-if="richData.memory_updated" class="memory-note">
        <el-icon><Cpu /></el-icon>
        Memory Agent 已更新研究画像
      </div>

      <!-- Next round actions -->
      <div class="next-round" :class="{ 'is-locked': nextRoundStarted }">
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
          <button
            v-if="!nextRoundStarted"
            class="mode-toggle-btn"
            @click="modeExpanded = !modeExpanded"
          >
            {{ modeExpanded ? '收起模式选择 ‹' : `模式：${modeMeta[selectedMode].icon} ${modeMeta[selectedMode].label} ›` }}
          </button>
          <el-tag
            v-else
            type="success"
            size="small"
            effect="plain"
          >
            ✓ 已进入第 {{ (richData.round_number || 0) + 1 }} 轮
          </el-tag>
        </div>

        <!-- Collapsible mode picker -->
        <div v-if="modeExpanded && !nextRoundStarted" class="mode-picker">
          <div class="mode-picker__label">
            选择检索模式
            <el-tooltip :content="recommendation.reason" placement="top">
              <el-tag type="info" size="small" effect="plain" class="rec-tag">
                💡 推荐：{{ modeMeta[recommendation.mode].label }}
              </el-tag>
            </el-tooltip>
          </div>
          <el-radio-group
            v-model="selectedMode"
            size="small"
            class="mode-radios"
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

        <span v-if="nextRoundStarted" class="hint hint-locked">
          本轮模式已锁定 · 若要重选，请等下一轮结束
        </span>
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
const modeExpanded = ref(false)

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
  max-width: 480px;
  background: #f0fdf4;
  border: 1.5px solid var(--signal-emerald);
}
.rich-msg__header {
  border-bottom: 1px solid var(--signal-emerald-bg);
}

/* Compact horizontal stat bar */
.bucket-bar {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.bucket-stat {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px var(--space-2);
  background: var(--paper);
  border: 1px solid var(--ink-100);
  border-radius: var(--radius-sm);
  transition: all var(--duration-fast) var(--ease-out);
}
.bucket-stat.has-value {
  border-color: var(--signal-emerald);
  background: var(--signal-emerald-bg);
}
.bucket-stat__num {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 900;
  color: var(--signal-emerald);
  line-height: 1;
}
.bucket-stat:not(.has-value) .bucket-stat__num { color: var(--ink-200); }
.bucket-stat__label {
  font-size: var(--type-micro-size);
  color: var(--ink-500);
  font-weight: 600;
  letter-spacing: 0.04em;
}

.memory-note {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  padding: 5px var(--space-3);
  background: var(--signal-emerald-bg);
  border: 1px dashed var(--signal-emerald);
  border-radius: var(--radius-sm);
  font-size: var(--type-meta-size);
  color: var(--signal-emerald);
}
.next-round {
  padding: var(--space-2) var(--space-3);
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
.next-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-wrap: wrap;
}
.mode-toggle-btn {
  background: none;
  border: none;
  padding: 3px 6px;
  font-size: var(--type-meta-size);
  color: var(--signal-emerald);
  cursor: pointer;
  font-family: var(--font-body);
  font-weight: 500;
  border-radius: var(--radius-sm);
  transition: background var(--duration-fast) var(--ease-out);
}
.mode-toggle-btn:hover { background: var(--signal-emerald-bg); }
.mode-picker {
  margin-top: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px dashed var(--signal-emerald);
  animation: richMsgEnter 200ms cubic-bezier(0.4, 0, 0.2, 1) both;
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
.mode-radios { margin-bottom: 0; }
.hint-locked {
  display: block;
  margin-top: var(--space-1);
  font-size: var(--type-meta-size);
  color: var(--ink-400);
  font-style: italic;
}
</style>
