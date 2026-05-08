<template>
  <div class="keyword-confirm-panel">
    <div class="panel-header">
      <div class="header-left">
        <span class="step-badge">{{ isStaticDb ? '📚' : '2.5' }}</span>
        <h3>{{ isStaticDb ? '本地知识库检索' : 'Per-Source 查询词优化' }}</h3>
        <span class="gen-time" v-if="keywordPlan?.generation_time_ms">
          {{ keywordPlan.generation_time_ms }}ms
        </span>
      </div>
      <div class="header-actions">
        <button class="btn-reset" @click="resetToDefaults">重置</button>
        <button v-if="!isStaticDb" class="btn-auto" @click="handleAutoConfirm" :disabled="enabledCount === 0"
                title="本轮及之后的轮次自动使用 LLM 优化的关键词，不再弹出确认">
          之后自动确认
        </button>
        <button class="btn-confirm" @click="handleConfirm" :disabled="enabledCount === 0">
          {{ isStaticDb ? '开始检索' : `确认本轮 (${enabledCount} 个源)` }}
        </button>
      </div>
    </div>

    <!-- QueryPlan 全局参数（Agent 生成，用户可修改） -->
    <div class="plan-params">
      <div class="plan-params-header">
        <span class="param-badge">Agent</span>
        <span class="param-title">检索方案</span>
        <span v-if="keywordPlan?.plan_source" class="param-source">{{ keywordPlan.plan_source === 'agent' ? 'AI 规划' : '规则生成' }}</span>
      </div>
      <p v-if="keywordPlan?.plan_rationale" class="plan-rationale">{{ keywordPlan.plan_rationale }}</p>
      <div class="param-grid">
        <div class="param-item param-wide">
          <label>英文查询词</label>
          <textarea v-model="planParams.base_query" class="query-input" rows="2" spellcheck="false" />
        </div>
        <div class="param-item param-wide">
          <label>中文查询词</label>
          <textarea v-model="planParams.original_chinese_query" class="query-input" rows="1" spellcheck="false" placeholder="（中文项目自动生成）" />
        </div>
        <div class="param-item">
          <label>起始年份</label>
          <input v-model.number="planParams.year_from" type="number" class="query-input" min="1900" max="2030" />
        </div>
        <div class="param-item">
          <label>截止年份</label>
          <input v-model.number="planParams.year_to" type="number" class="query-input" min="1900" max="2030" />
        </div>
        <div class="param-item">
          <label>每源上限</label>
          <input v-model.number="planParams.max_per_source" type="number" class="query-input" min="5" max="200" />
        </div>
        <div class="param-item">
          <label>语言范围</label>
          <select v-model="planParams.language_scope" class="query-input">
            <option value="chinese_first">中文优先</option>
            <option value="international">国际</option>
            <option value="global">全球</option>
          </select>
        </div>
        <div class="param-item param-wide">
          <label>排除词（逗号分隔）</label>
          <input v-model="excludeTermsStr" class="query-input" placeholder="排除的关键词，逗号分隔" />
        </div>
        <!-- 检索模式在 RoundComplete 卡片里就已经选过了，这里只读展示，不让用户改
             （旧下拉会让用户困惑：为什么刚选过的又出现一次？） -->
        <div class="param-item">
          <label>检索模式 <span class="param-hint">（已在上一轮或项目创建时确定）</span></label>
          <div class="query-input query-input--readonly">{{ searchModeLabel }}</div>
        </div>
      </div>
    </div>

    <!-- Per-Source 查询词 (隐藏于 static_db 模式)
         A2: 默认只显示 TOP_N=5 个源（enabled 优先），避免 15 源全展开变成表格地狱
         单卡渲染下沉到 SourcePlanCard.vue（含三层降级编辑 + dual format） -->
    <div v-if="!isStaticDb" class="source-grid">
      <SourcePlanCard
        v-for="plan in displayedPlans"
        :key="plan.source_id"
        :plan="plan"
      />
    </div>

    <!-- A2: 展开/收起按钮（当有被隐藏的源时显示） -->
    <div v-if="!isStaticDb && hiddenCount > 0" class="source-expander">
      <button v-if="!expandedAllSources" class="btn-expand" @click="expandedAllSources = true">
        展开另外 {{ hiddenCount }} 个数据源
        <span class="expand-arrow">↓</span>
      </button>
      <button v-else class="btn-expand" @click="expandedAllSources = false">
        收起（仅显示 Top {{ TOP_N_SOURCES }}）
        <span class="expand-arrow">↑</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import SourcePlanCard, { type SourcePlan } from './SourcePlanCard.vue'

