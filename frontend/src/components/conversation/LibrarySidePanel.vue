<template>
  <aside class="lib-side">
    <div class="lib-side__head">
      <span class="lib-side__title">文献库</span>
      <span class="lib-side__chip">共 {{ bucketStore.total }}</span>
    </div>

    <div class="lib-side__section">
      <div class="lib-side__label">分类桶</div>
      <div
        v-for="b in BUCKETS"
        :key="b.key"
        class="lib-bucket-row"
        :class="{ active: activeBucket === b.key }"
        :style="{
          background: activeBucket === b.key ? b.bg : 'transparent',
          color: activeBucket === b.key ? b.color : 'var(--ink-900)',
        }"
        @click="setActiveBucket(b.key)"
      >
        <span class="lib-bucket-dot" :style="{ background: b.color }" />
        <span class="lib-bucket-name">{{ b.label }}</span>
        <span
          class="lib-bucket-count"
          :style="{
            color: activeBucket === b.key ? b.color : 'var(--ink-400)',
            fontWeight: activeBucket === b.key ? 700 : 400,
          }"
        >{{ bucketStore.counts[b.key] || 0 }}</span>
      </div>
    </div>

    <div v-if="recentDocs.length" class="lib-side__section">
      <div class="lib-side__label lib-side__label--split">
        <span>{{ activeBucketMeta.label }} · 最近</span>
        <span class="lib-side__all" @click="$emit('open-library')">全部 →</span>
      </div>
      <div
        v-for="(d, i) in recentDocs"
        :key="d.document_id"
        class="lib-mini-card"
        :style="{ animationDelay: `${0.6 + i * 0.08}s` }"
        @click="$emit('view-doc', d)"
      >
        <div v-if="d.one_line_summary" class="lib-mini-card__sum">
          {{ d.one_line_summary }}
        </div>
        <div class="lib-mini-card__title">{{ d.title }}</div>
        <div class="lib-mini-card__meta">
          <span>{{ d.source }}</span>
          <span v-if="d.agent_score != null">
            · <b>{{ Number(d.agent_score).toFixed(1) }}</b>
          </span>
        </div>
      </div>
    </div>

    <div v-else-if="bucketStore.total === 0" class="lib-empty">
      <div class="lib-empty__icon">📚</div>
      <div class="lib-empty__title">还没有文献</div>
      <div class="lib-empty__sub">在对话里发起检索，文献会流入这里</div>
    </div>
    <div v-else class="lib-empty lib-empty--small">
      <div class="lib-empty__sub">「{{ activeBucketMeta.label }}」桶暂无文献，试试其他桶</div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useBucketStore, type BucketName, type BucketDoc } from '../../stores/bucket'

const props = defineProps<{ projectId: string }>()

defineEmits<{
  'view-doc': [doc: BucketDoc]
  'open-library': []
}>()

const bucketStore = useBucketStore()

type BucketMeta = { key: BucketName; label: string; color: string; bg: string }

const BUCKETS: BucketMeta[] = [
  { key: 'very_relevant', label: '核心', color: 'var(--signal-emerald)', bg: 'var(--signal-emerald-bg)' },
  { key: 'relevant',      label: '相关', color: 'var(--signal-blue)',    bg: 'var(--signal-blue-bg)' },
  { key: 'uncertain',     label: '待定', color: 'var(--signal-amber)',   bg: 'var(--signal-amber-bg)' },
  { key: 'irrelevant',    label: '排除', color: 'var(--ink-300)',        bg: 'var(--paper-hover)' },
]

const activeBucket = ref<BucketName>('very_relevant')

function setActiveBucket(k: BucketName) { activeBucket.value = k }

const activeBucketMeta = computed(() =>
  BUCKETS.find((b) => b.key === activeBucket.value) ?? BUCKETS[0]
)

const recentDocs = computed<BucketDoc[]>(() => {
  const arr = bucketStore.buckets[activeBucket.value] ?? []
  // 按 classified_at 倒序取最多 5 篇
  return [...arr]
    .sort((a, b) => new Date(b.classified_at).getTime() - new Date(a.classified_at).getTime())
    .slice(0, 5)
})

