/**
 * LiteratureWriter 单测
 *
 * Mock 策略：把 fs/files 的 invoke-based API 替换成内存 Map 实现。
 * 走完整 _atomicWrite 路径（写 .tmp → readback → 覆盖目标 → 删 .tmp），保证 round-trip。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { LiteratureWriter, _internal } from '../literatureWriter'

vi.mock('../files', () => {
  const store = new Map<string, string>()
  return {
    _store: store,
    async writeText(rel: string, content: string) {
      store.set(rel, content)
    },
    async readText(rel: string) {
      return store.has(rel) ? store.get(rel)! : null
    },
    async removePath(rel: string) {
      store.delete(rel)
    },
    async fileExists(rel: string) {
      return store.has(rel)
    },
    async writeBytes() { /* unused */ },
    async readBytes() { return null },
    async fileSize() { return null },
    async listDir() { return [] },
    async downloadToFile() { return { size: 0 } },
  }
})

// 直接 dynamic import 拿到 mock 上的 _store（绕开 module cache 不一致）
async function getStore(): Promise<Map<string, string>> {
  const m = await import('../files') as unknown as { _store: Map<string, string> }
  return m._store
}

beforeEach(async () => {
  const store = await getStore()
  store.clear()
})

afterEach(async () => {
  const store = await getStore()
  store.clear()
})

describe('LiteratureWriter.writeDoc', () => {
  it('单篇文献：frontmatter 含 doc_id/title/authors/score/bucket/tags', async () => {
    const w = new LiteratureWriter('proj-001', 'Demo Project')
    await w.writeDoc({
      docId: 'arxiv:2501.0001',
      title: 'Foo Bar Baz',
      authors: ['Alice', 'Bob'],
      year: 2025,
      source: 'arxiv',
      doi: '10.1/foo',
      summary: '一段中文摘要',
      keyPoints: ['要点 1', '要点 2'],
      score: 78,
      bucket: 'relevant',
      tags: ['ml', 'transformer'],
      addedAt: '2026-05-08',
    })
    const store = await getStore()
    // 安全 docId： : 替换成 -
    const expectedKey = 'projects/Demo-Project__proj-0/library/docs/arxiv-2501.0001.md'
    const text = store.get(expectedKey)
    expect(text).toBeTruthy()
    expect(text).toMatch(/doc_id: "?arxiv:2501\.0001"?/)
    expect(text).toContain('title: Foo Bar Baz')
    expect(text).toContain('authors: Alice, Bob')
    expect(text).toContain('year: 2025')
    expect(text).toContain('source: arxiv')
    expect(text).toContain('doi: 10.1/foo')
    expect(text).toContain('score: 78')
    expect(text).toContain('bucket: relevant')
    expect(text).toContain('tags: [ml, transformer]')
    expect(text).toContain('added_at: 2026-05-08')
    expect(text).toContain('# Foo Bar Baz')
    expect(text).toContain('一段中文摘要')
    expect(text).toContain('- 要点 1')
    expect(text).toContain('- 要点 2')
    expect(text).toContain('## 笔记')
  })

  it('docId 含特殊字符 → 文件名安全（: → -）', async () => {
    const w = new LiteratureWriter('proj-001')
    await w.writeDoc({ docId: 'a:b/c', title: 'X' })
    const store = await getStore()
    const key = 'projects/proj-001/library/docs/a-b-c.md'
    expect(store.get(key)).toBeTruthy()
  })

  it('事务式：写完 .tmp 应被删除', async () => {
    const w = new LiteratureWriter('proj-001')
    await w.writeDoc({ docId: 'd1', title: 'T1' })
    const store = await getStore()
    const tmp = 'projects/proj-001/library/docs/d1.md.tmp'
    expect(store.has(tmp)).toBe(false)
    expect(store.has('projects/proj-001/library/docs/d1.md')).toBe(true)
  })

  it('docId 为空抛错', async () => {
    const w = new LiteratureWriter('proj-001')
    await expect(w.writeDoc({ docId: '', title: 'X' })).rejects.toThrow(/docId/)
  })

  it('projectId 含路径符号被 assertSafeId 拒绝', () => {
    expect(() => new LiteratureWriter('../evil')).toThrow()
  })

  it('addedAt 缺省 → 当天 ISO yyyy-mm-dd', async () => {
    const w = new LiteratureWriter('proj-1')
    await w.writeDoc({ docId: 'd1', title: 'T' })
    const store = await getStore()
    const text = store.get('projects/proj-1/library/docs/d1.md')!
    expect(text).toMatch(/added_at: \d{4}-\d{2}-\d{2}/)
  })
})

