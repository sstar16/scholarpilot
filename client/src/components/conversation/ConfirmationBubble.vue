<template>
  <div class="confirm-bubble">
    <div class="confirm-bubble__header">
      <el-icon :size="16"><MagicStick /></el-icon>
      <span class="confirm-bubble__agent">{{ agentLabel }}</span>
    </div>

    <div class="confirm-bubble__summary" v-html="renderedSummary" />

    <!-- Editable details (expandable) -->
    <el-collapse v-if="hasEditableDetails" v-model="expanded" class="confirm-bubble__details">
      <el-collapse-item title="查看详情 / 编辑" name="details">
        <!-- 标题 / 描述 — 文本输入 -->
        <div v-if="'title' in editableDetails" class="detail-row">
          <span class="detail-label">标题</span>
          <el-input v-model="localEdits.title" size="small" />
        </div>
        <div v-if="'description' in editableDetails" class="detail-row">
          <span class="detail-label">描述</span>
          <el-input v-model="localEdits.description" type="textarea" :rows="2" size="small" />
        </div>

        <!-- 研究领域 — 多选 -->
        <div v-if="'domains' in editableDetails" class="detail-row">
          <span class="detail-label">研究领域</span>
          <el-select
            v-model="localEdits.domains"
            multiple
            collapse-tags
            collapse-tags-tooltip
            size="small"
            placeholder="选择领域（可多选）"
            style="width: 100%"
          >
            <el-option
              v-for="opt in DOMAIN_OPTIONS"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </div>

        <!-- 文献类型 — 单选 enum -->
        <div v-if="'doc_types' in editableDetails" class="detail-row">
          <span class="detail-label">文献类型</span>
          <el-select v-model="localEdits.doc_types" size="small" style="width: 100%">
            <el-option
              v-for="opt in DOC_TYPE_OPTIONS"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </div>

        <!-- 检索范围 — 单选 enum -->
        <div v-if="'scope' in editableDetails" class="detail-row">
          <span class="detail-label">检索范围</span>
          <el-select v-model="localEdits.scope" size="small" style="width: 100%">
            <el-option
              v-for="opt in SCOPE_OPTIONS"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </div>

        <!-- 关键概念 — 数组（标签输入） -->
        <div v-if="'key_concepts' in editableDetails" class="detail-row">
          <span class="detail-label">关键概念</span>
          <el-select
            v-model="localEdits.key_concepts"
            multiple
            filterable
            allow-create
            default-first-option
            size="small"
            placeholder="输入回车添加"
            style="width: 100%"
          >
            <el-option
              v-for="kc in (localEdits.key_concepts || [])"
              :key="kc"
              :label="kc"
              :value="kc"
            />
          </el-select>
        </div>
      </el-collapse-item>
    </el-collapse>

    <!-- Action buttons -->
    <div class="confirm-bubble__actions">
      <el-button @click="$emit('cancel')" size="default">
        取消 <span class="shortcut">Esc</span>
      </el-button>
      <el-button @click="showSupplement = true" size="default" v-if="envelope.options.includes('supplement')">
        补充...
      </el-button>
      <el-button type="primary" @click="handleConfirm" size="default">
        确认 <span class="shortcut">Enter</span>
      </el-button>
      <el-checkbox
        v-if="envelope.auto_confirmable"
        v-model="autoConfirm"
        label="后续自动确认"
        size="small"
        class="auto-check"
      />
    </div>

    <!-- Supplement input (inline) -->
    <div v-if="showSupplement" class="confirm-bubble__supplement">
      <el-input
        v-model="supplementText"
        type="textarea"
        :rows="2"
        placeholder="补充说明（自然语言）..."
        @keydown.enter.ctrl="handleSupplement"
      />
      <el-button type="primary" size="small" @click="handleSupplement" :disabled="!supplementText.trim()">
        发送补充
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import type { ConfirmationEnvelope } from '../../stores/conversation'

const props = defineProps<{ envelope: ConfirmationEnvelope }>()
const emit = defineEmits<{
  confirm: [edits: Record<string, any> | undefined, autoConfirm: boolean]
  cancel: []
  supplement: [text: string]
}>()

const expanded = ref<string[]>([])
const showSupplement = ref(false)
const supplementText = ref('')
const autoConfirm = ref(false)
const localEdits = ref<Record<string, any>>({})

const agentLabel = computed(() => {
  const names: Record<string, string> = {
    intent_analysis: 'IntentAnalysis Agent',
    query_plan: 'QueryPlan Agent',
    system: 'System',
  }
  return names[props.envelope.agent_name] || props.envelope.agent_name
})

