<template>
  <div class="rich-msg" :class="{ 'is-done': decided }">
    <header class="rich-msg__header">
      <span class="icon">🧩</span>
      <span class="title">AI 建议更新文献卡片</span>
      <el-tag v-if="decided === 'approved'" size="small" type="success" effect="plain">已采纳</el-tag>
      <el-tag v-else-if="decided === 'rejected'" size="small" effect="plain">已忽略</el-tag>
      <el-tag v-else size="small" type="warning" effect="plain">等你决定</el-tag>
    </header>

    <div class="rich-msg__body">
      <div class="doc-title">
        <span class="label">文献：</span>
        <span class="title-text">{{ richData.title || richData.doc_id }}</span>
      </div>
      <div class="field-label">
        <span>建议更新字段：</span>
        <el-tag size="small" effect="plain" type="info">{{ fieldLabel }}</el-tag>
      </div>

      <div class="comparison">
        <section class="side side-old">
          <div class="side-head">当前版本</div>
          <div v-if="Array.isArray(richData.current_value)" class="kp-list">
            <span v-for="(p, i) in richData.current_value" :key="i" class="kp">{{ p }}</span>
            <span v-if="!richData.current_value.length" class="empty">（空）</span>
          </div>
          <p v-else-if="richData.current_value" class="body-text">{{ richData.current_value }}</p>
          <p v-else class="empty">（空）</p>
        </section>
        <section class="side side-new">
          <div class="side-head">AI 建议版本</div>
          <div v-if="Array.isArray(richData.new_value)" class="kp-list">
            <span v-for="(p, i) in richData.new_value" :key="i" class="kp kp-new">{{ p }}</span>
          </div>
          <p v-else class="body-text">{{ richData.new_value }}</p>
        </section>
      </div>

      <div class="reason">
        <span class="r-label">理由：</span>
        <span>{{ richData.reason }}</span>
      </div>

      <footer v-if="!decided" class="actions">
        <el-button size="small" @click="reject">忽略</el-button>
        <el-button size="small" type="primary" :loading="loading" @click="approve">
          采纳更新
        </el-button>
      </footer>
      <footer v-else class="actions-done">
        <span v-if="decided === 'approved'">✓ 已写入（若你之前手动编辑过该字段，你的版本仍然优先）</span>
        <span v-else>已忽略此建议</span>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import { searchApi } from '../../../api/client'
import { useProjectStore } from '../../../stores/project'

interface Props {
  richData: {
    doc_id: string
    title?: string
    field: 'one_line_summary' | 'ai_summary' | 'ai_key_points'
    new_value: string | string[]
    reason: string
    current_value?: string | string[] | null
  }
}
const props = defineProps<Props>()

const projectStore = useProjectStore()
const loading = ref(false)
const decided = ref<'approved' | 'rejected' | null>(null)

const fieldLabel = computed(() => {
  const m: Record<string, string> = {
    one_line_summary: '一句话总结',
    ai_summary: '中文摘要',
    ai_key_points: '关键点',
  }
  return m[props.richData.field] || props.richData.field
})

async function approve() {
  const pid = projectStore.current?.id
  if (!pid) {
    ElMessage.error('未知项目上下文')
    return
  }
  loading.value = true
  try {
    await searchApi.applyAiUpdate(String(pid), props.richData.doc_id, {
      field: props.richData.field,
      new_value: props.richData.new_value,
      reason: props.richData.reason,
    })
    decided.value = 'approved'
    ElMessage.success('已采纳到文献卡片')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '应用失败')
  } finally {
    loading.value = false
  }
}

function reject() {
  decided.value = 'rejected'
}
</script>

<style scoped>
.rich-msg {
  margin: 14px 0;
  border-radius: 12px;
  background: linear-gradient(135deg, #f0f9ff 0%, #ecfdf5 100%);
  border: 1px solid #7dd3fc;
  overflow: hidden;
  transition: opacity 0.3s;
}
.rich-msg.is-done { opacity: 0.7; }
.rich-msg__header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  font-weight: 600;
  font-size: 13px;
  color: #0369a1;
  border-bottom: 1px solid #bae6fd;
  background: rgba(255, 255, 255, 0.5);
}
.icon { font-size: 16px; }
.rich-msg__body { padding: 12px 14px; }
.doc-title {
  font-size: 13px;
  color: #0f172a;
  margin-bottom: 6px;
  line-height: 1.5;
}
.doc-title .label { color: #64748b; margin-right: 4px; }
.title-text { font-weight: 500; word-break: break-word; }
.field-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #475569;
  margin-bottom: 8px;
}
.comparison {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 8px;
}
.side {
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 12.5px;
  min-width: 0;
}
.side-old { background: rgba(148, 163, 184, 0.12); border: 1px dashed #cbd5e1; }
.side-new { background: rgba(34, 197, 94, 0.10); border: 1px solid #86efac; }
.side-head {
  font-size: 11px;
  font-weight: 600;
  margin-bottom: 4px;
  color: #64748b;
}
.side-new .side-head { color: #15803d; }
.body-text {
  font-size: 12.5px;
  line-height: 1.5;
  color: #1f2937;
  margin: 0;
  word-break: break-word;
  white-space: pre-wrap;
}
.empty { font-size: 12px; color: #94a3b8; font-style: italic; margin: 0; }
.kp-list { display: flex; flex-wrap: wrap; gap: 4px; }
.kp {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: white;
  border: 1px solid #cbd5e1;
  color: #334155;
}
.kp-new {
  background: white;
  border-color: #86efac;
  color: #065f46;
}
.reason {
  font-size: 12px;
  color: #475569;
  line-height: 1.55;
  padding: 6px 8px;
  background: rgba(255, 255, 255, 0.55);
  border-radius: 6px;
  margin-bottom: 8px;
}
.reason .r-label { color: #0284c7; font-weight: 600; }
.actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}
.actions-done {
  font-size: 12px;
  color: #15803d;
  font-style: italic;
  padding: 4px 0;
}
</style>
