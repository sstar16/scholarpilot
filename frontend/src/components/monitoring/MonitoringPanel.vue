<template>
  <div class="monitoring-panel">
    <div class="mp-header">
      <div class="mp-title-row">
        <span class="mp-icon">📡</span>
        <h4 class="mp-title">每日监控</h4>
        <el-switch
          v-model="enabled"
          :loading="toggling"
          @change="onToggle"
          style="margin-left: auto"
        />
      </div>
      <p class="mp-desc">
        {{ enabled ? '监控已开启，系统每天自动检索新发表的相关文献' : '开启后系统将每天自动检索新论文并通知您' }}
      </p>
    </div>

    <!-- Config section (only when enabled) -->
    <div v-if="enabled" class="mp-config">
      <div class="mp-config-row">
        <span class="mp-label">频率</span>
        <el-radio-group v-model="schedule" size="small" @change="onConfigChange">
          <el-radio-button value="daily">每天</el-radio-button>
          <el-radio-button value="weekly">每周</el-radio-button>
        </el-radio-group>
      </div>
      <div v-if="lastRun" class="mp-config-row">
        <span class="mp-label">上次运行</span>
        <span class="mp-value">{{ formatDate(lastRun) }}</span>
      </div>
    </div>

    <!-- Recent results -->
    <div v-if="enabled && latestResults.length > 0" class="mp-results">
      <h5 class="mp-results-title">最近监控结果</h5>
      <div v-for="r in latestResults" :key="r.id" class="mp-result">
        <span class="mp-result-date">{{ formatDate(r.run_at) }}</span>
        <span class="mp-result-count">{{ r.new_docs_found }} 篇新文献</span>
      </div>
    </div>
    <p v-else-if="enabled" class="mp-empty">暂无监控结果</p>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { monitorApi } from '../../api/client'

const props = defineProps<{ projectId: string }>()

const enabled = ref(false)
const toggling = ref(false)
const schedule = ref('daily')
const lastRun = ref<string | null>(null)
const latestResults = ref<any[]>([])

async function fetchStatus() {
  try {
    const res = await monitorApi.get(props.projectId)
    enabled.value = res.data.enabled
    schedule.value = res.data.schedule || 'daily'
    lastRun.value = res.data.last_run_at
    latestResults.value = res.data.latest_results || []
  } catch { /* ignore */ }
}

async function onToggle(val: boolean) {
  toggling.value = true
  try {
    if (val) {
      await monitorApi.enable(props.projectId, { schedule: schedule.value })
      ElMessage.success('监控已开启')
    } else {
      await monitorApi.disable(props.projectId)
      ElMessage.success('监控已关闭')
    }
    await fetchStatus()
  } catch (e: any) {
    enabled.value = !val  // revert
    ElMessage.error(e.response?.data?.detail || '操作失败')
  } finally {
    toggling.value = false
  }
}

async function onConfigChange() {
  try {
    await monitorApi.update(props.projectId, { schedule: schedule.value })
  } catch { /* ignore */ }
}

function formatDate(d: string): string {
  if (!d) return ''
  return new Date(d).toLocaleString('zh-CN', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

onMounted(fetchStatus)
</script>

<style scoped>
.monitoring-panel {
  border: 1px solid var(--ink-100, #e2e8f0);
  border-radius: 12px;
  padding: 16px 20px;
  background: var(--paper, #fff);
}
.mp-header { margin-bottom: 12px; }
.mp-title-row {
  display: flex; align-items: center; gap: 8px;
}
.mp-icon { font-size: 18px; }
.mp-title {
  font-size: 14px; font-weight: 700; color: var(--ink-800, #1e293b);
  margin: 0;
}
.mp-desc {
  font-size: 12px; color: var(--ink-400, #94a3b8); margin: 6px 0 0;
}

.mp-config { margin: 12px 0; }
.mp-config-row {
  display: flex; align-items: center; gap: 12px;
  padding: 6px 0;
}
.mp-label {
  font-size: 12px; font-weight: 500; color: var(--ink-500, #64748b);
  min-width: 60px;
}
.mp-value { font-size: 12px; color: var(--ink-600, #475569); }

.mp-results { margin-top: 12px; }
.mp-results-title {
  font-size: 12px; font-weight: 600; color: var(--ink-600);
  margin: 0 0 8px;
}
.mp-result {
  display: flex; justify-content: space-between;
  padding: 6px 0; border-bottom: 1px solid var(--ink-50, #f8fafc);
  font-size: 12px;
}
.mp-result-date { color: var(--ink-400); }
.mp-result-count { color: var(--signal-teal, #0d9488); font-weight: 600; }
.mp-empty { font-size: 12px; color: var(--ink-300); margin: 8px 0; }
</style>