// summary_zh 由后端基于 details 字段反向格式化（中文标签），所以可以直接渲染
// markdown 加粗 + 换行。前端不再做字段拼接，避免和编辑面板出现差异。
const renderedSummary = computed(() => {
  return (props.envelope.summary_zh || '')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
})

const EDITABLE_KEYS = ['title', 'description', 'domains', 'doc_types', 'scope', 'key_concepts'] as const

const editableDetails = computed(() => {
  const d = props.envelope.details || {}
  const show: Record<string, any> = {}
  for (const k of EDITABLE_KEYS) {
    if (k in d && d[k] != null) show[k] = d[k]
  }
  return show
})

const hasEditableDetails = computed(() => Object.keys(editableDetails.value).length > 0)

// 中文 label 与 IntentAnalysisAgent VALID_* 集合对齐（backend/app/harness/intent_agent.py）
const DOMAIN_OPTIONS = [
  { value: 'biology', label: '生物学' },
  { value: 'chemistry', label: '化学' },
  { value: 'physics', label: '物理学' },
  { value: 'medicine', label: '医学' },
  { value: 'engineering', label: '工程' },
  { value: 'computer_science', label: '计算机科学' },
  { value: 'mathematics', label: '数学' },
  { value: 'materials_science', label: '材料科学' },
  { value: 'environmental_science', label: '环境科学' },
  { value: 'agriculture', label: '农业' },
  { value: 'psychology', label: '心理学' },
  { value: 'economics', label: '经济学' },
  { value: 'social_science', label: '社会科学' },
  { value: 'law', label: '法学' },
  { value: 'interdisciplinary', label: '跨学科' },
]
const DOC_TYPE_OPTIONS = [
  { value: 'literature', label: '学术文献' },
  { value: 'patent', label: '专利' },
  { value: 'both', label: '文献 + 专利' },
]
const SCOPE_OPTIONS = [
  { value: 'chinese_first', label: '中文优先' },
  { value: 'international', label: '国际英文' },
  { value: 'global', label: '全球多语言' },
]

// Initialize localEdits from details — 全部 EDITABLE_KEYS 都同步
onMounted(() => {
  const d = props.envelope.details || {}
  const init: Record<string, any> = {}
  for (const k of EDITABLE_KEYS) {
    const v = d[k]
    if (Array.isArray(v)) {
      init[k] = [...v]
    } else if (v == null) {
      init[k] = k === 'domains' || k === 'key_concepts' ? [] : ''
    } else {
      init[k] = v
    }
  }
  localEdits.value = init
})

function handleConfirm() {
  // Collect edits that differ from original — 数组用 JSON 比较，字符串用 ===
  const edits: Record<string, any> = {}
  const orig = props.envelope.details || {}
  for (const [k, v] of Object.entries(localEdits.value)) {
    const origV = orig[k]
    const isEqual = Array.isArray(v) && Array.isArray(origV)
      ? JSON.stringify(v) === JSON.stringify(origV)
      : v === origV
    if (!isEqual && v !== '' && !(Array.isArray(v) && v.length === 0)) {
      edits[k] = v
    }
  }
  emit('confirm', Object.keys(edits).length > 0 ? edits : undefined, autoConfirm.value)
}

function handleSupplement() {
  if (supplementText.value.trim()) {
    emit('supplement', supplementText.value.trim())
    supplementText.value = ''
    showSupplement.value = false
  }
}

// Keyboard shortcuts
function onKeydown(e: KeyboardEvent) {
  // 忽略表单元素内的按键，避免 ChatPanel 输入框按 Enter 发送消息时
  // 冒泡到 window 同时触发 handleConfirm，造成"并发创建项目"race condition
  const target = e.target as HTMLElement | null
  if (target) {
    const tag = target.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA' || target.isContentEditable) {
      return
    }
  }
  if (e.key === 'Escape') {
    emit('cancel')
  } else if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !showSupplement.value) {
    handleConfirm()
  }
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.confirm-bubble {
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 12px;
  padding: 16px;
  margin: 12px 0;
  animation: richMsgEnter 280ms cubic-bezier(0.4, 0, 0.2, 1) both;
}
.confirm-bubble__header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #67c23a;
  font-weight: 600;
  margin-bottom: 10px;
}
.confirm-bubble__summary { font-size: 14px; line-height: 1.7; margin-bottom: 12px; }
.confirm-bubble__details { margin-bottom: 12px; }
.detail-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.detail-label { font-size: 13px; color: #606266; min-width: 80px; }
.confirm-bubble__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.auto-check { margin-left: auto; }
.shortcut {
  font-size: 11px;
  color: #c0c4cc;
  margin-left: 4px;
}
.confirm-bubble__supplement {
  margin-top: 10px;
  display: flex;
  gap: 8px;
  align-items: flex-end;
}
.confirm-bubble__supplement .el-input { flex: 1; }
</style>
