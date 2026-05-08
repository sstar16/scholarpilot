<template>
  <div class="library-file-list">
    <!-- P1: 顶部批量操作 toolbar，选中 > 0 时出现 -->
    <div v-if="store.selectedSlugs.size > 0" class="batch-toolbar">
      <span class="batch-count">已选 {{ store.selectedSlugs.size }} / {{ totalVisible }} 项</span>
      <el-button size="small" text @click="store.clearSelection()">清除</el-button>
      <el-button
        size="small"
        type="danger"
        plain
        :loading="store.deleting"
        @click="onBatchDelete"
      >
        <el-icon><Delete /></el-icon>
        批量移除
      </el-button>
    </div>

    <template v-for="(items, bucket) in store.groupedFiles" :key="bucket">
      <div v-if="items.length" class="bucket-group">
        <h4 class="bucket-title">
          <el-checkbox
            :model-value="isBucketAllSelected(items)"
            :indeterminate="isBucketIndeterminate(items)"
            @change="(v: any) => toggleBucketSelect(items, !!v)"
          />
          <span class="bucket-name">{{ bucketLabel(bucket) }}</span>
          <span class="count">{{ items.length }}</span>
        </h4>
        <div
          v-for="f in items"
          :key="f.slug"
          class="file-card"
          :class="{
            active: store.selectedSlug === f.slug,
            selected: store.selectedSlugs.has(f.slug),
          }"
          @click="onSelect(f)"
        >
          <div class="card-row">
            <el-checkbox
              :model-value="store.selectedSlugs.has(f.slug)"
              @click.stop
              @change="() => store.toggleSelect(f.slug)"
            />
            <div class="card-main">
              <div class="title">{{ f.title_zh || f.title }}</div>
              <div class="meta">
                <span v-if="f.authors_short">{{ f.authors_short }}</span>
                <span v-if="f.year">· {{ f.year }}</span>
                <span v-if="f.quality_score != null" class="score">
                  · {{ Number(f.quality_score).toFixed(2) }}
                </span>
              </div>
              <!-- P1: 卡片操作按钮（hover 显示） -->
              <div class="card-actions">
                <el-tooltip v-if="f.url" content="打开原文网页" placement="top">
                  <a :href="f.url" target="_blank" rel="noopener" class="act-btn" @click.stop>
                    <el-icon><Link /></el-icon>
                    原文
                  </a>
                </el-tooltip>
                <el-tooltip v-if="f.pdf_url" content="打开 PDF（新窗口）" placement="top">
                  <a :href="f.pdf_url" target="_blank" rel="noopener" class="act-btn" @click.stop>
                    <el-icon><Document /></el-icon>
                    PDF
                  </a>
                </el-tooltip>
                <el-tooltip v-if="f.doi" content="复制 DOI" placement="top">
                  <button class="act-btn" @click.stop="copyDoi(f.doi!)">
                    <el-icon><CopyDocument /></el-icon>
                    DOI
                  </button>
                </el-tooltip>
                <el-tooltip content="从项目移除（仅本项目）" placement="top">
                  <button class="act-btn act-danger" @click.stop="onSingleDelete(f)">
                    <el-icon><Delete /></el-icon>
                  </button>
                </el-tooltip>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Delete, Link, Document, CopyDocument } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useLibraryStore } from '../../stores/library'
import type { LibraryFile } from '../../api/client'

const props = defineProps<{
  projectId: string
}>()

const store = useLibraryStore()

const BUCKET_LABELS: Record<string, string> = {
  very_relevant: '极相关',
  relevant: '相关',
  uncertain: '不确定',
  irrelevant: '不相关',
  uncategorized: '未分类',
}

function bucketLabel(key: string | number): string {
  return BUCKET_LABELS[String(key)] || String(key)
}

const totalVisible = computed(() => store.filteredFiles.length)

function isBucketAllSelected(items: LibraryFile[]): boolean {
  return items.length > 0 && items.every((f) => store.selectedSlugs.has(f.slug))
}
function isBucketIndeterminate(items: LibraryFile[]): boolean {
  const selected = items.filter((f) => store.selectedSlugs.has(f.slug)).length
  return selected > 0 && selected < items.length
}
function toggleBucketSelect(items: LibraryFile[], selectAll: boolean) {
  const next = new Set(store.selectedSlugs)
  for (const f of items) {
    if (selectAll) next.add(f.slug)
    else next.delete(f.slug)
  }
  store.selectedSlugs = next
}

async function onSelect(f: LibraryFile) {
  await store.selectFile(props.projectId, f.slug)
}

