<template>
  <transition name="el-fade-in">
    <div v-if="plan" class="agent-plan">
      <div class="plan-header">
        <el-icon style="color: #6e40c9"><MagicStick /></el-icon>
        <span>AI Agent 策略</span>
      </div>
      <div class="plan-body">
        <p class="plan-rationale">{{ plan.rationale }}</p>
        <div class="plan-meta">
          <el-tag v-if="plan.year_range" size="small" effect="plain">
            {{ plan.year_range }}
          </el-tag>
          <el-tag v-if="plan.tools" size="small" type="success" effect="plain">
            {{ Array.isArray(plan.tools) ? plan.tools.length : plan.tools }} 个数据源
          </el-tag>
        </div>
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const plan = ref<{ rationale: string; tools: any; year_range: string } | null>(null)

function setPlan(data: any) {
  plan.value = data
}

function reset() {
  plan.value = null
}

defineExpose({ setPlan, reset })
</script>

<style scoped>
.agent-plan {
  background: linear-gradient(135deg, #f3f0ff, #ede9fe);
  border: 1px solid #d8b4fe; border-radius: 8px;
  padding: 16px; margin-bottom: 16px;
  animation: slideIn 0.4s ease-out;
}
.plan-header {
  display: flex; align-items: center; gap: 8px;
  font-size: 14px; font-weight: 600; color: #6e40c9;
  margin-bottom: 8px;
}
.plan-rationale { font-size: 13px; color: #4c1d95; margin: 0 0 8px; line-height: 1.5; }
.plan-meta { display: flex; gap: 8px; }
@keyframes slideIn {
  from { opacity: 0; transform: translateY(-10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