describe('LiteratureWriter.writeIndex', () => {
  it('空数组 → "暂无文献"', async () => {
    const w = new LiteratureWriter('p')
    await w.writeIndex([])
    const store = await getStore()
    const text = store.get('projects/p/library/index.md')!
    expect(text).toContain('# 文献库索引')
    expect(text).toContain('共 0 篇')
    expect(text).toContain('_暂无文献_')
  })

  it('按桶 / 按 round / 按 tag 分组', async () => {
    const w = new LiteratureWriter('p')
    await w.writeIndex([
      { docId: 'a', title: 'A', bucket: 'very_relevant', roundNumber: 1, tags: ['ml'] },
      { docId: 'b', title: 'B', bucket: 'relevant', roundNumber: 1, tags: ['ml', 'nlp'] },
      { docId: 'c', title: 'C', bucket: 'relevant', roundNumber: 2 },
    ])
    const store = await getStore()
    const text = store.get('projects/p/library/index.md')!
    expect(text).toContain('共 3 篇')
    // 按桶
    expect(text).toContain('### 强相关（1）')
    expect(text).toContain('### 相关（2）')
    expect(text).toContain('[A](docs/a.md)')
    expect(text).toContain('[B](docs/b.md)')
    expect(text).toContain('[C](docs/c.md)')
    // 按 round
    expect(text).toContain('### Round 1（2）')
    expect(text).toContain('### Round 2（1）')
    // 按 tag — ml 出现 2 次
    expect(text).toContain('### #ml（2）')
    expect(text).toContain('### #nlp（1）')
  })

  it('uncategorized 桶（缺省 bucket）', async () => {
    const w = new LiteratureWriter('p')
    await w.writeIndex([{ docId: 'x', title: 'X' }])
    const store = await getStore()
    const text = store.get('projects/p/library/index.md')!
    expect(text).toContain('### 未分类（1）')
  })
})

describe('LiteratureWriter.readDoc', () => {
  it('round-trip：writeDoc → readDoc 拿到 frontmatter + body', async () => {
    const w = new LiteratureWriter('p')
    await w.writeDoc({
      docId: 'r1',
      title: 'Title',
      authors: 'X',
      year: 2024,
      source: 'arxiv',
      bucket: 'uncertain',
      tags: ['a', 'b'],
    })
    const parsed = await w.readDoc('r1')
    expect(parsed).toBeTruthy()
    expect(parsed!.frontmatter.doc_id).toBe('r1')
    expect(parsed!.frontmatter.title).toBe('Title')
    expect(parsed!.frontmatter.year).toBe(2024)
    expect(parsed!.frontmatter.bucket).toBe('uncertain')
    expect(Array.isArray(parsed!.frontmatter.tags)).toBe(true)
    expect((parsed!.frontmatter.tags as unknown[])).toEqual(['a', 'b'])
    expect(parsed!.body).toContain('# Title')
    expect(parsed!.body).toContain('## 笔记')
    expect(parsed!.noteMarkdown).toContain('（用户可手动编辑）')
  })

  it('文件不存在 → null', async () => {
    const w = new LiteratureWriter('p')
    expect(await w.readDoc('ghost')).toBeNull()
  })

  it('docId 空字符串 → null（不抛）', async () => {
    const w = new LiteratureWriter('p')
    expect(await w.readDoc('')).toBeNull()
  })
})

describe('LiteratureWriter.appendNote', () => {
  it('已存在文献：追加 user 笔记到 ## 笔记 段', async () => {
    const w = new LiteratureWriter('p')
    await w.writeDoc({ docId: 'd1', title: 'T' })
    await w.appendNote('d1', '这是一条用户笔记')
    const parsed = await w.readDoc('d1')
    expect(parsed!.noteMarkdown).toContain('这是一条用户笔记')
    // 占位「（用户可手动编辑）」应被替换掉
    expect(parsed!.noteMarkdown).not.toContain('（用户可手动编辑）')
  })

  it('附加多条 → 都保留', async () => {
    const w = new LiteratureWriter('p')
    await w.writeDoc({ docId: 'd1', title: 'T' })
    await w.appendNote('d1', '笔记 A')
    await w.appendNote('d1', '笔记 B')
    const parsed = await w.readDoc('d1')
    expect(parsed!.noteMarkdown).toContain('笔记 A')
    expect(parsed!.noteMarkdown).toContain('笔记 B')
  })

  it('文献不存在 → 抛错', async () => {
    const w = new LiteratureWriter('p')
    await expect(w.appendNote('ghost', 'x')).rejects.toThrow(/not found/)
  })

  it('空 note → no-op', async () => {
    const w = new LiteratureWriter('p')
    await w.writeDoc({ docId: 'd1', title: 'T' })
    const before = (await w.readDoc('d1'))!.body
    await w.appendNote('d1', '   ')
    const after = (await w.readDoc('d1'))!.body
    expect(after).toBe(before)
  })
})

describe('frontmatter parser internals', () => {
  it('serialize → parse round-trip 保数组 + bool + 数字', () => {
    const fm = {
      doc_id: 'd1',
      title: 'Hello: World',
      authors: 'X',
      year: 2025,
      source: 'arxiv',
      doi: '',
      score: 80,
      bucket: 'relevant',
      tags: ['ml', 'nlp'],
      added_at: '2026-05-08',
    }
    const text = _internal.serializeFrontmatter(fm)
    const wrapped = `${text}\n\nbody here`
    const parsed = _internal.parseFrontmatter(wrapped)
    expect(parsed.fm.doc_id).toBe('d1')
    expect(parsed.fm.title).toBe('Hello: World')
    expect(parsed.fm.year).toBe(2025)
    expect(parsed.fm.score).toBe(80)
    expect(parsed.fm.tags).toEqual(['ml', 'nlp'])
    expect(parsed.body.trim()).toBe('body here')
  })

  it('isoToday 形如 yyyy-mm-dd', () => {
    expect(_internal.isoToday()).toMatch(/^\d{4}-\d{2}-\d{2}$/)
  })
})
