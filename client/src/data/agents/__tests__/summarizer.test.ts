/**
 * LLMSummarizer 单测 — 覆盖任务规范要求的全部场景：
 *  1. parseSummarizerJson / sanitizeSummarizerOutput 单元测
 *  2. happy path：LLM 返合规 JSON
 *  3. 占位符过滤：summary 含 `{背景}` → 拒绝 → 重试
 *  4. summary 太短：summary < 50 字符 → 拒绝 → 重试
 *  5. keyPoints 不足：返回 0 条 → 拒绝 → 重试
 *  6. 全失败 → fallback 用 abstract，quality='low'
 *  7. summarizeBatch：10 篇 → onProgress 调 10 次
 *
 * Mock 策略：
 *  - LLM 用 vi.fn() 伪造 generate
 *  - LLMQueue 通过 _dbForTesting 注入内存 stub，不依赖 Tauri SQLite plugin
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  LLMSummarizer,
  parseSummarizerJson,
  sanitizeSummarizerOutput,
  type LLMLike,
  type SummarizeOutput,
} from '../summarizer'
import { LLMQueue } from '../../llm/concurrent_queue'

// ──────────────────────── Helpers ────────────────────────

function makeLLM(
  textsOrFn: (string | null)[] | ((prompt: string, idx: number) => string | null),
): LLMLike & { generate: ReturnType<typeof vi.fn> } {
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
      usage: { input_tokens: 50, output_tokens: 200 },
      cost_usd: 0.003,
      latency_ms: 500,
      provider: 'mock',
      model: 'mock-model',
    }
  })
  return { generate } as LLMLike & { generate: ReturnType<typeof vi.fn> }
}

/** 内存 DB stub —— 不写真实 SQLite，只记录 row 状态，让 LLMQueue 流程能跑通。 */
function makeMemoryDb() {
  const rows = new Map<string, Record<string, unknown>>()
  const execute = vi.fn(async (sql: string, params: unknown[] = []) => {
    if (sql.includes('INSERT OR IGNORE INTO llm_run_jobs')) {
      const [job_id, run_id, doc_id, agent_kind, prompt_hash, , created_at, updated_at] = params as [
        string, string, string | null, string, string, string, number, number,
      ]
      if (!rows.has(job_id)) {
        rows.set(job_id, {
          job_id,
          run_id,
          doc_id,
          agent_kind,
          prompt_hash,
          status: 'pending',
          result_json: null,
          error_message: null,
          retried_count: 0,
          schema_version: 1,
          created_at,
          updated_at,
        })
      }
    } else if (sql.includes('UPDATE llm_run_jobs')) {
      // 取最后一个参数 = job_id
      const job_id = params[params.length - 1] as string
      const row = rows.get(job_id)
      if (row) {
        const [status, result_json, error_message] = params as [string, string | null, string | null, ...unknown[]]
        row.status = status
        row.result_json = result_json
        row.error_message = error_message
        if (sql.includes('retried_count=retried_count+1')) {
          row.retried_count = (row.retried_count as number) + 1
        }
      }
    } else if (sql.includes('DELETE FROM llm_run_jobs')) {
      const run_id = params[0] as string
      for (const [k, v] of rows.entries()) {
        if (v.run_id === run_id) rows.delete(k)
      }
    }
    return { rowsAffected: 1 }
  })
  const select = vi.fn(async () => Array.from(rows.values()))
  return { execute, select, _rows: rows }
}

// ──────────────────────── Reset ────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
})

// ──────────────────────── parseSummarizerJson ────────────────────────

describe('parseSummarizerJson', () => {
  it('解析裸 JSON object（含 summary 字段）', () => {
    const out = parseSummarizerJson('{"summary":"## 背景\\n这是一篇文献。","key_points":["a"],"language":"zh"}')
    expect(out).not.toBeNull()
    expect((out as { summary: string }).summary).toContain('## 背景')
  })

  it('剥 ```json fence', () => {
    const out = parseSummarizerJson('```json\n{"summary":"hello world","key_points":[],"language":"en"}\n```')
    expect((out as { summary: string }).summary).toBe('hello world')
  })

  it('从前后解释里挑出 JSON', () => {
    const out = parseSummarizerJson(
      'Here is your summary:\n{"summary":"x","key_points":["k1"],"language":"zh"}\nThanks.',
    )
    expect((out as { summary: string }).summary).toBe('x')
  })

  it('多个候选对象 → 取第一个含 summary 的', () => {
    const out = parseSummarizerJson(
      '{"unrelated":1} {"summary":"first","key_points":[],"language":"zh"} {"summary":"second"}',
    )
    expect((out as { summary: string }).summary).toBe('first')
  })

  it('完全无效 → null', () => {
    expect(parseSummarizerJson('not a json at all')).toBeNull()
    expect(parseSummarizerJson('')).toBeNull()
    expect(parseSummarizerJson(null)).toBeNull()
  })
})

