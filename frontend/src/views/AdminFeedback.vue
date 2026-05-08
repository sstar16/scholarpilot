<template>
  <div class="admin-fb">
    <header class="admin-fb-head">
      <h2>
        <el-icon><ChatDotSquare /></el-icon>
        用户反馈管理
      </h2>
      <div class="head-right">
        <el-select
          v-model="filter.status"
          placeholder="所有状态"
          clearable size="small"
          style="width: 140px"
          @change="refresh()"
        >
          <el-option label="待处理" value="open" />
          <el-option label="已确认" value="triaged" />
          <el-option label="已解决" value="resolved" />
          <el-option label="不修" value="wontfix" />
        </el-select>
        <el-select
          v-model="filter.category"
          placeholder="所有类别"
          clearable size="small"
          style="width: 140px"
          @change="refresh()"
        >
          <el-option label="Bug" value="bug" />
          <el-option label="建议" value="suggestion" />
          <el-option label="好评" value="praise" />
          <el-option label="其他" value="other" />
        </el-select>
        <el-button size="small" @click="refresh()" :loading="loading">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>
    </header>

    <div v-if="loading && !items.length" class="admin-fb-empty">
      <el-icon class="is-loading"><Loading /></el-icon>
      加载中...
    </div>

    <div v-else-if="!items.length" class="admin-fb-empty">
      <el-icon :size="36"><ChatDotSquare /></el-icon>
      <p>还没有反馈</p>
    </div>

    <ul v-else class="fb-list">
      <li v-for="it in items" :key="it.id" class="fb-item" :class="'fb-item--' + it.status">
        <div class="fb-item-head">
          <span class="fb-tag" :class="'fb-tag--' + it.category">
            {{ categoryLabel(it.category) }}
          </span>
          <span class="fb-user">{{ it.user_email || '(匿名)' }}</span>
          <span class="fb-time">{{ formatTime(it.created_at) }}</span>
          <div class="spacer" />
          <el-select
            :model-value="it.status"
            size="small"
            style="width: 120px"
            @update:model-value="(v: string) => patchStatus(it, v)"
          >
            <el-option label="待处理" value="open" />
            <el-option label="已确认" value="triaged" />
            <el-option label="已解决" value="resolved" />
            <el-option label="不修" value="wontfix" />
          </el-select>
        </div>
        <div class="fb-content">{{ it.content }}</div>
        <div v-if="it.contact || it.page_url" class="fb-meta">
          <span v-if="it.contact">📮 {{ it.contact }}</span>
          <span v-if="it.page_url">🔗 {{ it.page_url }}</span>
        </div>
        <div class="fb-note">
          <el-input
            v-model="it.admin_note"
            size="small"
            placeholder="管理员备注（失焦即保存）"
            :maxlength="4000"
            @blur="saveNoteIfChanged(it)"
          />
        </div>
      </li>
    </ul>

    <div v-if="total > pageSize" class="fb-pager">
      <el-pagination
        small
        background
        layout="prev, pager, next, total"
        :total="total"
        :page-size="pageSize"
        :current-page="currentPage"
        @current-change="onPageChange"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotSquare, Loading, Refresh } from '@element-plus/icons-vue'
import { siteFeedbackApi, type SiteFeedbackItem } from '../api/client'

const items = ref<SiteFeedbackItem[]>([])
const total = ref(0)
const loading = ref(false)
const pageSize = 20
const currentPage = ref(1)

const filter = reactive({
  status: '',
  category: '',
})

const noteSnapshots = new Map<string, string>()

async function refresh() {
  loading.value = true
  try {
    const offset = (currentPage.value - 1) * pageSize
    const { data } = await siteFeedbackApi.adminList({
      status: filter.status || undefined,
      category: filter.category || undefined,
      limit: pageSize,
      offset,
    })
    items.value = data.items
    total.value = data.total
    noteSnapshots.clear()
    for (const it of items.value) {
      noteSnapshots.set(it.id, it.admin_note || '')
    }
  } catch (e: any) {
    if (e?.response?.status === 403) {
      ElMessage.error('需要管理员权限')
    } else {
      ElMessage.error('加载失败')
    }
  } finally {
    loading.value = false
  }
}

function onPageChange(p: number) {
  currentPage.value = p
  refresh()
}

function categoryLabel(c: string) {
  return { bug: '🐞 Bug', suggestion: '💡 建议', praise: '❤️ 好评', other: '📝 其他' }[c] || c
}

function formatTime(iso: string) {
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

async function patchStatus(it: SiteFeedbackItem, status: string) {
  if (it.status === status) return
  try {
    const { data } = await siteFeedbackApi.adminUpdate(it.id, { status })
    Object.assign(it, data)
    ElMessage.success('状态已更新')
  } catch {
    ElMessage.error('更新失败')
  }
}

async function saveNoteIfChanged(it: SiteFeedbackItem) {
  const snap = noteSnapshots.get(it.id) || ''
  const curr = (it.admin_note || '').trim()
  if (snap === curr) return
  try {
    await siteFeedbackApi.adminUpdate(it.id, { admin_note: curr })
    noteSnapshots.set(it.id, curr)
    ElMessage.success('备注已保存')
  } catch {
    ElMessage.error('备注保存失败')
  }
}

onMounted(refresh)
</script>

<style scoped>
.admin-fb {
  max-width: 920px;
  margin: 0 auto;
  padding: 24px 20px 60px;
}
.admin-fb-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 18px;
}
.admin-fb-head h2 {
  margin: 0;
  font-size: 18px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #0f172a;
}
.admin-fb-head .head-right {
  margin-left: auto;
  display: flex;
  gap: 8px;
  align-items: center;
}
.admin-fb-empty {
  text-align: center;
  padding: 60px 0;
  color: #94a3b8;
  font-size: 14px;
}
.admin-fb-empty .el-icon { margin-bottom: 8px; }

.fb-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.fb-item {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 16px;
  transition: border-color 0.15s;
}
.fb-item:hover { border-color: #cbd5e1; }
.fb-item--resolved { opacity: 0.7; background: #f8fafc; }
.fb-item--wontfix { opacity: 0.6; background: #fafafa; }
.fb-item--triaged { border-color: #a7f3d0; }

.fb-item-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  font-size: 12px;
}
.fb-item-head .spacer { flex: 1; }
.fb-tag {
  padding: 2px 8px;
  border-radius: 99px;
  font-size: 11px;
  font-weight: 600;
}
.fb-tag--bug { background: #fef2f2; color: #b91c1c; }
.fb-tag--suggestion { background: #ecfdf5; color: #065f46; }
.fb-tag--praise { background: #fff1f2; color: #9f1239; }
.fb-tag--other { background: #f1f5f9; color: #475569; }
.fb-user {
  font-weight: 500;
  color: #334155;
}
.fb-time {
  color: #94a3b8;
  font-size: 11px;
}
.fb-content {
  font-size: 13.5px;
  color: #1e293b;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  padding: 6px 0;
}
.fb-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  font-size: 11.5px;
  color: #64748b;
  padding-top: 4px;
}
.fb-note {
  margin-top: 8px;
}
.fb-pager {
  margin-top: 20px;
  display: flex;
  justify-content: center;
}
</style>
