<template>
  <div class="pef" :style="{ animationDelay: `${0.15 + idx * 0.05}s` }">
    <div class="pef__num">§{{ String(idx).padStart(2, '0') }}</div>
    <div class="pef__body">
      <div class="pef__label">{{ label }}</div>
      <input
        v-if="editing"
        ref="inputEl"
        v-model="localVal"
        class="pef__input"
        :class="{ 'pef__input--mono': mono }"
        @keydown.enter.prevent="save"
        @keydown.escape="cancel"
      />
      <div
        v-else
        class="pef__value"
        :class="{ 'pef__value--mono': mono, 'pef__value--empty': !value }"
      >{{ value || '— 未填写 —' }}</div>
      <div class="pef__sub">{{ sub }}</div>
    </div>
    <div class="pef__actions">
      <template v-if="editing">
        <button class="pef-btn pef-btn--ghost" @click="cancel">取消</button>
        <button class="pef-btn pef-btn--primary" @click="save">保存</button>
      </template>
      <button v-else class="pef-btn pef-btn--outline" @click="startEdit">编辑</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue'

const props = defineProps<{
  label: string
  sub: string
  value: string
  mono?: boolean
  idx: number
}>()

const emit = defineEmits<{ save: [v: string] }>()

const editing = ref(false)
const localVal = ref(props.value)
const inputEl = ref<HTMLInputElement | null>(null)

async function startEdit() {
  localVal.value = props.value
  editing.value = true
  await nextTick()
  inputEl.value?.focus()
}

function cancel() {
  localVal.value = props.value
  editing.value = false
}

function save() {
  const v = localVal.value.trim()
  emit('save', v)
  editing.value = false
}
</script>

<style scoped>
.pef {
  display: grid;
  grid-template-columns: 110px 1fr auto;
  gap: 24px;
  align-items: center;
  padding: 20px 0;
  border-bottom: 1px solid rgba(20, 20, 20, 0.1);
  animation: pef-fade 0.4s var(--ease-spring) both;
}
.pef__num {
  font-family: var(--font-mono);
  font-size: 10px;
  color: rgba(20, 20, 20, 0.55);
  letter-spacing: 0.25em;
}
.pef__body { min-width: 0; }
.pef__label {
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 800;
  letter-spacing: -0.2px;
  margin-bottom: 4px;
}
.pef__value {
  font-family: var(--font-display);
  font-size: 16px;
  color: rgba(20, 20, 20, 0.85);
  font-style: italic;
  word-break: break-all;
}
.pef__value--mono {
  font-family: var(--font-mono);
  font-size: 14px;
  font-style: normal;
  color: rgba(20, 20, 20, 0.85);
}
.pef__value--empty {
  color: rgba(20, 20, 20, 0.35);
  font-style: italic;
}
.pef__input {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--ink-950);
  background: #fff;
  outline: none;
  font-family: inherit;
  font-size: 14px;
  color: var(--ink-950);
  box-sizing: border-box;
}
.pef__input--mono {
  font-family: var(--font-mono);
  font-size: 13px;
}
.pef__sub {
  font-size: 11.5px;
  color: rgba(20, 20, 20, 0.5);
  font-style: italic;
  font-family: var(--font-display);
  margin-top: 5px;
}
.pef__actions {
  display: flex;
  gap: 8px;
}

.pef-btn {
  padding: 8px 16px;
  border: 1px solid;
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.2em;
  cursor: pointer;
  font-weight: 700;
  transition: all var(--duration-fast) var(--ease-out);
}
.pef-btn--primary {
  background: var(--ink-950);
  color: var(--paper-warm);
  border-color: var(--ink-950);
}
.pef-btn--ghost {
  background: transparent;
  color: var(--ink-950);
  border-color: rgba(20, 20, 20, 0.2);
}
.pef-btn--ghost:hover {
  background: var(--ink-950);
  color: var(--paper-warm);
}
.pef-btn--outline {
  background: transparent;
  color: rgba(20, 20, 20, 0.55);
  border-color: rgba(20, 20, 20, 0.15);
}
.pef-btn--outline:hover {
  background: var(--ink-950);
  color: var(--paper-warm);
  border-color: var(--ink-950);
}

@keyframes pef-fade {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 900px) {
  .pef {
    grid-template-columns: 40px 1fr;
    gap: 14px;
  }
  .pef__actions {
    grid-column: 2;
    justify-self: start;
  }
}
</style>