// ──────────────────────── sanitizeSummarizerOutput ────────────────────────

describe('sanitizeSummarizerOutput', () => {
  it('合规输出 → 返回 sanitized', () => {
    const r = sanitizeSummarizerOutput({
      summary: '这是一段足够长的中文摘要文本描述了背景方法结果与启发能通过最小 50 字符校验门槛要求确保文本长度足够支撑 sanitize 通过。',
      key_points: ['k1', 'k2', 'k3'],
      problems: ['p1'],
      language: 'zh',
    })
    expect('reason' in r).toBe(false)
    if (!('reason' in r)) {
      expect(r.summary.length).toBeGreaterThanOrEqual(50)
      expect(r.keyPoints).toHaveLength(3)
      expect(r.problems).toHaveLength(1)
      expect(r.language).toBe('zh')
    }
  })

  it('summary 缺失 → reason', () => {
    const r = sanitizeSummarizerOutput({ summary: '', key_points: ['x'], language: 'zh' })
    expect((r as { reason: string }).reason).toMatch(/summary/i)
  })

  it('summary 太短（< 50 字符）→ reason', () => {
    const r = sanitizeSummarizerOutput({ summary: 'too short', key_points: ['x'], language: 'zh' })
    expect((r as { reason: string }).reason).toMatch(/too short/i)
  })

  it('summary 含占位符 `{背景}` → reason', () => {
    const r = sanitizeSummarizerOutput({
      summary: '{背景} 用了 X，{方法}用了 Y，{结果}发现 Z，{启发}建议 W，足够长达到 50 字符校验门槛。',
      key_points: ['k1'],
      language: 'zh',
    })
    expect((r as { reason: string }).reason).toMatch(/placeholder/i)
  })

  it('summary 含 `[abstract]` 模板片段 → reason', () => {
    const r = sanitizeSummarizerOutput({
      summary: 'See [abstract] for details. We need to expand the summary text to reach the minimum 50 character threshold here.',
      key_points: ['k1'],
      language: 'en',
    })
    expect((r as { reason: string }).reason).toMatch(/placeholder/i)
  })

  it('keyPoints 全是占位符 → reason', () => {
    const r = sanitizeSummarizerOutput({
      summary: '这是一段足够长的摘要文本以通过 50 字符校验里面有正常的中文内容描述背景方法结果和启发并且确保通过 sanitize 流程不被拒绝。',
      key_points: ['示例', 'TBD', '...'],
      language: 'zh',
    })
    expect((r as { reason: string }).reason).toMatch(/keyPoints/i)
  })

  it('keyPoints 有 1 条非占位符 → 通过', () => {
    const r = sanitizeSummarizerOutput({
      summary: '这是一段足够长的摘要文本以通过 50 字符校验里面有正常的中文内容描述背景方法结果和启发并且确保通过 sanitize 流程不被拒绝。',
      key_points: ['示例', 'TBD', '真实要点'],
      language: 'zh',
    })
    expect('reason' in r).toBe(false)
    if (!('reason' in r)) {
      expect(r.keyPoints).toEqual(['真实要点'])
    }
  })

  it('language 字段消毒（默认 zh，en 透传）', () => {
    const enR = sanitizeSummarizerOutput({
      summary: 'A long enough English summary here describing background methods results and implications, well over fifty chars.',
      key_points: ['k1'],
      language: 'en',
    })
    expect('reason' in enR).toBe(false)
    if (!('reason' in enR)) expect(enR.language).toBe('en')

    const unknownR = sanitizeSummarizerOutput({
      summary: '这是一段足够长的摘要文本以通过 50 字符校验里面有正常的中文内容描述背景方法结果和启发并且确保通过 sanitize 流程不被拒绝。',
      key_points: ['k1'],
      language: 'pirate',
    })
    expect('reason' in unknownR).toBe(false)
    if (!('reason' in unknownR)) expect(unknownR.language).toBe('zh')
  })

  it('keyPoints / problems 数组上限（5 / 3）', () => {
    const r = sanitizeSummarizerOutput({
      summary: '这是一段足够长的摘要文本以通过 50 字符校验里面有正常的中文内容描述背景方法结果和启发并且确保通过 sanitize 流程不被拒绝。',
      key_points: ['k1', 'k2', 'k3', 'k4', 'k5', 'k6', 'k7'],
      problems: ['p1', 'p2', 'p3', 'p4', 'p5'],
      language: 'zh',
    })
    expect('reason' in r).toBe(false)
    if (!('reason' in r)) {
      expect(r.keyPoints).toHaveLength(5)
      expect(r.problems).toHaveLength(3)
    }
  })

  it('非 object → reason', () => {
    expect((sanitizeSummarizerOutput(null) as { reason: string }).reason).toBeDefined()
    expect((sanitizeSummarizerOutput('string') as { reason: string }).reason).toBeDefined()
  })
})

