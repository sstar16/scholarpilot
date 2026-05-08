<template>
  <div v-if="pushes.length > 0" class="push-banner">
    <div class="push-banner__header" @click="expanded = !expanded">
      <el-icon :size="18" color="#e6a23c"><Bell /></el-icon>
      <span class="push-banner__text">
        您有 <strong>{{ pushes.length }}</strong> 条新发现等待分类
      </span>
      <el-button text size="small" @click.stop="clearAll" :loading="clearing">
        全部忽略
      </el-button>
      <span class="push-banner__arrow">{{ expanded ? '▾' : '▸' }}</span>
    </div>

    <transition name="slide">
      <div v-if="expanded" class="push-banner__list">
        <div v-for="push in pushes" :key="push.push_id" class="push-item">
          <div class="push-item__content">
            <p class="push-item__title">{{ push.title }}</p>
            <p class="push-item__summary" v-if="push.push_summary">{{ push.push_summary }}</p>
            <div class="push-item__meta">
              <el-tag size="small">{{ push.source }}</el-tag>
              <el-tag size="small" type="warning">新颖度 {{ (push.novelty_score * 100).toFixed(0) }}%</el-tag>
            </div>
          </div>
          <div class="push-item__actions">
            <el-button size="small" type="success" @click="classify(push, 'very_relevant')">很相关</el-button>
            <el-button size="small" type="primary" @click="classify(push, 'relevant')">相关</el-button>
            <el-button size="small" @click="classify(push, 'uncertain')">不确定</el-button>
            <el-button size="small" type="danger" text @click="dismiss(push)">忽略</el-button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { monitorApi } from '../../api/client'
import { ElMessage } from 'element-plus'

const props = defineProps<{ projectId: string }>()
const pushes = ref<any[]>([])
const expanded = ref(false)
const clearing = ref(false)

onMounted(loadPushes)

async function loadPushes() {
  try {
    const res = await monitorApi.getPushes(props.projectId)
    pushes.value = res.data.pushes || []
    if (pushes.value.length > 0) expanded.value = true
  } catch { /* ignore */ }
}

async function classify(push: any, bucket: string) {
  try {
    await monitorApi.classifyPush(props.projectId, push.push_id, { bucket })
    pushes.value = pushes.value.filter(p => p.push_id !== push.push_id)
    ElMessage.success(`已分类到「${bucket}」`)
  } catch {
    ElMessage.error('分类失败')
  }
}

async function dismiss(push: any) {
  try {
    await monitorApi.dismissPush(props.projectId, push.push_id)
    pushes.value = pushes.value.filter(p => p.push_id !== push.push_id)
  } catch {
    ElMessage.error('操作失败')
  }
}

async function clearAll() {
  clearing.value = true
  try {
    await monitorApi.clearPushes(props.projectId)
    pushes.value = []
    expanded.value = false
  } catch {
    ElMessage.error('清空失败')
  } finally {
    clearing.value = false
  }
}
</script>

<style scoped>
.push-banner {
  background: var(--signal-amber-bg);
  border: 1px solid var(--signal-amber-bg);
  border-radius: 8px;
  margin-bottom: 16px;
}
.push-banner__header {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 14px; cursor: pointer;
}
.push-banner__text { flex: 1; font-size: 14px; color: var(--signal-amber); }
.push-banner__arrow { font-size: 10px; color: var(--signal-amber); }
.push-banner__list { padding: 0 14px 14px; }
.push-item {
  display: flex; gap: 12px; align-items: flex-start;
  padding: 10px; margin-bottom: 8px;
  background: var(--paper); border-radius: 8px;
  border: 1px solid var(--ink-200);
}
.push-item__content { flex: 1; min-width: 0; }
.push-item__title { font-size: 13px; font-weight: 600; margin: 0 0 4px; }
.push-item__summary { font-size: 12px; color: var(--ink-400); margin: 0 0 6px; }
.push-item__meta { display: flex; gap: 4px; }
.push-item__actions { display: flex; flex-direction: column; gap: 4px; flex-shrink: 0; }
.slide-enter-active { transition: all 0.2s ease-out; }
.slide-leave-active { transition: all 0.15s ease-in; }
.slide-enter-from, .slide-leave-to { opacity: 0; max-height: 0; overflow: hidden; }
.slide-enter-to, .slide-leave-from { opacity: 1; max-height: 1000px; }
</style>