async function copyDoi(doi: string) {
  try {
    await navigator.clipboard.writeText(doi)
    ElMessage.success(`DOI 已复制：${doi}`)
  } catch {
    ElMessage.warning('复制失败，请手动选中')
  }
}

async function onSingleDelete(f: LibraryFile) {
  try {
    await ElMessageBox.confirm(
      `确认从本项目移除《${f.title_zh || f.title}》？\n（仅删除项目关联，全局文献库保留）`,
      '移除确认',
      { type: 'warning', confirmButtonText: '移除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  store.selectedSlugs = new Set([f.slug])
  const res = await store.deleteSelected(props.projectId)
  if (res.deleted > 0) ElMessage.success(`已移除 1 篇`)
  if (res.failed.length) ElMessage.warning(`${res.failed.length} 篇失败`)
}

async function onBatchDelete() {
  const n = store.selectedSlugs.size
  if (!n) return
  try {
    await ElMessageBox.confirm(
      `确认从本项目移除选中的 ${n} 篇文献？\n\n此操作会删除：\n· 项目的分类关联\n· 本项目所有检索轮关联\n· 反馈数据\n· 本项目 workspace 里的 md 文件\n\n（全局 Document 表保留，其他项目不受影响）`,
      '批量移除确认',
      {
        type: 'warning',
        confirmButtonText: `移除 ${n} 篇`,
        cancelButtonText: '取消',
        distinguishCancelAndClose: true,
      },
    )
  } catch {
    return
  }
  const res = await store.deleteSelected(props.projectId)
  if (res.deleted > 0) ElMessage.success(`已移除 ${res.deleted} 篇`)
  if (res.failed.length) ElMessage.warning(`${res.failed.length} 篇失败：${res.failed.join(', ')}`)
}
</script>

<style scoped>
.library-file-list {
  height: 100%;
  overflow-y: auto;
  padding: var(--space-2) 0;
}
.batch-toolbar {
  position: sticky;
  top: 0;
  z-index: 3;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  margin: 0 0 var(--space-2);
  background: var(--signal-coral-bg);
  border-bottom: 1px solid var(--signal-coral);
  font-size: var(--type-meta-size);
}
.batch-count { flex: 1; color: var(--signal-coral); font-weight: 500; }
.bucket-group { margin-bottom: var(--space-4); }
.bucket-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0 var(--space-3) var(--space-2);
  font-size: var(--type-meta-size);
  font-weight: 600;
  color: var(--ink-400);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.bucket-title .bucket-name { flex: 1; }
.bucket-title .count {
  padding: 2px var(--space-2);
  background: var(--ink-100);
  border-radius: var(--radius-full);
  font-size: var(--type-micro-size);
}
.file-card {
  margin: var(--space-1) var(--space-2);
  padding: 10px var(--space-3);
  border: 1px solid var(--ink-100);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}
.file-card:hover {
  border-color: var(--ink-300);
  background: var(--paper-warm);
}
.file-card:hover .card-actions { opacity: 1; }
.file-card.active {
  border-color: var(--signal-blue);
  background: var(--signal-blue-bg);
}
.file-card.selected {
  border-color: var(--signal-amber);
  background: var(--signal-amber-bg);
}
.card-row {
  display: flex;
  gap: var(--space-3);
  align-items: flex-start;
}
.card-main { flex: 1; min-width: 0; }
.file-card .title {
  font-family: var(--font-display);
  font-size: var(--type-body-size);
  font-weight: 600;
  color: var(--ink-900);
  line-height: 1.4;
  margin-bottom: var(--space-1);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.file-card .meta {
  font-size: var(--type-meta-size);
  color: var(--ink-400);
}
.file-card .meta .score {
  color: var(--signal-teal);
  font-family: var(--font-mono);
  font-weight: 600;
}

/* 卡片操作按钮 —— 默认半透明，hover 完全显示 */
.card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  margin-top: var(--space-2);
  opacity: 0.5;
  transition: opacity var(--duration-fast) var(--ease-out);
}
.act-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 3px var(--space-2);
  font-size: var(--type-micro-size);
  color: var(--ink-500);
  background: var(--paper-hover);
  border: 1px solid var(--ink-100);
  border-radius: var(--radius-full);
  cursor: pointer;
  text-decoration: none;
  font-family: inherit;
}
.act-btn:hover {
  background: var(--ink-100);
  color: var(--ink-900);
  border-color: var(--ink-200);
}
.act-btn.act-danger { color: var(--signal-coral); }
.act-btn.act-danger:hover {
  background: var(--signal-coral-bg);
  border-color: var(--signal-coral);
  color: var(--signal-coral);
}
</style>