// ──────────────────────── summarizeSingle: happy path ────────────────────────

const VALID_SUMMARY_JSON = JSON.stringify({
  summary:
    '## 背景\n这篇论文研究了 Transformer 架构。\n## 方法\n提出了 self-attention 机制取代 RNN。\n## 结果\n在翻译任务上达到 SOTA。\n## 启发\n开启了大模型时代。',
  key_points: ['Self-attention 取代 RNN', '并行训练效率提升', '在 WMT 翻译任务 SOTA'],
  problems: ['长序列内存开销大', '需要大量训练数据'],
  language: 'zh',
})

function baseDoc() {
  return {
    docId: 'doc-001',
    title: 'Attention is All You Need',
    abstract: 'We propose a new architecture, the Transformer, based solely on attention mechanisms.',
    authors: 'Vaswani et al.',
    year: 2017,
  }
}

describe('summarizeSingle: happy path', () => {
  it('LLM 返合规 JSON → 返回 SummarizeOutput', async () => {
    const llm = makeLLM([VALID_SUMMARY_JSON])
    const summarizer = new LLMSummarizer(llm)
    const out = await summarizer.summarizeSingle({ doc: baseDoc() })

    expect(out.docId).toBe('doc-001')
    expect(out.summary).toContain('## 背景')
    expect(out.summary).toContain('## 方法')
    expect(out.keyPoints).toHaveLength(3)
    expect(out.problems).toHaveLength(2)
    expect(out.language).toBe('zh')
    expect(out.quality).toBe('high')
    expect(llm.generate).toHaveBeenCalledTimes(1)
    // 透传 temperature + response_format
    expect(llm.generate.mock.calls[0][1]).toEqual({
      temperature: 0.3,
      response_format: { type: 'json_object' },
    })
  })

  it('targetLanguage=en → prompt 含 en，输出 language=en', async () => {
    const enJson = JSON.stringify({
      summary: '## Background\nWe study Transformers.\n## Methods\nSelf-attention.\n## Results\nSOTA.\n## Implications\nLarge models era.',
      key_points: ['Self-attention replaces RNN'],
      language: 'en',
    })
    const llm = makeLLM([enJson])
    const summarizer = new LLMSummarizer(llm)
    const out = await summarizer.summarizeSingle({ doc: baseDoc(), targetLanguage: 'en' })

    expect(out.language).toBe('en')
    expect(out.summary).toContain('## Background')
    // prompt 应包含 target language
    const promptArg = llm.generate.mock.calls[0][0] as string
    expect(promptArg).toContain('en')
  })
})

// ──────────────────────── summarizeSingle: 占位符过滤 → 重试 ────────────────────────

describe('summarizeSingle: 占位符过滤', () => {
  it('第一次返 `{背景}` 占位符 → 第二次合规 → 成功', async () => {
    const placeholderJson = JSON.stringify({
      summary: '{背景}用了 X，{方法}用了 Y，{结果}发现 Z，{启发}建议 W，凑够 50 字符的不合规摘要内容。',
      key_points: ['k1'],
      language: 'zh',
    })
    const llm = makeLLM([placeholderJson, VALID_SUMMARY_JSON])
    const summarizer = new LLMSummarizer(llm)
    const out = await summarizer.summarizeSingle({ doc: baseDoc() })

    expect(out.quality).toBe('high')
    expect(out.summary).toContain('## 背景\n这篇')
    expect(llm.generate).toHaveBeenCalledTimes(2)
    // 第二次 prompt 应含纠正提示
    const retryPrompt = llm.generate.mock.calls[1][0] as string
    expect(retryPrompt).toMatch(/上一轮失败原因/)
    expect(retryPrompt).toMatch(/placeholder/i)
  })

  it('两次都是占位符 → fallback quality=low', async () => {
    const placeholderJson = JSON.stringify({
      summary: '{背景}用了 X，{方法}用了 Y，{结果}发现 Z，{启发}建议 W，凑够 50 字符的不合规摘要内容。',
      key_points: ['k1'],
      language: 'zh',
    })
    const llm = makeLLM([placeholderJson, placeholderJson])
    const summarizer = new LLMSummarizer(llm)
    const out = await summarizer.summarizeSingle({ doc: baseDoc() })

    expect(out.quality).toBe('low')
    // fallback 用 abstract
    expect(out.summary).toBe(baseDoc().abstract)
    expect(out.keyPoints).toEqual([])
  })
})

