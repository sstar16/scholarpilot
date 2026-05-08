import MarkdownIt from 'markdown-it'

// Shared markdown-it instance for chat / collaboration messages.
// html: false → raw HTML 不会被渲染（等于内置 XSS 护栏）
// linkify/typographer → 自动把 http:// 变链接 + 常见标点优化
const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  breaks: true, // 单个换行也转 <br>（聊天场景更自然）
})

// 让所有链接在新 tab 打开
const defaultLinkOpen =
  md.renderer.rules.link_open ||
  function (tokens: any, idx: number, options: any, _env: any, self: any) {
    return self.renderToken(tokens, idx, options)
  }

md.renderer.rules.link_open = function (tokens, idx, options, env, self) {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen(tokens, idx, options, env, self)
}

export function renderMarkdown(text: string): string {
  if (!text) return ''
  return md.render(text)
}

export function renderMarkdownInline(text: string): string {
  if (!text) return ''
  return md.renderInline(text)
}
