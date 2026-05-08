<template>
  <!-- Keyword Confirmation -->
  <KeywordConfirmMessage
    v-if="msg.rich_type === 'keyword_confirmation'"
    :rich-data="msg.rich_data"
    :is-active="isLatestRichOfType('keyword_confirmation')"
    @confirm="(p: any) => emit('confirm-keywords', p)"
    @auto-confirm="(p: any) => emit('confirm-keywords', p)"
  />

  <!-- Search Progress -->
  <SearchProgressMessage
    v-else-if="msg.rich_type === 'search_progress'"
    :rich-data="msg.rich_data"
    :is-active="isLatestRichOfType('search_progress')"
    :finalizing="finalizing"
    @view-detail="(p: any) => emit('view-doc', p)"
    @finalize="emit('finalize')"
  />

  <!-- Answer Now 部分结果：在长检索流程被用户中断后，由后端 deliver_partial_answer 注入 -->
  <PartialAnswerMessage
    v-else-if="msg.rich_type === 'partial_answer'"
    :rich-data="msg.rich_data"
  />

  <!-- round_results 旧消息类型已合并进 search_progress；保留向后兼容（旧
       session 持久化数据可能含此 type），渲染时直接 fallthrough 不输出 DOM -->
  <RoundCompleteMessage
    v-else-if="msg.rich_type === 'round_complete'"
    :rich-data="msg.rich_data"
    @start-next-round="(p?: { mode?: string }) => emit('start-next-round', p)"
  />

  <CollaborationScopeBubble
    v-else-if="msg.rich_type === 'collaboration_scope'"
    :rich-data="msg.rich_data"
    :is-active="isLatestRichOfType('collaboration_scope') && currentState === 'collaboration_selecting'"
    @start="(ids: string[]) => emit('start-collaboration', ids)"
    @cancel="emit('cancel-collaboration')"
  />

  <CollaborationStartedMessage
    v-else-if="msg.rich_type === 'collaboration_started'"
    :rich-data="msg.rich_data"
  />

  <ReadPlanBubble
    v-else-if="msg.rich_type === 'collaboration_read_plan'"
    :rich-data="msg.rich_data"
    :is-active="isLatestRichOfType('collaboration_read_plan') && !hasLaterRichOfType('collaboration_answer')"
    @resume-start="emit('deep-read-start')"
  />

  <CollaborationAnswerMessage
    v-else-if="msg.rich_type === 'collaboration_answer'"
    :rich-data="msg.rich_data"
  />

  <CardUpdateSuggestionMessage
    v-else-if="msg.rich_type === 'card_update_suggestion'"
    :rich-data="msg.rich_data"
  />

  <CollaborationEndedMessage
    v-else-if="msg.rich_type === 'collaboration_ended'"
    :rich-data="msg.rich_data"
  />

  <FeatureGateBlockedBubble
    v-else-if="msg.rich_type === 'feature_gate_blocked'"
    :payload="msg.metadata"
    @action="(t: string) => emit('suggested-action', t)"
  />

  <!-- pdf_import_parsing 气泡视觉过于长条占位，暂时隐藏；解析完成后会有 pdf_import_editing 面板接手 -->
  <template v-else-if="msg.rich_type === 'pdf_import_parsing'"></template>

  <PdfImportEditBubble
    v-else-if="msg.rich_type === 'pdf_import_editing'"
    :payload="msg.rich_data"
    @confirmed="(id: string) => emit('pdf-import-confirmed', id)"
    @cancelled="(id: string) => emit('pdf-import-cancel', id)"
  />

  <!-- 评分 / 摘要生成中的进度动画（final_card 到达后自动隐藏） -->
  <PdfImportScoringBubble
    v-else-if="msg.rich_type === 'pdf_import_scoring' && !completedScoringJobIds.has(msg.rich_data?.job_id)"
    :payload="msg.rich_data"
  />

  <PdfImportFinalCard
    v-else-if="msg.rich_type === 'pdf_import_final_card'"
    :payload="msg.rich_data"
    :project-id="projectId || ''"
    @bucketed="(docId: string, bucket: string) => emit('pdf-import-bucketed', docId, bucket)"
  />

  <div
    v-else-if="msg.rich_type === 'pdf_import_failed' || msg.rich_type === 'pdf_import_cancelled'"
    class="pdf-status-line"
  >
    <span v-if="msg.rich_type === 'pdf_import_failed'">❌</span>
    <span v-else>🚫</span>
    {{ msg.content }}
  </div>

  <!-- B3/C1: 由 POST_FEEDBACK hook 推送的智能 skill 推荐 -->
  <SkillSuggestionMessage
    v-else-if="msg.rich_type === 'skill_suggestion'"
    :payload="msg.rich_data"
  />

  <!-- 距上次检索 N 天的软提示，由 GET 项目页时 staleCheck 触发注入 -->
  <StaleHintMessage
    v-else-if="msg.rich_type === 'stale_hint' && !dismissedStaleHints.has(msg.timestamp)"
    :rich-data="msg.rich_data"
    :project-id="projectId || ''"
    @start-round="emit('stale-hint-start')"
    @dismissed="emit('stale-hint-dismissed', msg)"
  />

  <!-- flow_exited: session_exit.py 的"已退出 X 流程"通知，走 system 行文案 -->
  <div
    v-else-if="msg.rich_type === 'flow_exited'"
    class="flow-exited-line"
  >
    <el-icon :size="13"><CircleCheck /></el-icon>
    <span>{{ msg.content || '已退出当前流程' }}</span>
    <span
      v-if="msg.rich_data?.cleanup_summary || msg.rich_payload?.cleanup_summary"
      class="flow-exited-hint"
    >· {{ msg.rich_data?.cleanup_summary || msg.rich_payload?.cleanup_summary }}</span>
  </div>

  <!-- Fallback: 未识别的 rich_type（未来新增契约前就已下发的消息）— 不再静默丢弃 -->
  <ChatMessage
    v-else
    :msg="msg"
    :animate="false"
  />
