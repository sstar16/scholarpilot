/**
 * IntentAgent 单测 — Phase B B9 续作。
 *
 * 覆盖：
 *  1. happy path：研究请求 → 解析出完整 IntentResult
 *  2. 非研究请求 → reply（用 LLM 给的或兜底池）
 *  3. JSON malformed → 重试一次后 null
 *  4. 占位符 title（"研究意图待明确"）→ _reject 兜底
 *  5. 低 confidence (<0.35) → _reject 兜底
 *  6. domain / doc_types / scope / year_focus 校验：枚举外的值降级
 *  7. LLM throw → null
 *  8. _parseIntent 暴露的纯函数行为
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { IntentAgent, _parseIntent, type IntentResult, type UserIntent } from '../intentAgent'
import type { LLMManagerLike } from '../types'

// ──────────────────────── Helpers ────────────────────────

function makeLLM(
  textsOrFn: Array<string | null> | ((prompt: string, idx: number) => string | null),
): LLMManagerLike & { generate: ReturnType<typeof vi.fn> } {
  let i = 0
  const generate = vi.fn(async (prompt: string) => {
    let text: string | null
    if (typeof textsOrFn === 'function') {
      text = textsOrFn(prompt, i)
    } else {
      text = i < textsOrFn.length ? textsOrFn[i] : null
    }
    i++
    if (text === null) return null
    return {
      text,
      usage: { input_tokens: 10, output_tokens: 20 },
      cost_usd: 0.0001,
      latency_ms: 100,
      provider: 'mock',
      model: 'mock-model',
    }
  })
  return { generate }
}

function makeThrowingLLM(): LLMManagerLike {
  return {
    generate: vi.fn(async () => {
      throw new Error('mock LLM down')
    }),
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ──────────────────────── _parseIntent 直接测 ────────────────────────

describe('_parseIntent 纯函数', () => {
  it('合法 research 请求 → 完整 IntentResult', () => {
    const json = JSON.stringify({
      is_research_request: true,
      intent: 'start_search',
      title: '锂电池正极',
      description: '高镍正极界面',
      domains: ['materials_science', 'chemistry'],
      doc_types: 'both',
      scope: 'international',
      year_focus: 'recent',
      key_concepts: ['NMC', 'high-nickel cathode', 'interface'],
      suggested_sources: ['openalex', 'lens'],
      confidence: 0.92,
      clarification_needed: null,
    })
    const out = _parseIntent(json)
    expect(out).not.toBeNull()
    expect(out!.is_research_request).toBe(true)
    expect(out!.intent).toBe('start_search')
    expect(out!.title).toBe('锂电池正极')
    expect(out!.domains).toEqual(['materials_science', 'chemistry'])
    expect(out!.doc_types).toBe('both')
    expect(out!.confidence).toBe(0.92)
  })

  it('is_research_request=false → reply 短路', () => {
    const json = JSON.stringify({
      is_research_request: false,
      intent: 'chat',
      reply: '喵~ 想查啥直接说！',
    })
    const out = _parseIntent(json)
    expect(out).not.toBeNull()
    expect(out!.is_research_request).toBe(false)
    expect(out!.intent).toBe('chat')
    expect(out!.reply).toBe('喵~ 想查啥直接说！')
  })

  it('reply 是公式化客气话 → 兜底池随机替换', () => {
    const json = JSON.stringify({
      is_research_request: false,
      reply: '您好！请告诉我您想研究什么',
    })
    const out = _parseIntent(json)
    expect(out!.is_research_request).toBe(false)
    expect(out!.reply).not.toContain('您好')
    expect(out!.reply).not.toContain('请告诉我')
    // 兜底池所有文案都包含"研究/关键词/主题/方向"之一
    expect(out!.reply!).toMatch(/研究|关键词|主题|方向/)
  })

  it('title 为占位符 → _reject 兜底', () => {
    const json = JSON.stringify({
      is_research_request: true,
      title: '研究意图待明确',
      domains: ['interdisciplinary'],
      confidence: 0.9,
    })
    const out = _parseIntent(json)
    expect(out!.is_research_request).toBe(false)
    expect(out!.reply).toBeTruthy()
  })

  it('confidence < 0.45 → _reject 兜底', () => {
    const json = JSON.stringify({
      is_research_request: true,
      title: '一些研究',
      domains: ['interdisciplinary'],
      confidence: 0.4,
    })
    const out = _parseIntent(json)
    expect(out!.is_research_request).toBe(false)
  })

  it('domains 含枚举外值 → 过滤掉，空时填 interdisciplinary', () => {
    const json = JSON.stringify({
      is_research_request: true,
      title: '跨学科研究',
      domains: ['unknown_field', 'astronomy'],  // 都不在枚举里
      confidence: 0.7,
    })
    const out = _parseIntent(json)
    expect(out!.domains).toEqual(['interdisciplinary'])
  })

  it('doc_types / scope / year_focus 枚举外 → 默认降级', () => {
    const json = JSON.stringify({
      is_research_request: true,
      title: '基础研究',
      domains: ['biology'],
      doc_types: 'invalid_type',
      scope: 'galaxy_wide',
      year_focus: 'forever',
      confidence: 0.7,
    })
    const out = _parseIntent(json)
    expect(out!.doc_types).toBe('literature')
    expect(out!.scope).toBe('international')
    expect(out!.year_focus).toBe('recent')
  })

  it('confidence 是 string "0.85" → 解析为 number', () => {
    const json = JSON.stringify({
      is_research_request: true,
      title: '研究',
      domains: ['biology'],
      confidence: '0.85',
    })
    const out = _parseIntent(json)
    expect(out!.confidence).toBeCloseTo(0.85, 5)
  })

  it('完全 garbage 文本 → null', () => {
    expect(_parseIntent('not json at all')).toBeNull()
    expect(_parseIntent('')).toBeNull()
  })

  it('缺 title 字段 → null', () => {
    const json = JSON.stringify({ is_research_request: true, domains: ['x'] })
    expect(_parseIntent(json)).toBeNull()
  })

  it('剥 ```json fence', () => {
    const json = '```json\n'
      + JSON.stringify({
        is_research_request: true,
        title: '量子计算',
        domains: ['physics'],
        confidence: 0.8,
      })
      + '\n```'
    const out = _parseIntent(json)
    expect(out!.title).toBe('量子计算')
  })
})

// ──────────────────────── IntentAgent.analyze 行为 ────────────────────────

describe('IntentAgent.analyze — happy path', () => {
  it('research 请求 → 一次成功解析', async () => {
    const json = JSON.stringify({
      is_research_request: true,
      intent: 'start_search',
      title: 'CRISPR 治疗',
      description: '基因编辑临床应用',
      domains: ['medicine', 'biology'],
      doc_types: 'both',
      scope: 'international',
      year_focus: 'recent',
      key_concepts: ['CRISPR', 'gene editing', 'clinical trial'],
      suggested_sources: ['pubmed', 'openalex'],
      confidence: 0.95,
    })
    const llm = makeLLM([json])
    const agent = new IntentAgent(llm)
    const out = await agent.analyze({ userInput: '我想研究 CRISPR 在临床上的最新进展' })
    expect(llm.generate).toHaveBeenCalledTimes(1)
    expect(out).not.toBeNull()
    expect(out!.is_research_request).toBe(true)
    expect(out!.intent).toBe('start_search')
    expect(out!.title).toBe('CRISPR 治疗')
    expect(out!.domains).toContain('medicine')
  })

  it('携带 supplementaryContext → prompt 含 supplement_section', async () => {
    const json = JSON.stringify({
      is_research_request: true,
      intent: 'start_search',
      title: 'X',
      domains: ['biology'],
      confidence: 0.9,
    })
    const llm = makeLLM([json])
    const agent = new IntentAgent(llm)
    await agent.analyze({
      userInput: '研究 X',
      supplementaryContext: '用户已设定中文优先',
    })
    const promptArg = (llm.generate.mock.calls[0]?.[0] ?? '') as string
    expect(promptArg).toContain('用户已设定中文优先')
  })
})

// ──────────────────────── 5 类 intent happy-path ─────────────────────────

describe('UserIntent — 5 类分类 happy-path', () => {
  it('start_search：用户描述研究方向', async () => {
    const json = JSON.stringify({
      is_research_request: true,
      intent: 'start_search',
      title: '全固态锂电池',
      domains: ['materials_science', 'chemistry'],
      confidence: 0.92,
    })
    const llm = makeLLM([json])
    const agent = new IntentAgent(llm)
    const out = await agent.analyze({ userInput: '我想研究全固态锂电池正极界面' })
    expect(out).not.toBeNull()
    expect(out!.intent).toBe('start_search' satisfies UserIntent)
    expect(out!.is_research_request).toBe(true)
  })

  it('start_collaboration：用户想对比文献库内容', async () => {
    const json = JSON.stringify({
      is_research_request: false,
      intent: 'start_collaboration',
      reply: '嘿嘿，协作模式开启！',
    })
    const llm = makeLLM([json])
    const agent = new IntentAgent(llm)
    const out = await agent.analyze({ userInput: '帮我对比文献库里几篇 review' })
    expect(out).not.toBeNull()
    expect(out!.intent).toBe('start_collaboration' satisfies UserIntent)
    expect(out!.is_research_request).toBe(false)
    expect(out!.reply).toBeTruthy()
  })

  it('start_pdf_import：用户想导入 PDF', async () => {
    const json = JSON.stringify({
      is_research_request: false,
      intent: 'start_pdf_import',
      reply: '喵！点上方按钮上传 PDF~',
    })
    const llm = makeLLM([json])
    const agent = new IntentAgent(llm)
    const out = await agent.analyze({ userInput: '我想导入一份 PDF' })
    expect(out).not.toBeNull()
    expect(out!.intent).toBe('start_pdf_import' satisfies UserIntent)
    expect(out!.is_research_request).toBe(false)
  })

  it('configure_push：用户想配置定时推送', async () => {
    const json = JSON.stringify({
      is_research_request: false,
      intent: 'configure_push',
      reply: '定时推送面板在右侧~',
    })
    const llm = makeLLM([json])
    const agent = new IntentAgent(llm)
    const out = await agent.analyze({ userInput: '帮我配置每天自动推送新论文' })
    expect(out).not.toBeNull()
    expect(out!.intent).toBe('configure_push' satisfies UserIntent)
    expect(out!.is_research_request).toBe(false)
  })

  it('chat：用户闲聊问候', async () => {
    const json = JSON.stringify({
      is_research_request: false,
      intent: 'chat',
      reply: '喵！在的，说来~',
    })
    const llm = makeLLM([json])
    const agent = new IntentAgent(llm)
    const out = await agent.analyze({ userInput: '你好' })
    expect(out).not.toBeNull()
    expect(out!.intent).toBe('chat' satisfies UserIntent)
    expect(out!.is_research_request).toBe(false)
  })

  it('未知 intent 字符串 → 兜底为 chat', () => {
    const json = JSON.stringify({
      is_research_request: false,
      intent: 'unknown_action',
      reply: '喵？',
    })
    const out = _parseIntent(json)
    expect(out!.intent).toBe('chat' satisfies UserIntent)
  })
})

describe('IntentAgent.analyze — 兜底', () => {
  it('LLM 第一次返 garbage → 重试第二次成功', async () => {
    const validJson = JSON.stringify({
      is_research_request: true,
      title: '神经网络',
      domains: ['computer_science'],
      confidence: 0.8,
    })
    const llm = makeLLM(['this is not json', validJson])
    const agent = new IntentAgent(llm)
    const out = await agent.analyze({ userInput: '研究神经网络' })
    expect(llm.generate).toHaveBeenCalledTimes(2)
    expect(out!.title).toBe('神经网络')
  })

  it('LLM 两次都 garbage → 返 null', async () => {
    const llm = makeLLM(['garbage 1', 'garbage 2'])
    const agent = new IntentAgent(llm)
    const out = await agent.analyze({ userInput: '研究 xxx' })
    expect(out).toBeNull()
  })

  it('LLM 抛异常 → 重试一次后仍异常 → null', async () => {
    const llm = makeThrowingLLM()
    const agent = new IntentAgent(llm)
    const out = await agent.analyze({ userInput: '研究 yyy' })
    expect(out).toBeNull()
  })

  it('userInput 太短 (< 2 字符) → 直接 null（不调 LLM）', async () => {
    const llm = makeLLM(['should-not-be-called'])
    const agent = new IntentAgent(llm)
    const out = await agent.analyze({ userInput: 'a' })
    expect(out).toBeNull()
    expect(llm.generate).not.toHaveBeenCalled()
  })

  it('userInput 全是空白 → null', async () => {
    const llm = makeLLM([])
    const agent = new IntentAgent(llm)
    const out = await agent.analyze({ userInput: '   \n  ' })
    expect(out).toBeNull()
  })
})

describe('IntentAgent.analyze — 非研究请求路径', () => {
  it('LLM 返 is_research_request=false → 透传 reply', async () => {
    const json = JSON.stringify({
      is_research_request: false,
      reply: '喵！直接告诉我研究方向就行~',
    })
    const llm = makeLLM([json])
    const agent = new IntentAgent(llm)
    const out = await agent.analyze({ userInput: '你好' })
    expect(out).not.toBeNull()
    expect(out!.is_research_request).toBe(false)
    expect(out!.reply).toContain('喵')
  })

  it('LLM 复读"您好！请告诉我..." → 替换为兜底池', async () => {
    const json = JSON.stringify({
      is_research_request: false,
      reply: '您好！请告诉我您想研究什么领域。',
    })
    const llm = makeLLM([json])
    const agent = new IntentAgent(llm)
    const out = await agent.analyze({ userInput: 'hi' })
    expect(out!.reply).not.toContain('您好')
    expect(out!.reply).not.toContain('请告诉我')
    // 兜底池里所有文案都带"研究"关键字
    expect(out!.reply).toMatch(/研究|关键词|主题|方向/)
  })
})

describe('IntentAgent — 边界', () => {
  it('LLM 返回 null 两次 → 最终 null', async () => {
    const llm = makeLLM([null, null])
    const agent = new IntentAgent(llm)
    const out = await agent.analyze({ userInput: '研究 zzz' })
    expect(out).toBeNull()
  })

  it('LLM 返回 LLMResult.text 为空 → null', async () => {
    const llm: LLMManagerLike = {
      generate: vi.fn(async () => ({
        text: '',
        usage: { input_tokens: 0, output_tokens: 0 },
        cost_usd: 0,
        latency_ms: 1,
        provider: 'mock',
        model: 'mock',
      })),
    }
    const agent = new IntentAgent(llm)
    const out = await agent.analyze({ userInput: '研究 xxx' })
    expect(out).toBeNull()
  })

  it('description 缺失 → 用 title 兜底', () => {
    const json = JSON.stringify({
      is_research_request: true,
      title: '量子纠缠',
      domains: ['physics'],
      confidence: 0.8,
    })
    const out = _parseIntent(json) as IntentResult
    expect(out.description).toBe('量子纠缠')
  })

  it('suggested_sources 空 → 默认 [openalex, crossref]', () => {
    const json = JSON.stringify({
      is_research_request: true,
      title: '研究',
      domains: ['biology'],
      confidence: 0.7,
    })
    const out = _parseIntent(json) as IntentResult
    expect(out.suggested_sources).toEqual(['openalex', 'crossref'])
  })

  it('confidence 字段类型奇怪 (object) → 默认 0.5', () => {
    const json = JSON.stringify({
      is_research_request: true,
      title: '某研究',
      domains: ['biology'],
      confidence: { weird: 'shape' },
    })
    const out = _parseIntent(json) as IntentResult
    expect(out.confidence).toBe(0.5)
  })

  it('key_concepts 截断到 15 项', () => {
    const concepts = Array.from({ length: 30 }, (_, i) => `c${i}`)
    const json = JSON.stringify({
      is_research_request: true,
      title: '研究',
      domains: ['biology'],
      confidence: 0.8,
      key_concepts: concepts,
    })
    const out = _parseIntent(json) as IntentResult
    expect(out.key_concepts!.length).toBe(15)
    expect(out.key_concepts![0]).toBe('c0')
  })
})
