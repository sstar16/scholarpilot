/**
 * GraphAgent 单测 — 覆盖三层兜底：
 *  1. parseGraphJson 各种输入格式
 *  2. extract happy path（合规 JSON → GraphFragment）
 *  3. extract zod schema validate 拒绝非法 type/relation/weight
 *  4. extract 占位符过滤（label="string" 等）
 *  5. extract LLM 返 malformed → 重试一次成功
 *  6. extract 两次都失败 → throw GraphExtractionError
 *
 * Mock 策略：
 *  - LLM 用 vi.fn() mockImplementation 伪造 generate 返回 LLMResult
 *  - 不依赖任何 fs / Tauri IPC（GraphAgent 本身不写盘）
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ENTITY_TYPES,
  GraphAgent,
  GraphExtractionError,
  parseGraphJson,
  RELATION_TYPES,
  type GraphFragment,
  type LLMLike,
} from '../graphAgent'

// ──────────────────────── Helpers ────────────────────────

function makeLLM(textsOrFn: string[] | ((prompt: string, idx: number) => string | null)): LLMLike {
  let callIdx = 0
  const generate = vi.fn(async (prompt: string) => {
    let text: string | null
    if (typeof textsOrFn === 'function') {
      text = textsOrFn(prompt, callIdx)
    } else {
      text = callIdx < textsOrFn.length ? textsOrFn[callIdx] : null
    }
    callIdx++
    if (text === null) return null
    return {
      text,
      usage: { input_tokens: 50, output_tokens: 100 },
      cost_usd: 0.001,
      latency_ms: 200,
      provider: 'mock',
      model: 'mock-model',
    }
  })
  return { generate } as LLMLike & { generate: ReturnType<typeof vi.fn> }
}

const VALID_FRAGMENT_JSON = JSON.stringify({
  entities: [
    { label: 'Transformer', type: 'method', weight: 0.9 },
    { label: 'Self-Attention', type: 'concept', weight: 0.85 },
    { label: 'Vaswani', type: 'author', weight: 0.6 },
  ],
  relations: [
    { source: 'Vaswani', target: 'Transformer', relation: 'method_of', weight: 0.8 },
    { source: 'Transformer', target: 'Self-Attention', relation: 'topic', weight: 0.9 },
  ],
})

function baseExtractParams() {
  return {
    docId: 'doc-001',
    title: 'Attention is All You Need',
    authors: 'Vaswani et al.',
    year: 2017,
    abstract: 'We propose a new architecture: the Transformer.',
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

// ──────────────────────── parseGraphJson ────────────────────────

describe('parseGraphJson', () => {
  it('解析裸 JSON object（含 entities 字段）', () => {
    const out = parseGraphJson('{"entities":[{"label":"x","type":"concept","weight":0.5}],"relations":[]}')
    expect(out).not.toBeNull()
    expect((out as any).entities[0].label).toBe('x')
  })

  it('剥 ```json fence', () => {
    const out = parseGraphJson('```json\n{"entities":[{"label":"y","type":"paper","weight":0.5}],"relations":[]}\n```')
    expect((out as any).entities[0].label).toBe('y')
  })

  it('从前后解释里挑出 JSON', () => {
    const out = parseGraphJson(
      'Here is the result:\n{"entities":[{"label":"z","type":"concept","weight":0.7}],"relations":[]}\nDone.',
    )
    expect((out as any).entities[0].label).toBe('z')
  })

  it('多个候选对象 → 取第一个含 entities 的', () => {
    const out = parseGraphJson(
      '{"unrelated":1} {"entities":[{"label":"first","type":"concept","weight":0.1}],"relations":[]}',
    )
    expect((out as any).entities[0].label).toBe('first')
  })

  it('完全无效 → null', () => {
    expect(parseGraphJson('not a json at all')).toBeNull()
    expect(parseGraphJson('')).toBeNull()
    expect(parseGraphJson(null)).toBeNull()
  })
})

// ──────────────────────── enum exports ────────────────────────

describe('ENTITY_TYPES / RELATION_TYPES', () => {
  it('暴露 6 类实体 + 6 类关系', () => {
    expect(ENTITY_TYPES.length).toBe(6)
    expect(ENTITY_TYPES).toContain('paper')
    expect(ENTITY_TYPES).toContain('concept')
    expect(ENTITY_TYPES).toContain('author')
    expect(ENTITY_TYPES).toContain('organization')
    expect(ENTITY_TYPES).toContain('method')
    expect(ENTITY_TYPES).toContain('technology')

    expect(RELATION_TYPES.length).toBe(6)
    expect(RELATION_TYPES).toContain('cites')
    expect(RELATION_TYPES).toContain('extends')
    expect(RELATION_TYPES).toContain('contradicts')
    expect(RELATION_TYPES).toContain('coauthor')
    expect(RELATION_TYPES).toContain('topic')
    expect(RELATION_TYPES).toContain('method_of')
  })
})

// ──────────────────────── extract happy path ────────────────────────

describe('GraphAgent.extract: happy path', () => {
  it('合规 JSON → 返回 GraphFragment（含 source_doc_ids）', async () => {
    const llm = makeLLM([VALID_FRAGMENT_JSON])
    const agent = new GraphAgent(llm)
    const fragment: GraphFragment = await agent.extract(baseExtractParams())

    expect(fragment.entities).toHaveLength(3)
    expect(fragment.entities[0].label).toBe('Transformer')
    expect(fragment.entities[0].type).toBe('method')
    expect(fragment.entities[0].weight).toBeCloseTo(0.9)
    // source_doc_ids 自动填充
    expect(fragment.entities[0].source_doc_ids).toEqual(['doc-001'])
    for (const e of fragment.entities) {
      expect(e.source_doc_ids).toEqual(['doc-001'])
    }

    expect(fragment.relations).toHaveLength(2)
    expect(fragment.relations[0].source).toBe('Vaswani')
    expect(fragment.relations[0].target).toBe('Transformer')
    expect(fragment.relations[0].relation).toBe('method_of')
  })

  it('LLM 调用一次（不触发 retry）', async () => {
    const generateSpy = vi.fn().mockResolvedValue({
      text: VALID_FRAGMENT_JSON,
      usage: { input_tokens: 1, output_tokens: 1 },
      cost_usd: 0,
      latency_ms: 1,
      provider: 'mock',
      model: 'm',
    })
    const agent = new GraphAgent({ generate: generateSpy } as any)
    await agent.extract(baseExtractParams())
    expect(generateSpy).toHaveBeenCalledTimes(1)
    // 透传 temperature 和 response_format
    expect(generateSpy.mock.calls[0][1]).toEqual({
      temperature: 0.1,
      response_format: { type: 'json_object' },
    })
  })
})

// ──────────────────────── zod schema 校验 ────────────────────────

describe('GraphAgent.extract: zod schema validate', () => {
  it('错误 entity type → 拒绝 → 重试 → 仍失败 throw', async () => {
    const badType = JSON.stringify({
      entities: [{ label: 'X', type: 'invalid_type', weight: 0.5 }],
      relations: [],
    })
    const llm = makeLLM([badType, badType])
    const agent = new GraphAgent(llm)
    await expect(agent.extract(baseExtractParams())).rejects.toBeInstanceOf(GraphExtractionError)
  })

  it('错误 relation enum → 拒绝 → 重试 → 仍失败 throw', async () => {
    const badRel = JSON.stringify({
      entities: [{ label: 'X', type: 'concept', weight: 0.5 }],
      relations: [{ source: 'X', target: 'Y', relation: 'unknown_rel', weight: 0.5 }],
    })
    // entities 没有 Y → 但 zod 不检查这个，只检查 enum；这里两次都返一样的 → throw
    const llm = makeLLM([badRel, badRel])
    const agent = new GraphAgent(llm)
    await expect(agent.extract(baseExtractParams())).rejects.toBeInstanceOf(GraphExtractionError)
  })

  it('weight > 1 → 拒绝 → throw', async () => {
    const badWeight = JSON.stringify({
      entities: [{ label: 'X', type: 'concept', weight: 1.5 }],
      relations: [],
    })
    const llm = makeLLM([badWeight, badWeight])
    const agent = new GraphAgent(llm)
    await expect(agent.extract(baseExtractParams())).rejects.toBeInstanceOf(GraphExtractionError)
  })

  it('entities 空数组 → 拒绝 → throw', async () => {
    const empty = JSON.stringify({ entities: [], relations: [] })
    const llm = makeLLM([empty, empty])
    const agent = new GraphAgent(llm)
    await expect(agent.extract(baseExtractParams())).rejects.toBeInstanceOf(GraphExtractionError)
  })
})

// ──────────────────────── 占位符过滤 ────────────────────────

describe('GraphAgent.extract: 占位符过滤', () => {
  it('全是 placeholder label → 拒绝 → 重试', async () => {
    const allPlaceholder = JSON.stringify({
      entities: [
        { label: 'string', type: 'concept', weight: 0.5 },
        { label: '<placeholder>', type: 'paper', weight: 0.5 },
        { label: '   ', type: 'concept', weight: 0.5 }, // 空白也算 placeholder
      ],
      relations: [],
    })
    // 第二次也返 placeholder → throw
    const llm = makeLLM([allPlaceholder, allPlaceholder])
    const agent = new GraphAgent(llm)
    await expect(agent.extract(baseExtractParams())).rejects.toBeInstanceOf(GraphExtractionError)
  })

  it('第一次返 placeholder 第二次返合规 → 第二次成功', async () => {
    const allPlaceholder = JSON.stringify({
      entities: [{ label: 'string', type: 'concept', weight: 0.5 }],
      relations: [],
    })
    const llm = makeLLM([allPlaceholder, VALID_FRAGMENT_JSON])
    const agent = new GraphAgent(llm)
    const fragment = await agent.extract(baseExtractParams())
    expect(fragment.entities[0].label).toBe('Transformer')
  })

  it('混合：部分 placeholder → 过滤后保留有效的', async () => {
    const mixed = JSON.stringify({
      entities: [
        { label: 'string', type: 'concept', weight: 0.5 },
        { label: 'Real Concept', type: 'concept', weight: 0.7 },
        { label: '<unknown>', type: 'paper', weight: 0.5 },
      ],
      relations: [],
    })
    const llm = makeLLM([mixed])
    const agent = new GraphAgent(llm)
    const fragment = await agent.extract(baseExtractParams())
    // placeholder 被过滤，只剩 Real Concept
    expect(fragment.entities).toHaveLength(1)
    expect(fragment.entities[0].label).toBe('Real Concept')
  })

  it('过滤后 relation 引用不存在 entity → relation 也被去掉', async () => {
    const orphanRel = JSON.stringify({
      entities: [
        { label: 'string', type: 'concept', weight: 0.5 }, // placeholder
        { label: 'KeptOne', type: 'paper', weight: 0.5 },
      ],
      relations: [
        { source: 'string', target: 'KeptOne', relation: 'cites', weight: 0.5 }, // src 是 placeholder
        { source: 'KeptOne', target: 'KeptOne', relation: 'cites', weight: 0.5 }, // self-loop
      ],
    })
    const llm = makeLLM([orphanRel])
    const agent = new GraphAgent(llm)
    const fragment = await agent.extract(baseExtractParams())
    expect(fragment.entities).toHaveLength(1)
    expect(fragment.relations).toHaveLength(0) // 两条都被过滤
  })
})

// ──────────────────────── malformed → retry ────────────────────────

describe('GraphAgent.extract: malformed JSON → 重试一次成功', () => {
  it('iter1=garbage iter2=valid → 解析成功', async () => {
    const llm = makeLLM(['I think the paper is about... (no JSON here)', VALID_FRAGMENT_JSON])
    const agent = new GraphAgent(llm)
    const fragment = await agent.extract(baseExtractParams())
    expect(fragment.entities[0].label).toBe('Transformer')
  })

  it('LLM 返 null 第一次 → 重试 → 成功', async () => {
    const llm = makeLLM([null as any, VALID_FRAGMENT_JSON]) as LLMLike
    const agent = new GraphAgent(llm)
    const fragment = await agent.extract(baseExtractParams())
    expect(fragment.entities).toHaveLength(3)
  })

  it('LLM throw 第一次 → 重试 → 成功', async () => {
    let calls = 0
    const llm: LLMLike = {
      generate: vi.fn(async () => {
        calls++
        if (calls === 1) throw new Error('network down')
        return {
          text: VALID_FRAGMENT_JSON,
          usage: { input_tokens: 1, output_tokens: 1 },
          cost_usd: 0,
          latency_ms: 1,
          provider: 'mock',
          model: 'm',
        }
      }),
    }
    const agent = new GraphAgent(llm)
    const fragment = await agent.extract(baseExtractParams())
    expect(fragment.entities[0].label).toBe('Transformer')
  })
})

// ──────────────────────── 全失败 → throw ────────────────────────

describe('GraphAgent.extract: 两次都失败 → throw', () => {
  it('两次都返 garbage → throw GraphExtractionError', async () => {
    const llm = makeLLM(() => 'totally not json')
    const agent = new GraphAgent(llm)
    await expect(agent.extract(baseExtractParams())).rejects.toBeInstanceOf(GraphExtractionError)
  })

  it('两次都返 null → throw', async () => {
    const llm = makeLLM(() => null)
    const agent = new GraphAgent(llm)
    await expect(agent.extract(baseExtractParams())).rejects.toBeInstanceOf(GraphExtractionError)
  })

  it('入参缺 docId → throw', async () => {
    const agent = new GraphAgent(makeLLM([VALID_FRAGMENT_JSON]))
    await expect(
      agent.extract({ ...baseExtractParams(), docId: '' }),
    ).rejects.toBeInstanceOf(GraphExtractionError)
  })

  it('入参缺 title → throw', async () => {
    const agent = new GraphAgent(makeLLM([VALID_FRAGMENT_JSON]))
    await expect(
      agent.extract({ ...baseExtractParams(), title: '' }),
    ).rejects.toBeInstanceOf(GraphExtractionError)
  })
})
