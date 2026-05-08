<template>
  <div class="collab-banner">
    <div class="collab-banner__pulse" />
    <div class="collab-banner__icon">
      <el-icon :size="22"><Stopwatch /></el-icon>
    </div>
    <div class="collab-banner__info">
      <div class="mode-label">协作研究模式</div>
      <div class="scope">
        {{ collabStore.docCount }} 篇文献参与 ·
        <span v-if="lastRefresh">{{ formatRelative(lastRefresh) }}刷新</span>
        <span v-else>刚进入</span>
      </div>
    </div>
    <div class="collab-banner__actions">
      <el-button size="small" type="info" plain @click="$emit('manage-docs')">
        <el-icon><Folder /></el-icon>
        管理文献
      </el-button>
      <el-button size="small" type="info" plain @click="$emit('view-graph')">
        <el-icon><Share /></el-icon>
        知识图谱
      </el-button>
      <el-button size="small" type="danger" plain @click="showExitDialog = true">
        <el-icon><Close /></el-icon>
        退出协作
      </el-button>
    </div>

    <el-dialog
      v-model="showExitDialog"
      title="退出协作研究模式"
      width="460px"
      align-center
    >
      <p class="exit-intro">您希望如何处理这次协作？</p>
      <el-radio-group v-model="exitChoice" class="exit-choices">
        <el-radio value="keep" class="exit-choice">
          <div>
            <div class="choice-title">保留</div>
            <div class="choice-desc">下次再进入时会刷新文献库和研究记忆，对话历史保留</div>
          </div>
        </el-radio>
        <el-radio value="archive" class="exit-choice">
          <div>
            <div class="choice-title">归档</div>
            <div class="choice-desc">历史记录仍保留，但不能再次进入此协作</div>
          </div>
        </el-radio>
      </el-radio-group>
      <template #footer>
        <el-button @click="showExitDialog = false">取消</el-button>
        <el-button type="primary" :loading="exiting" @click="confirmExit">
          确认退出
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Stopwatch, Folder, Share, Close } from '@element-plus/icons-vue'
import { useToast } from '../../composables/useToast'
import { useCollaborationStore } from '../../stores/collaboration'

defineEmits<{
  'manage-docs': []
  'view-graph': []
}>()

const collabStore = useCollaborationStore()
const toast = useToast()
const showExitDialog = ref(false)
const exitChoice = ref<'keep' | 'archive'>('keep')
const exiting = ref(false)

const lastRefresh = computed(() => collabStore.snapshot?.memory_sync_at)

function formatRelative(iso: string): string {
  try {
    const d = new Date(iso)
    const diff = Date.now() - d.getTime()
    const min = Math.floor(diff / 60000)
    if (min < 1) return '刚刚'
    if (min < 60) return `${min} 分钟前`
    const h = Math.floor(min / 60)
    if (h < 24) return `${h} 小时前`
    const days = Math.floor(h / 24)
    return `${days} 天前`
  } catch { return '' }
}

async function confirmExit() {
  exiting.value = true
  try {
    await collabStore.exitCollaboration(exitChoice.value === 'archive')
    toast.success(exitChoice.value === 'archive' ? '协作已归档' : '协作已保留')
    showExitDialog.value = false
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || '退出失败')
  } finally {
    exiting.value = false
  }
}
</script>

<style scoped>
/* 协作 banner 是全局 mode banner：teal→purple 渐变是 mode 切换的视觉锚点
   （不同于 rich-msg 的静默卡片，banner 是顶层流程标识） */
.collab-banner {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 10px var(--space-5);
  background: linear-gradient(135deg, var(--signal-teal) 0%, var(--signal-purple) 100%);
  color: #fff;
  height: 56px;
  box-shadow: 0 2px 8px rgba(13, 148, 136, 0.25);
}
.collab-banner__pulse {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--signal-emerald);
  box-shadow: 0 0 0 0 var(--signal-emerald-bg);
  animation: collab-pulse 2s infinite;
  flex-shrink: 0;
  margin-left: var(--space-1);
}
@keyframes collab-pulse {
  0% { box-shadow: 0 0 0 0 rgba(5, 150, 105, 0.6); }
  70% { box-shadow: 0 0 0 10px rgba(5, 150, 105, 0); }
  100% { box-shadow: 0 0 0 0 rgba(5, 150, 105, 0); }
}
.collab-banner__icon { display: flex; align-items: center; }
.collab-banner__info { flex: 1; min-width: 0; }
.mode-label {
  font-family: var(--font-display);
  font-size: var(--type-body-size);
  font-weight: 700;
  letter-spacing: 0.5px;
}
.scope {
  font-size: var(--type-meta-size);
  opacity: 0.85;
  margin-top: 1px;
}
.collab-banner__actions {
  display: flex;
  gap: var(--space-2);
}
.collab-banner__actions :deep(.el-button) {
  background: rgba(255, 255, 255, 0.12);
  border-color: rgba(255, 255, 255, 0.3);
  color: #fff;
}
.collab-banner__actions :deep(.el-button:hover) {
  background: rgba(255, 255, 255, 0.2);
  border-color: rgba(255, 255, 255, 0.5);
}
.exit-intro { margin: 0 0 var(--space-4); color: var(--ink-500); }
.exit-choices {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  width: 100%;
}
.exit-choice {
  width: 100%;
  padding: 10px;
  border: 1px solid var(--ink-100);
  border-radius: var(--radius-md);
  margin: 0 !important;
}
.choice-title { font-weight: 600; color: var(--ink-900); }
.choice-desc { font-size: var(--type-meta-size); color: var(--ink-400); margin-top: 2px; }
.note-btn--ping :deep(.el-icon) {
  color: var(--signal-amber);
  animation: note-ping 1.6s ease-in-out infinite;
}
@keyframes note-ping {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.18); }
}
</style>
