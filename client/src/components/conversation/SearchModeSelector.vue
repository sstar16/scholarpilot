<template>
  <div class="mode-selector">
    <div class="mode-selector__title">选择检索模式</div>
    <div class="mode-selector__cards">
      <div
        v-for="mode in modes"
        :key="mode.value"
        class="mode-card"
        :class="{ 'mode-card--selected': selected === mode.value }"
        @click="selected = mode.value"
      >
        <el-icon :size="28" :color="mode.color"><component :is="mode.icon" /></el-icon>
        <div class="mode-card__name">{{ mode.name }}</div>
        <div class="mode-card__desc">{{ mode.desc }}</div>
      </div>
    </div>
    <el-button
      type="primary"
      @click="handleSelect"
      :disabled="!selected"
      style="width: 100%; margin-top: 12px"
    >
      确认选择
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { ref, markRaw } from 'vue'
import { Coin, Cloudy, SetUp } from '@element-plus/icons-vue'

const emit = defineEmits<{ select: [mode: string] }>()
const selected = ref<string>('hybrid')

const modes = [
  {
    value: 'static_db',
    name: '静态知识库',
    desc: '从本地知识库推荐，速度快（<1s），无 API 消耗',
    icon: markRaw(Coin),
    color: '#67c23a',
  },
  {
    value: 'api',
    name: 'API 实时检索',
    desc: '搜索最新数据，覆盖广，消耗 API 额度',
    icon: markRaw(Cloudy),
    color: '#409eff',
  },
  {
    value: 'hybrid',
    name: '混合检索',
    desc: '两者结合，先展示本地结果，API 结果流式追加（推荐）',
    icon: markRaw(SetUp),
    color: '#e6a23c',
  },
]

function handleSelect() {
  if (selected.value) {
    emit('select', selected.value)
  }
}
</script>

<style scoped>
.mode-selector { margin: 12px 0; }
.mode-selector__title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 12px;
}
.mode-selector__cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
.mode-card {
  border: 2px solid #ebeef5;
  border-radius: 10px;
  padding: 16px 12px;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
}
.mode-card:hover { border-color: #c0c4cc; }
.mode-card--selected {
  border-color: #409eff;
  background: #ecf5ff;
}
.mode-card__name {
  font-size: 14px;
  font-weight: 600;
  margin: 8px 0 4px;
}
.mode-card__desc {
  font-size: 12px;
  color: #909399;
  line-height: 1.4;
}
</style>
