<template>
  <div class="project-view">
    <template v-if="projectStore.loading">
      <el-skeleton :rows="5" animated style="padding:24px" />
    </template>

    <template v-else-if="project">
      <!-- Top bar -->
      <div class="project-topbar">
        <div class="topbar-left">
          <el-button text @click="router.push('/dashboard')"><el-icon><ArrowLeft /></el-icon></el-button>
          <div>
            <h2 class="project-title">{{ project.title }}</h2>
            <span class="project-domain">{{ (project.domains || [project.domain]).join(' · ') }}</span>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:10px">
          <el-button size="small" :type="devViewOpen ? 'primary' : ''" :plain="!devViewOpen" @click="devViewOpen = !devViewOpen">
            <el-icon><DataAnalysis /></el-icon> Dev View
          </el-button>
          <el-button size="small" @click="openSettings"><el-icon><Setting /></el-icon> 搜索设置</el-button>
          <el-tag :type="statusType(project.status)" size="large">{{ statusLabel(project.status) }}</el-tag>
        </div>
      </div>

      <!-- Settings dialog -->
      <el-dialog v-model="settingsVisible" title="数据源设置" width="480px" :close-on-click-modal="false">
        <p style="font-size:13px;color:#909399;margin:0 0 12px">默认全部开启；关闭的数据源在下一轮检索中生效</p>
        <div class="settings-source-grid">
          <div v-for="src in ALL_SOURCES" :key="src.id" class="settings-source-item">
            <el-switch :model-value="!settingsForm.disabledSources.includes(src.id)" @update:model-value="toggleSettingsSource(src.id, $event)" size="small" />
            <div>
              <span class="settings-source-label">{{ src.label }}</span>
              <span class="settings-source-desc">{{ src.desc }}</span>
            </div>
          </div>
        </div>
        <template #footer>
          <el-button @click="settingsVisible = false">取消</el-button>
          <el-button type="primary" :loading="savingSettings" @click="saveSettings">保存</el-button>
        </template>
      </el-dialog>

      <div class="project-body">
        <!-- Left: round timeline -->
        <aside class="sidebar">
          <RoundTimeline :project="project" :rounds="searchStore.rounds" />
        </aside>

        <!-- Main content -->
        <main class="main-content">
          <!-- No round started yet -->
          <div v-if="searchStore.rounds.length === 0" class="start-panel">
            <el-empty description="准备好开始检索了吗？">
              <template #image>
                <div style="font-size:64px">🔬</div>
              </template>
              <el-button type="primary" size="large" :loading="searchStore.isStarting" @click="startRound">
                开始第1轮检索（近5年）
              </el-button>
            </el-empty>
          </div>

          <!-- Active round display -->
          <template v-else>
            <div class="round-header">
              <div>
                <h3>第 {{ currentRound?.round_number }} 轮检索</h3>
                <p class="round-desc">{{ roundDesc(currentRound) }}</p>
              </div>
              <el-tag :type="roundStatusType(currentRound?.status)" effect="plain" size="large">
                {{ roundStatusLabel(currentRound?.status) }}
              </el-tag>
            </div>

            <!-- Searching/summarizing state -->
            <div v-if="isProcessing" class="processing-state">
              <el-progress type="circle" :percentage="Math.round((currentRound?.progress ?? 0) * 100)" />
              <div class="processing-text">
                <p>{{ processingMessage }}</p>
                <p class="processing-hint">通常需要 1-3 分钟，请稍候…</p>
              </div>
            </div>

            <!-- Results + feedback -->
            <template v-else-if="currentRound?.status === 'awaiting_feedback' || currentRound?.status === 'complete'">
              <!-- Source stats summary -->
              <div v-if="searchStore.sourceStats && Object.keys(searchStore.sourceStats).length > 0" class="source-stats">
                <span class="source-stats-label">数据源：</span>
                <el-tooltip
                  v-for="(stat, sourceId) in searchStore.sourceStats"
                  :key="sourceId"
                  :content="getSourceTooltip(sourceId, stat)"
                  placement="top"
                >
                  <el-tag
                    :type="stat.status === 'ok' && stat.count > 0 ? 'success' : stat.status === 'error' ? 'danger' : 'info'"
                    size="small"
                    effect="plain"
                    style="margin-right: 6px; margin-bottom: 4px; cursor: default"
                  >
                    {{ sourceId }}: {{ stat.count ?? 0 }}篇
                    <span v-if="stat.status === 'error'" style="color: #f56c6c"> !</span>
                  </el-tag>
                </el-tooltip>
              </div>

              <!-- Dev View Panel -->
              <transition name="el-zoom-in-top">
                <div v-if="devViewOpen" class="dev-view-panel">
                  <div class="dev-view-header">
                    <el-icon style="font-size:15px"><DataAnalysis /></el-icon>
                    <span>检索详情 Dev View</span>
                    <el-tag size="small" type="info" effect="dark" style="margin-left:8px">Round {{ currentRound?.round_number }}</el-tag>
                  </div>

                  <!-- Query Plan -->
                  <div v-if="currentRound?.search_queries" class="dev-section">
                    <div class="dev-section-title">查询计划</div>
                    <div class="dev-plan-grid">
                      <div class="dev-plan-row">
                        <span class="dev-label">翻译查询词</span>
                        <span class="dev-value dev-highlight">{{ currentRound.search_queries.base_query }}</span>
                      </div>
                      <div v-if="currentRound.search_queries.original_chinese_query" class="dev-plan-row">
                        <span class="dev-label">原始中文词</span>
                        <span class="dev-value">{{ currentRound.search_queries.original_chinese_query }}</span>
                      </div>
                      <div class="dev-plan-row">
                        <span class="dev-label">扩展词汇</span>
                        <span class="dev-value">
                          <el-tag v-for="t in (currentRound.search_queries.expanded_terms || [])" :key="t" size="small" effect="plain" style="margin-right:4px;margin-bottom:2px">{{ t }}</el-tag>
                        </span>
                      </div>
                      <div v-if="currentRound.search_queries.exclude_terms?.length" class="dev-plan-row">
                        <span class="dev-label">排除词</span>
                        <span class="dev-value">
                          <el-tag v-for="t in currentRound.search_queries.exclude_terms" :key="t" size="small" type="danger" effect="plain" style="margin-right:4px">{{ t }}</el-tag>
                        </span>
                      </div>
                      <div class="dev-plan-row">
                        <span class="dev-label">时间范围</span>
                        <span class="dev-value">{{ currentRound.search_queries.year_from ?? '不限' }} — {{ currentRound.search_queries.year_to ?? '不限' }}</span>
                      </div>
                      <div class="dev-plan-row">
                        <span class="dev-label">语言策略</span>
                        <span class="dev-value">{{ currentRound.search_queries.language_scope }}</span>
                      </div>
                      <div class="dev-plan-row">
                        <span class="dev-label">每源上限</span>
                        <span class="dev-value">{{ currentRound.search_queries.max_per_source }} 篇</span>
                      </div>
                    </div>
                  </div>

                  <!-- Per-source breakdown -->
                  <div v-if="Object.keys(searchStore.sourceStats).length > 0" class="dev-section">
                    <div class="dev-section-title">各数据源响应</div>
                    <div class="dev-source-cards">
                      <div
                        v-for="(stat, sourceId) in searchStore.sourceStats"
                        :key="sourceId"
                        class="dev-source-card"
                        :class="stat.status === 'ok' ? 'dev-card-ok' : 'dev-card-error'"
                      >
                        <div class="dev-card-header">
                          <span class="dev-card-name">{{ sourceId }}</span>
                          <div style="display:flex;gap:4px">
                            <el-tag :type="stat.status === 'ok' ? 'success' : 'danger'" size="small" effect="plain">
                              {{ stat.status === 'ok' ? stat.count + ' 篇' : '失败' }}
                            </el-tag>
                            <el-tag v-if="stat.execution_ms != null" type="info" size="small" effect="plain">{{ stat.execution_ms }}ms</el-tag>
                          </div>
                        </div>
                        <div v-if="stat.query_sent" class="dev-card-query">
                          <span class="dev-label">查询词</span>
                          <code class="dev-code">{{ stat.query_sent }}</code>
                        </div>
                        <div v-if="stat.year_from || stat.year_to" class="dev-card-meta">
                          年份 {{ stat.year_from ?? '不限' }}–{{ stat.year_to ?? '不限' }} · 上限 {{ stat.max_requested }} 篇
                        </div>
                        <div v-if="stat.error" class="dev-card-errmsg">{{ stat.error }}</div>
                      </div>
                    </div>
                  </div>

                  <!-- Summary -->
                  <div class="dev-summary">
                    候选总数：<strong>{{ currentRound?.total_candidates ?? 0 }}</strong> 篇
                    &nbsp;→&nbsp;
                    最终筛选：<strong>{{ currentRound?.selected_count ?? searchStore.documents.length }}</strong> 篇
                  </div>
                </div>
              </transition>

              <el-alert
                v-if="currentRound?.status === 'awaiting_feedback'"
                type="info"
                :closable="false"
                show-icon
                style="margin-bottom:16px"
              >
                <template #title>
                  请对以下文献评分（{{ minRatingHint }}），AI 将根据您的反馈优化下一轮检索方向
                </template>
              </el-alert>

              <!-- Feedback progress -->
              <div v-if="currentRound?.status === 'awaiting_feedback'" class="feedback-progress">
                <span>已评分 {{ searchStore.ratedCount }} / {{ searchStore.documents.length }} 篇</span>
                <el-button
                  type="primary"
                  :disabled="searchStore.ratedCount < minRequired"
                  :loading="submitting"
                  @click="submitFeedback"
                >
                  {{ nextRoundLabel }}
                </el-button>
              </div>

              <!-- Document cards -->
              <div class="doc-list">
                <DocumentCard
                  v-for="doc in searchStore.documents"
                  :key="String(doc.id)"
                  :doc="doc"
                  :initial-feedback="searchStore.feedbackDrafts[String(doc.id)] ?? doc.user_feedback"
                  :round-status="searchStore.currentRound?.status"
                  @feedback="(val) => searchStore.setFeedback(String(doc.id), val)"
                />
              </div>

              <!-- Completed round message -->
              <div v-if="currentRound?.status === 'complete' && project.current_round < (project.max_rounds || 5)" class="next-round-panel">
                <el-result icon="success" title="本轮检索完成">
                  <template #sub-title>
                    已完成第 {{ currentRound.round_number }} 轮，下一轮将扩大时间范围继续检索
                  </template>
                  <template #extra>
                    <el-button type="primary" :loading="searchStore.isStarting" @click="startRound">
                      开始第 {{ project.current_round + 1 }} 轮检索
                    </el-button>
                  </template>
                </el-result>
              </div>
            </template>

          </template>
        </main>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, computed, ref, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '../stores/project'
