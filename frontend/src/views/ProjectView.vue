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
            <span class="project-domain">{{ project.domain }}</span>
          </div>
        </div>
        <el-tag :type="statusType(project.status)" size="large">{{ statusLabel(project.status) }}</el-tag>
      </div>

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
              <el-alert
                v-if="currentRound?.status === 'awaiting_feedback'"
                type="info"
                :closable="false"
                show-icon
                style="margin-bottom:16px"
              >
                <template #title>
                  请对以下文献评分（至少完成3篇），AI 将根据您的反馈优化下一轮检索方向
                </template>
              </el-alert>

              <!-- Feedback progress -->
              <div v-if="currentRound?.status === 'awaiting_feedback'" class="feedback-progress">
                <span>已评分 {{ searchStore.ratedCount }} / {{ searchStore.documents.length }} 篇</span>
                <el-button
                  type="primary"
                  :disabled="searchStore.ratedCount < 3"
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
                  @feedback="(val) => searchStore.setFeedback(String(doc.id), val)"
                />
              </div>

              <!-- Completed round message -->
              <div v-if="currentRound?.status === 'complete' && project.current_round < 5" class="next-round-panel">
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
import { onMounted, computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '../stores/project'
import { useSearchStore } from '../stores/search'
import RoundTimeline from '../components/RoundTimeline.vue'
import DocumentCard from '../components/DocumentCard.vue'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const searchStore = useSearchStore()
const submitting = ref(false)

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
  if (round >= 5) return '完成全部检索'
  return `提交反馈，开始第 ${round + 1} 轮检索`
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

.next-round-panel { margin-top: 24px; }
</style>
