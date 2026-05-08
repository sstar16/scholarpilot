/**
 * MemoryMarkdownAgent 单测
 *
 * 用 mock LLM 覆盖：
 *   1. refineUser：对话信号 → updatedMd 包含 LLM 返回的新内容
 *   2. refineProject：保留原内容 + 增补
 *   3. LLM 返代码围栏 → _stripCodeFence 正确剥离
 *   4. LLM throw / null / 空 → 原样返回 currentMd（不抛）
 *   5. refineUserFromMessages 老接口兼容
 */
import { describe, it, expect, beforeEach } from 'vitest'

import {
  MemoryMarkdownAgent,
  type MemorySignal,
  type ConversationMessage,
} from '../memoryMarkdownAgent'
import type { LLMGenerator } from '../memoryAgent'
import { _clearCache as _clearPromptCache } from '../promptLoader'

beforeEach(() => {
  _clearPromptCache()
})

function makeMockLLM(responses: Array<string | null>): LLMGenerator & { calls: string[] } {
  const calls: string[] = []
  let i = 0
  return {
    calls,
    async generate(prompt) {
      calls.push(prompt)
      if (i >= responses.length) return null
      return responses[i++]
    },
  }
}

function makeThrowingLLM(): LLMGenerator {
  return {
    async generate() {
      throw new Error('mock LLM error')
    },
  }
}

const SIGNALS: MemorySignal[] = [
  {
    source: 'conversation',
    role: 'user',
    content: '我是同济计算机系的本科生，研究方向是大模型推理优化',
  },
  {
    source: 'feedback',
    content: '将 "vLLM PagedAttention" 标为很相关',
  },
  {
    source: 'round',
    content: '第 3 轮检索：聚焦 KV cache 压缩与 long-context attention',
  },
]

describe('MemoryMarkdownAgent.refineUser', () => {
  it('信号 → LLM → updatedMd 包含原内容 + 新增', async () => {
    const updated = `# 用户记忆

## 身份
- 同济计算机系本科

## 研究方向
- 大模型推理优化
`
    const mock = makeMockLLM([updated])
    const agent = new MemoryMarkdownAgent(mock)
    const result = await agent.refineUser({
      currentMd: '# 用户记忆\n\n## 身份\n- 同济计算机系本科',
      newSignals: SIGNALS,
      subject: '杨同学',
    })
    expect(mock.calls).toHaveLength(1)
    // prompt 必须含信号文本
    expect(mock.calls[0]).toContain('vLLM PagedAttention')
    expect(mock.calls[0]).toContain('同济计算机系')
    expect(mock.calls[0]).toContain('杨同学')

    expect(result.updatedMd).toBe(updated.trim())
    expect(result.updatedMd).toContain('同济计算机系本科')
    expect(result.updatedMd).toContain('大模型推理优化')
    expect(result.summary).toMatch(/^refined from 3 signals/)
  })

  it('LLM 返 ```markdown\\n...\\n``` → 自动剥离围栏', async () => {
    const fenced = '```markdown\n# 用户记忆\n\n## 研究方向\n- LLM\n```'
    const mock = makeMockLLM([fenced])
    const agent = new MemoryMarkdownAgent(mock)
    const result = await agent.refineUser({
      currentMd: '# 用户记忆',
      newSignals: SIGNALS,
    })
    expect(result.updatedMd).not.toContain('```')
    expect(result.updatedMd).toContain('# 用户记忆')
    expect(result.updatedMd).toContain('## 研究方向')
  })

  it('LLM 返 ``` 无 lang 标记也能剥', async () => {
    const fenced = '```\n# 用户\n## A\n- one\n```'
    const mock = makeMockLLM([fenced])
    const agent = new MemoryMarkdownAgent(mock)
    const result = await agent.refineUser({
      currentMd: '',
      newSignals: SIGNALS,
    })
    expect(result.updatedMd).not.toContain('```')
    expect(result.updatedMd).toContain('# 用户')
  })
})

