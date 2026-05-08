<template>
  <div
    v-if="msg.content || $slots.actions"
    class="chat-msg"
    :class="[`chat-msg--${msg.role}`]"
  >
    <div class="chat-msg__avatar">
      <UserAvatar v-if="msg.role === 'user'" :size="36" :name="userName" :url="userAvatarUrl" />
      <CatAvatar v-else-if="msg.role === 'assistant'" :size="36" />
      <el-icon v-else :size="18" class="chat-msg__avatar-sys"><InfoFilled /></el-icon>
    </div>
    <div class="chat-msg__body">
      <div class="chat-msg__content">
        <div class="chat-msg__text markdown-body">
          <span v-html="renderedContent" />
        </div>
        <slot name="actions" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'
import type { ChatMessage } from '../../stores/conversation'
import { useAuthStore } from '../../stores/auth'
import { renderMarkdown } from '../../composables/useMarkdown'
import CatAvatar from '../brand/CatAvatar.vue'
import UserAvatar from '../brand/UserAvatar.vue'

// animate prop 保留以兼容旧调用方但内部已忽略——打字机效果在 2026-04-29 移除
const props = defineProps<{ msg: ChatMessage; animate?: boolean }>()

const auth = useAuthStore()
const userName = computed(() => auth.user?.name || auth.user?.email || '')
const userAvatarUrl = computed(() => auth.user?.avatar_url || '')

const renderedContent = computed(() => renderMarkdown(props.msg.content || ''))
</script>

<style scoped>
.chat-msg {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  max-width: 85%;
}
.chat-msg--user {
  flex-direction: row-reverse;
  margin-left: auto;
  transform-origin: bottom right;
  animation: userEnter 620ms cubic-bezier(0.34, 1.56, 0.64, 1) both;
}
.chat-msg--assistant {
  margin-right: auto;
  transform-origin: bottom left;
  animation: aiEnter 620ms cubic-bezier(0.34, 1.56, 0.64, 1) both;
}
.chat-msg--system {
  margin: 0 auto;
  max-width: 70%;
  animation: fadeUp var(--duration-normal) var(--ease-out) both;
}

.chat-msg__avatar {
  flex-shrink: 0;
  display: flex;
  align-items: flex-start;
  justify-content: center;
}
.chat-msg__avatar-sys {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--signal-amber-bg);
  color: var(--signal-amber);
  display: flex;
  align-items: center;
  justify-content: center;
}

.chat-msg__body { min-width: 0; }

