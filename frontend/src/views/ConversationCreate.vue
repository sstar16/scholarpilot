<template>
  <div class="conv-create">
    <el-card class="conv-card" shadow="never">
      <template #header>
        <div class="card-header">
          <el-button text @click="router.back()"><el-icon><ArrowLeft /></el-icon></el-button>
          <span>创建研究项目</span>
          <el-button text size="small" class="legacy-link" @click="goLegacy">
            手动表单
          </el-button>
        </div>
      </template>

      <ChatPanel ref="chatPanelRef" />

      <!-- Navigate to project after search mode selected -->
      <div v-if="showGoToProject" class="conv-card__nav">
        <el-alert type="success" :closable="false" show-icon>
          <template #title>
            项目已创建，检索模式已选择！
          </template>
        </el-alert>
        <el-button type="primary" size="large" style="width: 100%; margin-top: 12px" @click="goToProject">
          进入项目，开始检索
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useConversationStore } from '../stores/conversation'
import ChatPanel from '../components/conversation/ChatPanel.vue'

const router = useRouter()
const store = useConversationStore()
const chatPanelRef = ref()

const showGoToProject = computed(() =>
  store.projectId && store.currentState === 'keyword_confirmation'
)

// Auto-redirect to ProjectView once search mode is selected
watch(() => store.currentState, (state) => {
  if (state === 'keyword_confirmation' && store.projectId) {
    router.push(`/projects/${store.projectId}`)
  }
})

onMounted(async () => {
  store.reset()
  await store.startSession()
})

function goLegacy() {
  router.push('/projects/new-legacy')
}

function goToProject() {
  if (store.projectId) {
    router.push(`/projects/${store.projectId}`)
  }
}
</script>

<style scoped>
/* 与 ProjectView 视觉一致：撑满整个工作区，避免用户从对话创建页跳进项目页时
   出现"突然全屏"的视觉跳变。容器全宽，内部 ChatPanel 自带阅读宽度防御。 */
.conv-create {
  width: 100%;
  margin: 0;
  padding: 0;
  height: calc(100vh - 52px);
  min-width: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.conv-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  border: none;
  border-radius: 0;
  min-width: 0;
}
.conv-card :deep(.el-card__body) {
  flex: 1;
  overflow: hidden;
  padding: 0;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.conv-card :deep(.el-card__header) {
  flex-shrink: 0;
}
.card-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 16px;
  font-weight: 600;
}
.legacy-link { margin-left: auto; font-size: 12px; color: #909399; }
.conv-card__nav { padding: 16px 20px; border-top: 1px solid #ebeef5; }
</style>