// ──────────────────────── summarizeSingle: summary 太短 ────────────────────────

describe('summarizeSingle: summary 太短', () => {
  it('第一次 summary="ok" 太短 → 第二次合规 → 成功', async () => {
    const tooShort = JSON.stringify({
      summary: 'ok',
      key_points: ['k1'],
      language: 'zh',
    })
    const llm = makeLLM([tooShort, VALID_SUMMARY_JSON])
    const summarizer = new LLMSummarizer(llm)
    const out = await summarizer.summarizeSingle({ doc: baseDoc() })

    expect(out.quality).toBe('high')
    expect(llm.generate).toHaveBeenCalledTimes(2)
  })

  it('两次都太短 → fallback', async () => {
    const tooShort = JSON.stringify({
      summary: 'ok',
      key_points: ['k1'],
      language: 'zh',
    })
    const llm = makeLLM([tooShort, tooShort])
    const summarizer = new LLMSummarizer(llm)
    const out = await summarizer.summarizeSingle({ doc: baseDoc() })

    expect(out.quality).toBe('low')
    expect(out.summary).toBe(baseDoc().abstract)
  })
})

// ──────────────────────── summarizeSingle: keyPoints 不足 ────────────────────────

describe('summarizeSingle: keyPoints 不足', () => {
  it('第一次 key_points 空数组 → 重试 → 成功', async () => {
    const noKeyPoints = JSON.stringify({
      summary: '这是一段足够长的合规摘要文本，描述背景方法结果与启发，能通过最小 50 字符校验门槛。',
      key_points: [],
      language: 'zh',
    })
    const llm = makeLLM([noKeyPoints, VALID_SUMMARY_JSON])
    const summarizer = new LLMSummarizer(llm)
    const out = await summarizer.summarizeSingle({ doc: baseDoc() })

    expect(out.quality).toBe('high')
    expect(out.keyPoints).toHaveLength(3)
  })
})

// ──────────────────────── summarizeSingle: 全失败 → fallback ────────────────────────

describe('summarizeSingle: 全失败 → fallback abstract，quality=low', () => {
  it('两次都返 garbage → fallback 用 abstract', async () => {
    const llm = makeLLM(() => 'totally not json at all')
    const summarizer = new LLMSummarizer(llm)
    const out = await summarizer.summarizeSingle({ doc: baseDoc() })

    expect(out.quality).toBe('low')
    expect(out.summary).toBe(baseDoc().abstract)
    expect(out.keyPoints).toEqual([])
    expect(out.language).toBe('zh')
  })

  it('两次都返 null → fallback', async () => {
    const llm = makeLLM(() => null)
    const summarizer = new LLMSummarizer(llm)
    const out = await summarizer.summarizeSingle({ doc: baseDoc() })

    expect(out.quality).toBe('low')
    expect(out.summary).toBe(baseDoc().abstract)
  })

  it('LLM 总是 throw → fallback', async () => {
    const llm: LLMLike = {
      generate: vi.fn(async () => {
        throw new Error('network down')
      }),
    }
    const summarizer = new LLMSummarizer(llm)
    const out = await summarizer.summarizeSingle({ doc: baseDoc() })
    expect(out.quality).toBe('low')
  })

  it('doc 缺 abstract / fulltext / title → fallback 用占位说明', async () => {
    const llm = makeLLM(() => null)
    const summarizer = new LLMSummarizer(llm)
    const out = await summarizer.summarizeSingle({
      doc: { docId: 'd-empty', title: '', abstract: '' },
    })
    // _chooseContent 返 null → 直接 fallback；abstract 也空 → '（无可用内容）'
    expect(out.quality).toBe('low')
    expect(out.summary).toBe('（无可用内容）')
    // LLM 没被调用过（chooseContent 直接返 null）
    expect((llm as { generate: ReturnType<typeof vi.fn> }).generate).not.toHaveBeenCalled()
  })

  it('doc 缺 docId → throw', async () => {
    const llm = makeLLM([VALID_SUMMARY_JSON])
    const summarizer = new LLMSummarizer(llm)
    await expect(
      summarizer.summarizeSingle({ doc: { ...baseDoc(), docId: '' } }),
    ).rejects.toThrow(/docId is required/)
  })
})

