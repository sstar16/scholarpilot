/**
 * 飞入动画 — 文档卡片飞向侧边栏桶
 * 使用 CSS transform + GPU 加速，支持 prefers-reduced-motion 降级
 */
export function flyTo(sourceEl: HTMLElement, targetEl: HTMLElement, color: string = '#0d9488') {
  // 检查 reduced motion 偏好
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

  const sourceRect = sourceEl.getBoundingClientRect()
  const targetRect = targetEl.getBoundingClientRect()

  // 创建 clone
  const clone = document.createElement('div')
  clone.style.cssText = `
    position: fixed;
    left: ${sourceRect.left}px;
    top: ${sourceRect.top}px;
    width: ${sourceRect.width}px;
    height: ${sourceRect.height}px;
    background: ${color}20;
    border: 2px solid ${color};
    border-radius: 12px;
    z-index: 9999;
    pointer-events: none;
    transition: all 0.5s cubic-bezier(0.22, 1, 0.36, 1);
    box-shadow: 0 0 20px ${color}40;
  `
  document.body.appendChild(clone)

  // 触发 reflow 后设置终点
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      clone.style.left = `${targetRect.left + targetRect.width / 2 - 20}px`
      clone.style.top = `${targetRect.top + targetRect.height / 2 - 10}px`
      clone.style.width = '40px'
      clone.style.height = '20px'
      clone.style.opacity = '0.3'
      clone.style.borderRadius = '20px'
    })
  })

  // 动画结束后移除
  clone.addEventListener('transitionend', () => {
    clone.remove()
  })
  // 安全兜底
  setTimeout(() => { if (clone.parentNode) clone.remove() }, 800)
}

/**
 * 桶颜色映射
 */
export const BUCKET_COLORS: Record<string, string> = {
  very_relevant: '#0d9488',  // teal
  relevant: '#2563eb',       // blue
  uncertain: '#64748b',      // slate
  irrelevant: '#dc2626',     // coral
}

export const BUCKET_LABELS: Record<string, string> = {
  very_relevant: '很相关',
  relevant: '相关',
  uncertain: '不确定',
  irrelevant: '不相关',
}