import { useSearchStore } from '../stores/search'
import { projectApi } from '../api/client'
import RoundTimeline from '../components/RoundTimeline.vue'
import DocumentCard from '../components/DocumentCard.vue'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const searchStore = useSearchStore()
const submitting = ref(false)
const devViewOpen = ref(false)
const ALL_SOURCES = [
  { id: 'openalex',         label: 'OpenAlex',            desc: '国际综合文献库' },
  { id: 'europe_pmc',       label: 'Europe PMC',          desc: '生物医学全文' },
  { id: 'crossref',         label: 'Crossref',            desc: '期刊引用数据' },
  { id: 'semantic_scholar', label: 'Semantic Scholar',    desc: 'AI语义检索' },
  { id: 'dblp',             label: 'DBLP',                desc: 'CS顶级会议/期刊（免费）' },
  { id: 'openalex_zh',      label: 'OpenAlex 中文',        desc: '中文论文（chinese_first 自动启用）' },
  { id: 'arxiv',            label: 'arXiv',               desc: '物理/CS/数学预印本' },
  { id: 'biorxiv',          label: 'bioRxiv',             desc: '生物预印本' },
  { id: 'medrxiv',          label: 'medRxiv',             desc: '医学预印本' },
  { id: 'lens_patent',      label: 'Lens.org 专利',       desc: '全球专利 CN/US/EP/WO（需 LENS_API_TOKEN）' },
  { id: 'epo_ops',          label: 'EPO OPS 专利',        desc: '欧洲专利局 EP/WO（需 EPO_CONSUMER_KEY）' },
  { id: 'soopat',           label: 'SooPat 中国专利',     desc: 'CN发明/实用新型（需 SOOPAT_COOKIES）' },
  { id: 'clinical_trials',  label: 'ClinicalTrials.gov',  desc: '临床试验注册' },
]