// ──────────────────────── summarizeBatch ────────────────────────

describe('summarizeBatch: 10 篇 → onProgress 调 10 次', () => {
  it('走 LLMQueue → 全部 done，progress 调 10 次', async () => {
    const docs = Array.from({ length: 10 }, (_, i) => ({
      docId: `doc-${i}`,
      title: `Title ${i}`,
      abstract: `Abstract ${i}, this is sufficient content for testing batch summarization at scale level.`,
      authors: `Author ${i}`,
      year: 2020 + i,
    }))
    const llm = makeLLM(() => VALID_SUMMARY_JSON)
    const memoryDb = makeMemoryDb()
    const queue = new LLMQueue({ concurrency: 4, _dbForTesting: memoryDb })
    const summarizer = new LLMSummarizer(llm, queue)

    const progressCalls: Array<{ done: number; total: number; hasResult: boolean }> = []
    const results = await summarizer.summarizeBatch({
      runId: 'run-001',
      docs,
      onProgress: (done, total, lastResult) => {
        progressCalls.push({ done, total, hasResult: !!lastResult })
      },
    })

    expect(results).toHaveLength(10)
    expect(progressCalls).toHaveLength(10)
    // total 始终是 10
    for (const p of progressCalls) expect(p.total).toBe(10)
    // done 严格递增到 10
    expect(progressCalls[progressCalls.length - 1].done).toBe(10)
    // 全部 high quality
    for (const r of results) {
      expect(r.quality).toBe('high')
      expect(r.keyPoints.length).toBeGreaterThanOrEqual(1)
    }
    // 顺序保留：results[i].docId === `doc-${i}`
    for (let i = 0; i < 10; i++) {
      expect(results[i].docId).toBe(`doc-${i}`)
    }
    expect(llm.generate).toHaveBeenCalledTimes(10)
  })

  it('docs 为空 → 立即返空数组，不调 LLM', async () => {
    const llm = makeLLM([])
    const summarizer = new LLMSummarizer(llm)
    const out = await summarizer.summarizeBatch({ runId: 'r', docs: [] })
    expect(out).toEqual([])
    expect(llm.generate).not.toHaveBeenCalled()
  })

  it('无 queue → 串行 fallback 仍工作', async () => {
    const docs = Array.from({ length: 3 }, (_, i) => ({
      docId: `d-${i}`,
      title: `T${i}`,
      abstract: 'Abstract content for testing serial fallback path with sufficient length over fifty chars.',
    }))
    const llm = makeLLM(() => VALID_SUMMARY_JSON)
    const summarizer = new LLMSummarizer(llm) // no queue
    const progressCalls: Array<[number, number]> = []
    const out = await summarizer.summarizeBatch({
      runId: 'r',
      docs,
      onProgress: (d, t) => progressCalls.push([d, t]),
    })
    expect(out).toHaveLength(3)
    expect(progressCalls).toEqual([[1, 3], [2, 3], [3, 3]])
  })

  it('部分 fallback：第 5 篇 LLM 全 garbage → quality=low，但流程不中断', async () => {
    // 用 title 携带 docId 让 prompt 可路由（title 会被渲染进 prompt）
    const docs = Array.from({ length: 6 }, (_, i) => ({
      docId: `d-${i}`,
      title: `Title-marker-${i}`,
      abstract: `Abstract content for doc ${i} with sufficient length to pass content choice gate over fifty chars.`,
    }))
    const llm: LLMLike = {
      generate: vi.fn(async (prompt: string) => {
        // doc index 4 的 prompt 全返 null → 两次 attempt 都失败 → fallback low
        if (prompt.includes('Title-marker-4')) return null
        return {
          text: VALID_SUMMARY_JSON,
          usage: { input_tokens: 1, output_tokens: 1 },
          cost_usd: 0,
          latency_ms: 1,
          provider: 'mock',
          model: 'm',
        }
      }),
    }
    const memoryDb = makeMemoryDb()
    const queue = new LLMQueue({ concurrency: 4, _dbForTesting: memoryDb })
    const summarizer = new LLMSummarizer(llm, queue)
    const out = await summarizer.summarizeBatch({ runId: 'r', docs })

    expect(out).toHaveLength(6)
    const lowCount = out.filter((o) => o.quality === 'low').length
    const highCount = out.filter((o) => o.quality === 'high').length
    expect(lowCount).toBe(1)
    expect(highCount).toBe(5)
    const lowDoc = out.find((o) => o.quality === 'low')
    expect(lowDoc?.docId).toBe('d-4')
  })
})
