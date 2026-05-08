/**
 * Memory Markdown Agent — 客户端版，从 backend `harness/agents/memory_markdown_agent.py` 移植。
 *
 * 责任：
 *   现有 .md + 新增对话/反馈/round signals → LLM → 增量改写后的 .md
 *
 * 两个 mode（对齐 backend）：
 * - user: 用户级（身份/职业/研究大方向）→ refineUser
 * - project: 项目级（本项目研究方向/子问题/关注点）→ refineProject
 *
 * Phase B B8 caller 视角的 refine() 抽象：
 *   接受 newSignals（feedback / conversation / round），统一拼接为对话块
 *   输入 LLM；返回 { updatedMd, summary }。
 */
import { llmManager as defaultLlmManager } from '../llm/manager'
import type { LLMResult } from '../llm/types'
import { loadPrompt } from './promptLoader'
import type { LLMGenerator } from './memoryAgent'

// ── 类型 ────────────────────────────────────────────────────────────────

/** 单条新信号 —— 来自 feedback / conversation / round 的统一形态。 */
export interface MemorySignal {
  /** 信号来源：feedback（4-bucket 反馈摘要）/ conversation（用户/AI 对话）/ round（每轮检索摘要） */
  source: 'feedback' | 'conversation' | 'round'
  /** 信号正文（一行或多行；caller 自行裁剪） */
  content: string
  /** 角色（仅 conversation 模式有意义；不传默认 'user'） */
  role?: 'user' | 'assistant' | 'system'
}

export interface RefineParams {
  /** 当前 .md 全文（首次 = ''） */
  currentMd: string
  /** 新增信号 */
  newSignals: MemorySignal[]
  /** 提示模板用：用户名（user mode）或项目标题（project mode） */
  subject?: string
}

export interface RefineResult {
  /** 增量改写后的 .md（无新信息时 = currentMd 一字不改） */
  updatedMd: string
  /** caller 视角的更新摘要（无变化 → 'no change'） */
  summary: string
}

/** Conversation 类消息（向 backend `_format_conversation` 对齐）。 */
export interface ConversationMessage {
  role: 'user' | 'assistant' | 'system' | string
  content: string
}

// ── 工具 ────────────────────────────────────────────────────────────────

const ROLE_TAG: Record<string, string> = {
  user: '用户',
  assistant: 'AI',
  system: '系统',
}

/** 把 MemorySignal[] 渲染成 prompt 里的「对话块」字符串。
 *
 *  对齐 backend `_format_conversation`：每条 `[tag] content`，空行分隔；空对话占位 `(无对话)`。
 */
function _formatSignals(signals: MemorySignal[]): string {
  const lines: string[] = []
  for (const s of signals) {
    const text = (s.content || '').trim()
    if (!text) continue
    if (s.source === 'conversation') {
      const tag = ROLE_TAG[s.role || 'user'] || s.role || 'user'
      lines.push(`[${tag}] ${text}`)
    } else if (s.source === 'feedback') {
      lines.push(`[反馈] ${text}`)
    } else if (s.source === 'round') {
      lines.push(`[检索轮次] ${text}`)
    } else {
      lines.push(text)
    }
  }
  return lines.length > 0 ? lines.join('\n\n') : '(无对话)'
}

/** 直接传 ConversationMessage[]（backend 老入口）的渲染等价物。 */
function _formatConversation(messages: ConversationMessage[]): string {
  const lines: string[] = []
  for (const m of messages) {
    const text = (m.content || '').trim()
    if (!text) continue
    const tag = ROLE_TAG[m.role] || m.role || 'user'
    lines.push(`[${tag}] ${text}`)
  }
  return lines.length > 0 ? lines.join('\n\n') : '(无对话)'
}

/** 防御 LLM 偷懒返回 ```...``` 代码块围栏。 */
function _stripCodeFence(text: string): string {
  let t = text.trim()
  if (!t.startsWith('```')) return t
  const lines = t.split('\n')
  // 去掉首行 ```xxx
  lines.shift()
  // 去掉尾行 ``` （若有）
  if (lines.length > 0 && lines[lines.length - 1].trim().startsWith('```')) {
    lines.pop()
  }
  t = lines.join('\n').trim()
  return t
}

/** 简单 diff 摘要：检测 updatedMd 与 currentMd 是否有实质变化。 */
function _summarize(currentMd: string, updatedMd: string, signalCount: number): string {
  const a = currentMd.trim()
  const b = updatedMd.trim()
  if (a === b) return 'no change'
  const delta = b.length - a.length
  const sign = delta >= 0 ? '+' : ''
  return `refined from ${signalCount} signals (${sign}${delta} chars)`
}

// ── MemoryMarkdownAgent ─────────────────────────────────────────────────

