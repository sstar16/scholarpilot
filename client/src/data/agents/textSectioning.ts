/**
 * Text sectioning — 客户端 TS 等价物，从 backend `harness/text_sectioning.py` 移植。
 *
 * 把学术论文全文切成"探针可独立消化"的小段：
 * 1. 优先按标题分段（markdown `##`、带编号 heading、经典 IMRaD 关键词）
 * 2. 没有明显结构时退化为等宽字符窗口 + 重叠
 * 3. 每段产出 (idx, label, char_start, char_end, text)
 *
 * 客户端差异：
 * - JS 没有 Python re.MULTILINE 默认开关，正则要显式加 `m` flag
 * - dataclass → plain interface
 */

export const MAX_SECTION_CHARS = 6000     // 单段上限（便于探针一次消化）
export const MIN_SECTION_CHARS = 400      // 小于此认为不值得独立切，合并到上一段
export const WINDOW_CHARS = 5000          // 退化策略的窗口大小
export const WINDOW_OVERLAP = 500         // 相邻窗口重叠，避免边界截断


export interface Section {
  idx: number
  label: string
  char_start: number
  char_end: number
  text: string
}


// markdown 风格 `##`、`###`：优先级高
const _MD_HEADING_RE = /^(#{1,4})\s+(.+?)\s*$/gm

// 经典 IMRaD heading + 编号或冒号 + 中英文兼容
const _IMRAD_HEADING_RE = new RegExp(
  '^(?:\\d+(?:\\.\\d+)*\\.?\\s+)?'
  + '(Abstract|Introduction|Background|Related\\s+Work|Preliminaries|'
  + 'Methods?|Methodology|Approach|Experiments?|'
  + 'Results?|Evaluation|Discussion|Analysis|'
  + 'Ablation(?:\\s+Stud(?:y|ies))?|Conclusions?|'
  + 'Limitations?|Future\\s+Work|Acknowledge?ments?|References?|Appendix|'
  + '摘要|引言|方法|实验|结果|讨论|结论|参考文献)'
  + '\\s*[:：]?\\s*$',
  'gim',
)


function _findHeadingAnchors(text: string): Array<[number, string]> {
  const anchors: Array<[number, string]> = []

  // markdown headings
  let m: RegExpExecArray | null
  _MD_HEADING_RE.lastIndex = 0
  while ((m = _MD_HEADING_RE.exec(text)) !== null) {
    const label = (m[2] ?? m[0]).trim().replace(/\s+/g, ' ').slice(0, 80)
    anchors.push([m.index, label])
  }

  // IMRaD headings — capture group 1 是 IMRaD 关键词
  _IMRAD_HEADING_RE.lastIndex = 0
  while ((m = _IMRAD_HEADING_RE.exec(text)) !== null) {
    const captured = m[1] ?? m[0]
    const label = captured.trim().replace(/\s+/g, ' ').slice(0, 80)
    anchors.push([m.index, label])
  }

  // 排序 + 去重（相邻 < 20 字符的 anchor 视为重复，与 backend 一致）
  anchors.sort((a, b) => a[0] - b[0])
  const dedup: Array<[number, string]> = []
  for (const [pos, label] of anchors) {
    if (dedup.length && pos - dedup[dedup.length - 1][0] < 20) continue
    dedup.push([pos, label])
  }
  return dedup
}


function _windowSplit(
  text: string,
  baseIdx: number,
  labelPrefix: string,
  baseOffset = 0,
): Section[] {
  const out: Section[] = []
  const n = text.length
  if (n === 0) return out
  let start = 0
  const step = Math.max(WINDOW_CHARS - WINDOW_OVERLAP, 1)
  let idx = baseIdx
  while (start < n) {
    const end = Math.min(start + WINDOW_CHARS, n)
    const chunk = text.slice(start, end)
    out.push({
      idx,
      label: `${labelPrefix} #${idx + 1}`,
      char_start: baseOffset + start,
      char_end: baseOffset + end,
      text: chunk,
    })
    idx += 1
    if (end >= n) break
    start += step
  }
  return out
}


/**
 * 主入口：把 fullText 切成 Section 列表。
 *
 * - 若检测到 ≥3 个 heading 锚点 → 按 heading 切
 * - 否则 → 按 WINDOW_CHARS 等宽 + 重叠
 * - heading 切法中，单段超过 MAX_SECTION_CHARS 会再做一次内部窗口切
 */
export function splitIntoSections(text: string): Section[] {
  if (!text || !text.trim()) return []

  const anchors = _findHeadingAnchors(text)
  if (anchors.length < 3) {
    // 结构不明显 → 窗口法
    return _windowSplit(text, 0, '片段')
  }

  const sections: Section[] = []
  let idx = 0

  // 把开头到第一个 heading 之间视为 "Preamble"
  const firstPos = anchors[0][0]
  if (firstPos > MIN_SECTION_CHARS) {
    const pre = text.slice(0, firstPos)
    if (pre.length > MAX_SECTION_CHARS) {
      sections.push(..._windowSplit(pre, idx, '开篇', 0))
      idx = sections.length
    } else {
      sections.push({
        idx,
        label: '开篇',
        char_start: 0,
        char_end: firstPos,
        text: pre,
      })
      idx += 1
    }
  }

  // 相邻 heading 之间一段
  const boundaries = anchors.map(a => a[0]).concat(text.length)
  const labels = anchors.map(a => a[1])
  for (let i = 0; i < labels.length; i++) {
    const start = boundaries[i]
    const end = boundaries[i + 1]
    const chunk = text.slice(start, end)
    const label = labels[i]
    if (chunk.length < MIN_SECTION_CHARS && sections.length) {
      // 太短合并到上一段
      const last = sections[sections.length - 1]
      sections[sections.length - 1] = {
        idx: last.idx,
        label: `${last.label} + ${label}`,
        char_start: last.char_start,
        char_end: end,
        text: last.text + chunk,
      }
      continue
    }
    if (chunk.length > MAX_SECTION_CHARS) {
      const sub = _windowSplit(chunk, idx, label, start)
      sections.push(...sub)
      idx = sections.length
    } else {
      sections.push({
        idx,
        label,
        char_start: start,
        char_end: end,
        text: chunk,
      })
      idx += 1
    }
  }

  // 重新排 idx，保证连续
  return sections.map((s, i) => ({ ...s, idx: i }))
}
