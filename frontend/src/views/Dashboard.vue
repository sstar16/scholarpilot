<template>
  <div class="dashboard">
    <div class="page-header">
      <h2>我的研究项目</h2>
      <el-button type="primary" @click="router.push('/projects/new')">
        <el-icon><Plus /></el-icon> 开始新项目
      </el-button>
    </div>

    <div v-if="loading" class="loading-state">
      <el-skeleton :rows="3" animated />
    </div>

    <div v-else-if="projects.length === 0" class="empty-state">
      <el-empty description="还没有研究项目">
        <el-button type="primary" size="large" @click="router.push('/projects/new')">
          开始第一个研究项目
        </el-button>
      </el-empty>
    </div>

    <div v-else class="project-grid">
      <el-card
        v-for="p in projects"
        :key="p.id"
        class="project-card"
        shadow="hover"
        @click="router.push(`/projects/${p.id}`)"
      >
        <div class="project-header">
          <span class="project-title">{{ p.title }}</span>
          <div style="display:flex;align-items:center;gap:6px">
            <el-tag :type="statusType(p.status)" size="small">{{ statusLabel(p.status) }}</el-tag>
            <el-button size="small" text type="danger" @click.stop="deleteProject(p)">删除</el-button>
          </div>
        </div>
        <p class="project-desc">{{ p.description.slice(0, 100) }}...</p>
        <div class="project-meta">
          <span>领域：{{ p.domain }}</span>
          <span>第 {{ p.current_round }} / 5 轮</span>
          <span>{{ formatDate(p.created_at) }}</span>
        </div>
        <el-progress
          v-if="p.status === 'active'"
          :percentage="p.current_round * 20"
          :stroke-width="4"
          :show-text="false"
          status="striped"
        />
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { projectApi } from '../api/client'

const router = useRouter()
const projects = ref<any[]>([])
const loading = ref(true)

onMounted(async () => {
  try {
    const res = await projectApi.list()
    projects.value = res.data
  } finally {
    loading.value = false
  }
})

async function deleteProject(p: any) {
  await ElMessageBox.confirm(`确认删除项目「${p.title}」？此操作不可撤销。`, '删除项目', { type: 'warning' })
  try {
    await projectApi.delete(p.id)
    projects.value = projects.value.filter(x => x.id !== p.id)
    ElMessage.success('项目已删除')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

function statusLabel(s: string) {
  return { active: '进行中', monitoring: '监控中', archived: '已归档' }[s] || s
}
function statusType(s: string) {
  return { active: 'primary', monitoring: 'success', archived: 'info' }[s] || ''
}
function formatDate(d: string) {
  return new Date(d).toLocaleDateString('zh-CN')
}
</script>

<style scoped>
.dashboard { max-width: 1200px; margin: 0 auto; padding: 24px; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }
.page-header h2 { margin: 0; }
.project-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }
.project-card { cursor: pointer; transition: transform 0.2s; }
.project-card:hover { transform: translateY(-2px); }
.project-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }
.project-title { font-size: 16px; font-weight: 600; }
.project-desc { color: #606266; font-size: 14px; margin: 8px 0; line-height: 1.5; }
.project-meta { display: flex; gap: 16px; color: #909399; font-size: 12px; margin-bottom: 12px; }
.empty-state { text-align: center; padding: 80px 0; }
</style>
