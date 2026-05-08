/**
 * Prompt loader — 客户端版，对齐 backend `services/prompt_loader.py`。
 *
 * 设计参考 backend：
 * - YAML frontmatter + body 解析
 * - `render(vars)` 用 `$var` / `${var}` 模板替换（不碰 body 里的 JSON 花括号）
 * - parser 永不抛异常，坏 md 只 warn log
 *
 * 客户端差异：
 * - **不做 mtime 热重载**：vite raw import 在 build 时已固化，运行时改文件无意义
 * - **编译时索引**：所有 prompt 在 build 阶段被打进 chunk，loadPrompt 是同步的
 *   （backend 是 async file IO，client 不需要）
 *
 * 用法：
 *
 *     import { loadPrompt } from '@/data/agents/promptLoader'
 *
 *     const pf = loadPrompt('agents/scoring')
 *     const rendered = pf.render({
 *       project_description: '...',
 *       memory_section: '...',
 *       title: '...',
 *       ...
 *     })
 */
import yaml from 'js-yaml'

// vite raw import — 编译时把 md 打成字符串
import scoringRaw from './prompts/agents/scoring.md?raw'
import queryPlanAgenticRaw from './prompts/agents/query_plan_agentic.md?raw'
import queryPlanLegacyRaw from './prompts/agents/query_plan_legacy.md?raw'
import intentAnalysisRaw from './prompts/agents/intent_analysis.md?raw'
import memoryUpdateRaw from './prompts/agents/memory_update.md?raw'
import memoryMarkdownUserRaw from './prompts/agents/memory_markdown_user.md?raw'
import memoryMarkdownProjectRaw from './prompts/agents/memory_markdown_project.md?raw'
import graphExtractionRaw from './prompts/agents/graph_extraction.md?raw'
import researchRaw from './prompts/agents/research.md?raw'
import probeRaw from './prompts/agents/probe.md?raw'
import summarizerRaw from './prompts/agents/summarizer.md?raw'
import chatSystemRaw from './prompts/agents/chat_system.md?raw'

// ── 注册表 ──────────────────────────────────────────────────────────────

/** name → raw md 字符串。新增 prompt 时在这里加一行。 */
const _registry: Record<string, string> = {
  'agents/scoring': scoringRaw,
  'agents/query_plan_agentic': queryPlanAgenticRaw,
  'agents/query_plan_legacy': queryPlanLegacyRaw,
  'agents/intent_analysis': intentAnalysisRaw,
  'agents/memory_update': memoryUpdateRaw,
  'agents/memory_markdown_user': memoryMarkdownUserRaw,
  'agents/memory_markdown_project': memoryMarkdownProjectRaw,
  'agents/graph_extraction': graphExtractionRaw,
  'agents/research': researchRaw,
  'agents/probe': probeRaw,
  'agents/summarizer': summarizerRaw,
  'agents/chat_system': chatSystemRaw,
}

// ── PromptFile ──────────────────────────────────────────────────────────

const _FRONTMATTER_RE = /^---\s*\n([\s\S]*?)\n---\s*\n?/

export class PromptFile {
  readonly name: string
  readonly meta: Record<string, unknown>
  readonly body: string

  constructor(name: string, meta: Record<string, unknown>, body: string) {
    this.name = name
    this.meta = meta
    this.body = body
  }

  /** Frontmatter 字段读取（meta.get(key, default)）。 */
  get<T = unknown>(key: string, defaultValue?: T): T {
    const v = this.meta[key]
    return (v === undefined ? defaultValue : v) as T
  }

  /** 用 `$var` / `${var}` 模板替换。
   *
   *  对齐 backend `string.Template.safe_substitute`：变量缺失时保留原字面量
   *  （不抛异常）；JSON body 里的 `{...}` 花括号不被误碰，因为模板只识别 `$xxx`。
   */
  render(vars: Record<string, string | number | undefined | null> = {}): string {
    if (!Object.keys(vars).length) return this.body
    return this.body.replace(/\$(?:\{(\w+)\}|(\w+))/g, (m, braced: string, bare: string) => {
      const key = braced ?? bare
      const v = vars[key]
      if (v === undefined || v === null) {
        // 保留原字面量（safe_substitute 行为）
        return m
      }
      return String(v)
    })
  }
}

// ── 解析 ────────────────────────────────────────────────────────────────

function _parseFrontmatter(text: string, source: string): {
  meta: Record<string, unknown>
  body: string
} {
  const m = _FRONTMATTER_RE.exec(text)
  if (!m) return { meta: {}, body: text }

  const yamlText = m[1] || ''
  const body = text.slice(m[0].length)

  let parsed: unknown
  try {
    parsed = yaml.load(yamlText)
  } catch (e) {
    console.warn(`[promptLoader] YAML parse failed in ${source}:`, e)
    return { meta: {}, body }
  }

  if (parsed === null || parsed === undefined) {
    return { meta: {}, body }
  }
  if (typeof parsed !== 'object' || Array.isArray(parsed)) {
    console.warn(
      `[promptLoader] frontmatter in ${source} is not a mapping, got ${typeof parsed}`,
    )
    return { meta: {}, body }
  }

  return { meta: parsed as Record<string, unknown>, body }
}

// ── 缓存 ────────────────────────────────────────────────────────────────

const _cache = new Map<string, PromptFile>()

// ── 公共 API ────────────────────────────────────────────────────────────

/** 加载一个 prompt md。
 *
 *  Args:
 *    name — 相对路径，不带 .md。例：`agents/scoring`
 *
 *  Throws:
 *    Error — 注册表里没这个 name（启动时就该爆，启动校验走 `loadAll()`）
 */
export function loadPrompt(name: string): PromptFile {
  const cached = _cache.get(name)
  if (cached) return cached

  const raw = _registry[name]
  if (raw === undefined) {
    throw new Error(`prompt not found: ${name}（请在 promptLoader.ts 的 _registry 注册）`)
  }

  const { meta, body } = _parseFrontmatter(raw, name)
  const pf = new PromptFile(name, meta, body.trim())
  _cache.set(name, pf)
  return pf
}

/** 启动校验：加载所有注册的 prompt。任何解析错在这里暴露。 */
export function loadAll(): Record<string, PromptFile> {
  const result: Record<string, PromptFile> = {}
  for (const name of Object.keys(_registry)) {
    try {
      result[name] = loadPrompt(name)
    } catch (e) {
      console.error(`[promptLoader] failed to load ${name}:`, e)
    }
  }
  return result
}

/** 测试用。 */
export function _clearCache(): void {
  _cache.clear()
}

/** 已注册的 prompt name 列表（DevTools / 测试用）。 */
export function listPrompts(): string[] {
  return Object.keys(_registry)
}
