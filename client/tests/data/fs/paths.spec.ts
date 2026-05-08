import { describe, it, expect } from 'vitest'

import { PATHS, isSafeId, assertSafeId } from '@/data/fs/paths'

describe('paths', () => {
  it('PATHS.pdfFile 拼正确路径', () => {
    expect(PATHS.pdfFile('proj-1', 'doc-2')).toBe('projects/proj-1/pdfs/doc-2.pdf')
  })

  it('PATHS.fulltextFile / noteFile 用 forward slash', () => {
    expect(PATHS.fulltextFile('p', 'd')).toBe('projects/p/full_text/d.txt')
    expect(PATHS.noteFile('p', 'd')).toBe('projects/p/notes/d.md')
  })

  it('isSafeId 拒绝路径符号 / 空格 / 中文', () => {
    expect(isSafeId('abc-123_def.ext')).toBe(true)
    expect(isSafeId('../escape')).toBe(false)
    expect(isSafeId('with space')).toBe(false)
    expect(isSafeId('中文 id')).toBe(false)
    expect(isSafeId('a/b')).toBe(false)
    expect(isSafeId('a\\b')).toBe(false)
  })

  it('assertSafeId 不安全时抛错', () => {
    expect(() => assertSafeId('safe-1')).not.toThrow()
    expect(() => assertSafeId('../bad')).toThrow(/Unsafe/)
  })
})
