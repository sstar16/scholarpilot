<template>
  <div class="rich-msg rich-msg--plan" :class="{ 'is-locked': !isActive }">
    <header class="rich-msg__header">
      <el-icon :size="18"><MagicStick /></el-icon>
      <span class="title">AI 的调研计划</span>
      <el-tag v-if="isActive" size="small" type="warning" effect="plain">等你确认</el-tag>
      <el-tag v-else size="small" effect="plain" type="success">已提交</el-tag>
    </header>

    <div v-if="isActive" class="rich-msg__body">
      <p class="intro">
        AI 基于你的问题 <em>"{{ truncate(richData.question, 60) }}"</em>，
        建议精读下列文献并展开以下实体。你可以勾选、补充或删除。
      </p>

      <!-- 精读文献 -->
      <section class="plan-section">
        <div class="sec-head">
          <el-icon><Reading /></el-icon>
          <strong>要精读的文献</strong>
          <span class="count">· 选中 {{ selectedPicks.length }} / {{ picks.length }}</span>
          <div class="spacer" />
          <el-popover placement="bottom-end" :width="340" trigger="click">
            <template #reference>
              <el-button size="small" text type="primary" :disabled="!addablePicks.length">
                + 加一篇
              </el-button>
            </template>
            <div class="popover-title">从候选里补一篇（仅列全文可用的）</div>
            <div
              v-for="cand in addablePicks"
              :key="cand.id"
              class="popover-item"
              @click="addPick(cand)"
            >
              <div class="pi-title">{{ cand.title }}</div>
              <div v-if="cand.one_line_summary" class="pi-summary">
                {{ cand.one_line_summary }}
              </div>
            </div>
            <div v-if="!addablePicks.length" class="empty">没有更多有全文的候选</div>
          </el-popover>
        </div>
        <div v-if="!picks.length" class="empty-line">
          （AI 认为摘要已足够；你也可以手动加一篇精读）
        </div>
        <div
          v-for="(p, i) in picks"
          :key="'p-' + i"
          class="item pick-item"
          :class="{ off: !p._checked }"
        >
          <div class="pick-head">
            <el-checkbox v-model="p._checked" />
            <div class="item-body">
              <div class="item-title">{{ titleForDoc(p.doc_id) }}</div>
              <el-input
                v-model="p.reason"
                size="small"
                placeholder="为什么要读这篇全文？"
                :maxlength="200"
                class="reason-input"
              />
            </div>
            <el-button size="small" text @click="removePick(i)">
              <el-icon><Close /></el-icon>
            </el-button>
          </div>
          <!-- 探针命中 excerpts -->
          <div v-if="probesForDoc(p.doc_id).length" class="probes-block">
            <div class="probes-head">
              <span class="probes-title">
                🧬 探针命中 {{ probesForDoc(p.doc_id).length }} 段原文
              </span>
              <el-button
                size="small"
                text
                type="primary"
                @click="toggleAllProbesForDoc(p.doc_id)"
              >
                {{ allProbesCheckedForDoc(p.doc_id) ? '全不选' : '全选' }}
              </el-button>
            </div>
            <div
              v-for="ex in probesForDoc(p.doc_id)"
              :key="excerptKey(ex)"
              class="probe-item"
              :class="{ off: !excerptChecked[excerptKey(ex)] }"
            >
              <el-checkbox v-model="excerptChecked[excerptKey(ex)]" />
              <div class="probe-body">
                <div class="probe-meta">
                  <el-tag size="small" effect="plain" type="warning">
                    {{ ex.section_label || '片段 ' + ex.section_idx }}
                  </el-tag>
                  <span class="probe-score">
                    相关性 {{ (ex.relevance || 0).toFixed(2) }}
                  </span>
                  <span class="probe-range">
                    字符 {{ ex.char_start }}-{{ ex.char_end }}
                  </span>
                </div>
                <div v-if="ex.insight" class="probe-insight">
                  {{ ex.insight }}
                </div>
                <blockquote class="probe-quote">"{{ ex.excerpt_quote }}"</blockquote>
              </div>
            </div>
          </div>
          <div v-else-if="hasAnyProbes" class="probes-empty">
            （此篇探针未命中任何高相关性段落）
          </div>
        </div>
      </section>

      <!-- KG 实体 -->
      <section class="plan-section">
        <div class="sec-head">
          <el-icon><Share /></el-icon>
          <strong>要查询的 KG 实体</strong>
          <span class="count">· 选中 {{ selectedQueries.length }} / {{ queries.length }}</span>
          <div class="spacer" />
          <el-popover placement="bottom-end" :width="340" trigger="click">
            <template #reference>
              <el-button size="small" text type="primary" :disabled="!addableEntities.length">
                + 加一个
              </el-button>
            </template>
            <div class="popover-title">从 KG 候选里补一个</div>
            <div
              v-for="ent in addableEntities"
              :key="ent.entity_id"
              class="popover-item"
              @click="addQuery(ent)"
            >
              <div class="pi-title">
                <el-tag size="small" effect="plain">{{ ent.node_type }}</el-tag>
                <span class="ent-label">{{ ent.label }}</span>
                <span class="degree">· degree {{ ent.degree }}</span>
              </div>
            </div>
            <div v-if="!addableEntities.length" class="empty">KG 里没有更多可选实体</div>
          </el-popover>
        </div>
        <div v-if="!queries.length" class="empty-line">
          （AI 本轮没挑 KG 实体；你也可以手动加一个）
        </div>
        <div
          v-for="(q, i) in queries"
          :key="'q-' + i"
          class="item"
          :class="{ off: !q._checked }"
        >
          <el-checkbox v-model="q._checked" />
          <div class="item-body">
            <div class="item-title">
              <el-tag v-if="q.node_type" size="small" effect="plain">{{ q.node_type }}</el-tag>
              <span class="ent-label">{{ q.entity }}</span>
            </div>
            <el-input
              v-model="q.reason"
              size="small"
              placeholder="查这个实体的目的"
              :maxlength="200"
              class="reason-input"
            />
          </div>
          <el-button size="small" text @click="removeQuery(i)">
            <el-icon><Close /></el-icon>
          </el-button>
        </div>
      </section>

      <footer class="action-row">
        <el-button @click="skipFullRead" :loading="loading">仅用摘要回答</el-button>
        <el-button type="primary" :loading="loading" @click="confirm(false)">
          继续（精读 {{ selectedPicks.length }} + 查 {{ selectedQueries.length }}）
        </el-button>
        <el-tooltip content="之后全部自动继续，不再弹出这个面板；退出协作后恢复默认">
          <el-button type="success" :loading="loading" @click="confirm(true)">
            自动模式继续
          </el-button>
        </el-tooltip>
      </footer>
    </div>

    <div v-else class="rich-msg__body locked">
      <span class="locked-hint">
        已按 {{ submittedSummary }} 提交给 AI
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { MagicStick, Reading, Share, Close } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useCollaborationStore } from '../../../stores/collaboration'