.chat-msg__content {
  padding: 10px var(--space-4);
  border-radius: var(--radius-lg);
  font-size: var(--type-body-size);
  line-height: var(--type-body-lh);
  word-break: break-word;
  position: relative;
  transition: transform var(--duration-fast) var(--ease-out),
              box-shadow var(--duration-fast) var(--ease-out);
}
.chat-msg__content:hover {
  transform: translateY(-1px);
}
.chat-msg--user .chat-msg__content {
  background: linear-gradient(135deg, var(--signal-teal), #0b8077);
  color: #fff;
  border-bottom-right-radius: 4px;
  box-shadow: 0 4px 16px rgba(13, 148, 136, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.18);
}
.chat-msg--user .chat-msg__content:hover {
  box-shadow: 0 8px 24px rgba(13, 148, 136, 0.38), inset 0 1px 0 rgba(255, 255, 255, 0.22);
}

/* 用户气泡里 markdown 子元素的颜色：全部白/浅，覆盖全局 teal-on-light 配色 */
.chat-msg--user .markdown-body,
.chat-msg--user .markdown-body :deep(p),
.chat-msg--user .markdown-body :deep(li),
.chat-msg--user .markdown-body :deep(span),
.chat-msg--user .markdown-body :deep(h1),
.chat-msg--user .markdown-body :deep(h2),
.chat-msg--user .markdown-body :deep(h3),
.chat-msg--user .markdown-body :deep(h4),
.chat-msg--user .markdown-body :deep(strong),
.chat-msg--user .markdown-body :deep(em) {
  color: #fff !important;
}
.chat-msg--user .markdown-body :deep(a) {
  color: #fffbe6 !important;
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 2px;
}
.chat-msg--user .markdown-body :deep(a:hover) {
  color: #fff !important;
}
.chat-msg--user .markdown-body :deep(code) {
  background: rgba(255, 255, 255, 0.18);
  color: #fff !important;
  border: 1px solid rgba(255, 255, 255, 0.22);
}
.chat-msg--user .markdown-body :deep(pre) {
  background: rgba(0, 0, 0, 0.28);
  color: #f4f4f5 !important;
  border: 1px solid rgba(255, 255, 255, 0.12);
}
.chat-msg--user .markdown-body :deep(pre code) {
  background: none;
  color: inherit !important;
  border: none;
}
.chat-msg--user .markdown-body :deep(blockquote) {
  background: rgba(255, 255, 255, 0.1);
  border-left-color: rgba(255, 255, 255, 0.6);
  color: rgba(255, 255, 255, 0.9) !important;
}
.chat-msg--user .markdown-body :deep(hr) {
  border-top-color: rgba(255, 255, 255, 0.3);
}
.chat-msg--user .markdown-body :deep(th),
.chat-msg--user .markdown-body :deep(td) {
  border-color: rgba(255, 255, 255, 0.25);
  color: #fff !important;
}
.chat-msg--user .markdown-body :deep(th) {
  background: rgba(255, 255, 255, 0.15);
}
.chat-msg--assistant .chat-msg__content {
  background: linear-gradient(180deg, #fdfcf8, var(--paper-cool));
  color: var(--ink-800);
  border: 1px solid var(--ink-100);
  border-bottom-left-radius: 4px;
  box-shadow: 0 2px 10px rgba(20, 20, 20, 0.04);
}
.chat-msg--assistant .chat-msg__content:hover {
  border-color: rgba(198, 172, 87, 0.35);
  box-shadow: 0 6px 18px rgba(20, 20, 20, 0.08);
}
.chat-msg--system .chat-msg__content {
  background: var(--signal-amber-bg);
  color: var(--ink-600);
  text-align: center;
  font-size: var(--type-sub-size);
  border: 1px dashed rgba(217, 119, 6, 0.35);
}

.chat-msg__text { display: inline; }

/* Markdown body styles (v-html rendered content) */
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  margin: 0.6em 0 0.3em;
  font-weight: 600;
  line-height: 1.3;
  font-family: var(--font-display);
}
.markdown-body :deep(h1) { font-size: 1.3em; }
.markdown-body :deep(h2) { font-size: 1.2em; }
.markdown-body :deep(h3) { font-size: 1.1em; }
.markdown-body :deep(h4) { font-size: 1.02em; }
.markdown-body :deep(p) { margin: 0.35em 0; }
.markdown-body :deep(p:first-child) { margin-top: 0; }
.markdown-body :deep(p:last-child) { margin-bottom: 0; }
.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  margin: 0.4em 0;
  padding-left: 1.4em;
}
.markdown-body :deep(li) { margin: 0.15em 0; }
.markdown-body :deep(li > p) { margin: 0.15em 0; }
.markdown-body :deep(code) {
  background: var(--signal-teal-bg);
  color: var(--signal-teal);
  padding: 1px 5px;
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 0.88em;
}
.markdown-body :deep(pre) {
  background: var(--ink-900);
  color: var(--ink-100);
  padding: 10px 12px;
  border-radius: var(--radius-md);
  overflow-x: auto;
  margin: 0.6em 0;
  font-size: 0.85em;
}
.markdown-body :deep(pre code) {
  background: none;
  color: inherit;
  padding: 0;
  font-size: inherit;
}
.markdown-body :deep(blockquote) {
  margin: 0.6em 0;
  padding: 4px 12px;
  border-left: 3px solid var(--signal-teal);
  background: var(--signal-teal-bg);
  color: var(--ink-500);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
}
.markdown-body :deep(table) {
  border-collapse: collapse;
  margin: 0.6em 0;
  font-size: 0.92em;
}
.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid var(--ink-100);
  padding: 4px 10px;
}
.markdown-body :deep(th) {
  background: var(--paper-cool);
  font-weight: 600;
}
.markdown-body :deep(a) {
  color: var(--signal-blue);
  text-decoration: underline;
  text-decoration-thickness: 1px;
  text-underline-offset: 2px;
}
.markdown-body :deep(a:hover) { color: var(--signal-blue-light); }
.markdown-body :deep(hr) {
  margin: 0.8em 0;
  border: none;
  border-top: 1px dashed var(--ink-200);
}
.markdown-body :deep(strong) { font-weight: 600; }
</style>
