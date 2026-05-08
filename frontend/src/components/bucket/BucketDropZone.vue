<template>
  <div class="bucket-drop-zone">
    <span class="bz-label">分类到</span>
    <button
      v-for="b in bucketDefs"
      :key="b.key"
      class="bz-btn"
      :class="{ active: currentBucket === b.key }"
      :style="currentBucket === b.key ? { background: b.color + '18', borderColor: b.color + '50', color: b.color } : {}"
      :ref="el => { if (el) btnRefs[b.key] = el as HTMLElement }"
      @click="onPick(b.key)"
    >
      <span class="bz-dot" :style="{ background: b.color }"></span>
      {{ b.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import type { BucketName } from '../../stores/bucket'
import { flyTo, BUCKET_COLORS } from '../../composables/useFlyTo'

const props = defineProps<{
  docId: string
  currentBucket?: string | null
  cardEl?: HTMLElement
}>()

const emit = defineEmits<{
  (e: 'classify', bucket: BucketName): void
}>()

const btnRefs = reactive<Record<string, HTMLElement>>({})
const currentBucket = ref<string | null>(props.currentBucket || null)

watch(() => props.currentBucket, v => { currentBucket.value = v || null })

const bucketDefs = [
  { key: 'very_relevant' as BucketName, label: '很相关', color: '#0d9488' },
  { key: 'relevant' as BucketName, label: '相关', color: '#2563eb' },
  { key: 'uncertain' as BucketName, label: '不确定', color: '#64748b' },
  { key: 'irrelevant' as BucketName, label: '不相关', color: '#dc2626' },
]

function onPick(bucket: BucketName) {
  currentBucket.value = bucket

  // 飞入动画：从卡片飞向侧边栏中的目标桶
  if (props.cardEl) {
    const targetBucket = document.querySelector(`[data-bucket="${bucket}"]`)
    if (targetBucket) {
      flyTo(props.cardEl, targetBucket as HTMLElement, BUCKET_COLORS[bucket])
    }
  }

  emit('classify', bucket)
}
</script>

<style scoped>
.bucket-drop-zone {
  display: flex; align-items: center; gap: 8px;
  padding-top: 12px; border-top: 1px solid var(--ink-100, #e2e8f0);
}
.bz-label {
  font-size: 12px; font-weight: 500; color: var(--ink-400, #94a3b8);
  white-space: nowrap;
}
.bz-btn {
  display: flex; align-items: center; gap: 5px;
  padding: 5px 14px; border-radius: 20px;
  font-size: 12px; font-weight: 500; cursor: pointer;
  border: 1.5px solid var(--ink-200, #e2e8f0);
  background: var(--paper, #fff);
  color: var(--ink-500, #64748b);
  font-family: var(--font-body);
  transition: all 0.2s;
}
.bz-btn:hover {
  border-color: var(--ink-300); background: var(--paper-hover, #f8fafc);
  transform: translateY(-1px);
}
.bz-btn.active {
  font-weight: 700;
  box-shadow: 0 0 0 1px currentColor;
}
.bz-dot {
  width: 6px; height: 6px; border-radius: 50%;
}
</style>
