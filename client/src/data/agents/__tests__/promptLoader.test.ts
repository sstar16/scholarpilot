/**
 * promptLoader 单测 — 验证：
 *  1. loadPrompt 返回非空字符串
 *  2. frontmatter 正确解析（version / temperature / max_iterations 等）
 *  3. render() 替换 $var / ${var} 模板
 *  4. 不存在的 prompt 名抛错
 */
import { describe, it, expect, beforeEach } from 'vitest'

import {
  loadPrompt,
  loadAll,
  listPrompts,
  _clearCache,
  PromptFile,
} from '../promptLoader'

beforeEach(() => {
  _clearCache()
})

describe('loadPrompt', () => {
  it('agents/scoring：返回非空 body', () => {
    const pf = loadPrompt('agents/scoring')
    expect(pf).toBeInstanceOf(PromptFile)
    expect(pf.body.length).toBeGreaterThan(100)
    expect(pf.name).toBe('agents/scoring')
  })

  it('agents/scoring frontmatter：name/version/temperature/model_hint', () => {
    const pf = loadPrompt('agents/scoring')
    expect(pf.get('name')).toBe('scoring')
    expect(pf.get('version')).toBe(3)
    expect(pf.get('temperature')).toBe(0.1)
    expect(pf.get('model_hint')).toBe('sonnet')
  })

  it('agents/query_plan_agentic：max_iterations / preview_source 解析', () => {
    const pf = loadPrompt('agents/query_plan_agentic')
    expect(pf.get('max_iterations')).toBe(5)
    expect(pf.get('preview_source')).toBe('local_kb')
    expect(pf.get('model_hint')).toBe('opus')
  })

  it('agents/intent_analysis：max_retries / temperature', () => {
    const pf = loadPrompt('agents/intent_analysis')
    expect(pf.get('max_retries')).toBe(2)
    expect(pf.get('temperature')).toBe(0.4)
  })

  it('agents/memory_update：基础字段', () => {
    const pf = loadPrompt('agents/memory_update')
    expect(pf.get('name')).toBe('memory_update')
    expect(pf.get('version')).toBe(4)
  })

  it('agents/query_plan_legacy：基础字段', () => {
    const pf = loadPrompt('agents/query_plan_legacy')
    expect(pf.get('name')).toBe('query_plan_legacy')
  })

  it('不存在的 prompt name → 抛 Error', () => {
    expect(() => loadPrompt('agents/nonexistent_xxx')).toThrowError(/prompt not found/)
  })

  it('get(key, default)：缺失字段返回 default', () => {
    const pf = loadPrompt('agents/scoring')
    expect(pf.get('totally_made_up', 'fallback_val')).toBe('fallback_val')
  })

  it('两次 loadPrompt 同名命中 cache（同实例）', () => {
    const a = loadPrompt('agents/scoring')
    const b = loadPrompt('agents/scoring')
    expect(a).toBe(b)
  })
})

describe('PromptFile.render', () => {
  it('替换 $var 占位符', () => {
    const pf = new PromptFile('test', {}, 'hello $name, you are $age')
    expect(pf.render({ name: 'alice', age: 25 })).toBe('hello alice, you are 25')
  })

  it('替换 ${var} 占位符', () => {
    const pf = new PromptFile('test', {}, 'data: ${value}')
    expect(pf.render({ value: 'xyz' })).toBe('data: xyz')
  })

  it('缺失变量保留原字面量（safe_substitute 行为）', () => {
    const pf = new PromptFile('test', {}, 'hello $name, $unknown')
    expect(pf.render({ name: 'alice' })).toBe('hello alice, $unknown')
  })

  it('JSON body 里的 {...} 不被误碰', () => {
    const body = '{"score": 8.5, "rationale": "..."}'
    const pf = new PromptFile('test', {}, body)
    expect(pf.render({ score: 0 })).toBe(body)
  })

  it('空 vars 返回原 body', () => {
    const pf = new PromptFile('test', {}, 'no $vars here')
    expect(pf.render({})).toBe('no $vars here')
  })

  it('agents/scoring render：替换 project_description / title 等', () => {
    const pf = loadPrompt('agents/scoring')
    const rendered = pf.render({
      project_description: 'AI in healthcare',
      memory_section: '',
      title: 'Test paper',
      doc_type: 'literature',
      source: 'arxiv',
      publication_date: '2024-01-01',
      citation_count: 100,
      authors: 'A; B',
      abstract: 'Lorem ipsum',
      extra_info: '',
    })
    expect(rendered).toContain('AI in healthcare')
    expect(rendered).toContain('Test paper')
    expect(rendered).toContain('arxiv')
    // 未替换变量不应残留 $ 形式（render 后应该全替换）
    expect(rendered).not.toMatch(/\$project_description/)
  })
})

describe('listPrompts / loadAll', () => {
  it('listPrompts 包含核心 prompt（含 graph_extraction）', () => {
    const list = listPrompts()
    expect(list).toContain('agents/scoring')
    expect(list).toContain('agents/query_plan_agentic')
    expect(list).toContain('agents/query_plan_legacy')
    expect(list).toContain('agents/intent_analysis')
    expect(list).toContain('agents/memory_update')
    expect(list).toContain('agents/memory_markdown_user')
    expect(list).toContain('agents/memory_markdown_project')
    expect(list).toContain('agents/graph_extraction')
    // 数量 ≥ 8（其他 agent 可能并行注册更多）
    expect(list.length).toBeGreaterThanOrEqual(8)
  })

  it('loadAll 加载所有 prompt 不抛异常', () => {
    const all = loadAll()
    expect(Object.keys(all).length).toBeGreaterThanOrEqual(8)
    for (const pf of Object.values(all)) {
      expect(pf.body.length).toBeGreaterThan(0)
    }
  })
})