describe('MemoryMarkdownAgent.refineProject', () => {
  it('preserve 原内容 + 增补 LLM 输出', async () => {
    const orig = `# 项目记忆

## 研究方向

## 关键术语
- attention
`
    const updated = `# 项目记忆

## 研究方向
- 大模型推理 KV cache 压缩

## 关键术语
- attention
- KV cache
- PagedAttention
`
    const mock = makeMockLLM([updated])
    const agent = new MemoryMarkdownAgent(mock)
    const result = await agent.refineProject({
      currentMd: orig,
      newSignals: SIGNALS,
      subject: 'LLM 推理优化项目',
    })
    expect(result.updatedMd).toContain('attention')
    expect(result.updatedMd).toContain('KV cache')
    expect(result.updatedMd).toContain('PagedAttention')
    expect(result.summary).toMatch(/^refined from/)
  })

  it('refine() 默认走 project mode', async () => {
    const mock = makeMockLLM(['# 默认 project 输出'])
    const agent = new MemoryMarkdownAgent(mock)
    await agent.refine({ currentMd: '# orig', newSignals: SIGNALS })
    // prompt 必须是 project_title 模板（含「项目」字样）
    expect(mock.calls[0]).toContain('项目')
  })

  it('refine({ mode: "user" }) 走 user prompt', async () => {
    const mock = makeMockLLM(['# 用户输出'])
    const agent = new MemoryMarkdownAgent(mock)
    await agent.refine({ mode: 'user', currentMd: '', newSignals: SIGNALS, subject: '匿名' })
    expect(mock.calls[0]).toContain('用户级')
  })
})

describe('MemoryMarkdownAgent — graceful failures', () => {
  it('LLM throw → 原样返 currentMd', async () => {
    const agent = new MemoryMarkdownAgent(makeThrowingLLM())
    const result = await agent.refineUser({
      currentMd: '# original',
      newSignals: SIGNALS,
    })
    expect(result.updatedMd).toBe('# original')
    expect(result.summary).toContain('LLM error')
  })

  it('LLM 返 null → 原样', async () => {
    const mock = makeMockLLM([null])
    const agent = new MemoryMarkdownAgent(mock)
    const result = await agent.refineUser({
      currentMd: '# orig',
      newSignals: SIGNALS,
    })
    expect(result.updatedMd).toBe('# orig')
    expect(result.summary).toContain('empty LLM result')
  })

  it('LLM 返空字符串 → 原样', async () => {
    const mock = makeMockLLM([''])
    const agent = new MemoryMarkdownAgent(mock)
    const result = await agent.refineUser({ currentMd: '# X', newSignals: SIGNALS })
    expect(result.updatedMd).toBe('# X')
  })

  it('updatedMd 与 currentMd 完全一致 → summary = no change', async () => {
    const md = '# 不变\n\n## A\n- one'
    const mock = makeMockLLM([md])
    const agent = new MemoryMarkdownAgent(mock)
    const result = await agent.refineUser({ currentMd: md, newSignals: SIGNALS })
    expect(result.updatedMd).toBe(md)
    expect(result.summary).toBe('no change')
  })
})

describe('MemoryMarkdownAgent — backward compat (messages[])', () => {
  it('refineUserFromMessages：直接传 backend 风格 messages', async () => {
    const messages: ConversationMessage[] = [
      { role: 'user', content: '我用 vLLM 跑推理' },
      { role: 'assistant', content: '了解，可以聊 paged attention 吗？' },
    ]
    const mock = makeMockLLM(['# updated'])
    const agent = new MemoryMarkdownAgent(mock)
    await agent.refineUserFromMessages('# orig', messages, '老杨')
    expect(mock.calls[0]).toContain('[用户] 我用 vLLM')
    expect(mock.calls[0]).toContain('[AI] 了解，可以聊')
    expect(mock.calls[0]).toContain('老杨')
  })

  it('空 messages → conversation = (无对话)', async () => {
    const mock = makeMockLLM(['# done'])
    const agent = new MemoryMarkdownAgent(mock)
    await agent.refineProjectFromMessages('# orig', [], '项目X')
    expect(mock.calls[0]).toContain('(无对话)')
  })
})

describe('MemoryMarkdownAgent — signal formatting', () => {
  it('空 signals → conversation = (无对话)', async () => {
    const mock = makeMockLLM(['# x'])
    const agent = new MemoryMarkdownAgent(mock)
    await agent.refineUser({ currentMd: '', newSignals: [] })
    expect(mock.calls[0]).toContain('(无对话)')
  })

  it('signal source 区分：feedback / round / conversation', async () => {
    const sigs: MemorySignal[] = [
      { source: 'conversation', role: 'user', content: 'hello' },
      { source: 'feedback', content: 'fb1' },
      { source: 'round', content: 'r1' },
    ]
    const mock = makeMockLLM(['# x'])
    const agent = new MemoryMarkdownAgent(mock)
    await agent.refineUser({ currentMd: '', newSignals: sigs })
    expect(mock.calls[0]).toContain('[用户] hello')
    expect(mock.calls[0]).toContain('[反馈] fb1')
    expect(mock.calls[0]).toContain('[检索轮次] r1')
  })
})