const settingsVisible = ref(false)
const savingSettings = ref(false)
const settingsForm = reactive({ disabledSources: [] as string[] })

const SOURCE_HINTS: Record<string, string> = {
  pubmed: '国内访问受限（TLS超时），用 Europe PMC 替代',
  lens_patent: '需在 .env 配置 LENS_API_TOKEN（lens.org 免费申请）',
  epo_ops: '需在 .env 配置 EPO_CONSUMER_KEY + EPO_CONSUMER_SECRET（ops.epo.org 免费申请）',
  soopat: '需在 .env 配置 SOOPAT_EMAIL + SOOPAT_PASSWORD（自动登录）或 SOOPAT_COOKIES（手动）',
  semantic_scholar: '频率限制（429），已降低优先级',
  arxiv: '国内访问受限',
  openalex_zh: '中文论文专用（chinese_first + 中文描述时自动启用，使用 OpenAlex language:zh 过滤）',
  dblp: 'CS顶会/期刊（CVPR/NeurIPS/ACL等），无需鉴权',
}

function getSourceTooltip(sourceId: string, stat: { status: string; count: number; error?: string }): string {
  if (stat.status === 'error') {
    return `错误：${stat.error || '未知错误'}`
  }
  if (stat.count === 0 && SOURCE_HINTS[sourceId]) {
    return SOURCE_HINTS[sourceId]
  }
  if (stat.count > 0) {
    return `成功返回 ${stat.count} 篇`
  }
  return '本次查询无匹配结果'
}