export class MemoryMarkdownAgent {
  private llm: LLMGenerator

  constructor(llm?: LLMGenerator | null) {
    this.llm = (llm as LLMGenerator) ?? defaultLlmManager
  }

  /** 用户级 .md 增量提炼。LLM 不可用 / 失败 → 原样返回 currentMd（不抛）。 */
  async refineUser(params: RefineParams): Promise<RefineResult> {
    return this._refine('agents/memory_markdown_user', params, 'user_name')
  }

  /** 项目级 .md 增量提炼。 */
  async refineProject(params: RefineParams): Promise<RefineResult> {
    return this._refine('agents/memory_markdown_project', params, 'project_title')
  }

  /** 通用入口（默认走 project mode；caller 可显式选 mode）。 */
  async refine(
    params: RefineParams & { mode?: 'user' | 'project' },
  ): Promise<RefineResult> {
    const mode = params.mode ?? 'project'
    return mode === 'user' ? this.refineUser(params) : this.refineProject(params)
  }

  /** Phase B B8 任务规范方法名 —— 项目级 .md 增量提炼（spec 别名，等价 refineProject）。 */
  async refineProjectMemory(params: RefineParams): Promise<RefineResult> {
    return this.refineProject(params)
  }

  /** Phase B B8 任务规范方法名 —— 用户级 .md 增量提炼（spec 别名，等价 refineUser）。 */
  async refineUserMemory(params: RefineParams): Promise<RefineResult> {
    return this.refineUser(params)
  }

  /** 直接传 backend 风格的 messages[]（兼容老 caller）。 */
  async refineUserFromMessages(
    currentMd: string,
    messages: ConversationMessage[],
    userName?: string,
  ): Promise<RefineResult> {
    return this._refineRaw('agents/memory_markdown_user', currentMd, _formatConversation(messages), userName, 'user_name')
  }

  async refineProjectFromMessages(
    currentMd: string,
    messages: ConversationMessage[],
    projectTitle?: string,
  ): Promise<RefineResult> {
    return this._refineRaw(
      'agents/memory_markdown_project',
      currentMd,
      _formatConversation(messages),
      projectTitle,
      'project_title',
    )
  }

  // ── private ──

  private async _refine(
    promptName: string,
    params: RefineParams,
    subjectVar: 'user_name' | 'project_title',
  ): Promise<RefineResult> {
    const conversation = _formatSignals(params.newSignals || [])
    return this._refineRaw(promptName, params.currentMd, conversation, params.subject, subjectVar)
  }

  private async _refineRaw(
    promptName: string,
    currentMd: string,
    conversation: string,
    subject: string | undefined,
    subjectVar: 'user_name' | 'project_title',
  ): Promise<RefineResult> {
    let promptText: string
    try {
      const pf = loadPrompt(promptName)
      const renderVars: Record<string, string> = {
        current_markdown: currentMd.trim() || '(空)',
        conversation,
      }
      renderVars[subjectVar] = subject || (subjectVar === 'user_name' ? '(匿名)' : '本项目')
      promptText = pf.render(renderVars)
    } catch (e) {
      console.warn('[MemoryMarkdownAgent] prompt render failed:', e)
      return { updatedMd: currentMd, summary: 'no change (prompt render failed)' }
    }

    let raw: string | null = null
    try {
      const result = await this.llm.generate(promptText, {
        temperature: 0.1,
        max_tokens: 3000,
      })
      if (typeof result === 'string') {
        raw = result
      } else if (result && typeof (result as LLMResult).text === 'string') {
        raw = (result as LLMResult).text
      }
    } catch (e) {
      console.warn('[MemoryMarkdownAgent] LLM call failed:', e)
      return { updatedMd: currentMd, summary: 'no change (LLM error)' }
    }

    const text = (raw ?? '').trim()
    if (!text) {
      return { updatedMd: currentMd, summary: 'no change (empty LLM result)' }
    }

    const updatedMd = _stripCodeFence(text)
    const signalCount = (() => {
      // 估算：按双换行段落数（_formatSignals 用 \n\n 分隔）
      if (conversation === '(无对话)') return 0
      return conversation.split(/\n\n+/).filter(Boolean).length
    })()
    return {
      updatedMd,
      summary: _summarize(currentMd, updatedMd, signalCount),
    }
  }
}

// ── 单例便捷入口 ─────────────────────────────────────────────────────────

let _singleton: MemoryMarkdownAgent | null = null
export function getMemoryMarkdownAgent(): MemoryMarkdownAgent {
  if (!_singleton) _singleton = new MemoryMarkdownAgent()
  return _singleton
}

export function _resetMemoryMarkdownAgentForTesting(
  replacement: MemoryMarkdownAgent | null = null,
): void {
  _singleton = replacement
}
