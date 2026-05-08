<template>
  <div class="collab-doc-list">
    <div class="collab-doc-list__head">
      <div class="head-title">
        <el-icon><Collection /></el-icon>
        协作文献 ({{ docs.length }})
      </div>
      <el-button size="small" text @click="$emit('manage')">
        <el-icon><Plus /></el-icon>
        调整
      </el-button>
    </div>

    <div class="doc-items">
      <div
        v-for="doc in docs"
        :key="doc.id"
        class="doc-item"
      >
        <div class="doc-title" @click="$emit('view', doc)">
          {{ doc.title }}
        </div>
        <div class="doc-meta">
          <el-tag size="small" effect="plain">{{ doc.source }}</el-tag>
          <el-tag
            v-if="doc.fulltext_status === 'available'"
            size="small"
            effect="plain"
            type="success"
          >全文 ✓</el-tag>
          <el-tag
            v-else
            size="small"
            effect="plain"
            type="info"
          >仅摘要</el-tag>
        </div>
        <div v-if="doc.one_line_summary" class="doc-summary">
          {{ doc.one_line_summary }}
        </div>
        <div class="doc-actions">
          <el-button size="small" text @click="$emit('view', doc)">
            查看详情
          </el-button>
          <el-popover
            trigger="click"
            placement="left"
            :width="320"
          >
            <template #reference>
              <el-button size="small" text :loading="updatingDoc === doc.id">
                <el-icon><MagicStick /></el-icon>
                让 AI 更新
              </el-button>
            </template>
            <div class="update-popover">
              <p class="hint">可选：告诉 AI 您希望重点关注哪个方向</p>
              <el-input
                v-model="hintMap[doc.id]"
                type="textarea"
                :rows="3"
                placeholder="例如：重点总结这篇文献对某某问题的贡献"
              />
              <div style="text-align:right;margin-top:8px">
                <el-button
                  type="primary"
                  size="small"
                  @click="onRegenerateAnalysis(doc)"
                >
                  开始更新
                </el-button>
              </div>
            </div>
          </el-popover>
          <el-button
            size="small"
            text
            type="danger"
            @click="onRemoveDoc(doc.id)"
          >
            移除
          </el-button>
        </div>
      </div>

      <el-empty v-if="!docs.length" description="暂无协作文献" :image-size="80" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Collection, Plus, MagicStick } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useCollaborationStore } from '../../stores/collaboration'
import { collaborationApi } from '../../api/client'

const props = defineProps<{
  projectId: string
}>()

defineEmits<{
  view: [doc: any]
  manage: []
}>()

const collabStore = useCollaborationStore()
const updatingDoc = ref<string | null>(null)
const hintMap = ref<Record<string, string>>({})

const docs = computed(() => collabStore.docs)

async function onRegenerateAnalysis(doc: any) {
  updatingDoc.value = doc.id
  try {
    await collaborationApi.regenerateDocAnalysis(
      props.projectId,
      doc.id,
      hintMap.value[doc.id] || undefined,
    )
    ElMessage.success('AI 已更新该文献分析，刷新协作快照中...')
    await collabStore.refresh()
    hintMap.value[doc.id] = ''
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '更新失败')
  } finally {
    updatingDoc.value = null
  }
}

async function onRemoveDoc(docId: string) {
  try {
    await ElMessageBox.confirm('从协作中移除此文献？对话历史会保留。', '确认移除')
    await collabStore.updateDocs('remove', [docId])
    ElMessage.success('已移除')
  } catch { /* cancelled */ }
}
</script>

<style scoped>
.collab-doc-list {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--paper);
}
.collab-doc-list__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--ink-200);
}
.head-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 14px;
  color: var(--ink-900);
}
.doc-items {
  flex: 1;
  overflow-y: auto;
  padding: 10px 12px;
}
.doc-item {
  padding: 10px;
  margin-bottom: 10px;
  background: var(--paper-cool);
  border: 1px solid var(--ink-200);
  border-radius: 8px;
}
.doc-title {
  font-size: 13px;
  color: var(--ink-900);
  line-height: 1.4;
  font-weight: 500;
  cursor: pointer;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}
.doc-title:hover { color: var(--signal-teal); }
.doc-meta {
  display: flex;
  gap: 4px;
  margin: 6px 0;
  flex-wrap: wrap;
}
.doc-summary {
  font-size: 12px;
  color: var(--ink-400);
  line-height: 1.4;
  margin-bottom: 6px;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}
.doc-actions {
  display: flex;
  gap: 4px;
  justify-content: flex-end;
  padding-top: 6px;
  border-top: 1px dashed var(--ink-200);
}
.update-popover .hint {
  font-size: 12px;
  color: var(--ink-400);
  margin: 0 0 8px;
}
</style>
