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

            <!-- Searching/summarizing state — real-time SSE powered -->
            <div v-if="isProcessing" class="processing-state-v2">
              <div class="processing-header">
                <el-progress
                  :percentage="Math.round((currentRound?.progress ?? 0) * 100)"
                  :stroke-width="8"
                  :text-inside="true"
                  style="flex:1"
                />
                <span class="processing-status">{{ currentRound?.progress_message || processingMessage }}</span>
              </div>

              <!-- Agent plan (appears when agent planning is active) -->
              <AgentPlanView ref="agentPlanRef" />

              <!-- Per-source progress (appears when sources start responding) -->
              <SourceProgressBar ref="sourceProgressRef" />

              <!-- Streaming document arrivals -->
              <div v-if="searchStore.streamingDocs.length > 0" class="streaming-docs">
                <div class="streaming-header">
                  <span>已到达 {{ searchStore.streamingDocs.length }} 篇文献</span>
                  <span class="streaming-hint">摘要生成中...</span>
                </div>
                <TransitionGroup name="doc-list" tag="div" class="streaming-list">
                  <div
                    v-for="doc in searchStore.streamingDocs.slice(-8)"
                    :key="doc.external_id + doc.source"
                    class="streaming-doc-item"
                  >
                    <span class="streaming-dot" :class="doc.has_abstract ? 'dot-has' : 'dot-no'"></span>
                    <el-tag size="small" effect="plain" style="flex-shrink:0">{{ doc.source }}</el-tag>
                    <span class="streaming-doc-title">{{ doc.title }}</span>
                  </div>
                </TransitionGroup>
              </div>

              <!-- Skeleton placeholders when waiting for first docs -->
              <div v-else-if="currentRound?.status === 'searching'" class="skeleton-placeholders">
                <DocumentSkeleton />
                <DocumentSkeleton />
              </div>

              <p class="processing-hint">实时推送中，无需刷新页面</p>
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

              <!-- Dev View: Pipeline -->
              <transition name="el-zoom-in-top">
                <div v-if="devViewOpen" class="dev-pipeline">
                  <div class="dev-pipeline-header">
                    <el-icon><DataAnalysis /></el-icon>
                    <span>检索 Pipeline</span>
                    <el-tag size="small" type="info" effect="dark" style="margin-left:8px">Round {{ currentRound?.round_number }}</el-tag>
                  </div>

                  <!-- STEP 1: 用户输入 -->
                  <div class="dev-step">
                    <div class="dev-step-num">1</div>
                    <div class="dev-step-body">
                      <div class="dev-step-title">用户输入</div>
                      <div class="dev-kv-list">
                        <div class="dev-kv">
                          <span class="dev-k">项目描述</span>
                          <span class="dev-v">{{ (project?.description || '').slice(0, 100) }}{{ (project?.description?.length ?? 0) > 100 ? '…' : '' }}</span>
                        </div>
                        <div class="dev-kv">
                          <span class="dev-k">研究领域</span>
                          <span class="dev-v">{{ (project?.domains || [project?.domain]).join(' · ') }}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div class="dev-connector"><span>↓</span></div>

                  <!-- STEP 2: LLM 翻译 & 查询构建 -->
                  <div class="dev-step">
                    <div class="dev-step-num">2</div>
                    <div class="dev-step-body">
                      <div class="dev-step-title">LLM 翻译 & 查询构建</div>
                      <template v-if="currentRound?.search_queries">
                        <div class="dev-kv-list">
                          <div v-if="currentRound.search_queries.original_chinese_query" class="dev-kv">
                            <span class="dev-k">中文核心词</span>
                            <code class="dev-code">{{ currentRound.search_queries.original_chinese_query }}</code>
                            <el-tag
                              size="small"
                              :type="currentRound.search_queries.cn_query_source === 'llm' ? 'success' : 'info'"
                              effect="plain"
                              class="dev-source-tag"
                            >{{ currentRound.search_queries.cn_query_source === 'llm' ? 'LLM' : currentRound.search_queries.cn_query_source === 'none' ? '未触发' : '正则' }}</el-tag>
                          </div>
                          <div class="dev-kv">
                            <span class="dev-k">英文查询词</span>
                            <code class="dev-code dev-code-primary">{{ currentRound.search_queries.base_query }}</code>
                            <el-tag
                              size="small"
                              :type="currentRound.search_queries.english_query_source === 'llm' ? 'success' : currentRound.search_queries.english_query_source === 'llm+regex' ? 'warning' : 'info'"
                              effect="plain"
                              class="dev-source-tag"
                            >{{ currentRound.search_queries.english_query_source === 'llm' ? 'LLM' : currentRound.search_queries.english_query_source === 'llm+regex' ? 'LLM+正则' : currentRound.search_queries.english_query_source === 'regex' ? '正则' : '旧数据' }}</el-tag>
                          </div>
                          <div v-if="currentRound.search_queries.anchor_keywords?.length" class="dev-kv">
                            <span class="dev-k" style="color:#6e7681">描述锚词</span>
                            <span class="dev-v dev-tags">
                              <el-tag v-for="t in currentRound.search_queries.anchor_keywords" :key="'anchor-'+t" size="small" effect="plain" style="opacity:0.6" class="dev-tag">{{ t }}</el-tag>
                            </span>
                          </div>
                          <div class="dev-kv">
                            <span class="dev-k">扩展词汇</span>
                            <span class="dev-v dev-tags">
                              <el-tag v-for="t in (currentRound.search_queries.expanded_terms || [])" :key="t" size="small" effect="plain" class="dev-tag">{{ t }}</el-tag>
                            </span>
                          </div>
                          <div v-if="currentRound.search_queries.exclude_terms?.length" class="dev-kv">
                            <span class="dev-k">排除词</span>
                            <span class="dev-v dev-tags">
                              <el-tag v-for="t in currentRound.search_queries.exclude_terms" :key="t" size="small" type="danger" effect="plain" class="dev-tag">{{ t }}</el-tag>
                            </span>
                          </div>
                          <div class="dev-kv">
                            <span class="dev-k">时间范围</span>
                            <span class="dev-v">{{ currentRound.search_queries.year_from ?? '不限' }} — {{ currentRound.search_queries.year_to ?? '今' }}</span>
                          </div>
                          <div class="dev-kv">
                            <span class="dev-k">语言策略</span>
                            <span class="dev-v">{{ langScopeLabel(currentRound.search_queries.language_scope) }}</span>
                          </div>
                          <div class="dev-kv">
                            <span class="dev-k">每源上限</span>
                            <span class="dev-v">{{ currentRound.search_queries.max_per_source }} 篇</span>
                          </div>
                          <!-- 新字段：中英文分行展示 -->
                          <template v-if="currentRound.search_queries.profile_injected_en?.length || currentRound.search_queries.profile_injected_zh?.length">
                            <div class="dev-kv">
                              <span class="dev-k">画像注入</span>
                              <span class="dev-v" style="display:flex;flex-direction:column;gap:5px">
                                <span v-if="currentRound.search_queries.profile_injected_en?.length" class="dev-tags">
                                  <el-tag size="small" type="info" effect="plain" style="font-size:10px;flex-shrink:0">排序扩展</el-tag>
                                  <el-tag v-for="t in currentRound.search_queries.profile_injected_en" :key="'en-'+t" size="small" type="warning" effect="plain" class="dev-tag">{{ t }}</el-tag>
                                </span>
                                <span v-if="currentRound.search_queries.profile_injected_zh?.length" class="dev-tags">
                                  <el-tag size="small" type="info" effect="plain" style="font-size:10px;flex-shrink:0">中文追加</el-tag>
                                  <el-tag v-for="t in currentRound.search_queries.profile_injected_zh" :key="'zh-'+t" size="small" type="success" effect="plain" class="dev-tag">{{ t }}</el-tag>
                                </span>
                                <span v-if="currentRound.search_queries.profile_query_extension" class="dev-tags">
                                  <el-tag size="small" type="warning" effect="dark" style="font-size:10px;flex-shrink:0">API召回扩展</el-tag>
                                  <code class="dev-code" style="font-size:11px">{{ currentRound.search_queries.profile_query_extension }}</code>
                                  <el-tag
                                    size="small"
                                    :type="currentRound.search_queries.profile_query_extension?.split(' ').every(w => currentRound.search_queries.anchor_keywords?.includes(w)) ? 'success' : 'info'"
                                    effect="plain"
                                    style="font-size:10px;flex-shrink:0"
                                  >{{ currentRound.search_queries.profile_query_extension?.split(' ').every(w => currentRound.search_queries.anchor_keywords?.includes(w)) ? '描述已确认' : '画像降级' }}</el-tag>
                                </span>
                              </span>
                            </div>
                          </template>
                          <!-- 旧数据降级显示 -->
                          <template v-else-if="currentRound.search_queries.profile_keywords?.length">
                            <div class="dev-kv">
                              <span class="dev-k">画像注入词</span>
                              <span class="dev-v dev-tags">
                                <el-tag v-for="t in currentRound.search_queries.profile_keywords" :key="t" size="small" type="warning" effect="plain" class="dev-tag">{{ t }}</el-tag>
                              </span>
                            </div>
                          </template>
                          <div v-if="currentRound.search_queries.profile_excluded?.length" class="dev-kv">
                            <span class="dev-k">画像排除词</span>
                            <span class="dev-v dev-tags">
                              <el-tag v-for="t in currentRound.search_queries.profile_excluded" :key="t" size="small" type="danger" effect="plain" class="dev-tag">{{ t }}</el-tag>
                            </span>
                          </div>
                        </div>
                      </template>
                      <div v-else class="dev-no-data">本轮数据未记录，请重启 worker 后新开一轮</div>
                    </div>
                  </div>
                  <div class="dev-connector"><span>↓ 并行发送</span></div>

                  <!-- STEP 3: 各数据源 -->
                  <div class="dev-step">
                    <div class="dev-step-num">3</div>
                    <div class="dev-step-body">
                      <div class="dev-step-title">
                        并行检索
                        <span class="dev-step-sub">{{ Object.keys(searchStore.sourceStats).length }} 个数据源</span>
                      </div>
                      <div v-if="Object.keys(searchStore.sourceStats).length > 0" class="dev-src-table">
                        <div class="dev-src-thead">
                          <span class="c-exp"></span>
                          <span class="c-src">数据源</span>
                          <span class="c-query">实际发出的查询词</span>
                          <span class="c-count">API返回</span>
                          <span class="c-time">耗时</span>
                        </div>
                        <div
                          v-for="(stat, srcId) in sortedSourceStats"
                          :key="srcId"
                          class="dev-src-block"
                          :class="{ 'row-ok': stat.status === 'ok' && stat.count > 0, 'row-zero': stat.status === 'ok' && stat.count === 0, 'row-err': stat.status === 'error' }"
                        >
                          <!-- 主行：可点击展开 -->
                          <div
                            class="dev-src-row"
                            :style="docsBySource[srcId]?.length ? 'cursor:pointer' : ''"
                            @click="docsBySource[srcId]?.length ? toggleSource(String(srcId)) : null"
                          >
                            <span class="c-exp">
                              <el-icon v-if="docsBySource[srcId]?.length" class="expand-icon" :class="{ 'icon-open': expandedSources.has(String(srcId)) }"><ArrowRight /></el-icon>
                            </span>
                            <span class="c-src">
                              <span class="src-dot" :class="stat.status === 'ok' && stat.count > 0 ? 'dot-ok' : stat.status === 'error' ? 'dot-err' : 'dot-zero'"></span>
                              {{ srcId }}
                            </span>
                            <span class="c-query">
                              <code v-if="stat.query_sent && stat.status !== 'error'" class="dev-code-sm">{{ stat.query_sent }}</code>
                              <span v-if="stat.error" class="dev-err-txt">{{ stat.error.slice(0, 80) }}</span>
                            </span>
                            <span class="c-count" :class="stat.count > 0 ? 'cnt-ok' : 'cnt-zero'">{{ stat.count ?? 0 }} 篇</span>
                            <span class="c-time">{{ stat.execution_ms != null ? stat.execution_ms + 'ms' : '—' }}</span>
                          </div>
                          <!-- 展开区：该源的筛选文献 -->
                          <div v-if="expandedSources.has(String(srcId)) && docsBySource[srcId]?.length" class="dev-src-docs">
                            <div v-for="doc in docsBySource[srcId]" :key="doc.id" class="dev-src-doc-row">
                              <span class="doc-rank">#{{ doc.rank_in_round ?? '—' }}</span>
                              <span class="doc-score">{{ doc.initial_score?.toFixed(3) ?? '—' }}</span>
                              <span class="doc-title-sm">{{ doc.title }}</span>
                              <span class="doc-date-sm">{{ doc.publication_date?.slice(0, 7) ?? '' }}</span>
                            </div>
                            <div v-if="docsBySource[srcId].length < (stat.count ?? 0)" class="dev-src-note">
                              仅显示进入最终结果的 {{ docsBySource[srcId].length }} 篇（API原始返回 {{ stat.count }} 篇）
                            </div>
                          </div>
                        </div>
                      </div>
                      <div v-else class="dev-no-data">暂无数据</div>
                    </div>
                  </div>
                  <div class="dev-connector"><span>↓ 去重 · 补全 · 评分 · 筛选</span></div>

                  <!-- STEP 3.5: LLM 摘要生成 -->
                  <div class="dev-step">
                    <div class="dev-step-num dev-step-llm">AI</div>
                    <div class="dev-step-body">
                      <div class="dev-step-title">
                        LLM 摘要生成
                        <span class="dev-step-sub">{{ searchStore.documents.filter(d => d.ai_summary).length }} / {{ searchStore.documents.length }} 篇成功</span>
                        <span class="dev-toggle-btn" @click="llmAllOpen = !llmAllOpen">{{ llmAllOpen ? '全部收起' : '全部展开' }}</span>
                      </div>
                      <div v-if="searchStore.documents.length > 0" class="dev-llm-list">
                        <div v-for="doc in searchStore.documents" :key="doc.id" class="dev-llm-item">
                          <!-- 标题行（可点击） -->
                          <div class="dev-llm-title-row" @click="toggleLlmDoc(String(doc.id))">
                            <el-icon class="expand-icon" :class="{ 'icon-open': llmAllOpen || expandedLlmDocs.has(String(doc.id)) }"><ArrowRight /></el-icon>
                            <el-tag size="small" effect="dark" style="flex-shrink:0;font-size:10px">{{ doc.source }}</el-tag>
                            <span class="dev-llm-doc-title">{{ doc.title }}</span>
                            <span class="dev-llm-badge" :class="doc.ai_summary ? 'badge-ok' : 'badge-none'">{{ doc.ai_summary ? '✓ AI摘要' : '无摘要' }}</span>
                          </div>
                          <!-- 展开区：原文 → LLM输出 -->
                          <div v-if="llmAllOpen || expandedLlmDocs.has(String(doc.id))" class="dev-llm-detail">
                            <div class="dev-llm-col">
                              <div class="dev-llm-col-label">原文摘要 <span class="col-label-sub">（API返回）</span></div>
                              <div class="dev-llm-text dev-llm-raw">{{ doc.abstract?.slice(0, 300) ?? '（无摘要）' }}{{ (doc.abstract?.length ?? 0) > 300 ? '…' : '' }}</div>
                            </div>
                            <div class="dev-llm-arrow">→</div>
                            <div class="dev-llm-col">
                              <div class="dev-llm-col-label">AI 中文摘要 <span class="col-label-sub">（LLM输出）</span></div>
                              <div class="dev-llm-text dev-llm-ai">{{ doc.ai_summary?.slice(0, 300) ?? '（未生成）' }}{{ (doc.ai_summary?.length ?? 0) > 300 ? '…' : '' }}</div>
                              <div v-if="doc.ai_key_points?.length" class="dev-llm-points">
                                <span v-for="pt in doc.ai_key_points.slice(0, 3)" :key="pt" class="dev-llm-point">{{ pt }}</span>
                              </div>
                              <div v-if="doc.ai_relevance_reason" class="dev-llm-reason">相关理由：{{ doc.ai_relevance_reason }}</div>
                            </div>
                          </div>
                        </div>
                      </div>
                      <div v-else class="dev-no-data">暂无文献数据</div>
                    </div>
                  </div>
                  <div class="dev-connector"><span>↓</span></div>

                  <!-- STEP 4: 后处理 & 最终结果 -->
                  <div class="dev-step">
                    <div class="dev-step-num">4</div>
                    <div class="dev-step-body">
                      <div class="dev-step-title">后处理 & 最终结果</div>
                      <div class="dev-funnel">
                        <div class="funnel-node">
                          <span class="funnel-num">{{ currentRound?.total_candidates ?? '?' }}</span>
                          <span class="funnel-label">原始候选</span>
                        </div>
                        <span class="funnel-op">→ 跨源去重 →</span>
                        <span class="funnel-op">元数据补全 →</span>
                        <span class="funnel-op">相关性评分 →</span>
                        <div class="funnel-node funnel-final">
                          <span class="funnel-num">{{ currentRound?.selected_count ?? searchStore.documents.length }}</span>
                          <span class="funnel-label">最终呈现</span>
                        </div>
                      </div>
                    </div>
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
import { onMounted, computed, ref, reactive, watch, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '../stores/project'
import { useSearchStore } from '../stores/search'
import { projectApi } from '../api/client'
import RoundTimeline from '../components/RoundTimeline.vue'
import DocumentCard from '../components/DocumentCard.vue'
import DocumentSkeleton from '../components/document/DocumentSkeleton.vue'
import SourceProgressBar from '../components/search/SourceProgressBar.vue'
import AgentPlanView from '../components/pipeline/AgentPlanView.vue'
import { useSSE } from '../composables/useSSE'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const searchStore = useSearchStore()
const submitting = ref(false)
const devViewOpen = ref(false)
const llmAllOpen = ref(false)
const expandedSources = reactive<Set<string>>(new Set())
const expandedLlmDocs = reactive<Set<string>>(new Set())

// SSE real-time streaming
const sse = useSSE()
const sourceProgressRef = ref<InstanceType<typeof SourceProgressBar> | null>(null)
const agentPlanRef = ref<InstanceType<typeof AgentPlanView> | null>(null)

function setupSSE(roundId: string) {
  sse.on('round_status', (data: any) => searchStore.handleSSEEvent('round_status', data))
  sse.on('doc_arrived', (data: any) => searchStore.handleSSEEvent('doc_arrived', data))
  sse.on('summary_ready', (data: any) => searchStore.handleSSEEvent('summary_ready', data))
  sse.on('round_complete', (data: any) => {
    searchStore.handleSSEEvent('round_complete', data)
    sse.disconnect()
  })
  sse.on('agent_plan', (data: any) => agentPlanRef.value?.setPlan(data))
  sse.on('source_started', (data: any) => sourceProgressRef.value?.onSourceStarted(data))
  sse.on('source_complete', (data: any) => sourceProgressRef.value?.onSourceComplete(data))
  sse.on('source_error', (data: any) => sourceProgressRef.value?.onSourceError(data))
  sse.connect(roundId)
}

onUnmounted(() => sse.disconnect())

function toggleSource(srcId: string) {
  expandedSources.has(srcId) ? expandedSources.delete(srcId) : expandedSources.add(srcId)
}
function toggleLlmDoc(docId: string) {
  expandedLlmDocs.has(docId) ? expandedLlmDocs.delete(docId) : expandedLlmDocs.add(docId)
}
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

const docsBySource = computed(() => {
  const result: Record<string, any[]> = {}
  for (const doc of searchStore.documents) {
    if (!result[doc.source]) result[doc.source] = []
    result[doc.source].push(doc)
  }
  return result
})

const sortedSourceStats = computed(() => {
  const entries = Object.entries(searchStore.sourceStats) as [string, any][]
  entries.sort((a, b) => (b[1].count ?? 0) - (a[1].count ?? 0))
  return Object.fromEntries(entries)
})

function langScopeLabel(scope: string) {
  return ({ chinese_first: '中文优先', international: '国际英文', bilingual: '中英双语', global: '全球多语言' } as any)[scope] ?? scope
}

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
    const round = await searchStore.startRound(route.params.id as string)
    await projectStore.fetchProject(route.params.id as string)
    // Connect SSE for real-time streaming
    if (round?.id) {
      setupSSE(round.id)
    }
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
  // Auto-connect SSE for active rounds (page refresh scenario)
  if (searchStore.currentRound && ['searching', 'summarizing', 'running', 'pending'].includes(searchStore.currentRound.status)) {
    setupSSE(searchStore.currentRound.id)
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

/* Old processing state (kept for fallback) */
.processing-state {
  display: flex; gap: 32px; align-items: center;
  background: #fff; border-radius: 8px; padding: 40px;
  justify-content: center;
}
.processing-text p { margin: 0; font-size: 15px; font-weight: 500; }
.processing-hint { color: #909399; font-size: 13px; margin-top: 8px; text-align: center; }

/* New SSE-powered processing state */
.processing-state-v2 {
  background: #fff; border-radius: 10px; padding: 24px;
  border: 1px solid #e4e7ed; margin-bottom: 16px;
}
.processing-header {
  display: flex; align-items: center; gap: 16px; margin-bottom: 16px;
}
.processing-status {
  font-size: 13px; color: #606266; white-space: nowrap; flex-shrink: 0;
}

/* Streaming doc list */
.streaming-docs {
  background: #f5f7fa; border-radius: 8px; padding: 12px 16px;
  margin-top: 12px;
}
.streaming-header {
  display: flex; justify-content: space-between; align-items: center;
  font-size: 14px; font-weight: 600; color: #303133; margin-bottom: 8px;
}
.streaming-hint { font-size: 12px; color: #909399; font-weight: 400; }
.streaming-list { display: flex; flex-direction: column; gap: 6px; }
.streaming-doc-item {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 10px; background: #fff; border-radius: 6px;
  border: 1px solid #ebeef5; font-size: 13px;
  animation: slideIn 0.3s ease-out;
}
.streaming-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.dot-has { background: #67c23a; }
.dot-no { background: #e6a23c; }
.streaming-doc-title {
  flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: #606266;
}
.skeleton-placeholders { display: flex; flex-direction: column; gap: 12px; margin-top: 12px; }

/* TransitionGroup animations */
.doc-list-enter-active { animation: slideIn 0.4s ease-out; }
.doc-list-leave-active { animation: slideIn 0.3s ease-in reverse; }
@keyframes slideIn {
  from { opacity: 0; transform: translateX(20px); }
  to { opacity: 1; transform: translateX(0); }
}

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

/* ── Dev View Pipeline ── */
.dev-pipeline {
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 10px;
  padding: 18px 20px;
  margin-bottom: 16px;
  color: #c9d1d9;
  font-size: 13px;
}
.dev-pipeline-header {
  display: flex; align-items: center; gap: 8px;
  font-size: 14px; font-weight: 700; color: #58a6ff;
  margin-bottom: 18px; padding-bottom: 12px;
  border-bottom: 1px solid #21262d;
}

/* Step block */
.dev-step {
  display: flex; gap: 14px; align-items: flex-start;
  background: #161b22; border: 1px solid #21262d;
  border-radius: 8px; padding: 14px 16px;
}
.dev-step-num {
  width: 24px; height: 24px; border-radius: 50%;
  background: #1f6feb; color: #fff;
  font-size: 12px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0; margin-top: 1px;
}
.dev-step-body { flex: 1; min-width: 0; }
.dev-step-title {
  font-size: 13px; font-weight: 600; color: #e6edf3;
  margin-bottom: 10px; display: flex; align-items: center; gap: 8px;
}
.dev-step-sub { font-size: 11px; font-weight: 400; color: #8b949e; }

/* Connector between steps */
.dev-connector {
  text-align: center; color: #8b949e;
  font-size: 11px; padding: 4px 0;
  display: flex; align-items: center; justify-content: center; gap: 6px;
}
.dev-connector span {
  background: #161b22; border: 1px solid #21262d;
  border-radius: 20px; padding: 2px 12px;
}

/* KV rows */
.dev-kv-list { display: flex; flex-direction: column; gap: 6px; }
.dev-kv { display: flex; align-items: flex-start; gap: 10px; }
.dev-k {
  font-size: 11px; color: #8b949e;
  min-width: 76px; flex-shrink: 0; padding-top: 2px;
}
.dev-v { color: #c9d1d9; flex: 1; }
.dev-tags { display: flex; flex-wrap: wrap; gap: 4px; }
.dev-tag { font-family: monospace; }
.dev-source-tag { flex-shrink: 0; margin-left: 4px; }

/* Code */
.dev-code {
  font-family: 'Consolas', monospace; font-size: 12px;
  background: #0d1117; border: 1px solid #21262d;
  border-radius: 4px; padding: 2px 7px;
  color: #79c0ff;
}
.dev-code-primary { color: #a5f3c0; font-size: 13px; font-weight: 500; }
.dev-code-sm {
  font-family: 'Consolas', monospace; font-size: 11.5px;
  color: #79c0ff; word-break: break-all;
}

/* Source table */
.dev-src-table { width: 100%; }
.dev-src-thead, .dev-src-row {
  display: grid;
  grid-template-columns: 20px 120px 1fr 58px 68px;
  align-items: center;
}
.dev-src-thead {
  font-size: 11px; color: #8b949e; font-weight: 600;
  padding: 4px 8px 6px; border-bottom: 1px solid #21262d;
  text-transform: uppercase; letter-spacing: 0.05em;
}
.dev-src-block { border-bottom: 1px solid #21262d; }
.dev-src-block:last-child { border-bottom: none; }
.row-zero { opacity: 0.6; }
.row-err .dev-src-row { background: #160808; }
.dev-src-row {
  padding: 7px 8px;
  transition: background 0.12s;
}
.dev-src-row:hover { background: #1c2128; }

.c-exp { display: flex; align-items: center; justify-content: center; color: #8b949e; }
.c-src { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 500; color: #c9d1d9; }
.c-query { font-size: 12px; color: #8b949e; padding-right: 8px; overflow: hidden; }
.c-count { font-size: 12px; text-align: right; padding-right: 8px; }
.c-time { font-size: 11px; color: #8b949e; text-align: right; }
.cnt-ok { color: #3fb950; font-weight: 600; }
.cnt-zero { color: #8b949e; }

.src-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.dot-ok { background: #3fb950; }
.dot-zero { background: #484f58; }
.dot-err { background: #f85149; }
.dev-err-txt { font-size: 11px; color: #f85149; word-break: break-all; }

/* Expand icon */
.expand-icon { font-size: 11px; transition: transform 0.2s; }
.icon-open { transform: rotate(90deg); }

/* Expanded source doc list */
.dev-src-docs {
  padding: 6px 8px 10px 28px;
  border-top: 1px solid #21262d;
  background: #0d1117;
}
.dev-src-doc-row {
  display: grid;
  grid-template-columns: 28px 52px 1fr 58px;
  align-items: baseline;
  gap: 8px;
  padding: 4px 0;
  border-bottom: 1px solid #161b22;
  font-size: 12px;
}
.dev-src-doc-row:last-of-type { border-bottom: none; }
.doc-rank { color: #484f58; font-size: 11px; text-align: right; }
.doc-score { color: #8957e5; font-family: monospace; font-size: 11px; }
.doc-title-sm { color: #c9d1d9; line-height: 1.4; }
.doc-date-sm { color: #484f58; font-size: 11px; text-align: right; white-space: nowrap; }
.dev-src-note { font-size: 11px; color: #484f58; padding: 6px 0 2px; font-style: italic; }

/* LLM Step */
.dev-step-llm { background: #6e40c9 !important; font-size: 10px !important; }
.dev-toggle-btn {
  margin-left: auto; font-size: 11px; color: #58a6ff;
  cursor: pointer; padding: 2px 8px;
  border: 1px solid #1f6feb; border-radius: 10px;
  background: transparent;
  transition: background 0.15s;
  white-space: nowrap;
}
.dev-toggle-btn:hover { background: #1f3a5f; }

.dev-llm-list { display: flex; flex-direction: column; gap: 6px; }
.dev-llm-item {
  background: #0d1117; border: 1px solid #21262d;
  border-radius: 6px; overflow: hidden;
}
.dev-llm-title-row {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 10px; cursor: pointer;
  transition: background 0.12s;
}
.dev-llm-title-row:hover { background: #161b22; }
.dev-llm-doc-title {
  flex: 1; font-size: 12px; color: #c9d1d9;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.dev-llm-badge { font-size: 10px; white-space: nowrap; }
.badge-ok { color: #3fb950; }
.badge-none { color: #484f58; }

.dev-llm-detail {
  display: grid; grid-template-columns: 1fr 24px 1fr;
  gap: 0; border-top: 1px solid #21262d;
}
.dev-llm-col { padding: 10px 12px; }
.dev-llm-arrow {
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; color: #8b949e;
  background: #0a0d12; border-left: 1px solid #21262d; border-right: 1px solid #21262d;
}
.dev-llm-col-label {
  font-size: 10px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.06em; color: #8b949e; margin-bottom: 6px;
}
.col-label-sub { font-weight: 400; text-transform: none; letter-spacing: 0; color: #484f58; }
.dev-llm-text { font-size: 12px; line-height: 1.6; }
.dev-llm-raw { color: #8b949e; font-style: italic; }
.dev-llm-ai { color: #79c0ff; }
.dev-llm-points {
  display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px;
}
.dev-llm-point {
  font-size: 11px; background: #1f3a5f; color: #79c0ff;
  padding: 2px 7px; border-radius: 10px;
}
.dev-llm-reason {
  font-size: 11px; color: #8b949e; margin-top: 6px;
  font-style: italic; border-top: 1px solid #21262d; padding-top: 6px;
}

/* Funnel */
.dev-funnel {
  display: flex; align-items: center; flex-wrap: wrap;
  gap: 8px; padding: 10px 0 4px;
}
.funnel-node {
  display: flex; flex-direction: column; align-items: center;
  background: #21262d; border-radius: 8px; padding: 8px 16px;
  min-width: 72px;
}
.funnel-final { background: #1a3d1f; border: 1px solid #238636; }
.funnel-num { font-size: 22px; font-weight: 700; color: #e6edf3; line-height: 1; }
.funnel-final .funnel-num { color: #3fb950; }
.funnel-label { font-size: 11px; color: #8b949e; margin-top: 3px; }
.funnel-op { font-size: 12px; color: #8b949e; white-space: nowrap; }

.dev-no-data { font-size: 12px; color: #484f58; padding: 6px 0; }
</style>
