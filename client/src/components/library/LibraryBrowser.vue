<template>
  <div class="library-browser">
    <LibraryFilterBar
      :project-id="projectId"
      @back="$emit('back')"
      @rebuild="onRebuild"
    />

    <div class="body">
      <LibraryEmpty
        v-if="!store.loading && store.total === 0"
        :reason="emptyReason"
        :rebuilding="store.rebuilding"
        @rebuild="onRebuild"
      />
      <template v-else>
        <aside class="sidebar">
          <LibraryFileList :project-id="projectId" />
        </aside>
        <main class="main">
          <LibraryMarkdownViewer :project-id="projectId" />
        </main>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import LibraryFilterBar from './LibraryFilterBar.vue'
import LibraryFileList from './LibraryFileList.vue'
import LibraryMarkdownViewer from './LibraryMarkdownViewer.vue'
import LibraryEmpty from './LibraryEmpty.vue'
import { useLibraryStore } from '../../stores/library'

const props = defineProps<{
  projectId: string
}>()

defineEmits<{ (e: 'back'): void }>()

const store = useLibraryStore()
const route = useRoute()
const router = useRouter()

const emptyReason = computed<'no_round' | 'not_built' | 'error'>(() => {
  // S1 刻意简化: 都显示 not_built 提示, 让用户点 Rebuild 即可.
  // 未来可从 project 的 current_round 判断 no_round vs not_built.
  return 'not_built'
})

async function onRebuild() {
  await store.triggerRebuild(props.projectId)
  ElMessage.success('文献库重建中,请稍候刷新')
}

// 初次加载 + 根据 URL query.slug 自动打开
onMounted(async () => {
  await store.loadFiles(props.projectId)
  const slugFromUrl = route.query.slug as string | undefined
  if (slugFromUrl && store.files.some((f) => f.slug === slugFromUrl)) {
    await store.selectFile(props.projectId, slugFromUrl)
  }
})

// 监听 query.slug 变化 (例如 wiki-link 点击导致)
watch(
  () => route.query.slug,
  async (newSlug) => {
    if (
      typeof newSlug === 'string' &&
      newSlug &&
      newSlug !== store.selectedSlug
    ) {
      await store.selectFile(props.projectId, newSlug)
    }
  }
)

// 选中 slug 变化时 → 写回 URL
watch(
  () => store.selectedSlug,
  (slug) => {
    if (slug && route.query.slug !== slug) {
      router.replace({ query: { ...route.query, slug } })
    }
  }
)
</script>

<style scoped>
.library-browser {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--paper);
}
.body {
  flex: 1;
  display: flex;
  overflow: hidden;
}
.sidebar {
  width: 340px;
  min-width: 280px;
  max-width: 420px;
  border-right: 1px solid var(--ink-100);
  background: var(--paper-cool);
  overflow: hidden;
}
.main {
  flex: 1;
  overflow: hidden;
}
</style>
