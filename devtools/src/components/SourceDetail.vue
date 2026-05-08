<script setup lang="ts">
import { ref, watch } from 'vue'
import type { SourceInfo } from '../api/client'

const props = defineProps<{
  source: SourceInfo | null
  globalProxy: string
}>()

const emit = defineEmits<{
  'config-updated': [sourceId: string, config: { enabled?: boolean; credentials?: Record<string, string>; proxy?: string; global_proxy?: string }]
  'stats-reset': [sourceId: string]
}>()

const localEnabled = ref(true)
const credentialInputs = ref<Record<string, string>>({})
const localProxy = ref('')
const localGlobalProxy = ref('')
const saving = ref(false)

watch(
  () => props.source,
  (s) => {
    if (s) {
      localEnabled.value = s.enabled
      credentialInputs.value = {}
      for (const key of s.credentials.required) {
        credentialInputs.value[key] = ''
      }
      localProxy.value = s.proxy || ''
      localGlobalProxy.value = props.globalProxy || ''
    }
  },
  { immediate: true },
)

function handleSave() {
  if (!props.source) return
  saving.value = true

  const creds: Record<string, string> = {}
  for (const [k, v] of Object.entries(credentialInputs.value)) {
    if (v.trim()) creds[k] = v.trim()
  }

  emit('config-updated', props.source.source_id, {
    enabled: localEnabled.value,
    credentials: Object.keys(creds).length > 0 ? creds : undefined,
    proxy: localProxy.value,
    global_proxy: localGlobalProxy.value !== props.globalProxy ? localGlobalProxy.value : undefined,
  })

  setTimeout(() => { saving.value = false }, 500)
}

function docTypeLabel(t: string) {
  const map: Record<string, string> = { paper: 'Paper', preprint: 'Preprint', patent: 'Patent', clinical_trial: 'Clinical Trial' }
  return map[t] || t
}
</script>

<template>
  <div class="source-detail" v-if="source">
    <!-- Info Section -->
    <div class="detail-section">
      <h3 class="section-title">{{ source.name }}</h3>
      <p class="source-desc">{{ source.description }}</p>
      <div class="meta-grid">
        <div class="meta-item">
          <span class="meta-label">TYPE</span>
          <span class="meta-value">{{ docTypeLabel(source.doc_type) }}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">CATEGORY</span>
          <span class="meta-value">{{ source.category }}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">LANGUAGE</span>
          <span class="meta-value">{{ source.language }}</span>
        </div>
        <div class="meta-item">
          <span class="meta-label">PHASE</span>
          <span class="meta-value">{{ source.phase }}</span>
        </div>
      </div>
    </div>

    <!-- Stats Section -->
    <div class="detail-section">
      <h4 class="section-subtitle">Runtime Stats</h4>
      <div class="stats-row">
        <div class="mini-stat">
          <span class="stat-val mono">{{ source.stats.total_invocations }}</span>
          <span class="stat-label">Calls</span>
        </div>
        <div class="mini-stat">
          <span class="stat-val mono" :style="{ color: source.stats.reliability >= 0.9 ? '#4ade80' : source.stats.reliability >= 0.7 ? '#fbbf24' : '#f87171' }">
            {{ source.stats.total_invocations > 0 ? (source.stats.reliability * 100).toFixed(1) + '%' : '--' }}
          </span>
          <span class="stat-label">Reliability</span>
        </div>
        <div class="mini-stat">
          <span class="stat-val mono">{{ source.stats.avg_latency_ms > 0 ? source.stats.avg_latency_ms + 'ms' : '--' }}</span>
          <span class="stat-label">Avg Latency</span>
        </div>
        <button class="action-btn small" @click="emit('stats-reset', source.source_id)">Reset</button>
      </div>
    </div>

    <!-- Config Section -->
    <div class="detail-section">
      <h4 class="section-subtitle">Configuration</h4>
      <div class="config-row">
        <span class="config-label">Enabled</span>
        <label class="toggle">
          <input type="checkbox" v-model="localEnabled" :disabled="!source.has_fetcher" />
          <span class="toggle-slider" />
        </label>
        <span v-if="!source.has_fetcher" class="no-impl-hint">No fetcher implementation</span>
      </div>

      <div class="cred-section">
        <div class="cred-row">
          <label class="cred-label mono">GLOBAL_PROXY</label>
          <input
            type="text"
            class="cred-input mono"
            v-model="localGlobalProxy"
            placeholder="http://127.0.0.1:7890"
          />
        </div>
        <div class="cred-row">
          <label class="cred-label mono">SOURCE_PROXY</label>
          <input
            type="text"
            class="cred-input mono"
            v-model="localProxy"
            placeholder="(use global)"
          />
        </div>
      </div>

      <div v-if="source.credentials.required.length > 0" class="cred-section">
        <div v-for="key in source.credentials.required" :key="key" class="cred-row">
          <label class="cred-label mono">{{ key }}</label>
          <input
            type="password"
            class="cred-input mono"
            v-model="credentialInputs[key]"
            :placeholder="source.credentials.configured[key] || '(not set)'"
          />
        </div>
      </div>

      <button class="action-btn primary" :disabled="saving" @click="handleSave">
        {{ saving ? 'Saving...' : 'Save Config' }}
      </button>
    </div>
  </div>

  <div v-else class="empty-detail">
    <span class="empty-icon">&#9881;</span>
    <p>Select a source to view details</p>
  </div>
