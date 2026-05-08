<script setup lang="ts">
import { ref } from 'vue'
import { testSource, type SourceTestResult } from '../api/client'

const props = defineProps<{
  sourceId: string | null
  sourceName: string
}>()

const query = ref('')
const maxResults = ref(5)
const yearFrom = ref<number | undefined>(undefined)
const yearTo = ref<number | undefined>(undefined)
const language = ref('')

const testing = ref(false)
const result = ref<SourceTestResult | null>(null)
const expandedIdx = ref<number | null>(null)

async function handleTest() {
  if (!props.sourceId || !query.value.trim()) return
  testing.value = true
  result.value = null
  expandedIdx.value = null

  try {
    const resp = await testSource({
      source_id: props.sourceId,
      query: query.value.trim(),
      max_results: maxResults.value,
      year_from: yearFrom.value || null,
      year_to: yearTo.value || null,
      language: language.value || null,
    })
    result.value = resp.data
  } catch (e: any) {
    result.value = {
      source_id: props.sourceId,
      status: 'error',
      count: 0,
      elapsed_ms: 0,
      results: [],
      error: e.message || 'Request failed',
      error_trace: null,
    }
  } finally {
    testing.value = false
  }
}

function toggleExpand(idx: number) {
  expandedIdx.value = expandedIdx.value === idx ? null : idx
}

function statusColor(s: string) {
  if (s === 'ok') return '#4ade80'
  if (s === 'timeout') return '#fbbf24'
  return '#f87171'
}
</script>

<template>
  <div class="test-panel">
    <h4 class="panel-title">Test: {{ sourceName || 'Select a source' }}</h4>

    <div class="test-form">
      <div class="form-row">
        <input
          class="query-input mono"
          v-model="query"
          placeholder="Enter search query..."
          :disabled="!sourceId"
          @keyup.enter="handleTest"
        />
      </div>
      <div class="form-row params">
        <label class="param">
          <span class="param-label">Max</span>
          <input type="number" class="param-input mono" v-model.number="maxResults" min="1" max="50" />
        </label>
        <label class="param">
          <span class="param-label">Year From</span>
          <input type="number" class="param-input mono" v-model.number="yearFrom" placeholder="--" />
        </label>
        <label class="param">
          <span class="param-label">Year To</span>
          <input type="number" class="param-input mono" v-model.number="yearTo" placeholder="--" />
        </label>
        <label class="param">
          <span class="param-label">Lang</span>
          <select class="param-input" v-model="language">
            <option value="">Any</option>
            <option value="en">en</option>
            <option value="zh">zh</option>
          </select>
        </label>
        <button
          class="test-btn"
          :disabled="!sourceId || !query.trim() || testing"
          @click="handleTest"
        >
          {{ testing ? 'Testing...' : 'Execute' }}
        </button>
      </div>
    </div>

    <!-- Result -->
    <div v-if="result" class="test-result">
      <div class="result-header">
        <span class="result-badge" :style="{ background: statusColor(result.status) + '22', color: statusColor(result.status), borderColor: statusColor(result.status) }">
          {{ result.status.toUpperCase() }}
        </span>
        <span class="result-meta mono">{{ result.elapsed_ms }}ms</span>
        <span class="result-meta mono">{{ result.count }} results</span>
      </div>

      <!-- Error -->
      <div v-if="result.error" class="result-error">
        <div class="error-msg">{{ result.error }}</div>
        <pre v-if="result.error_trace" class="error-trace mono">{{ result.error_trace }}</pre>
      </div>

      <!-- Results list -->
      <div v-if="result.results.length > 0" class="result-list">
        <div
          v-for="(item, idx) in result.results"
          :key="idx"
          class="result-item"
          @click="toggleExpand(idx)"
        >
          <div class="item-header">
            <span class="item-idx mono">#{{ idx + 1 }}</span>
            <span class="item-title">{{ item.title || '(no title)' }}</span>
            <span class="item-chevron">{{ expandedIdx === idx ? '▾' : '▸' }}</span>
          </div>
          <div class="item-meta" v-if="item.authors || item.publication_date">
            <span v-if="item.authors" class="item-authors">{{ item.authors }}</span>
            <span v-if="item.publication_date" class="item-date mono">{{ item.publication_date }}</span>
          </div>
          <pre v-if="expandedIdx === idx" class="item-json mono">{{ JSON.stringify(item, null, 2) }}</pre>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="testing" class="test-loading">
      <div class="spinner" />
      <span>Fetching from {{ sourceName }}...</span>
    </div>
  </div>
