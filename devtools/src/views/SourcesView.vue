<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  getSourceRegistry,
  updateSourceConfig,
  resetSourceStats,
  type SourceInfo,
} from '../api/client'
import AppNav from '../components/AppNav.vue'
import SourceTable from '../components/SourceTable.vue'
import SourceDetail from '../components/SourceDetail.vue'
import SourceTestPanel from '../components/SourceTestPanel.vue'

const sources = ref<SourceInfo[]>([])
const selectedId = ref<string | null>(null)
const loading = ref(false)
const globalProxy = ref('')

let refreshTimer: ReturnType<typeof setInterval> | null = null

const selectedSource = computed(() =>
  sources.value.find((s) => s.source_id === selectedId.value) ?? null,
)

async function fetchSources() {
  loading.value = true
  try {
    const resp = await getSourceRegistry()
    sources.value = resp.data.sources
    globalProxy.value = resp.data.global_proxy || ''
  } catch {
    // silent
  } finally {
    loading.value = false
  }
}

async function handleConfigUpdate(
  sourceId: string,
  config: { enabled?: boolean; credentials?: Record<string, string> },
) {
  try {
    await updateSourceConfig(sourceId, config)
    await fetchSources()
  } catch {
    // silent
  }
}

async function handleStatsReset(sourceId: string) {
  try {
    await resetSourceStats(sourceId)
    await fetchSources()
  } catch {
    // silent
  }
}

onMounted(async () => {
  await fetchSources()
  refreshTimer = setInterval(fetchSources, 30_000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<template>
  <div class="sources-page">
    <AppNav>
      <template #actions>
        <button class="refresh-btn" @click="fetchSources">↻ Refresh</button>
      </template>
    </AppNav>

    <!-- Main content -->
    <main class="sources-content">
      <!-- Left: Source List -->
      <div class="panel left-panel">
        <SourceTable
          :sources="sources"
          :selected-id="selectedId"
          @select="(id) => selectedId = id"
        />
      </div>

      <!-- Right -->
      <div class="right-panels">
        <!-- Detail + Config -->
        <div class="panel detail-panel">
          <SourceDetail
            :source="selectedSource"
            :global-proxy="globalProxy"
            @config-updated="handleConfigUpdate"
            @stats-reset="handleStatsReset"
          />
        </div>

        <!-- Test Panel -->
        <div class="panel test-panel-wrap">
          <SourceTestPanel
            :source-id="selectedId"
            :source-name="selectedSource?.name ?? ''"
          />
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.sources-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #0a0a1a 0%, #1a1a2e 50%, #0a0a1a 100%);
  color: #e2e2f0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.refresh-btn {
  background: rgba(42, 42, 74, 0.5); color: #c4b5fd;
  border: 1px solid rgba(42, 42, 74, 0.8); border-radius: 6px;
  padding: 5px 12px; font-size: 12px; cursor: pointer; transition: all 0.15s;
}
.refresh-btn:hover { background: rgba(124, 58, 237, 0.15); border-color: #7c3aed; }

/* ── Layout ── */
.sources-content {
  display: grid;
  grid-template-columns: 380px 1fr;
  gap: 16px;
  padding: 20px 24px;
  max-width: 1600px;
  margin: 0 auto;
  height: calc(100vh - 60px);
}

.panel {
  background: rgba(19, 19, 43, 0.7);
  border: 1px solid rgba(42, 42, 74, 0.6);
  border-radius: 12px;
  overflow: hidden;
}

.left-panel { height: 100%; overflow: hidden; }

.right-panels {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
  overflow: hidden;
}
.detail-panel { flex: 0 0 auto; max-height: 40%; overflow-y: auto; }
.test-panel-wrap { flex: 1; min-height: 300px; overflow: auto; display: flex; flex-direction: column; }

.mono { font-family: 'Fira Code', 'Cascadia Code', monospace; }
</style>