</template>

<script setup lang="ts">
import { CircleCheck } from '@element-plus/icons-vue'
import ChatMessage from './ChatMessage.vue'
import KeywordConfirmMessage from './rich/KeywordConfirmMessage.vue'
import SearchProgressMessage from './rich/SearchProgressMessage.vue'
import PartialAnswerMessage from './rich/PartialAnswerMessage.vue'
import RoundCompleteMessage from './rich/RoundCompleteMessage.vue'
import CollaborationScopeBubble from './rich/CollaborationScopeBubble.vue'
import CollaborationStartedMessage from './rich/CollaborationStartedMessage.vue'
import CollaborationAnswerMessage from './rich/CollaborationAnswerMessage.vue'
import CardUpdateSuggestionMessage from './rich/CardUpdateSuggestionMessage.vue'
import CollaborationEndedMessage from './rich/CollaborationEndedMessage.vue'
import ReadPlanBubble from './rich/ReadPlanBubble.vue'
import FeatureGateBlockedBubble from './FeatureGateBlockedBubble.vue'
import PdfImportScoringBubble from './PdfImportScoringBubble.vue'
import PdfImportEditBubble from './PdfImportEditBubble.vue'
import PdfImportFinalCard from './PdfImportFinalCard.vue'
import SkillSuggestionMessage from './rich/SkillSuggestionMessage.vue'
import StaleHintMessage from './rich/StaleHintMessage.vue'

const props = defineProps<{
  msg: any
  idx: number
  messages: any[]
  currentState?: string
  projectId?: string
  finalizing: boolean
  completedScoringJobIds: Set<string>
  dismissedStaleHints: Set<string>
}>()

const emit = defineEmits<{
  'confirm-keywords': [payload: any]
  'view-doc': [payload: any]
  'finalize': []
  'start-next-round': [payload?: { mode?: string }]
  'start-collaboration': [docIds: string[]]
  'cancel-collaboration': []
  'deep-read-start': []
  'pdf-import-confirmed': [docId: string]
  'pdf-import-cancel': [jobId: string]
  'pdf-import-bucketed': [docId: string, bucket: string]
  'suggested-action': [trigger: string]
  'stale-hint-start': []
  'stale-hint-dismissed': [msg: any]
}>()

// 判断当前 idx 是否是某 rich_type 的最新一条（更早的同 type 显示为"历史快照"）
function isLatestRichOfType(type: string): boolean {
  for (let j = props.messages.length - 1; j >= 0; j--) {
    if ((props.messages[j] as any).rich_type === type) return j === props.idx
  }
  return false
}

// 是否在 idx 之后出现过某 rich_type（用于 ReadPlanBubble 被 answer 覆盖后失效）
function hasLaterRichOfType(type: string): boolean {
  for (let j = props.idx + 1; j < props.messages.length; j++) {
    if ((props.messages[j] as any).rich_type === type) return true
  }
  return false
}
</script>

<style scoped>
.flow-exited-line {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  margin: var(--space-3) auto;
  padding: 6px var(--space-4);
  font-size: var(--type-meta-size);
  color: var(--signal-emerald);
  background: var(--signal-emerald-bg);
  border: 1px solid var(--signal-emerald);
  border-radius: var(--radius-full);
  animation: fadeUp var(--duration-normal) var(--ease-out) both;
}
.flow-exited-hint {
  color: var(--ink-400);
}

.pdf-status-line {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #fef6ec;
  border-radius: 6px;
  font-size: 13px;
  color: #b88230;
  margin: 6px 0;
}
</style>
