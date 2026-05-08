<template>
  <!-- Confirmed/historical: collapsed one-line summary bubble -->
  <div v-if="isDone" class="rich-msg rich-msg--keyword is-done">
    <div class="summary-line" @click="showDetails = !showDetails">
      <el-icon><CircleCheck /></el-icon>
      <span class="summary-text">
        第 {{ effectivePlan.round_number }} 轮关键词已生成
        <span class="meta">· {{ effectiveSourcePlans.length }} 个数据源</span>
        <span v-if="effectivePlan.year_from || effectivePlan.year_to" class="meta">
          · {{ effectivePlan.year_from || '—' }}~{{ effectivePlan.year_to || '—' }}
        </span>
        <span v-if="effectivePlan.search_mode" class="meta">
          · {{ searchModeLabel }}
        </span>
      </span>
      <el-button size="small" text @click.stop="showDetails = !showDetails">
        {{ showDetails ? '收起' : '查看' }}
        <el-icon><component :is="showDetails ? ArrowUp : ArrowDown" /></el-icon>
      </el-button>
    </div>
    <div v-if="showDetails" class="details">
      <div class="snapshot-row">
        <span class="label">基础查询:</span>
        <span class="value">{{ effectivePlan.base_query || '(未设置)' }}</span>
      </div>
      <div v-if="effectivePlan.original_chinese_query" class="snapshot-row">
        <span class="label">中文意图:</span>
        <span class="value">{{ effectivePlan.original_chinese_query }}</span>
      </div>
      <div class="snapshot-row">
        <span class="label">语言范围:</span>
        <span class="value">{{ langScopeLabel }}</span>
      </div>
      <div class="snapshot-row">
        <span class="label">每源上限:</span>
        <span class="value">{{ effectivePlan.max_per_source ?? effectivePlan.max_results_per_source ?? 10 }} 篇</span>
      </div>
      <div class="snapshot-row">
        <span class="label">数据源:</span>
        <span class="value">
          <el-tag
            v-for="sp in effectiveSourcePlans"
            :key="sp.source_id"
            size="small"
            style="margin: 2px 4px 2px 0"
          >{{ sp.source_id }}</el-tag>
        </span>
      </div>
    </div>
  </div>

  <!-- Active: full editable panel -->
  <!-- :key="richData.round_id" 强制每轮独立 mount，避免上一轮 KeywordConfirmPanel
       的 child DOM（备选关键词列表等）被 Vue 复用并出现在新一轮卡片下方 -->
  <div v-else class="rich-msg rich-msg--keyword" :key="`kw-active-${richData.round_id}`">
    <div class="rich-msg__header">
      <el-icon :size="18"><Edit /></el-icon>
      <span class="title">第 {{ richData.round_number }} 轮 · 关键词方案</span>
      <el-tag type="warning" size="small" effect="dark">待确认</el-tag>
      <div class="spacer" />
      <span class="agent-credit">
        <el-icon><MagicStick /></el-icon>
        QueryPlanAgent · LLM 优化
      </span>
    </div>
    <div class="rich-msg__body">
      <!-- 优先用 store.keywordPlan（含用户编辑），fallback 到 richData 快照
           （DB 持久化的富消息有完整 source_plans，不受 Redis 600s TTL 影响，
           解决"退出再进 → 一直载入"卡死） -->
      <div v-if="!hasPlanData" class="loading-hint">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>正在载入关键词方案...</span>
      </div>
      <KeywordConfirmPanel
        v-else
        :keyword-plan="effectivePlan"
        @confirm="onConfirm"
        @auto-confirm="onAutoConfirm"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Edit, Loading, CircleCheck, ArrowUp, ArrowDown, MagicStick } from '@element-plus/icons-vue'
import { useSearchStore } from '../../../stores/search'
import KeywordConfirmPanel from '../../retrieval/KeywordConfirmPanel.vue'

const props = defineProps<{
  richData: any
  isActive?: boolean
}>()