interface PickDraft {
  doc_id: string
  reason: string
  _checked: boolean
}
interface QueryDraft {
  entity: string
  entity_id?: string
  node_type?: string
  reason: string
  _checked: boolean
}

interface ProbeExcerpt {
  doc_id: string
  section_idx: number
  section_label: string
  char_start: number
  char_end: number
  relevance: number
  excerpt_quote: string
  insight?: string
  concepts?: string[]
}

const props = defineProps<{
  richData: {
    question: string
    picks: Array<{ doc_id: string; reason?: string }>
    kg_queries: Array<{ entity: string; entity_id?: string; node_type?: string; reason?: string }>
    candidates: Array<{ id: string; title: string; has_fulltext: boolean; one_line_summary?: string }>
    kg_candidates: Array<{ entity_id: string; label: string; node_type: string; degree: number }>
    probes?: ProbeExcerpt[]
  }
  isActive?: boolean
}>()

const emit = defineEmits<{
  /** 用户点"继续" / "仅摘要" / "自动模式" 的瞬间触发 —— ChatPanel 用它立即显示精读 typing bubble */
  'resume-start': []
}>()

const collabStore = useCollaborationStore()
const loading = ref(false)

const picks = ref<PickDraft[]>(
  (props.richData.picks || []).map((p) => ({
    doc_id: p.doc_id,
    reason: p.reason || '',
    _checked: true,
  })),
)
const queries = ref<QueryDraft[]>(
  (props.richData.kg_queries || []).map((q) => ({
    entity: q.entity,
    entity_id: q.entity_id,
    node_type: q.node_type,
    reason: q.reason || '',
    _checked: true,
  })),
)