</template>

<style scoped>
.test-panel { display: flex; flex-direction: column; gap: 0; height: 100%; }

.panel-title {
  font-size: 11px; font-weight: 700; color: #8888aa;
  text-transform: uppercase; letter-spacing: 1.5px;
  padding: 12px 16px; margin: 0;
  border-bottom: 1px solid rgba(42, 42, 74, 0.4);
}

.test-form { padding: 12px 16px; border-bottom: 1px solid rgba(42, 42, 74, 0.4); }
.form-row { display: flex; gap: 8px; }
.form-row.params { margin-top: 8px; align-items: flex-end; flex-wrap: wrap; }

.query-input {
  flex: 1;
  background: rgba(10, 10, 26, 0.6);
  border: 1px solid rgba(42, 42, 74, 0.8);
  border-radius: 6px;
  color: #e2e2f0;
  padding: 8px 12px;
  font-size: 13px;
  outline: none;
}
.query-input:focus { border-color: #7c3aed; }
.query-input:disabled { opacity: 0.4; }

.param { display: flex; flex-direction: column; gap: 2px; }
.param-label { font-size: 9px; color: #666; text-transform: uppercase; letter-spacing: 1px; }
.param-input {
  background: rgba(10, 10, 26, 0.6);
  border: 1px solid rgba(42, 42, 74, 0.8);
  border-radius: 6px;
  color: #e2e2f0;
  padding: 5px 8px;
  font-size: 11px;
  width: 70px;
  outline: none;
}
.param-input:focus { border-color: #7c3aed; }

.test-btn {
  background: rgba(124, 58, 237, 0.2);
  color: #c4b5fd;
  border: 1px solid rgba(124, 58, 237, 0.4);
  border-radius: 6px;
  padding: 6px 16px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  margin-left: auto;
}
.test-btn:hover:not(:disabled) { background: rgba(124, 58, 237, 0.35); }
.test-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.test-result { flex: 1; overflow-y: auto; }

.result-header {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 16px;
  border-bottom: 1px solid rgba(42, 42, 74, 0.3);
}
.result-badge {
  font-size: 10px; font-weight: 700; letter-spacing: 1px;
  border: 1px solid; border-radius: 4px;
  padding: 2px 8px;
}
.result-meta { font-size: 12px; color: #8888aa; }

.result-error { padding: 12px 16px; }
.error-msg { font-size: 13px; color: #f87171; font-weight: 600; margin-bottom: 8px; }
.error-trace {
  background: rgba(248, 113, 113, 0.06);
  border: 1px solid rgba(248, 113, 113, 0.15);
  border-radius: 6px;
  padding: 10px;
  font-size: 11px;
  color: #f87171;
  overflow-x: auto;
  max-height: 200px;
  white-space: pre-wrap;
  word-break: break-all;
}

.result-list { padding: 4px 0; }
.result-item {
  padding: 8px 16px;
  border-bottom: 1px solid rgba(42, 42, 74, 0.2);
  cursor: pointer;
  transition: background 0.1s;
}
.result-item:hover { background: rgba(124, 58, 237, 0.04); }

.item-header { display: flex; align-items: center; gap: 8px; }
.item-idx { font-size: 10px; color: #666; width: 24px; flex-shrink: 0; }
.item-title { font-size: 13px; color: #e2e2f0; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.item-chevron { font-size: 10px; color: #666; flex-shrink: 0; }

.item-meta { display: flex; gap: 12px; margin-top: 3px; padding-left: 32px; }
.item-authors { font-size: 11px; color: #8888aa; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
.item-date { font-size: 11px; color: #666; flex-shrink: 0; }

.item-json {
  margin-top: 8px;
  background: rgba(10, 10, 26, 0.5);
  border: 1px solid rgba(42, 42, 74, 0.4);
  border-radius: 6px;
  padding: 10px;
  font-size: 11px;
  color: #c4b5fd;
  overflow-x: auto;
  max-height: 300px;
  white-space: pre-wrap;
  word-break: break-all;
}

.test-loading {
  display: flex; align-items: center; justify-content: center; gap: 10px;
  padding: 30px; color: #8888aa; font-size: 13px;
}
.spinner {
  width: 18px; height: 18px;
  border: 2px solid rgba(124, 58, 237, 0.2);
  border-top-color: #7c3aed;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.mono { font-family: 'Fira Code', 'Cascadia Code', monospace; }
</style>
