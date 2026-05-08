<template>
  <div class="library-markdown-viewer">
    <div v-if="store.detailLoading" class="loading">
      <el-icon class="is-loading" :size="24"><Loading /></el-icon>
      <span>加载中...</span>
    </div>
    <div v-else-if="!store.currentDetail" class="placeholder">
      <el-icon :size="48" color="#cbd5e1"><Document /></el-icon>
      <p>从左侧选择一篇文献</p>
    </div>
    <div
      v-else
      ref="contentRef"
      class="md-content"
      v-html="renderedHtml"
      @click="onContentClick"
    ></div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import MarkdownIt from 'markdown-it'
import { Loading, Document } from '@element-plus/icons-vue'
import { useLibraryStore } from '../../stores/library'

const props = defineProps<{
  projectId: string
}>()

const store = useLibraryStore()
const router = useRouter()
const route = useRoute()
const contentRef = ref<HTMLElement>()

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  breaks: false,
})

// wiki-link 插件: [[slug]] → <a class="wiki-link" data-slug="slug">slug</a>
md.core.ruler.after('inline', 'wiki_link', (state: any) => {
  const wikiRe = /\[\[([\w\u4e00-\u9fa5-]+)\]\]/g
  state.tokens.forEach((blockToken: any) => {
    if (blockToken.type !== 'inline' || !blockToken.children) return
    const newChildren: any[] = []
    for (const child of blockToken.children) {
      if (child.type !== 'text' || !wikiRe.test(child.content)) {
        newChildren.push(child)
        wikiRe.lastIndex = 0
        continue
      }
      wikiRe.lastIndex = 0
      let lastIdx = 0
      let match: RegExpExecArray | null
      while ((match = wikiRe.exec(child.content)) !== null) {
        if (match.index > lastIdx) {
          const text = new state.Token('text', '', 0)
          text.content = child.content.slice(lastIdx, match.index)
          newChildren.push(text)
        }
        const html = new state.Token('html_inline', '', 0)
        const slug = match[1]
        html.content = `<a class="wiki-link" data-slug="${slug}">${slug}</a>`
        newChildren.push(html)
        lastIdx = match.index + match[0].length
      }
      if (lastIdx < child.content.length) {
        const text = new state.Token('text', '', 0)
        text.content = child.content.slice(lastIdx)
        newChildren.push(text)
      }
    }
    blockToken.children = newChildren
  })
  return true
})

const renderedHtml = computed(() => {
  const detail = store.currentDetail
  if (!detail) return ''
  return md.render(detail.body_md || '')
})

async function onContentClick(ev: MouseEvent) {
  const target = ev.target as HTMLElement
  if (target.classList?.contains('wiki-link')) {
    const slug = target.getAttribute('data-slug')
    if (slug) {
      ev.preventDefault()
      await router.replace({
        query: { ...route.query, slug },
      })
      await store.selectFile(props.projectId, slug)
    }
  }
}
</script>

<style scoped>
.library-markdown-viewer {
  height: 100%;
  overflow-y: auto;
  padding: 24px 32px;
  background: var(--paper-cool);
}
.loading,
.placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  color: var(--ink-300);
}
</style>

<style>
/* Global styles for markdown content (non-scoped) */
.md-content {
  max-width: 800px;
  margin: 0 auto;
  font-size: 15px;
  line-height: 1.7;
  color: var(--ink-800);
}
.md-content h1 {
  font-size: 24px;
  font-weight: 700;
  margin: 0 0 12px;
  padding-bottom: 8px;
  border-bottom: 2px solid var(--ink-200);
}
.md-content h2 {
  font-size: 18px;
  font-weight: 600;
  margin: 24px 0 8px;
  color: var(--ink-700);
}
.md-content h3 {
  font-size: 16px;
  font-weight: 600;
  margin: 16px 0 6px;
  color: var(--ink-600);
}
.md-content p {
  margin: 8px 0;
}
.md-content blockquote {
  margin: 12px 0;
  padding: 8px 16px;
  border-left: 4px solid var(--signal-blue-light);
  background: var(--signal-blue-bg);
  color: var(--signal-blue);
  font-size: 14px;
}
.md-content ul {
  margin: 8px 0;
  padding-left: 24px;
}
.md-content li {
  margin: 4px 0;
}
.md-content a {
  color: var(--signal-blue);
  text-decoration: none;
}
.md-content a:hover {
  text-decoration: underline;
}
.md-content .wiki-link {
  color: var(--signal-purple-light);
  background: var(--signal-purple-bg);
  padding: 0 4px;
  border-radius: 3px;
  font-size: 13px;
  cursor: pointer;
}
.md-content .wiki-link:hover {
  background: var(--signal-purple-bg);
  text-decoration: none;
}
.md-content sub {
  font-size: 11px;
  color: var(--ink-400);
}
.md-content hr {
  margin: 24px 0;
  border: none;
  border-top: 1px solid var(--ink-200);
}
</style>
