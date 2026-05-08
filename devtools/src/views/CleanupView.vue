<script setup lang="ts">
import { ref, onMounted } from 'vue'
import AppNav from '../components/AppNav.vue'
import { getCleanupPreview, runCleanupRounds, type CleanupPreview } from '../api/client'

const preview = ref<CleanupPreview | null>(null)
const loading = ref(false)
const running = ref(false)
const lastRunResult = ref<{ deleted: number; triggered_by: string } | null>(null)
const error = ref<string | null>(null)

async function loadPreview() {
  loading.value = true
  error.value = null
  try {
    const res = await getCleanupPreview()
    preview.value = res.data
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function runCleanup() {
  if (!preview.value || preview.value.expired_count === 0) {
    alert('当前没有过期 round 可清理')
    return
  }
  if (!confirm(
    `确认清理 ${preview.value.expired_count} 个过期 round?\n\n` +
    '说明：仅删 search_rounds（CASCADE 带走 round_documents 关联），不删 documents 全局表。' +
    '\n\n⚠️ web 用户没客户端副本时云端是唯一来源，删除不可撤销。',
  )) return

  running.value = true
  try {
    const res = await runCleanupRounds()
    lastRunResult.value = res.data
    await loadPreview()  // 刷新预览
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    running.value = false
  }
}

onMounted(loadPreview)
</script>

<template>
  <div class="page">
    <AppNav />

    <div class="content">
      <div class="header">
        <h1>Cleanup · 过期轮次清理</h1>
        <p class="subtitle">
          M3 F1: 自动 beat 已禁用（避免 web 用户历史 round 被自动删）。
          这里手动 review + trigger。
        </p>
      </div>

      <div v-if="loading" class="loading">加载中…</div>

      <div v-else-if="preview" class="card-grid">
        <div class="card">
          <div class="card-label">过期可清理</div>
          <div class="card-value danger">{{ preview.expired_count }}</div>
          <div class="card-hint">expires_at &lt; now_utc</div>
        </div>
        <div class="card">
          <div class="card-label">已设 TTL</div>
          <div class="card-value">{{ preview.has_ttl_count }}</div>
          <div class="card-hint">finalize 时设为 NOW + 7d</div>
        </div>
        <div class="card">
          <div class="card-label">total rounds</div>
          <div class="card-value">{{ preview.total_rounds }}</div>
          <div class="card-hint">DB 全部 search_rounds</div>
        </div>
      </div>

      <div v-if="preview" class="schedule-bar">
        <span class="dot" :class="preview.auto_schedule_enabled ? 'on' : 'off'" />
        Auto schedule: <strong>{{ preview.auto_schedule_enabled ? 'ENABLED' : 'DISABLED' }}</strong>
        <span class="hint">— {{ preview.auto_schedule_note }}</span>
      </div>

      <div v-if="lastRunResult" class="run-result">
        ✓ 上次手动清理：删除 {{ lastRunResult.deleted }} 条 round（by {{ lastRunResult.triggered_by }}）
      </div>

      <div v-if="error" class="err">⚠️ {{ error }}</div>

      <div class="actions">
        <button class="btn-refresh" @click="loadPreview" :disabled="loading">🔄 刷新预览</button>
        <button
          class="btn-run"
          :disabled="!preview || preview.expired_count === 0 || running"
          @click="runCleanup"
        >
          {{ running ? '清理中…' : '⚠️ 立即清理' }}
        </button>
      </div>

      <div class="footnote">
        <p><strong>什么会被删</strong>：search_rounds.expires_at &lt; NOW 的 round（一般是 finalize 后超过 7 天）。</p>
        <p><strong>不会删</strong>：documents 全局表（多 round 共用），round_documents 通过 CASCADE 自动删（join 表，安全）。</p>
        <p><strong>恢复</strong>：删除不可撤销。client 端 SQLite 副本仍保留（M2 设计）。</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { min-height: 100vh; background: #0a0a1a; color: #e8e8f0; }
.content { max-width: 920px; margin: 32px auto; padding: 0 24px; }
.header h1 { margin: 0 0 6px; font-size: 22px; color: #fff; }
.subtitle { margin: 0 0 24px; color: #8888aa; font-size: 13px; }

.loading { padding: 40px; text-align: center; color: #8888aa; }

.card-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.card {
  padding: 16px 20px;
  background: rgba(124, 58, 237, 0.06);
  border: 1px solid rgba(124, 58, 237, 0.2);
  border-radius: 8px;
}
.card-label { font-size: 11px; color: #8888aa; letter-spacing: 1px; text-transform: uppercase; }
.card-value { font-size: 32px; font-weight: 700; margin: 6px 0; color: #fff; }
.card-value.danger { color: #f87171; }
.card-hint { font-size: 11px; color: #6a6a85; }

.schedule-bar {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 16px; margin-bottom: 16px;
  background: rgba(42, 42, 74, 0.3); border-radius: 6px; font-size: 13px;
}
.schedule-bar .dot { width: 8px; height: 8px; border-radius: 50%; }
.schedule-bar .dot.on { background: #67c23a; }
.schedule-bar .dot.off { background: #f87171; }
.schedule-bar .hint { color: #8888aa; font-size: 12px; }

.run-result { padding: 10px 16px; margin-bottom: 16px; background: rgba(103, 194, 58, 0.1); border-radius: 6px; color: #67c23a; font-size: 13px; }
.err { padding: 10px 16px; margin-bottom: 16px; background: rgba(248, 113, 113, 0.1); border-radius: 6px; color: #f87171; font-size: 13px; }

.actions { display: flex; gap: 10px; margin-bottom: 24px; }
.btn-refresh, .btn-run {
  padding: 8px 18px; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 600;
  border: 1px solid rgba(124, 58, 237, 0.3);
  background: rgba(124, 58, 237, 0.08);
  color: #c4b5fd;
}
.btn-refresh:hover { background: rgba(124, 58, 237, 0.18); }
.btn-run {
  border-color: rgba(248, 113, 113, 0.4);
  background: rgba(248, 113, 113, 0.1);
  color: #f87171;
}
.btn-run:hover:not(:disabled) { background: rgba(248, 113, 113, 0.2); }
.btn-run:disabled { opacity: 0.4; cursor: not-allowed; }

.footnote {
  font-size: 12px; color: #8888aa; line-height: 1.7;
  padding: 14px 18px; background: rgba(42, 42, 74, 0.2); border-radius: 6px;
}
.footnote p { margin: 0 0 6px; }
.footnote p:last-child { margin: 0; }
</style>