// —— 探针 excerpts 勾选状态（key = doc_id:section_idx）——
const probes = computed<ProbeExcerpt[]>(() => props.richData.probes || [])
const hasAnyProbes = computed(() => probes.value.length > 0)

function excerptKey(ex: ProbeExcerpt): string {
  return `${ex.doc_id}:${ex.section_idx}`
}

const excerptChecked = ref<Record<string, boolean>>(
  Object.fromEntries(probes.value.map((ex) => [excerptKey(ex), true])),
)

function probesForDoc(docId: string): ProbeExcerpt[] {
  return probes.value
    .filter((ex) => ex.doc_id === docId)
    .sort((a, b) => (b.relevance || 0) - (a.relevance || 0))
}

function allProbesCheckedForDoc(docId: string): boolean {
  const list = probesForDoc(docId)
  return list.length > 0 && list.every((ex) => excerptChecked.value[excerptKey(ex)])
}

function toggleAllProbesForDoc(docId: string) {
  const list = probesForDoc(docId)
  const targetVal = !allProbesCheckedForDoc(docId)
  for (const ex of list) excerptChecked.value[excerptKey(ex)] = targetVal
}

const selectedPicks = computed(() => picks.value.filter((p) => p._checked))
const selectedQueries = computed(() => queries.value.filter((q) => q._checked))

const candidateMap = computed(() => {
  const m: Record<string, { title: string; has_fulltext: boolean }> = {}
  for (const c of props.richData.candidates || []) {
    m[c.id] = { title: c.title, has_fulltext: c.has_fulltext }
  }
  return m
})

const addablePicks = computed(() => {
  const taken = new Set(picks.value.map((p) => p.doc_id))
  return (props.richData.candidates || []).filter(
    (c) => c.has_fulltext && !taken.has(c.id),
  )
})

const addableEntities = computed(() => {
  const takenLower = new Set(queries.value.map((q) => q.entity.toLowerCase()))
  return (props.richData.kg_candidates || []).filter(
    (e) => !takenLower.has((e.label || '').toLowerCase()),
  )
})

const submittedSummary = computed(() => {
  const p = (props.richData.picks || []).length
  const q = (props.richData.kg_queries || []).length
  return `${p} 篇精读 + ${q} 个实体`
})

function titleForDoc(docId: string): string {
  return candidateMap.value[docId]?.title || docId
}

function truncate(t: string, n: number): string {
  if (!t) return ''
  return t.length > n ? t.slice(0, n) + '…' : t
}

function addPick(cand: { id: string; title: string }) {
  picks.value.push({ doc_id: cand.id, reason: '用户手动添加', _checked: true })
}
function removePick(i: number) {
  picks.value.splice(i, 1)
}

function addQuery(ent: { entity_id: string; label: string; node_type: string }) {
  queries.value.push({
    entity: ent.label,
    entity_id: ent.entity_id,
    node_type: ent.node_type,
    reason: '用户手动添加',
    _checked: true,
  })
}
function removeQuery(i: number) {
  queries.value.splice(i, 1)
}

async function confirm(autoFromNow: boolean) {
  loading.value = true
  try {
    const picksOut = selectedPicks.value.map((p) => ({
      doc_id: p.doc_id,
      reason: p.reason,
    }))
    const queriesOut = selectedQueries.value.map((q) => ({
      entity: q.entity,
      entity_id: q.entity_id,
      node_type: q.node_type,
      reason: q.reason,
    }))
    // 过滤出用户勾选的 excerpts，限制在仍被保留的 picks 下
    let selectedKeys: string[] | null = null
    if (hasAnyProbes.value) {
      const keepDocs = new Set(picksOut.map((p) => p.doc_id))
      selectedKeys = Object.entries(excerptChecked.value)
        .filter(([, v]) => v)
        .map(([k]) => k)
        .filter((k) => keepDocs.has(k.split(':')[0]))
    }
    emit('resume-start')
    await collabStore.resumePlan(picksOut, queriesOut, autoFromNow, selectedKeys)
    if (autoFromNow) {
      ElMessage.success('已切换为自动模式，退出协作后恢复')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '继续失败')
  } finally {
    loading.value = false
  }
}

