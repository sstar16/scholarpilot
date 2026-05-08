<template>
  <div class="chat-composer" :class="{ 'is-sending': isSending }">
    <el-input
      v-model="inputText"
      :placeholder="placeholder"
      :disabled="disabled"
      @keydown.enter.exact="handleSend"
      size="large"
      clearable
    >
      <template #append>
        <el-button
          :icon="Promotion"
          class="chat-send-btn"
          :class="{ 'is-pulsing': isSending }"
          @click="handleSend"
          :disabled="!inputText.trim() || disabled"
        />
      </template>
    </el-input>
    <div class="chat-composer__hints">
      <span v-if="busy" class="hint-busy">⏳ 检索进行中，等待本轮结束后再继续对话</span>
      <span v-else-if="confirming">Enter 确认 / Esc 取消 / 输入文字补充</span>
      <span v-else>Enter 发送</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Promotion } from '@element-plus/icons-vue'

const props = defineProps<{
  /** 输入框 + 发送按钮统一 disabled 开关（AI 思考中 / 检索中等综合态由父组件计算） */
  disabled: boolean
  /** 输入框 placeholder 文案 */
  placeholder: string
  /** 显示"检索进行中"忙碌提示 */
  busy: boolean
  /** 显示"Enter 确认 / Esc 取消"提示（confirmation 阶段） */
  confirming: boolean
}>()

const emit = defineEmits<{
  send: [text: string]
}>()

const inputText = ref('')
const isSending = ref(false)

function handleSend() {
  const text = inputText.value.trim()
  if (!text || props.disabled) return
  // 触发发送脉冲（按钮 pop + 输入闪烁 + halo ripple）
  isSending.value = true
  setTimeout(() => { isSending.value = false }, 420)
  inputText.value = ''
  emit('send', text)
}
</script>

<style scoped>
.chat-composer {
  border-top: 1px solid rgba(20, 20, 20, 0.08);
  padding: 14px 20px 10px;
  position: relative;
  z-index: 2;
  background: rgba(253, 252, 248, 0.7);
  backdrop-filter: blur(6px);
  transition: box-shadow 0.25s var(--ease-out);
}
.chat-composer::before {
  /* 金色 halo ripple, 发送时向上弹出，呼应气泡轨迹 */
  content: '';
  position: absolute;
  left: 50%;
  top: 0;
  width: 60%;
  height: 3px;
  transform: translateX(-50%) scaleX(0);
  background: linear-gradient(90deg, transparent, rgba(198, 172, 87, 0.65), transparent);
  border-radius: 2px;
  pointer-events: none;
  opacity: 0;
}
.chat-composer.is-sending::before {
  animation: send-halo 420ms var(--ease-out);
}
.chat-composer.is-sending :deep(.el-input__wrapper) {
  box-shadow:
    0 0 0 1px rgba(198, 172, 87, 0.6),
    0 0 0 4px rgba(198, 172, 87, 0.18),
    0 8px 20px rgba(198, 172, 87, 0.25) !important;
  transition: box-shadow 0.2s;
}
@keyframes send-halo {
  0%   { opacity: 0; transform: translateX(-50%) scaleX(0.2) translateY(0); }
  35%  { opacity: 1; transform: translateX(-50%) scaleX(1)   translateY(-2px); }
  100% { opacity: 0; transform: translateX(-50%) scaleX(1.2) translateY(-18px); }
}

/* 发送按钮：期刊金色 + 点击 pop + 发送时回弹 + 图标旋转 */
.chat-send-btn {
  transition: transform 0.18s var(--ease-spring), box-shadow 0.18s;
}
.chat-send-btn :deep(.el-icon) {
  transition: transform 0.25s var(--ease-spring);
}
.chat-send-btn:hover:not(:disabled) :deep(.el-icon) {
  transform: translateX(2px) rotate(-8deg);
}
.chat-send-btn.is-pulsing {
  animation: send-pop 420ms var(--ease-spring);
}
.chat-send-btn.is-pulsing :deep(.el-icon) {
  animation: send-icon-fly 420ms var(--ease-spring);
}
@keyframes send-pop {
  0%   { transform: scale(1); }
  30%  { transform: scale(0.88); box-shadow: 0 0 0 0 rgba(198, 172, 87, 0.55); }
  60%  { transform: scale(1.12); box-shadow: 0 0 0 10px rgba(198, 172, 87, 0); }
  100% { transform: scale(1); }
}
@keyframes send-icon-fly {
  0%   { transform: translate(0, 0) rotate(0); }
  40%  { transform: translate(10px, -10px) rotate(-20deg); opacity: 0.4; }
  41%  { transform: translate(-6px, 4px) rotate(0); opacity: 0; }
  65%  { opacity: 1; }
  100% { transform: translate(0, 0) rotate(0); opacity: 1; }
}
.chat-composer__hints .hint-busy {
  color: #d97706;
  font-weight: 500;
}
.chat-composer__hints {
  font-size: 12px;
  color: #c0c4cc;
  margin-top: 6px;
  text-align: right;
}
</style>
