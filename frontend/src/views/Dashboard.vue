<template>
  <div class="dashboard">
    <!-- Hero header -->
    <div class="dash-hero">
      <div class="hero-inner">
        <div>
          <h1 class="hero-title">研究项目</h1>
          <p class="hero-sub">管理你的文献检索与情报追踪</p>
        </div>
        <button class="btn-create" @click="router.push('/projects/new')">
          <el-icon><Plus /></el-icon>
          <span>新建项目</span>
        </button>
      </div>
    </div>

    <div class="dash-body">
      <div v-if="loading" class="loading-state">
        <div v-for="i in 3" :key="i" class="skel-card">
          <div class="skel-bar skel-title"></div>
          <div class="skel-bar skel-desc"></div>
          <div class="skel-bar skel-meta"></div>
        </div>
      </div>

      <div v-else-if="projects.length === 0" class="empty-state">
        <div class="empty-icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/><path d="M8 7h6"/><path d="M8 11h8"/></svg>
        </div>
        <h3>还没有研究项目</h3>
        <p>创建你的第一个项目，开始检索文献</p>
        <button class="btn-create" @click="router.push('/projects/new')">
          <el-icon><Plus /></el-icon> 开始第一个项目
        </button>
      </div>

      <div v-else class="project-grid">
        <div
          v-for="(p, idx) in projects"
          :key="p.id"
          class="project-card"
          :style="{ animationDelay: `${idx * 60}ms` }"
          @click="router.push(`/projects/${p.id}`)"
        >
          <!-- Status ribbon -->
          <div class="card-status" :class="'status-' + p.status">
            {{ statusLabel(p.status) }}
          </div>

          <h3 class="card-title">{{ p.title }}</h3>
          <p class="card-desc">{{ p.description.slice(0, 120) }}{{ p.description.length > 120 ? '...' : '' }}</p>

          <div class="card-domains">
            <span v-for="d in (p.domains || [p.domain])" :key="d" class="domain-chip">{{ domainLabel(d) }}</span>
          </div>

          <div class="card-footer">
            <div class="round-indicator">
              <div class="round-track">
                <div class="round-fill" :style="{ width: `${(p.current_round / (p.max_rounds || 5)) * 100}%` }"></div>
              </div>
              <span class="round-text">{{ p.current_round }}/{{ p.max_rounds || 5 }} 轮</span>
            </div>
            <span class="card-date">{{ formatDate(p.created_at) }}</span>
            <button class="btn-delete" @click.stop="deleteProject(p)" title="删除">
              <el-icon><Delete /></el-icon>
            </button>
          </div>
        </div>
      </div>
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
  } finally { loading.value = false }
})

async function deleteProject(p: any) {
  await ElMessageBox.confirm(`确认删除「${p.title}」？`, '删除项目', { type: 'warning' })
  try {
    await projectApi.delete(p.id)
    projects.value = projects.value.filter(x => x.id !== p.id)
    ElMessage.success('项目已删除')
  } catch (e: any) { ElMessage.error(e.response?.data?.detail || '删除失败') }
}

function statusLabel(s: string) { return ({ active: '进行中', monitoring: '监控中', archived: '已归档' } as any)[s] || s }
function formatDate(d: string) { return new Date(d).toLocaleDateString('zh-CN') }
const DOMAIN_LABELS: Record<string, string> = {
  biology: '生物医学', chemistry: '化学', materials: '材料科学',
  mechanical: '设备机械', cs: '计算机', physics: '物理学',
  economics: '经济学', environment: '环境科学', other: '其他',
}
function domainLabel(d: string) { return DOMAIN_LABELS[d] || d }
</script>

<style scoped>
.dashboard { min-height: calc(100vh - 52px); }

/* ── Hero ── */
.dash-hero {
  background: var(--ink-900);
  border-bottom: 1px solid var(--ink-700);
  padding: 0 24px;
}
.hero-inner {
  max-width: 1100px; margin: 0 auto;
  display: flex; justify-content: space-between; align-items: center;
  padding: 28px 0 24px;
}
.hero-title {
  font-family: var(--font-display);
  font-size: 26px; font-weight: 900; color: #fff;
  margin: 0; letter-spacing: -0.5px;
}
.hero-sub { font-size: 13px; color: var(--ink-400); margin: 4px 0 0; }

