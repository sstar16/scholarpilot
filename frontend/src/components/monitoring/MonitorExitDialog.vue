<template>
  <el-dialog v-model="visible" title="退出项目" width="460px" :close-on-click-modal="false">
    <div class="exit-options">
      <div
        class="exit-option"
        :class="{ 'exit-option--selected': choice === 'direct' }"
        @click="choice = 'direct'"
      >
        <el-icon :size="28" color="#909399"><SwitchButton /></el-icon>
        <div class="exit-option__text">
          <div class="exit-option__name">直接退出</div>
          <div class="exit-option__desc">项目保持活跃状态，下次可继续操作</div>
        </div>
      </div>

      <div
        class="exit-option"
        :class="{ 'exit-option--selected': choice === 'monitor' }"
        @click="choice = 'monitor'"
      >
        <el-icon :size="28" color="#0d9488"><Bell /></el-icon>
        <div class="exit-option__text">
          <div class="exit-option__name">退出并开启监控</div>
          <div class="exit-option__desc">AI 每天搜索新文献，有新发现时通知您</div>
        </div>
      </div>
    </div>

    <!-- Monitor config (only when monitor selected) -->
    <div v-if="choice === 'monitor'" class="monitor-config">
      <el-divider content-position="left">监控配置</el-divider>

      <el-form label-position="left" label-width="100px" size="default">
        <el-form-item label="推送时间">
          <el-time-select
            v-model="config.schedule"
            start="06:00"
            end="22:00"
            step="01:00"
            placeholder="选择每天推送时间"
          />
        </el-form-item>

        <el-form-item label="新颖度阈值">
          <el-slider v-model="config.noveltyThreshold" :min="0.1" :max="1.0" :step="0.1" show-stops />
          <span class="config-hint">越高越严格，仅推送最新颖的发现</span>
        </el-form-item>

        <el-form-item label="每日上限">
          <el-input-number v-model="config.maxPerDay" :min="1" :max="50" />
        </el-form-item>
      </el-form>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="handleConfirm" :loading="loading">
        {{ choice === 'monitor' ? '开启监控并退出' : '退出项目' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { monitorApi } from '../../api/client'
import { ElMessage } from 'element-plus'

const props = defineProps<{ projectId: string }>()
const visible = defineModel<boolean>('visible', { default: false })
const router = useRouter()
const loading = ref(false)
const choice = ref<'direct' | 'monitor'>('direct')

const config = reactive({
  schedule: '08:00',
  noveltyThreshold: 0.6,
  maxPerDay: 10,
})

async function handleConfirm() {
  loading.value = true
  try {
    if (choice.value === 'monitor') {
      await monitorApi.enable(props.projectId, {
        schedule: 'daily',
      })
      await monitorApi.update(props.projectId, {
        novelty_threshold: config.noveltyThreshold,
        push_config: {
          schedule_time: config.schedule,
          max_per_day: config.maxPerDay,
        },
      })
      ElMessage.success('监控已开启，将每天为您推送新发现')
    }
    visible.value = false
    router.push('/dashboard')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.exit-options { display: flex; flex-direction: column; gap: 12px; }
.exit-option {
  display: flex; align-items: center; gap: 14px;
  padding: 16px; border: 2px solid #ebeef5; border-radius: 10px;
  cursor: pointer; transition: all 0.2s;
}
.exit-option:hover { border-color: #c0c4cc; }
.exit-option--selected { border-color: #409eff; background: #ecf5ff; }
.exit-option__name { font-size: 15px; font-weight: 600; }
.exit-option__desc { font-size: 12px; color: #909399; margin-top: 2px; }
.monitor-config { margin-top: 16px; }
.config-hint { font-size: 11px; color: #c0c4cc; margin-left: 8px; }
</style>
