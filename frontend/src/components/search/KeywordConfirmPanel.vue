<template>
  <div class="keyword-confirm-panel">
    <div class="panel-header">
      <div class="header-left">
        <span class="step-badge">2.5</span>
        <h3>Per-Source 查询词优化</h3>
        <span class="gen-time" v-if="keywordPlan?.generation_time_ms">
          {{ keywordPlan.generation_time_ms }}ms
        </span>
      </div>
      <div class="header-actions">
        <button class="btn-reset" @click="resetToDefaults">重置</button>
        <button class="btn-auto" @click="handleAutoConfirm" :disabled="enabledCount === 0"
                title="本轮及之后的轮次自动使用 LLM 优化的关键词，不再弹出确认">
          之后自动确认
        </button>
        <button class="btn-confirm" @click="handleConfirm" :disabled="enabledCount === 0">
          确认本轮 ({{ enabledCount }} 个源)
        </button>
      </div>
    </div>

    <div class="source-grid">
      <div
        v-for="plan in localPlans"
        :key="plan.source_id"
        class="source-card"
        :class="{ disabled: !plan.enabled }"
      >
        <div class="card-header">
          <label class="source-toggle">
            <input type="checkbox" v-model="plan.enabled" />
            <span class="toggle-slider"></span>
          </label>
          <span class="source-name">{{ plan.display_name }}</span>
          <span class="lang-badge" :class="'lang-' + plan.language">
            {{ plan.language === 'zh' ? '中文' : plan.language === 'multilingual' ? '多语' : 'EN' }}
          </span>
          <span class="method-badge" :class="'method-' + plan.generation_method">
            {{ plan.generation_method === 'llm' ? 'LLM' : plan.generation_method === 'heuristic' ? '规则' : '直传' }}
          </span>
        </div>
        <div class="card-body">
          <!-- Dual format (openalex_zh): show two separate fields -->
          <template v-if="plan.query_format === 'dual' && plan.query.includes('|||')">
            <div class="dual-label">中文词 (language:zh)</div>
            <textarea
              :value="plan.query.split('|||')[0]"
              @input="updateDualPart(plan, 0, ($event.target as HTMLTextAreaElement).value)"
              class="query-input"
              :disabled="!plan.enabled"
              rows="1"
              spellcheck="false"
            ></textarea>
            <div class="dual-label" style="margin-top:6px">英文词 (country:cn)</div>
            <textarea
              :value="plan.query.split('|||')[1]"
              @input="updateDualPart(plan, 1, ($event.target as HTMLTextAreaElement).value)"
              class="query-input"
              :disabled="!plan.enabled"
              rows="1"
              spellcheck="false"
            ></textarea>
          </template>
          <!-- Normal single field -->
          <textarea
            v-else
            v-model="plan.query"
            class="query-input"
            :disabled="!plan.enabled"
            rows="2"
            spellcheck="false"
          ></textarea>
          <div class="card-notes" v-if="plan.notes">
            {{ plan.notes }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'

interface SourcePlan {
  source_id: string
  display_name: string
  query: string
  query_format: string
  language: string
  enabled: boolean
  generation_method: string
  notes: string
  category: string
}

const props = defineProps<{
  keywordPlan: any
}>()

const emit = defineEmits<{
  confirm: [plans: SourcePlan[]]
  autoConfirm: [plans: SourcePlan[]]
  cancel: []
}>()

const localPlans = ref<SourcePlan[]>([])

watch(
  () => props.keywordPlan,
  (plan) => {
    if (plan?.source_plans) {
      localPlans.value = plan.source_plans.map((p: any) => ({ ...p }))
    }
  },
  { immediate: true }
)

const enabledCount = computed(() => localPlans.value.filter(p => p.enabled).length)

function resetToDefaults() {
  if (props.keywordPlan?.source_plans) {
    localPlans.value = props.keywordPlan.source_plans.map((p: any) => ({ ...p }))
  }
}

function updateDualPart(plan: SourcePlan, partIndex: number, value: string) {
  const parts = plan.query.split('|||')
  parts[partIndex] = value
  plan.query = parts.join('|||')
}

function getPlansPayload() {
  return localPlans.value.map(p => ({
    source_id: p.source_id,
    query: p.query,
    enabled: p.enabled,
  }))
}

function handleConfirm() {
  emit('confirm', getPlansPayload() as any)
}

function handleAutoConfirm() {
  emit('autoConfirm', getPlansPayload() as any)
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
  color: #e2e8f0;
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
  color: #64748b;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.btn-reset {
  background: transparent;
  border: 1px solid rgba(100, 116, 139, 0.4);
  color: #94a3b8;
  padding: 6px 14px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}

.btn-reset:hover {
  border-color: rgba(148, 163, 184, 0.6);
  color: #cbd5e1;
}

.btn-auto {
  background: transparent;
  border: 1px solid rgba(16, 185, 129, 0.4);
  color: #34d399;
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

.source-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
}

.source-card {
  background: rgba(30, 41, 59, 0.7);
  border: 1px solid rgba(100, 180, 255, 0.1);
  border-radius: 8px;
  padding: 12px;
  transition: all 0.2s;
}

.source-card:hover {
  border-color: rgba(100, 180, 255, 0.25);
}

.source-card.disabled {
  opacity: 0.45;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.source-name {
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
  flex: 1;
}

.lang-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.lang-en {
  background: rgba(59, 130, 246, 0.2);
  color: #60a5fa;
}

.lang-zh {
  background: rgba(234, 179, 8, 0.2);
  color: #fbbf24;
}

.lang-multilingual {
  background: rgba(168, 85, 247, 0.2);
  color: #c084fc;
}

.method-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.method-llm {
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
}

.method-heuristic {
  background: rgba(251, 146, 60, 0.2);
  color: #fb923c;
}

.method-passthrough {
  background: rgba(100, 116, 139, 0.2);
  color: #94a3b8;
}

.card-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.query-input {
  width: 100%;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(100, 180, 255, 0.12);
  border-radius: 6px;
  color: #e2e8f0;
  font-family: 'Cascadia Code', 'Fira Code', monospace;
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

.query-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.dual-label {
  font-size: 11px;
  color: #94a3b8;
  font-weight: 500;
  margin-bottom: 3px;
}

.card-notes {
  font-size: 11px;
  color: #64748b;
  padding-left: 2px;
}

/* Toggle switch */
.source-toggle {
  position: relative;
  display: inline-block;
  width: 32px;
  height: 18px;
  flex-shrink: 0;
}

.source-toggle input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(100, 116, 139, 0.4);
  transition: 0.2s;
  border-radius: 9px;
}

.toggle-slider:before {
  content: "";
  position: absolute;
  height: 14px;
  width: 14px;
  left: 2px;
  bottom: 2px;
  background-color: white;
  transition: 0.2s;
  border-radius: 50%;
}

.source-toggle input:checked + .toggle-slider {
  background-color: #3b82f6;
}

.source-toggle input:checked + .toggle-slider:before {
  transform: translateX(14px);
}
</style>