onMounted(() => {
  if (props.projectId && bucketStore.total === 0) {
    bucketStore.fetchBuckets(props.projectId).catch(() => {})
  }
})
</script>

<style scoped>
.lib-side {
  width: 300px;
  flex-shrink: 0;
  border-left: 1px solid var(--ink-100);
  background: var(--paper-cool);
  overflow-y: auto;
  animation: lib-slide-in 0.6s 0.3s both var(--ease-out);
  display: flex;
  flex-direction: column;
}

.lib-side__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid var(--ink-100);
}
.lib-side__title {
  font-family: var(--font-display);
  font-size: var(--type-sub-size);
  font-weight: 700;
  color: var(--ink-700);
}
.lib-side__chip {
  font-family: var(--font-mono);
  font-size: var(--type-micro-size);
  padding: 2px 10px;
  border-radius: var(--radius-sm);
  background: var(--paper-hover);
  color: var(--ink-500);
  border: 1px solid var(--ink-100);
}

.lib-side__section {
  padding: 14px 18px;
  border-bottom: 1px solid var(--ink-100);
}
.lib-side__section:last-child { border-bottom: none; }

.lib-side__label {
  font-family: var(--font-mono);
  font-size: var(--type-micro-size);
  font-weight: 700;
  color: var(--ink-400);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  margin-bottom: 10px;
}
.lib-side__label--split {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.lib-side__all {
  font-weight: 400;
  color: var(--signal-blue);
  cursor: pointer;
  letter-spacing: 0;
  text-transform: none;
  transition: color var(--duration-fast) var(--ease-out);
}
.lib-side__all:hover { color: var(--signal-blue-light); }

/* ── Bucket rows ── */
.lib-bucket-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 7px 10px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  font-size: var(--type-sub-size);
  margin-bottom: 2px;
  transition: background var(--duration-fast) var(--ease-out);
}
.lib-bucket-row:hover {
  background: var(--paper-hover) !important;
}
.lib-bucket-row.active:hover {
  /* active 态已有 bg，hover 时保持不变 */
}
.lib-bucket-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 4px;
  margin-right: 8px;
  flex-shrink: 0;
}
.lib-bucket-name { flex: 1; }
.lib-bucket-count {
  font-family: var(--font-mono);
  font-size: var(--type-meta-size);
}

/* ── Mini doc cards ── */
.lib-mini-card {
  padding: 10px 12px;
  border: 1px solid var(--ink-100);
  background: var(--paper);
  border-radius: var(--radius-sm);
  margin-bottom: 8px;
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
  animation: lib-fade-up 0.4s both var(--ease-out);
}
.lib-mini-card:hover {
  background: var(--paper-warm);
  box-shadow: var(--shadow-sm);
  border-color: var(--ink-200);
  transform: translateY(-1px);
}
.lib-mini-card__sum {
  font-size: var(--type-meta-size);
  color: var(--ink-700);
  line-height: 1.5;
  margin-bottom: 6px;
}
.lib-mini-card__title {
  font-size: 11.5px;
  font-weight: 600;
  color: var(--ink-900);
  line-height: 1.45;
  margin-bottom: 4px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.lib-mini-card__meta {
  font-size: 10.5px;
  color: var(--ink-400);
  font-family: var(--font-mono);
}
.lib-mini-card__meta b {
  color: var(--signal-teal);
  font-weight: 700;
}

/* ── Empty states ── */
.lib-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  text-align: center;
}
.lib-empty__icon {
  font-size: 32px;
  opacity: 0.5;
  margin-bottom: 10px;
}
.lib-empty__title {
  font-family: var(--font-display);
  font-size: var(--type-body-size);
  font-weight: 600;
  color: var(--ink-700);
  margin-bottom: 4px;
}
.lib-empty__sub {
  font-size: var(--type-meta-size);
  color: var(--ink-400);
  line-height: 1.5;
}
.lib-empty--small {
  padding: 14px 18px;
  flex: 0 0 auto;
}

@keyframes lib-slide-in {
  from { opacity: 0; transform: translateX(24px); }
  to { opacity: 1; transform: translateX(0); }
}
@keyframes lib-fade-up {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
