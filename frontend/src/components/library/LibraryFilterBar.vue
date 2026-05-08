<template>
  <div class="library-filter-bar">
    <el-button link @click="$emit('back')">
      <el-icon><ArrowLeft /></el-icon>
      返回对话
    </el-button>
    <h3 class="title">文献库 ({{ store.total }})</h3>
    <el-radio-group v-model="bucketFilter" size="small" class="bucket-filter">
      <el-radio-button value="all">全部</el-radio-button>
      <el-radio-button value="very_relevant">
        极相关 ({{ store.byBucket.very_relevant || 0 }})
      </el-radio-button>
      <el-radio-button value="relevant">
        相关 ({{ store.byBucket.relevant || 0 }})
      </el-radio-button>
      <el-radio-button value="uncertain">
        不确定 ({{ store.byBucket.uncertain || 0 }})
      </el-radio-button>
    </el-radio-group>
    <el-input
      v-model="searchText"
      placeholder="搜索标题/作者"
      size="small"
      clearable
      class="search-input"
    >
      <template #prefix>
        <el-icon><Search /></el-icon>
      </template>
    </el-input>
    <el-button size="small" :loading="store.rebuilding" @click="$emit('rebuild')">
      <el-icon><Refresh /></el-icon>
      Rebuild
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ArrowLeft, Search, Refresh } from '@element-plus/icons-vue'
import { useLibraryStore } from '../../stores/library'

const store = useLibraryStore()

defineEmits<{
  (e: 'back'): void
  (e: 'rebuild'): void
}>()

const bucketFilter = computed({
  get: () => store.filter.bucket,
  set: (v: string) => store.setFilter({ bucket: v }),
})

const searchText = computed({
  get: () => store.filter.search,
  set: (v: string) => store.setFilter({ search: v }),
})
</script>

<style scoped>
.library-filter-bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: 10px var(--space-4);
  border-bottom: 1px solid var(--ink-100);
  background: var(--paper);
}
.library-filter-bar .title {
  margin: 0;
  font-family: var(--font-display);
  font-size: 16px;
  font-weight: 700;
  color: var(--ink-900);
}
.library-filter-bar .bucket-filter {
  margin-left: 16px;
}
.library-filter-bar .search-input {
  flex: 1;
  max-width: 280px;
  margin-left: auto;
}
</style>