const emit = defineEmits<{
  confirm: [payload: any]
  autoConfirm: [payload: any]
}>()

const searchStore = useSearchStore()
const showDetails = ref(false)

const isDone = computed(() => {
  if (!props.isActive) return true
  // If current round has moved past awaiting_keywords, treat as done
  const curr = searchStore.currentRound
  if (!curr) return true
  if (curr.id !== props.richData.round_id) return true
  return curr.status !== 'awaiting_keywords'
})

// 统一数据源：当 store.keywordPlan 是同一轮的最新版本时优先用它（包含用户编辑）
// fallback 到 richData 快照（历史轮次或 store 还未加载时）。这是 Bug B 的核心修复
// —— 杜绝"上方折叠摘要"和"下方编辑面板"显示不同字段。
const effectivePlan = computed(() => {
  const sp = searchStore.keywordPlan
  if (sp && sp.round_id === props.richData.round_id) {
    return { ...props.richData, ...sp }
  }
  return props.richData || {}
})

const effectiveSourcePlans = computed(() => {
  return effectivePlan.value.source_plans || []
})

// 只要有 source_plans（来自 store 或 richData 快照）就可渲染，无需等 store
const hasPlanData = computed(() => effectiveSourcePlans.value.length > 0)

const langScopeLabel = computed(() => {
  const m: Record<string, string> = {
    chinese_first: '中文优先',
    international: '国际英文',
    bilingual: '中英双语',
    global: '全球多语言',
  }
  const v = effectivePlan.value.language_scope
  return v ? (m[v] || v) : '默认'
})

const searchModeLabel = computed(() => {
  const m: Record<string, string> = {
    static_db: '静态知识库',
    api: 'API 实时',
    hybrid: '混合检索',
  }
  const v = effectivePlan.value.search_mode
  return v ? (m[v] || v) : ''
})

function onConfirm(payload: any) { emit('confirm', payload) }
function onAutoConfirm(payload: any) { emit('autoConfirm', payload) }
</script>

<style scoped>
/* variant 色板（基础骨架见 design-system.css） */
.rich-msg {
  background: #fefce8;
  border: 1.5px solid var(--signal-amber);
}
.rich-msg.is-done {
  background: #f0fdf4;
  border-color: var(--signal-emerald);
  border-width: 1px;
}

/* Collapsed summary line (after confirmation) */
.summary-line {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 10px var(--space-4);
  font-size: var(--type-sub-size);
  color: var(--signal-emerald);
  cursor: pointer;
  user-select: none;
}
.summary-line:hover { background: var(--signal-emerald-bg); }
.summary-text { flex: 1; color: var(--ink-700); }
.summary-text .meta { color: var(--signal-emerald); font-weight: 500; }

.details {
  padding: var(--space-2) var(--space-4) var(--space-3);
  border-top: 1px dashed var(--signal-emerald);
  font-size: var(--type-meta-size);
  color: var(--ink-500);
}
.snapshot-row { display: flex; margin: var(--space-1) 0; }
.snapshot-row .label {
  flex-shrink: 0;
  width: 72px;
  color: var(--ink-300);
}
.snapshot-row .value { flex: 1; word-break: break-word; color: var(--ink-700); }

/* Active state header (before confirmation) — 只保留 variant 边框色 */
.rich-msg__header {
  border-bottom: 1px solid var(--signal-amber-bg);
}
.rich-msg__header .agent-credit {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--type-micro-size);
  font-weight: 500;
  color: var(--signal-amber);
  background: var(--signal-amber-bg);
  padding: 2px var(--space-2);
  border-radius: var(--radius-full);
  border: 1px solid var(--signal-amber-bg);
}
.rich-msg__body { padding: var(--space-3) var(--space-4); } /* overrides default --space-4 */
.loading-hint {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--signal-amber);
  font-size: var(--type-sub-size);
  padding: var(--space-2) 0;
}
</style>