function toggleSettingsSource(id: string, enabled: boolean) {
  if (enabled) {
    const idx = settingsForm.disabledSources.indexOf(id)
    if (idx !== -1) settingsForm.disabledSources.splice(idx, 1)
  } else {
    if (!settingsForm.disabledSources.includes(id)) settingsForm.disabledSources.push(id)
  }
}

function openSettings() {
  const cfg = project.value?.search_config ?? {}
  settingsForm.disabledSources = [...(cfg.disabled_sources ?? [])]
  settingsVisible.value = true
}

async function saveSettings() {
  savingSettings.value = true
  try {
    const id = route.params.id as string
    const cfg = { ...(project.value?.search_config ?? {}), disabled_sources: [...settingsForm.disabledSources] }
    await projectApi.update(id, { search_config: cfg })
    await projectStore.fetchProject(id)
    settingsVisible.value = false
    ElMessage.success('设置已保存，下一轮检索生效')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    savingSettings.value = false
  }
}

const project = computed(() => projectStore.current)
const currentRound = computed(() => searchStore.currentRound)

const isProcessing = computed(() =>
  ['searching', 'summarizing'].includes(currentRound.value?.status ?? '')
)

const processingMessage = computed(() => {
  if (currentRound.value?.status === 'searching') return '正在从多个数据库检索文献...'
  return '正在生成 AI 摘要，请稍候...'
})

const nextRoundLabel = computed(() => {
  const round = project.value?.current_round ?? 0
  const maxRounds = project.value?.max_rounds || 5
  if (round >= maxRounds) return '完成全部检索'
  return `提交反馈，开始第 ${round + 1} 轮检索`
})

const minRequired = computed(() => {
  const total = searchStore.documents.length
  return total <= 3 ? total : 3
})

const minRatingHint = computed(() => {
  const total = searchStore.documents.length
  return total <= 3 ? `共${total}篇，请全部评分` : '至少完成3篇'
})

const ROUND_DESCS: Record<number, string> = {
  1: '近5年 · 中文优先 · Top 10',
  2: '近10年 · 中文优先 · Top 10',
  3: '近20年 · 中英双语 · Top 20',
  4: '全时间 · 中英双语 · 全部相关',
  5: '全时间 · 全球多语言 · AI中文摘要',
}

function roundDesc(round: any) {
  return ROUND_DESCS[round?.round_number ?? 0] ?? ''
}

function roundStatusLabel(s: string) {
  return ({
    pending: '待开始', searching: '检索中', summarizing: 'AI摘要生成中',
    awaiting_feedback: '等待您评分', complete: '已完成',
  } as any)[s] ?? s
}

function roundStatusType(s: string) {
  return ({
    searching: 'warning', summarizing: 'warning', awaiting_feedback: 'primary',
    complete: 'success', pending: 'info',
  } as any)[s] ?? ''
}

function statusLabel(s: string) {
  return ({ active: '进行中', monitoring: '监控中', archived: '已归档' } as any)[s] ?? s
}

function statusType(s: string) {
  return ({ active: 'primary', monitoring: 'success', archived: 'info' } as any)[s] ?? ''
}

async function startRound() {
  try {
    await searchStore.startRound(route.params.id as string)
    await projectStore.fetchProject(route.params.id as string)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '启动检索失败')
  }
}

async function submitFeedback() {
  submitting.value = true
  try {
    await searchStore.submitFeedback(route.params.id as string)
    await projectStore.fetchProject(route.params.id as string)
    ElMessage.success('反馈已提交')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  const id = route.params.id as string
  await projectStore.fetchProject(id)
  await searchStore.fetchRounds(id)
  // Load current round results if applicable
  if (searchStore.currentRound && searchStore.currentRound.round_number) {
    await searchStore.loadRoundResults(searchStore.currentRound.id)
  }
})
</script>

