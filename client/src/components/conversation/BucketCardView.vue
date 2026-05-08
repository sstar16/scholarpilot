<template>
  <div class="bucket-card-view">
    <!-- Filter pills -->
    <div class="bcv-filter">
      <span class="bcv-filter__label">筛选桶</span>
      <button
        class="bcv-pill"
        :class="{ 'is-on': filter === 'all' }"
        @click="filter = 'all'"
      >
        全部
        <span class="bcv-pill__count bcv-pill__count--ghost">{{ bucketStore.total }}</span>
      </button>
      <button
        v-for="b in BUCKETS"
        :key="b.key"
        class="bcv-pill"
        :class="{ 'is-on': filter === b.key }"
        :style="filter === b.key ? { background: b.bg, color: b.color, borderColor: b.color } : {}"
        @click="filter = b.key"
      >
        <span class="bcv-pill__dot" :style="{ background: b.color }" />
        {{ b.label }}
        <span
          class="bcv-pill__count"
          :style="{ background: b.color, color: '#fff' }"
        >{{ bucketStore.counts[b.key] || 0 }}</span>
      </button>
      <div class="bcv-filter__spacer" />
      <span class="bcv-filter__stat">显示 {{ visibleCount }} 篇</span>
    </div>

    <!-- Empty state -->
    <div v-if="bucketStore.total === 0" class="bcv-empty">
      <div class="bcv-empty__glyph">⊞</div>
      <div class="bcv-empty__title">还没有文献</div>
      <div class="bcv-empty__sub">在对话里发起检索，文献会按桶分组展示在这里</div>
    </div>

    <!-- Filter = all: grouped sections -->
    <template v-else-if="filter === 'all'">
      <div
        v-for="b in nonEmptyBuckets"
        :key="b.key"
        class="bcv-section"
      >
        <div class="bcv-section__head" :style="{ borderBottom: `2px solid ${b.color}33` }">
          <span class="bcv-section__dot" :style="{ background: b.color }" />
          <h3 class="bcv-section__title" :style="{ color: b.color }">{{ b.label }}</h3>
          <span class="bcv-section__count">{{ bucketStore.buckets[b.key].length }} 篇</span>
        </div>
        <div class="bcv-grid">
          <DocCardItem
            v-for="(d, i) in bucketStore.buckets[b.key]"
            :key="d.document_id"
            v-memo="[d.document_id, d.bucket, b.key]"
            :doc="d"
            :bucket-meta="b"
            :style="{ animationDelay: `${Math.min(i, 30) * 0.03}s` }"
            @click="$emit('view-doc', d)"
          />
        </div>
      </div>
    </template>

    <!-- Single bucket -->
    <template v-else-if="filteredDocs.length">
      <div class="bcv-grid">
        <DocCardItem
          v-for="(d, i) in filteredDocs"
          :key="d.document_id"
          v-memo="[d.document_id, d.bucket, currentBucketMeta?.key]"
          :doc="d"
          :bucket-meta="(currentBucketMeta as BucketMeta)"
          :style="{ animationDelay: `${Math.min(i, 30) * 0.03}s` }"
          @click="$emit('view-doc', d)"
        />
      </div>
    </template>
    <div v-else class="bcv-empty bcv-empty--small">
      <div class="bcv-empty__sub">「{{ currentBucketMeta?.label }}」桶暂无文献</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useBucketStore, type BucketName, type BucketDoc } from '../../stores/bucket'
import DocCardItem from './BucketCardItem.vue'

defineProps<{ projectId: string }>()
defineEmits<{ 'view-doc': [doc: BucketDoc] }>()

const bucketStore = useBucketStore()

type BucketMeta = { key: BucketName; label: string; color: string; bg: string }

const BUCKETS: BucketMeta[] = [
  { key: 'very_relevant', label: '核心', color: 'var(--signal-emerald)', bg: 'var(--signal-emerald-bg)' },
  { key: 'relevant',      label: '相关', color: 'var(--signal-blue)',    bg: 'var(--signal-blue-bg)' },
  { key: 'uncertain',     label: '待定', color: 'var(--signal-amber)',   bg: 'var(--signal-amber-bg)' },
  { key: 'irrelevant',    label: '排除', color: 'var(--ink-300)',        bg: 'var(--paper-hover)' },
]

const filter = ref<'all' | BucketName>('all')

const nonEmptyBuckets = computed(() =>
  BUCKETS.filter((b) => (bucketStore.buckets[b.key]?.length ?? 0) > 0)
)

const filteredDocs = computed<BucketDoc[]>(() => {
  if (filter.value === 'all') return []
  return bucketStore.buckets[filter.value] ?? []
})

const currentBucketMeta = computed<BucketMeta | undefined>(() =>
  filter.value === 'all' ? undefined : BUCKETS.find((b) => b.key === filter.value)
)

const visibleCount = computed(() =>
  filter.value === 'all' ? bucketStore.total : filteredDocs.value.length
)
</script>

<style scoped>
.bucket-card-view {
  flex: 1;
  overflow-y: auto;
  background: var(--paper-cool);
  padding: 20px 28px 32px;
  animation: bcv-fade-up var(--duration-slow) var(--ease-out) both;
}

/* ── Filter ── */
.bcv-filter {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: 18px;
  flex-wrap: wrap;
}
.bcv-filter__label {
  font-size: var(--type-meta-size);
  color: var(--ink-500);
  font-weight: 600;
  margin-right: var(--space-1);
}
.bcv-filter__spacer { flex: 1; }
.bcv-filter__stat {
  font-family: var(--font-mono);
  font-size: var(--type-meta-size);
  color: var(--ink-400);
}

.bcv-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--paper);
  color: var(--ink-400);
  border: 1px solid var(--ink-100);
  border-radius: var(--radius-full);
  font-family: inherit;
  font-size: var(--type-meta-size);
  font-weight: 600;
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}
.bcv-pill:hover {
  border-color: var(--ink-200);
  color: var(--ink-700);
}
.bcv-pill__dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 4px;
}
.bcv-pill__count {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: var(--radius-full);
  background: var(--paper-hover);
  color: var(--ink-500);
  font-weight: 700;
  margin-left: var(--space-1);
}
.bcv-pill__count--ghost {
  background: var(--paper-hover);
  color: var(--ink-500);
}

/* ── Section head ── */
.bcv-section { margin-bottom: 28px; }
.bcv-section__head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 10px;
  padding-bottom: 6px;
}
.bcv-section__dot {
  width: 8px;
  height: 8px;
  border-radius: 4px;
  align-self: center;
}
.bcv-section__title {
  margin: 0;
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 900;
  letter-spacing: -0.2px;
}
.bcv-section__count {
  font-family: var(--font-mono);
  font-size: var(--type-micro-size);
  color: var(--ink-300);
}

/* ── Grid ── */
.bcv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
}

/* ── Empty ── */
.bcv-empty {
  margin: 60px auto;
  max-width: 480px;
  padding: 48px 24px;
  text-align: center;
  border: 1px dashed var(--ink-200);
  background: var(--paper);
  border-radius: var(--radius-md);
}
.bcv-empty--small { margin: 20px 0; padding: 20px; }
.bcv-empty__glyph {
  font-size: 48px;
  color: var(--ink-200);
  margin-bottom: 12px;
  line-height: 1;
}
.bcv-empty__title {
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  color: var(--ink-700);
  margin-bottom: 6px;
}
.bcv-empty__sub {
  font-size: var(--type-sub-size);
  color: var(--ink-400);
  line-height: 1.5;
}

@keyframes bcv-fade-up {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