const props = defineProps<{
  keywordPlan: any
}>()

const emit = defineEmits<{
  confirm: [payload: any]
  autoConfirm: [payload: any]
  cancel: []
}>()

const localPlans = ref<SourcePlan[]>([])
const planParams = reactive({
  base_query: '',
  original_chinese_query: '',
  year_from: null as number | null,
  year_to: null as number | null,
  max_per_source: 20,
  language_scope: 'international',
  exclude_terms: [] as string[],
  search_mode: '',
})
const excludeTermsStr = computed({
  get: () => planParams.exclude_terms.join(', '),
  set: (v: string) => { planParams.exclude_terms = v.split(',').map(s => s.trim()).filter(Boolean) },
})

watch(
  () => props.keywordPlan,
  (plan) => {
    if (plan?.source_plans) {
      localPlans.value = plan.source_plans.map((p: any) => ({
        ...p,
        query_medium: p.query_medium ?? '',
        query_simple: p.query_simple ?? '',
      }))
    }
    if (plan) {
      planParams.base_query = plan.base_query || ''
      planParams.original_chinese_query = plan.original_chinese_query || ''
      planParams.year_from = plan.year_from ?? null
      planParams.year_to = plan.year_to ?? null
      planParams.max_per_source = plan.max_per_source || 20
      planParams.language_scope = plan.language_scope || 'international'
      planParams.exclude_terms = plan.exclude_terms || []
      planParams.search_mode = plan.search_mode || ''
    }
  },
  { immediate: true }
)

const isStaticDb = computed(() => planParams.search_mode === 'static_db')

// A2: 默认只显示前 N 个源（enabled 优先），解决"15 源表格地狱"
const TOP_N_SOURCES = 5
const expandedAllSources = ref(false)
const displayedPlans = computed(() => {
  if (expandedAllSources.value) return localPlans.value
  // 排序：启用的在前；不改 localPlans 本身的顺序（切片是新数组）
  return [...localPlans.value]
    .sort((a, b) => Number(b.enabled) - Number(a.enabled))
    .slice(0, TOP_N_SOURCES)
})
const hiddenCount = computed(() =>
  Math.max(0, localPlans.value.length - TOP_N_SOURCES)
)

const searchModeLabel = computed(() => {
  const m = planParams.search_mode
  if (m === 'static_db') return '📚 本地知识库'
  if (m === 'api') return '🌐 API 实时检索'
  if (m === 'hybrid') return '⚡ 混合检索'
  return '默认（全部源）'
})
const enabledCount = computed(() => localPlans.value.filter(p => p.enabled).length)

function resetToDefaults() {
  if (props.keywordPlan?.source_plans) {
    localPlans.value = props.keywordPlan.source_plans.map((p: any) => ({
      ...p,
      query_medium: p.query_medium ?? '',
      query_simple: p.query_simple ?? '',
    }))
  }
  if (props.keywordPlan) {
    planParams.base_query = props.keywordPlan.base_query || ''
    planParams.original_chinese_query = props.keywordPlan.original_chinese_query || ''
    planParams.year_from = props.keywordPlan.year_from ?? null
    planParams.year_to = props.keywordPlan.year_to ?? null
    planParams.max_per_source = props.keywordPlan.max_per_source || 20
    planParams.language_scope = props.keywordPlan.language_scope || 'international'
    planParams.exclude_terms = props.keywordPlan.exclude_terms || []
    planParams.search_mode = props.keywordPlan.search_mode || ''
  }
}

function getFullPayload() {
  return {
    source_plans: localPlans.value.map(p => ({
      source_id: p.source_id,
      query: p.query,
      query_medium: p.query_medium || '',
      query_simple: p.query_simple || '',
      enabled: p.enabled,
    })),
    base_query: planParams.base_query,
    original_chinese_query: planParams.original_chinese_query || null,
    exclude_terms: planParams.exclude_terms,
    year_from: planParams.year_from,
    year_to: planParams.year_to,
    max_per_source: planParams.max_per_source,
    language_scope: planParams.language_scope,
    search_mode: planParams.search_mode || null,
  }
}

function handleConfirm() {
  emit('confirm', getFullPayload() as any)
}

