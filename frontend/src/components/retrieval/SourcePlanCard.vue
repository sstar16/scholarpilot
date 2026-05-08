<template>
  <div class="source-card" :class="{ disabled: !plan.enabled }">
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
      <!-- Tier 1: 复杂 / primary。优先命中，若 0 结果降级 -->
      <div class="tier-label tier-complex">
        <span class="tier-dot"></span>
        <span class="tier-name">复杂 · 首次尝试</span>
        <span class="tier-hint">命中 &gt;0 即停</span>
      </div>
      <template v-if="plan.query_format === 'dual' && plan.query.includes('|||')">
        <div class="dual-label">中文词 (language:zh)</div>
        <textarea
          :value="plan.query.split('|||')[0]"
          @input="updateDualPart(0, ($event.target as HTMLTextAreaElement).value)"
          class="query-input"
          :disabled="!plan.enabled"
          rows="1"
          spellcheck="false"
        ></textarea>
        <div class="dual-label" style="margin-top:6px">英文词 (country:cn)</div>
        <textarea
          :value="plan.query.split('|||')[1]"
          @input="updateDualPart(1, ($event.target as HTMLTextAreaElement).value)"
          class="query-input"
          :disabled="!plan.enabled"
          rows="1"
          spellcheck="false"
        ></textarea>
      </template>
      <textarea
        v-else
        v-model="plan.query"
        class="query-input"
        :disabled="!plan.enabled"
        rows="2"
        spellcheck="false"
      ></textarea>

      <!-- Tier 2: 中等 -->
      <div class="tier-label tier-medium">
        <span class="tier-dot"></span>
        <span class="tier-name">中等 · 降级 1</span>
        <span class="tier-hint">复杂层 0 结果时使用</span>
      </div>
      <textarea
        v-model="plan.query_medium"
        class="query-input query-input--tier"
        :disabled="!plan.enabled"
        rows="1"
        spellcheck="false"
        placeholder="留空则跳过此层"
      ></textarea>

      <!-- Tier 3: 简单 -->
      <div class="tier-label tier-simple">
        <span class="tier-dot"></span>
        <span class="tier-name">简单 · 降级 2 · 兜底</span>
        <span class="tier-hint">前两层都 0 才用</span>
      </div>
      <textarea
        v-model="plan.query_simple"
        class="query-input query-input--tier"
        :disabled="!plan.enabled"
        rows="1"
        spellcheck="false"
        placeholder="留空则跳过此层"
      ></textarea>

      <div class="card-notes" v-if="plan.notes">
        {{ plan.notes }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
export interface SourcePlan {
  source_id: string
  display_name: string
  query: string               // primary = complex
  query_medium: string
  query_simple: string
  query_format: string
  language: string
  enabled: boolean
  generation_method: string
  notes: string
  category: string
}

const props = defineProps<{
  /** 父端的 plan reactive 引用；子组件直接 mutation 字段（与原 Panel 内的写法保持一致） */
  plan: SourcePlan
}>()

function updateDualPart(partIndex: number, value: string) {
  const parts = props.plan.query.split('|||')
  parts[partIndex] = value
  props.plan.query = parts.join('|||')
}
</script>

<style scoped>
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
  color: var(--ink-200);
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
  color: var(--signal-blue-light);
}

.lang-zh {
  background: rgba(234, 179, 8, 0.2);
  color: var(--signal-amber-light);
}

.lang-multilingual {
  background: rgba(168, 85, 247, 0.2);
  color: var(--signal-purple-light);
}

.method-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.method-llm {
  background: rgba(16, 185, 129, 0.2);
  color: var(--signal-emerald);
}

.method-heuristic {
  background: rgba(251, 146, 60, 0.2);
  color: var(--signal-amber-light);
}

.method-passthrough {
  background: rgba(100, 116, 139, 0.2);
  color: var(--ink-300);
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

.query-input:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.dual-label {
  font-size: 11px;
  color: var(--ink-300);
  font-weight: 500;
  margin-bottom: 3px;
}

/* 三层降级 tier 标签 */
.tier-label {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 8px 0 3px;
  font-size: 10.5px;
  font-weight: 600;
}
.tier-label .tier-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.tier-label .tier-name { flex-shrink: 0; }
.tier-label .tier-hint {
  color: var(--ink-400);
  font-weight: 400;
  font-size: 10px;
}
.tier-complex { color: var(--signal-blue-light); }
.tier-complex .tier-dot { background: var(--signal-blue-light); box-shadow: 0 0 6px rgba(59,130,246,0.55); }
.tier-medium { color: var(--signal-purple-light); }
.tier-medium .tier-dot { background: var(--signal-purple); }
.tier-simple { color: var(--ink-300); }
.tier-simple .tier-dot { background: var(--ink-400); }

.query-input--tier {
  font-size: 11.5px;
  padding: 6px 10px;
  background: rgba(15, 23, 42, 0.45);
}

.card-notes {
  font-size: 11px;
  color: var(--ink-400);
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
  background-color: var(--signal-blue-light);
}

.source-toggle input:checked + .toggle-slider:before {
  transform: translateX(14px);
}
</style>
