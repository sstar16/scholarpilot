<template>
  <img
    v-if="url"
    :src="url"
    :alt="name || 'user'"
    class="user-avatar user-avatar--img"
    :style="{ width: `${size}px`, height: `${size}px` }"
  />
  <div
    v-else
    class="user-avatar user-avatar--initial"
    :style="{
      width: `${size}px`,
      height: `${size}px`,
      fontSize: `${Math.round(size * 0.42)}px`,
    }"
  >{{ initial }}</div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{ size?: number; name?: string; url?: string }>(),
  { size: 32, name: '', url: '' }
)

const initial = computed(() => {
  const n = (props.name || '').trim()
  if (!n) return '?'
  return n.charAt(0).toUpperCase()
})
</script>

<style scoped>
.user-avatar {
  flex-shrink: 0;
  border-radius: 50%;
  box-shadow: var(--shadow-xs);
}
.user-avatar--img {
  object-fit: cover;
  border: 1.5px solid rgba(20, 20, 20, 0.08);
}
.user-avatar--initial {
  background: linear-gradient(135deg, #c6ac57, var(--signal-teal));
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-family: var(--font-display);
  font-weight: 900;
}
</style>