function handleAutoConfirm() {
  emit('autoConfirm', getFullPayload() as any)
}
</script>

<style scoped>
.keyword-confirm-panel {
  background: rgba(15, 23, 42, 0.85);
  border: 1px solid rgba(100, 180, 255, 0.15);
  border-radius: 12px;
  padding: 20px;
  margin: 16px 0;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 12px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-left h3 {
  margin: 0;
  font-size: 15px;
  color: var(--ink-200);
  font-weight: 600;
}

.step-badge {
  background: linear-gradient(135deg, #3b82f6, #6366f1);
  color: white;
  font-size: 12px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 10px;
  min-width: 24px;
  text-align: center;
}

.gen-time {
  font-size: 12px;
  color: var(--ink-400);
}

.header-actions {
  display: flex;
  gap: 8px;
}

.btn-reset {
  background: transparent;
  border: 1px solid rgba(100, 116, 139, 0.4);
  color: var(--ink-300);
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}

.btn-reset:hover {
  border-color: rgba(148, 163, 184, 0.6);
  color: var(--ink-200);
}

.btn-auto {
  background: transparent;
  border: 1px solid rgba(16, 185, 129, 0.4);
  color: var(--signal-emerald);
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}

.btn-auto:hover:not(:disabled) {
  border-color: rgba(16, 185, 129, 0.7);
  background: rgba(16, 185, 129, 0.1);
}

.btn-auto:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-confirm {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  border: none;
  color: white;
  padding: 6px 18px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.2s;
}

.btn-confirm:hover:not(:disabled) {
  background: linear-gradient(135deg, #60a5fa, #3b82f6);
  transform: translateY(-1px);
}

.btn-confirm:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ── QueryPlan 全局参数区 ── */
.plan-params {
  background: rgba(30, 41, 59, 0.5);
  border: 1px solid rgba(13, 148, 136, 0.2);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 16px;
}
.plan-params-header {
  display: flex; align-items: center; gap: 8px; margin-bottom: 8px;
}
.param-badge {
  background: linear-gradient(135deg, var(--signal-teal), var(--signal-teal-light));
  color: var(--paper); font-size: 10px; font-weight: 800;
  padding: 2px 8px; border-radius: 10px;
}
.param-title { font-size: 14px; font-weight: 600; color: var(--ink-200); }
.param-source { font-size: 11px; color: var(--ink-400); }
.plan-rationale {
  font-size: 12px; color: var(--ink-300); margin: 0 0 10px; font-style: italic;
}
.param-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.param-item label {
  display: block; font-size: 11px; color: var(--ink-300); margin-bottom: 4px; font-weight: 500;
}
.param-item select.query-input {
  appearance: auto; cursor: pointer;
}
.param-wide { grid-column: span 4; }

.source-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
}

/* 单源卡片（badge / textarea / tier label / toggle）样式已下沉到 SourcePlanCard.vue */

.query-input {
  width: 100%;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(100, 180, 255, 0.12);
  border-radius: 6px;
  color: var(--ink-200);
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 8px 10px;
  resize: vertical;
  transition: border-color 0.2s;
  line-height: 1.5;
}

.query-input:focus {
  outline: none;
  border-color: rgba(59, 130, 246, 0.5);
}

/* 只读模式：视觉上与可编辑 input 区分 */
.query-input--readonly {
  background: rgba(15, 23, 42, 0.3);
  border-style: dashed;
  color: var(--ink-300);
  cursor: not-allowed;
  user-select: none;
}

.param-hint {
  font-size: 10px;
  color: var(--ink-400);
  font-weight: 400;
  margin-left: 4px;
}

.query-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* dual-label / tier-* / query-input--tier / card-notes / source-toggle 等
   单卡内部样式已下沉到 SourcePlanCard.vue */

/* A2: 展开/收起更多数据源 */
.source-expander {
  display: flex;
  justify-content: center;
  margin-top: 12px;
}
.btn-expand {
  background: rgba(59, 130, 246, 0.08);
  border: 1px dashed rgba(59, 130, 246, 0.35);
  color: var(--signal-blue-light);
  padding: 8px 18px;
  border-radius: 20px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.btn-expand:hover {
  background: rgba(59, 130, 246, 0.15);
  border-color: rgba(59, 130, 246, 0.6);
  color: var(--signal-blue-light);
}
.expand-arrow {
  font-size: 14px;
  line-height: 1;
}
</style>