.btn-create {
  display: flex; align-items: center; gap: 6px;
  padding: 9px 20px; border-radius: var(--radius-md);
  background: var(--signal-teal); color: #fff;
  border: none; cursor: pointer;
  font-size: 13px; font-weight: 600;
  font-family: var(--font-body);
  transition: all var(--duration-normal) var(--ease-out);
  box-shadow: 0 2px 8px rgba(13, 148, 136, 0.3);
}
.btn-create:hover {
  background: var(--signal-teal-light);
  transform: translateY(-1px);
  box-shadow: 0 4px 16px rgba(13, 148, 136, 0.35);
}

/* ── Body ── */
.dash-body {
  max-width: 1100px; margin: 0 auto;
  padding: 28px 24px;
}

/* ── Grid ── */
.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 18px;
}

/* ── Card ── */
.project-card {
  position: relative;
  background: var(--paper);
  border: 1px solid var(--ink-100);
  border-radius: var(--radius-lg);
  padding: 22px 24px 18px;
  cursor: pointer;
  transition: all var(--duration-normal) var(--ease-out);
  animation: fadeUp var(--duration-slow) var(--ease-out) both;
}
.project-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-lg);
  border-color: var(--ink-200);
}

.card-status {
  position: absolute; top: 16px; right: 16px;
  font-size: 10px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 2px 10px; border-radius: var(--radius-full);
}
.status-active { background: var(--signal-teal-bg); color: var(--signal-teal); }
.status-monitoring { background: var(--signal-emerald-bg); color: var(--signal-emerald); }
.status-archived { background: var(--ink-50); color: var(--ink-400); }

.card-title {
  font-family: var(--font-display);
  font-size: 17px; font-weight: 700; color: var(--ink-900);
  margin: 0 0 8px; line-height: 1.4;
  padding-right: 60px;
}

.card-desc {
  font-size: 13px; color: var(--ink-500); line-height: 1.65;
  margin: 0 0 12px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}

.card-domains { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 16px; }
.domain-chip {
  font-size: 11px; font-weight: 500; color: var(--ink-500);
  padding: 2px 10px; border-radius: var(--radius-full);
  background: var(--ink-50); border: 1px solid var(--ink-100);
}

/* ── Card footer ── */
.card-footer {
  display: flex; align-items: center; gap: 12px;
  padding-top: 14px; border-top: 1px solid var(--ink-100);
}
.round-indicator { display: flex; align-items: center; gap: 8px; flex: 1; }
.round-track {
  flex: 1; height: 3px; border-radius: 2px;
  background: var(--ink-100); overflow: hidden;
}
.round-fill {
  height: 100%; border-radius: 2px;
  background: linear-gradient(90deg, var(--signal-teal), var(--signal-teal-light));
  transition: width 0.6s var(--ease-out);
}
.round-text { font-size: 11px; font-weight: 600; color: var(--ink-400); white-space: nowrap; }
.card-date { font-size: 11px; color: var(--ink-300); }
.btn-delete {
  width: 28px; height: 28px; border-radius: var(--radius-sm);
  border: 1px solid transparent; background: transparent;
  color: var(--ink-300); cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all var(--duration-fast);
  opacity: 0;
}
.project-card:hover .btn-delete { opacity: 1; }
.btn-delete:hover { background: var(--signal-coral-bg); color: var(--signal-coral); border-color: rgba(220,38,38,0.15); }

/* ── Empty ── */
.empty-state {
  text-align: center; padding: 80px 0;
  animation: fadeUp var(--duration-slow) var(--ease-out);
}
.empty-icon { color: var(--ink-300); margin-bottom: 16px; }
.empty-state h3 { font-family: var(--font-display); font-size: 20px; color: var(--ink-700); margin: 0 0 6px; }
.empty-state p { font-size: 14px; color: var(--ink-400); margin: 0 0 24px; }

/* ── Skeleton ── */
.loading-state { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 18px; }
.skel-card {
  background: var(--paper); border: 1px solid var(--ink-100);
  border-radius: var(--radius-lg); padding: 24px;
}
.skel-bar {
  border-radius: 4px;
  background: linear-gradient(90deg, var(--ink-50), var(--ink-100), var(--ink-50));
  background-size: 400% 100%;
  animation: shimmer 1.8s infinite;
}
.skel-title { height: 18px; width: 65%; margin-bottom: 12px; }
.skel-desc { height: 12px; width: 90%; margin-bottom: 8px; }
.skel-meta { height: 12px; width: 40%; }
</style>