async function skipFullRead() {
  loading.value = true
  try {
    emit('resume-start')
    // 显式不用任何全文/探针 → selectedExcerptKeys=[] 让后端退化到 only-摘要 路径
    await collabStore.resumePlan([], [], false, [])
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '继续失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.rich-msg {
  margin: 14px 0;
  border-radius: 12px;
  background: linear-gradient(135deg, #fef3c7 0%, #fae8ff 100%);
  border: 1px solid #fcd34d;
  overflow: hidden;
  transition: opacity 0.2s;
}
.rich-msg.is-locked {
  opacity: 0.65;
  pointer-events: none;
}
.rich-msg__header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  font-weight: 600;
  font-size: 13px;
  color: #92400e;
  border-bottom: 1px solid #fde68a;
  background: rgba(255, 255, 255, 0.4);
}
.rich-msg__body { padding: 14px; }
.rich-msg__body.locked {
  padding: 10px 14px;
  color: #78350f;
  font-size: 13px;
}
.locked-hint { font-style: italic; }
.intro {
  font-size: 13px;
  color: #78350f;
  margin: 0 0 12px;
  line-height: 1.5;
}
.intro em { color: #b45309; font-style: normal; }
.plan-section {
  background: rgba(255, 255, 255, 0.55);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
}
.sec-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  font-size: 13px;
  color: #0f172a;
}
.sec-head .count { color: #64748b; font-size: 12px; font-weight: 400; }
.sec-head .spacer { flex: 1; }
.empty-line {
  color: #78350f;
  font-size: 12.5px;
  font-style: italic;
  padding: 4px 0 6px;
}
.item {
  display: flex;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px dashed #fde68a;
}
.item:last-child { border-bottom: none; }
.item.off { opacity: 0.5; }
.item-body { flex: 1; min-width: 0; }
.item-title {
  font-size: 13px;
  line-height: 1.4;
  color: #0f172a;
  font-weight: 500;
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.ent-label { word-break: break-word; }
.reason-input { margin-top: 2px; }
.action-row {
  margin-top: 10px;
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  flex-wrap: wrap;
}
.popover-title {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 6px;
}
.popover-item {
  padding: 6px 8px;
  border-radius: 4px;
  cursor: pointer;
  border-bottom: 1px solid #f1f5f9;
}
.popover-item:hover { background: #fef3c7; }
.popover-item:last-child { border-bottom: 0; }
.pi-title {
  font-size: 13px;
  color: #0f172a;
  display: flex;
  align-items: center;
  gap: 4px;
}
.pi-summary {
  font-size: 12px;
  color: #64748b;
  margin-top: 2px;
  line-height: 1.3;
  overflow: hidden;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.degree { color: #94a3b8; font-size: 11px; margin-left: 4px; }
.empty {
  padding: 10px;
  text-align: center;
  color: #94a3b8;
  font-size: 12px;
}

/* —— 探针 excerpts —— */
.pick-item { flex-direction: column; align-items: stretch; gap: 6px; }
.pick-head { display: flex; gap: 8px; align-items: flex-start; }
.probes-block {
  margin: 4px 0 4px 24px;
  padding: 8px 10px;
  background: rgba(255, 247, 237, 0.85);
  border: 1px dashed #fbbf24;
  border-radius: 6px;
}
.probes-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.probes-title {
  font-size: 12px;
  font-weight: 600;
  color: #92400e;
}
.probe-item {
  display: flex;
  gap: 6px;
  padding: 6px 0;
  border-top: 1px solid rgba(251, 191, 36, 0.3);
}
.probe-item:first-of-type { border-top: none; }
.probe-item.off { opacity: 0.45; }
.probe-body { flex: 1; min-width: 0; }
.probe-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
  color: #78350f;
  margin-bottom: 3px;
  flex-wrap: wrap;
}
.probe-score { color: #b45309; font-weight: 500; }
.probe-range { color: #a16207; opacity: 0.75; }
.probe-insight {
  font-size: 12.5px;
  color: #0f172a;
  line-height: 1.45;
  margin-bottom: 3px;
}
.probe-quote {
  margin: 2px 0 0;
  padding: 4px 8px;
  border-left: 3px solid #f59e0b;
  background: rgba(255, 255, 255, 0.65);
  font-size: 12px;
  color: #1f2937;
  line-height: 1.55;
  font-style: normal;
  white-space: pre-wrap;
  word-break: break-word;
}
.probes-empty {
  margin: 4px 0 4px 24px;
  padding: 6px 10px;
  font-size: 11.5px;
  color: #94a3b8;
  font-style: italic;
}
</style>