</template>

<style scoped>
.source-detail { display: flex; flex-direction: column; gap: 0; }

.detail-section {
  padding: 14px 16px;
  border-bottom: 1px solid rgba(42, 42, 74, 0.4);
}
.section-title { font-size: 16px; font-weight: 700; color: #e2e2f0; margin: 0 0 4px; }
.section-subtitle { font-size: 11px; font-weight: 700; color: #8888aa; text-transform: uppercase; letter-spacing: 1.5px; margin: 0 0 10px; }
.source-desc { font-size: 12px; color: #8888aa; margin: 0 0 10px; line-height: 1.4; }

.meta-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.meta-item { display: flex; flex-direction: column; gap: 1px; }
.meta-label { font-size: 9px; font-weight: 700; color: #666; letter-spacing: 1px; text-transform: uppercase; }
.meta-value { font-size: 12px; color: #c4b5fd; }

.stats-row { display: flex; align-items: center; gap: 16px; }
.mini-stat { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.stat-val { font-size: 16px; font-weight: 700; color: #e2e2f0; }
.stat-label { font-size: 9px; color: #666; text-transform: uppercase; letter-spacing: 1px; }

.config-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.config-label { font-size: 12px; color: #c4b5fd; font-weight: 600; }
.no-impl-hint { font-size: 11px; color: #f87171; }

.toggle { position: relative; display: inline-block; width: 36px; height: 20px; }
.toggle input { opacity: 0; width: 0; height: 0; }
.toggle-slider {
  position: absolute; inset: 0;
  background: rgba(42, 42, 74, 0.8);
  border-radius: 10px;
  cursor: pointer;
  transition: 0.2s;
}
.toggle-slider::before {
  content: '';
  position: absolute;
  width: 16px; height: 16px;
  left: 2px; bottom: 2px;
  background: #8888aa;
  border-radius: 50%;
  transition: 0.2s;
}
.toggle input:checked + .toggle-slider { background: rgba(124, 58, 237, 0.4); }
.toggle input:checked + .toggle-slider::before { transform: translateX(16px); background: #7c3aed; }
.toggle input:disabled + .toggle-slider { opacity: 0.4; cursor: not-allowed; }

.cred-section { margin: 10px 0; display: flex; flex-direction: column; gap: 6px; }
.cred-row { display: flex; align-items: center; gap: 8px; }
.cred-label { font-size: 10px; color: #8888aa; width: 180px; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; }
.cred-input {
  flex: 1;
  background: rgba(10, 10, 26, 0.6);
  border: 1px solid rgba(42, 42, 74, 0.8);
  border-radius: 6px;
  color: #e2e2f0;
  padding: 5px 8px;
  font-size: 11px;
  outline: none;
}
.cred-input:focus { border-color: #7c3aed; }

.action-btn {
  background: rgba(42, 42, 74, 0.6);
  color: #c4b5fd;
  border: 1px solid rgba(42, 42, 74, 0.8);
  border-radius: 6px;
  padding: 6px 14px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.action-btn:hover { background: rgba(124, 58, 237, 0.15); border-color: #7c3aed; }
.action-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.action-btn.primary { background: rgba(124, 58, 237, 0.2); border-color: rgba(124, 58, 237, 0.4); margin-top: 6px; }
.action-btn.small { font-size: 10px; padding: 3px 8px; margin-left: auto; }

.empty-detail {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  height: 100%; color: #666; gap: 8px;
}
.empty-icon { font-size: 32px; opacity: 0.3; }
.empty-detail p { font-size: 13px; }

.mono { font-family: 'Fira Code', 'Cascadia Code', monospace; }
</style>