<style scoped>
.project-view { min-height: calc(100vh - 60px); background: #f5f7fa; }

.project-topbar {
  display: flex; justify-content: space-between; align-items: center;
  padding: 16px 24px; background: #fff; border-bottom: 1px solid #e4e7ed;
}
.topbar-left { display: flex; align-items: center; gap: 12px; }
.project-title { margin: 0; font-size: 18px; font-weight: 700; }
.project-domain { font-size: 12px; color: #909399; }

.project-body { display: flex; }

.sidebar {
  width: 220px; min-height: calc(100vh - 120px); background: #fff;
  border-right: 1px solid #e4e7ed; flex-shrink: 0; padding-top: 8px;
  position: sticky; top: 60px; align-self: flex-start;
}

.main-content { flex: 1; padding: 24px; max-width: 860px; }

.start-panel { display: flex; justify-content: center; padding: 80px 0; }

.round-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 20px;
}
.round-header h3 { margin: 0; font-size: 18px; }
.round-desc { color: #909399; font-size: 13px; margin: 4px 0 0; }

.processing-state {
  display: flex; gap: 32px; align-items: center;
  background: #fff; border-radius: 8px; padding: 40px;
  justify-content: center;
}
.processing-text p { margin: 0; font-size: 15px; font-weight: 500; }
.processing-hint { color: #909399; font-size: 13px; margin-top: 6px !important; }

.feedback-progress {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 16px; padding: 12px 16px;
  background: #fff; border-radius: 6px; border: 1px solid #e4e7ed;
  font-size: 14px; color: #606266;
}

.doc-list { display: flex; flex-direction: column; gap: 16px; }

.source-stats {
  display: flex; flex-wrap: wrap; align-items: center;
  margin-bottom: 12px; padding: 8px 12px;
  background: #fff; border-radius: 6px; border: 1px solid #e4e7ed;
}
.source-stats-label {
  font-size: 13px; color: #909399; margin-right: 8px; white-space: nowrap;
}

.next-round-panel { margin-top: 24px; }

.settings-source-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.settings-source-item { display: flex; align-items: center; gap: 8px; }
.settings-source-label { font-size: 13px; font-weight: 500; display: block; }
.settings-source-desc { font-size: 11px; color: #909399; display: block; }

/* Dev View */
.dev-view-panel {
  background: #1a1d23;
  border-radius: 8px;
  padding: 16px 20px;
  margin-bottom: 16px;
  border: 1px solid #2d3139;
  color: #c9d1d9;
  font-size: 13px;
}
.dev-view-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: #58a6ff;
  margin-bottom: 16px;
  padding-bottom: 10px;
  border-bottom: 1px solid #2d3139;
}
.dev-section { margin-bottom: 16px; }
.dev-section-title {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #8b949e;
  margin-bottom: 10px;
}
.dev-plan-grid { display: flex; flex-direction: column; gap: 6px; }
.dev-plan-row { display: flex; align-items: flex-start; gap: 12px; }
.dev-label {
  font-size: 11px;
  color: #8b949e;
  min-width: 72px;
  padding-top: 2px;
  flex-shrink: 0;
}
.dev-value { color: #e6edf3; flex: 1; }
.dev-highlight { color: #79c0ff; font-weight: 500; font-family: monospace; }

.dev-source-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
}
.dev-source-card {
  background: #0d1117;
  border-radius: 6px;
  padding: 10px 12px;
  border: 1px solid #2d3139;
}
.dev-card-ok { border-left: 3px solid #238636; }
.dev-card-error { border-left: 3px solid #da3633; }
.dev-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.dev-card-name { font-weight: 600; color: #c9d1d9; font-size: 13px; }
.dev-card-query {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 4px;
}
.dev-code {
  background: #161b22;
  border-radius: 4px;
  padding: 2px 6px;
  font-family: monospace;
  font-size: 12px;
  color: #a5d6ff;
  word-break: break-all;
  flex: 1;
}
.dev-card-meta { font-size: 11px; color: #8b949e; margin-top: 4px; }
.dev-card-errmsg {
  font-size: 11px;
  color: #f85149;
  margin-top: 6px;
  background: #1c0a0a;
  padding: 4px 6px;
  border-radius: 4px;
  word-break: break-all;
}
.dev-summary {
  padding-top: 12px;
  border-top: 1px solid #2d3139;
  font-size: 13px;
  color: #8b949e;
  text-align: right;
}
.dev-summary strong { color: #c9d1d9; }
</style>
