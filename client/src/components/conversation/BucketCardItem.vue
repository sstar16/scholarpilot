<template>
  <div class="bci" @click="$emit('click')">
    <!-- Left binding strip (期刊装订) -->
    <div class="bci__bind" :style="{ background: bucketMeta.color }" />

    <div class="bci__inner">
      <!-- Meta row -->
      <div class="bci__meta">
        <span
          class="bci__badge bci__badge--bucket"
          :style="{ background: bucketMeta.bg, color: bucketMeta.color }"
        >{{ bucketMeta.label.toUpperCase() }}</span>
        <span class="bci__badge bci__badge--src">{{ doc.source }}</span>
        <span class="bci__badge bci__badge--src" v-if="doc.agent_score != null">
          AI {{ Number(doc.agent_score).toFixed(1) }}
        </span>
        <div class="bci__spacer" />
        <span v-if="classifiedDate" class="bci__date">{{ classifiedDate }}</span>
      </div>

      <!-- One-line summary (teal highlight) -->
      <div v-if="doc.one_line_summary" class="bci__summary">
        {{ doc.one_line_summary }}
      </div>

      <!-- Title -->
      <h4 class="bci__title">{{ doc.title }}</h4>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { BucketDoc, BucketName } from '../../stores/bucket'

const props = defineProps<{
  doc: BucketDoc
  bucketMeta: { key: BucketName; label: string; color: string; bg: string }
}>()

defineEmits<{ click: [] }>()

const classifiedDate = computed(() => {
  if (!props.doc.classified_at) return ''
  const d = new Date(props.doc.classified_at)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getMonth() + 1}月${d.getDate()}日`
})
</script>

<style scoped>
.bci {
  background: var(--paper);
  border: 1px solid var(--ink-100);
  border-radius: var(--radius-md);
  overflow: hidden;
  cursor: pointer;
  display: flex;
  transition: all var(--duration-normal) var(--ease-out);
  animation: bci-fade-up var(--duration-slow) var(--ease-out) both;
}
.bci:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 30px -10px rgba(0, 0, 0, 0.12);
  border-color: var(--ink-200);
}

.bci__bind {
  width: 4px;
  flex-shrink: 0;
}

.bci__inner {
  flex: 1;
  padding: 14px 16px;
  min-width: 0;
}

.bci__meta {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: var(--space-2);
  flex-wrap: wrap;
}
.bci__spacer { flex: 1; }
.bci__badge {
  font-family: var(--font-mono);
  font-size: 9.5px;
  padding: 2px 7px;
  border-radius: var(--radius-full);
  font-weight: 800;
  letter-spacing: 0.06em;
}
.bci__badge--src {
  background: var(--paper-hover);
  color: var(--ink-500);
  font-weight: 600;
}
.bci__date {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--ink-300);
  flex-shrink: 0;
}

.bci__summary {
  font-size: var(--type-meta-size);
  color: var(--signal-teal);
  background: var(--signal-teal-bg);
  padding: 5px 9px;
  border-radius: var(--radius-sm);
  line-height: 1.5;
  margin-bottom: var(--space-2);
  font-weight: 500;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.bci__title {
  margin: 0;
  font-family: var(--font-display);
  font-size: 14.5px;
  font-weight: 700;
  line-height: 1.4;
  color: var(--ink-900);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

@keyframes bci-fade-up {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
