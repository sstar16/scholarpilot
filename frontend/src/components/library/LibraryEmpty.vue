<template>
  <div class="library-empty">
    <el-icon :size="60" color="#cbd5e1"><FolderOpened /></el-icon>
    <h3>{{ titleText }}</h3>
    <p class="sub">{{ subText }}</p>
    <el-button
      v-if="reason === 'not_built'"
      type="primary"
      :loading="rebuilding"
      @click="$emit('rebuild')"
    >
      立即构建
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { FolderOpened } from '@element-plus/icons-vue'

const props = defineProps<{
  reason: 'no_round' | 'not_built' | 'error'
  rebuilding: boolean
}>()

defineEmits<{ (e: 'rebuild'): void }>()

const titleText = computed(() => {
  if (props.reason === 'no_round') return '还没有文献'
  if (props.reason === 'not_built') return '文献库未生成'
  return '加载失败'
})

const subText = computed(() => {
  if (props.reason === 'no_round') return '先去对话里启动一次检索收集文献'
  if (props.reason === 'not_built') return '点下面的按钮从已有文献生成 markdown 卡片'
  return '请检查后端日志'
})
</script>

<style scoped>
.library-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px var(--space-5);
  color: var(--ink-400);
  text-align: center;
  width: 100%;
}
.library-empty h3 {
  margin: var(--space-4) 0 var(--space-2);
  font-family: var(--font-display);
  color: var(--ink-700);
}
.library-empty .sub {
  margin: 0 0 var(--space-5);
  font-size: var(--type-sub-size);
  color: var(--ink-300);
}
</style>
