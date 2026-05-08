/**
 * ResearchDecisionAgent 单测 — Phase B B9 续作。
 *
 * 覆盖：
 *  1. happy path：LLM 返合法 JSON → ProjectPlan 4 字段齐 + reasoning
 *  2. JSON malformed → 重试一次成功
 *  3. 两次都 malformed → fallback plan（不抛）
 *  4. 非研究请求 (is_research_request=false) → fallback plan
 *  5. 缺 query_plan.base_query → 用 key_concepts 抽关键词兜底
 *  6. confidence 高 + 多关键词 → estimatedRounds 较少
 *  7. clarification_needed → estimatedRounds 较多
 *  8. examples 注入 supplement_section
 *  9. LLM throw → fallback plan
 * 10. 空 userDescription → fallback plan
 * 11. _parseDecisionJson 边界
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ResearchDecisionAgent,
  __test__,
  type PlanNewProjectParams,
  type ProjectPlan,
} from '../researchDecisionAgent'
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

function buildResearchJson(opts: {
  title?: string
  description?: string
  domains?: string[]
  doc_types?: string
  scope?: string
  year_focus?: string
  key_concepts?: string[]
  confidence?: number
  clarification?: string | null
  query_plan?: {
    base_query?: string | null
    chinese_query?: string | null
    year_from?: number | null
    year_to?: number | null
    language_scope?: string
    rationale?: string
  } | null
}): string {
  return JSON.stringify({
    is_research_request: true,
    title: opts.title ?? '量子计算与机器学习融合',
    description: opts.description ?? '量子机器学习近期 NISQ 设备进展',
    domains: opts.domains ?? ['physics', 'computer_science'],
    doc_types: opts.doc_types ?? 'literature',
    scope: opts.scope ?? 'international',
    year_focus: opts.year_focus ?? 'recent',
    key_concepts: opts.key_concepts ?? ['quantum machine learning', 'NISQ'],
    suggested_sources: ['arxiv', 'openalex'],
    confidence: opts.confidence ?? 0.85,
    clarification_needed: opts.clarification ?? null,
    query_plan: opts.query_plan === undefined
      ? {
        base_query: 'quantum machine learning variational circuits NISQ',
        chinese_query: '量子机器学习 变分电路',
        year_from: 2021,
        year_to: 2026,
        language_scope: 'international',
        rationale: '聚焦 NISQ 实用进展',
      }
      : opts.query_plan,
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ──────────────────────── _parseDecisionJson ────────────────────────

describe('_parseDecisionJson 纯函数', () => {
  it('合法 JSON → 解析出全字段', () => {
    const out = __test__.parseDecisionJson(buildResearchJson({}))
    expect(out).not.toBeNull()
    expect(out!.is_research_request).toBe(true)
    expect(out!.title).toBe('量子计算与机器学习融合')
    expect(out!.query_plan?.base_query).toContain('quantum machine learning')
  })

  it('剥 ```json fence', () => {
    const out = __test__.parseDecisionJson('```json\n' + buildResearchJson({}) + '\n```')
    expect(out!.title).toContain('量子')
  })

  it('garbage → null', () => {
    expect(__test__.parseDecisionJson('not json')).toBeNull()
    expect(__test__.parseDecisionJson('')).toBeNull()
    expect(__test__.parseDecisionJson(null)).toBeNull()
  })

  it('多个 JSON 候选 → 优先含 is_research_request 的', () => {
    const text = `先来一段闲聊 {"unrelated":1} ${buildResearchJson({})} 末尾解释`
    const out = __test__.parseDecisionJson(text)
    expect(out!.title).toContain('量子')
  })
})

// ──────────────────────── happy path ────────────────────────

describe('ResearchDecisionAgent.planNewProject — happy path', () => {
  it('合法 LLM JSON → ProjectPlan 4 字段', async () => {
    const llm = makeLLM([buildResearchJson({})])
    const agent = new ResearchDecisionAgent(llm)
    const plan = await agent.planNewProject({ userDescription: '想研究量子机器学习' })
    expect(llm.generate).toHaveBeenCalledTimes(1)
    expect(plan.suggestedTitle).toBe('量子计算与机器学习融合')
    expect(plan.researchScope).toContain('量子机器学习')
    expect(plan.initialKeywords.length).toBeGreaterThan(0)
    expect(plan.initialKeywords[0]).toBe('quantum')
    expect(plan.estimatedRounds).toBeGreaterThanOrEqual(1)
    expect(plan.estimatedRounds).toBeLessThanOrEqual(5)
    expect(plan.reasoning).toContain('NISQ')
  })

  it('userDescription 短英文输入也能产 plan', async () => {
    const llm = makeLLM([
      buildResearchJson({
        title: 'Diffusion Models',
        key_concepts: ['stable diffusion', 'classifier guidance'],
        query_plan: {
          base_query: 'diffusion models text-to-image guidance',
          year_from: 2020,
          year_to: 2026,
          language_scope: 'international',
          rationale: 'core diffusion line',
        },
      }),
    ])
    const agent = new ResearchDecisionAgent(llm)
    const plan = await agent.planNewProject({ userDescription: 'diffusion models' })
    expect(plan.suggestedTitle).toBe('Diffusion Models')
    expect(plan.initialKeywords).toContain('diffusion')
  })
})

// ──────────────────────── 重试 + fallback ────────────────────────

describe('ResearchDecisionAgent.planNewProject — 重试与 fallback', () => {
  it('第一次 garbage → 第二次合法 → 返 plan', async () => {
    const llm = makeLLM(['this is not json', buildResearchJson({})])
    const agent = new ResearchDecisionAgent(llm)
    const plan = await agent.planNewProject({ userDescription: '研究' })
    expect(llm.generate).toHaveBeenCalledTimes(2)
    expect(plan.suggestedTitle).toContain('量子')
  })

  it('两次 garbage → fallback plan（不抛）', async () => {
    const llm = makeLLM(['garbage 1', 'garbage 2'])
    const agent = new ResearchDecisionAgent(llm)
    const plan = await agent.planNewProject({ userDescription: '锂离子电池正极材料' })
    expect(llm.generate).toHaveBeenCalledTimes(2)
    expect(plan.reasoning).toContain('fallback')
    // fallback 仍然给出可用 plan
    expect(plan.initialKeywords.length).toBeGreaterThan(0)
    expect(plan.suggestedTitle.length).toBeGreaterThan(0)
    expect(plan.estimatedRounds).toBe(3)
  })

  it('LLM 持续返 null → fallback plan', async () => {
    const llm = makeLLM([null, null])
    const agent = new ResearchDecisionAgent(llm)
    const plan = await agent.planNewProject({ userDescription: '生物信息学 转录组分析' })
    expect(plan.reasoning).toContain('fallback')
    expect(plan.initialKeywords).toContain('生物信息学')
  })

  it('LLM throw → fallback plan（不抛）', async () => {
    const llm = makeThrowingLLM()
    const agent = new ResearchDecisionAgent(llm)
    const plan = await agent.planNewProject({ userDescription: '催化剂设计' })
    expect(plan.reasoning).toContain('fallback')
    expect(plan.initialKeywords.length).toBeGreaterThan(0)
  })

  it('非研究请求 (is_research_request=false) → fallback plan', async () => {
    const json = JSON.stringify({
      is_research_request: false,
      reply: '喵~ 来个研究主题嘛',
    })
    const llm = makeLLM([json, json])
    const agent = new ResearchDecisionAgent(llm)
    const plan = await agent.planNewProject({ userDescription: '你好啊' })
    expect(plan.reasoning).toContain('fallback')
  })
})

// ──────────────────────── 关键词抽取与轮次估算 ────────────────────────

describe('_extractKeywords + _estimateRounds', () => {
  it('优先 query_plan.base_query 切词', () => {
    const out = __test__.extractKeywords({
      query_plan: { base_query: 'graph neural network attention' },
    })
    expect(out).toEqual(['graph', 'neural', 'network', 'attention'])
  })

  it('base_query 缺失 → 回退 key_concepts', () => {
    const out = __test__.extractKeywords({
      key_concepts: ['transformer', 'self-attention'],
    })
    expect(out).toEqual(['transformer', 'self-attention'])
  })

  it('两者都没 → 空数组', () => {
    expect(__test__.extractKeywords({})).toEqual([])
  })

  it('confidence ≥ 0.8 + 关键词 ≥ 4 → 2 轮', () => {
    const r = __test__.estimateRounds(
      { confidence: 0.9 },
      ['k1', 'k2', 'k3', 'k4'],
    )
    expect(r).toBe(2)
  })

  it('clarification_needed → 4 轮', () => {
    const r = __test__.estimateRounds(
      { confidence: 0.9, clarification_needed: '范围太广了' },
      ['k1', 'k2', 'k3', 'k4'],
    )
    expect(r).toBe(4)
  })

  it('confidence 中等 → 3 轮', () => {
    const r = __test__.estimateRounds({ confidence: 0.7 }, ['k1', 'k2'])
    expect(r).toBe(3)
  })

  it('低 confidence → 4 轮', () => {
    const r = __test__.estimateRounds({ confidence: 0.4 }, ['k1', 'k2'])
    expect(r).toBe(4)
  })

  it('confidence 是 string 也能解析', () => {
    const r = __test__.estimateRounds(
      { confidence: '0.9' },
      ['k1', 'k2', 'k3', 'k4'],
    )
    expect(r).toBe(2)
  })
})

// ──────────────────────── 边界 ────────────────────────

describe('ResearchDecisionAgent — 边界', () => {
  it('userDescription 为空 → 直接 fallback（不调 LLM）', async () => {
    const llm = makeLLM(['should-not-be-called'])
    const agent = new ResearchDecisionAgent(llm)
    const plan = await agent.planNewProject({ userDescription: '' })
    expect(llm.generate).not.toHaveBeenCalled()
    expect(plan.reasoning).toContain('fallback')
  })

  it('userDescription 全空白 → 直接 fallback', async () => {
    const llm = makeLLM([])
    const agent = new ResearchDecisionAgent(llm)
    const plan = await agent.planNewProject({ userDescription: '   \n  ' })
    expect(plan.reasoning).toContain('fallback')
  })

  it('examples 注入到 prompt 的 supplement_section', async () => {
    const llm = makeLLM([buildResearchJson({})])
    const agent = new ResearchDecisionAgent(llm)
    const params: PlanNewProjectParams = {
      userDescription: '量子机器学习',
      examples: ['例如 VQE', '例如 QAOA', ''],
    }
    await agent.planNewProject(params)
    const promptArg = (llm.generate.mock.calls[0]?.[0] ?? '') as string
    expect(promptArg).toContain('VQE')
    expect(promptArg).toContain('QAOA')
    // 空字符串 example 应被过滤
    expect(promptArg).toContain('## 用户补充示例')
  })

  it('plan 缺 query_plan，但有 key_concepts → 仍能生成 plan', async () => {
    const llm = makeLLM([
      buildResearchJson({
        query_plan: null,
        key_concepts: ['transfer learning', 'fine-tune', 'lora'],
      }),
    ])
    const agent = new ResearchDecisionAgent(llm)
    const plan = await agent.planNewProject({ userDescription: '迁移学习' })
    expect(plan.initialKeywords).toContain('transfer learning')
    expect(plan.initialKeywords).toContain('lora')
  })

  it('plan 缺关键词 → fallback plan', async () => {
    const llm = makeLLM([
      buildResearchJson({
        query_plan: null,
        key_concepts: [],
      }),
      buildResearchJson({
        query_plan: null,
        key_concepts: [],
      }),
    ])
    const agent = new ResearchDecisionAgent(llm)
    const plan = await agent.planNewProject({ userDescription: '某些笼统的主题描述' })
    expect(plan.reasoning).toContain('fallback')
  })

  it('LLM 第一次 throw → 第二次成功 → 仍能拿到 plan', async () => {
    let firstCall = true
    const llm: LLMManagerLike = {
      generate: vi.fn(async () => {
        if (firstCall) {
          firstCall = false
          throw new Error('first attempt failed')
        }
        return {
          text: buildResearchJson({}),
          usage: { input_tokens: 1, output_tokens: 1 },
          cost_usd: 0,
          latency_ms: 1,
          provider: 'mock',
          model: 'mock',
        }
      }),
    }
    const agent = new ResearchDecisionAgent(llm)
    const plan = await agent.planNewProject({ userDescription: '研究' })
    expect(plan.reasoning).not.toContain('fallback')
  })
})

// ──────────────────────── _toProjectPlan / _buildFallbackPlan ────────────────

describe('_buildFallbackPlan / _toProjectPlan', () => {
  it('空字符串 → 默认未命名研究', () => {
    const p = __test__.buildFallbackPlan('', 'empty')
    expect(p.suggestedTitle).toBe('未命名研究')
    expect(p.initialKeywords.length).toBeGreaterThan(0)
  })

  it('中文逗号切词正确', () => {
    const p = __test__.buildFallbackPlan('锂电池，正极材料，界面研究', 'parse fail')
    expect(p.initialKeywords).toContain('锂电池')
    expect(p.initialKeywords).toContain('正极材料')
  })

  it('_toProjectPlan：is_research_request=false → null', () => {
    const out = __test__.toProjectPlan({ is_research_request: false }, 'x')
    expect(out).toBeNull()
  })

  it('_toProjectPlan：title 太短 → null', () => {
    const out = __test__.toProjectPlan({ title: 'X' }, 'desc')
    expect(out).toBeNull()
  })

  it('_toProjectPlan：完整字段 → ProjectPlan', () => {
    const out = __test__.toProjectPlan({
      title: '某项目',
      description: '描述',
      confidence: 0.9,
      query_plan: {
        base_query: 'transformer attention pretraining decoder finetune',
        rationale: '策略一',
      },
    }, 'desc') as ProjectPlan
    expect(out).not.toBeNull()
    expect(out.suggestedTitle).toBe('某项目')
    expect(out.initialKeywords).toEqual([
      'transformer',
      'attention',
      'pretraining',
      'decoder',
      'finetune',
    ])
    expect(out.reasoning).toContain('策略一')
  })
})
