import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}))

import { invoke } from '@tauri-apps/api/core'
import {
  parseFrontmatter,
  serializeWithFrontmatter,
  listMemoryFiles,
  readMemoryFile,
  readMemoryRaw,
  writeMemoryFile,
  writeMemoryRaw,
  deleteMemoryFile,
  memoryFileExists,
  ensureMemoryIndex,
  applyMemoryUpdate,
  rebuildMemoryIndex,
  readUserMemoryMd,
  writeUserMemoryMd,
  appendUserMemoryEntry,
  promoteToUserMemory,
} from '@/data/memory/memoryRepo'

const mockInvoke = invoke as unknown as ReturnType<typeof vi.fn>

beforeEach(() => {
  mockInvoke.mockReset()
})

describe('parseFrontmatter / serializeWithFrontmatter', () => {
  it('无 frontmatter 直接返回 body', () => {
    const r = parseFrontmatter('# Hello\n\nworld')
    expect(r.meta).toEqual({})
    expect(r.body).toBe('# Hello\n\nworld')
  })

  it('解析基础 yaml 标量', () => {
    const text = `---
name: identity
description: 研究身份
type: identity
updated_at: 1715000000000
---

正文内容`
    const r = parseFrontmatter(text)
    expect(r.meta.name).toBe('identity')
    expect(r.meta.description).toBe('研究身份')
    expect(r.meta.type).toBe('identity')
    expect(r.meta.updated_at).toBe(1715000000000)
    expect(r.body).toBe('正文内容')
  })

  it('解析 inline list', () => {
    const text = `---
tags: [a, b, c]
nums: [1, 2, 3]
---

body`
    const r = parseFrontmatter(text)
    expect(r.meta.tags).toEqual(['a', 'b', 'c'])
    expect(r.meta.nums).toEqual([1, 2, 3])
  })

  it('解析 boolean / null', () => {
    const text = `---
enabled: true
disabled: false
nothing: null
---

body`
    const r = parseFrontmatter(text)
    expect(r.meta.enabled).toBe(true)
    expect(r.meta.disabled).toBe(false)
    expect(r.meta.nothing).toBeNull()
  })

  it('支持 quoted string', () => {
    const text = `---
name: "with: colon"
alt: 'single'
---

body`
    const r = parseFrontmatter(text)
    expect(r.meta.name).toBe('with: colon')
    expect(r.meta.alt).toBe('single')
  })

  it('serialize round-trip', () => {
    const meta = { name: 'identity', type: 'identity', updated_at: 1715000000000 }
    const body = '# body content'
    const text = serializeWithFrontmatter(meta, body)
    const parsed = parseFrontmatter(text)
    expect(parsed.meta.name).toBe(meta.name)
    expect(parsed.meta.type).toBe(meta.type)
    expect(parsed.meta.updated_at).toBe(meta.updated_at)
    expect(parsed.body).toBe(body)
  })

  it('serialize 空 meta 直接返回 body', () => {
    expect(serializeWithFrontmatter({}, 'body')).toBe('body')
  })

  it('serialize 含特殊字符自动加引号', () => {
    const text = serializeWithFrontmatter({ name: 'with: colon' }, 'body')
    expect(text).toContain('name: "with: colon"')
  })
})

describe('listMemoryFiles', () => {
  it('过滤非 .md 和子目录', async () => {
    mockInvoke.mockResolvedValue([
      { name: 'MEMORY.md', is_dir: false, size: 100, modified_ms: 1000 },
      { name: 'identity.md', is_dir: false, size: 200, modified_ms: 2000 },
      { name: 'subdir', is_dir: true, size: 0, modified_ms: 3000 },
      { name: 'note.txt', is_dir: false, size: 50, modified_ms: 4000 },
    ])
    const files = await listMemoryFiles('proj-1')
    expect(files).toHaveLength(2)
    expect(files.map((f) => f.name)).toEqual(['MEMORY.md', 'identity.md'])
    expect(files[0].size).toBe(100)
    expect(files[1].updated_at).toBe(2000)
  })

  it('空目录 → 空数组', async () => {
    mockInvoke.mockResolvedValue([])
    expect(await listMemoryFiles('proj-1')).toEqual([])
  })

  it('legacy UUID 兜底：slug 路径空时再试 legacy', async () => {
    mockInvoke
      .mockResolvedValueOnce([]) // slug 路径返回空
      .mockResolvedValueOnce([{ name: 'MEMORY.md', is_dir: false, size: 50, modified_ms: 1000 }])
    const files = await listMemoryFiles('proj-1', 'My Project')
    expect(files).toHaveLength(1)
    expect(mockInvoke).toHaveBeenCalledTimes(2)
  })
})

describe('readMemoryFile / readMemoryRaw', () => {
  it('readMemoryFile 解析 frontmatter', async () => {
    mockInvoke.mockResolvedValue(`---
name: identity
type: identity
---

body`)
    const r = await readMemoryFile('proj-1', 'identity.md')
    expect(r).not.toBeNull()
    expect(r!.meta.name).toBe('identity')
    expect(r!.body).toBe('body')
  })

  it('readMemoryFile 不存在 → null', async () => {
    mockInvoke.mockResolvedValue(null)
    expect(await readMemoryFile('proj-1', 'missing.md')).toBeNull()
  })

  it('readMemoryRaw 返回原文不解析', async () => {
    const raw = '# raw markdown without frontmatter'
    mockInvoke.mockResolvedValue(raw)
    expect(await readMemoryRaw('proj-1', 'note.md')).toBe(raw)
  })
})

describe('writeMemoryFile', () => {
  it('自动 stamp updated_at + 序列化 frontmatter', async () => {
    mockInvoke.mockResolvedValue(undefined)
    const before = Date.now()
    await writeMemoryFile('proj-1', 'identity.md', { name: 'identity', type: 'identity' }, '# body')
    const after = Date.now()

    expect(mockInvoke).toHaveBeenCalledWith(
      'fs_write_text',
      expect.objectContaining({
        relPath: 'projects/proj-1/memory/identity.md',
        content: expect.any(String),
      }),
    )
    const args = mockInvoke.mock.calls[0][1] as { content: string }
    const parsed = parseFrontmatter(args.content)
    expect(parsed.meta.updated_at).toBeGreaterThanOrEqual(before)
    expect(parsed.meta.updated_at).toBeLessThanOrEqual(after)
    expect(parsed.body).toBe('# body')
  })

  it('writeMemoryRaw 不加 frontmatter', async () => {
    mockInvoke.mockResolvedValue(undefined)
    await writeMemoryRaw('proj-1', 'MEMORY.md', '# 索引')
    expect(mockInvoke).toHaveBeenCalledWith(
      'fs_write_text',
      { relPath: 'projects/proj-1/memory/MEMORY.md', content: '# 索引' },
    )
  })
})

describe('deleteMemoryFile / memoryFileExists', () => {
  it('deleteMemoryFile 调 fs_remove', async () => {
    mockInvoke.mockResolvedValue(undefined)
    await deleteMemoryFile('proj-1', 'old.md')
    expect(mockInvoke).toHaveBeenCalledWith('fs_remove', {
      relPath: 'projects/proj-1/memory/old.md',
    })
  })

  it('memoryFileExists 调 fs_exists', async () => {
    mockInvoke.mockResolvedValue(true)
    expect(await memoryFileExists('proj-1', 'identity.md')).toBe(true)
    expect(mockInvoke).toHaveBeenCalledWith('fs_exists', {
      relPath: 'projects/proj-1/memory/identity.md',
    })
  })
})

describe('filename 安全校验', () => {
  it('拒绝 ../', async () => {
    await expect(readMemoryFile('proj-1', '../escape.md')).rejects.toThrow(/invalid memory filename/)
  })

  it('拒绝 forward slash', async () => {
    await expect(readMemoryFile('proj-1', 'sub/file.md')).rejects.toThrow(/invalid memory filename/)
  })

  it('拒绝 backslash', async () => {
    await expect(readMemoryFile('proj-1', 'sub\\file.md')).rejects.toThrow(/invalid memory filename/)
  })

  it('拒绝空字符串', async () => {
    await expect(readMemoryFile('proj-1', '')).rejects.toThrow(/invalid memory filename/)
  })
})

describe('applyMemoryUpdate (P0.5)', () => {
  it('写多 .md 文件 + rebuildMemoryIndex 重建 MEMORY.md', async () => {
    // 调用序列：
    //   backup阶段: fs_list_dir(slug) → fs_read_text(MEMORY.md) → fs_read_text(identity.md)
    //   写detail:   fs_write_text(research_focus.md) → fs_write_text(preferred_topics.md)
    //   rebuild:    fs_list_dir(slug) → fs_read_text(research_focus.md) → fs_read_text(preferred_topics.md) → fs_write_text(MEMORY.md)
    mockInvoke
      // backup: list → 已有 MEMORY.md + identity.md
      .mockResolvedValueOnce([
        { name: 'MEMORY.md', is_dir: false, size: 50, modified_ms: 1000 },
        { name: 'identity.md', is_dir: false, size: 80, modified_ms: 2000 },
      ])
      .mockResolvedValueOnce('# old MEMORY.md')   // read MEMORY.md raw
      .mockResolvedValueOnce('---\nname: identity\n---\n\nold identity') // read identity.md raw
      // write detail files
      .mockResolvedValueOnce(undefined) // write research_focus.md
      .mockResolvedValueOnce(undefined) // write preferred_topics.md
      // rebuild: list (returns all 4 now)
      .mockResolvedValueOnce([
        { name: 'MEMORY.md', is_dir: false, size: 50, modified_ms: 1000 },
        { name: 'identity.md', is_dir: false, size: 80, modified_ms: 2000 },
        { name: 'research_focus.md', is_dir: false, size: 90, modified_ms: 3000 },
        { name: 'preferred_topics.md', is_dir: false, size: 60, modified_ms: 4000 },
      ])
      // rebuild: read each detail for frontmatter
      .mockResolvedValueOnce('---\nname: identity\ntype: identity\nupdated_at: 2000\n---\n\nbody')
      .mockResolvedValueOnce('---\nname: 研究方向\ntype: identity\nupdated_at: 3000\n---\n\nFoo body')
      .mockResolvedValueOnce('---\nname: 偏好主题\ntype: preference\nupdated_at: 4000\n---\n\n- A\n- B')
      // rebuild: write MEMORY.md
      .mockResolvedValueOnce(undefined)

    const update = {
      version: 4,
      index_md: '# 项目记忆 v4\n\n- [研究方向](research_focus.md) — Foo',
      focus: '研究方向',
      files: [
        { filename: 'research_focus.md', type: 'identity', name: '研究方向', description: 'Foo', body: 'Foo body' },
        { filename: 'preferred_topics.md', type: 'preference', name: '偏好主题', description: '2 个', body: '- A\n- B' },
      ],
    }
    const r = await applyMemoryUpdate('proj-1', 'My Project', update)

    expect(r.written).toBe(2)
    expect(r.failed).toEqual([])
    expect(r.rolledBack).toBe(false)

    // detail 文件带 frontmatter
    const writeCalls = mockInvoke.mock.calls.filter((c) => c[0] === 'fs_write_text')
    const detailContent = (writeCalls[0][1] as { content: string }).content
    const parsed = parseFrontmatter(detailContent)
    expect(parsed.meta.name).toBe('研究方向')
    expect(parsed.meta.type).toBe('identity')
    expect(parsed.meta.version).toBe(4)
    expect(parsed.meta.updated_at).toBeGreaterThan(0)
    expect(parsed.body).toBe('Foo body')

    // MEMORY.md 由 rebuildMemoryIndex 生成（含 v4 标题）
    const indexCall = writeCalls[writeCalls.length - 1]
    expect((indexCall[1] as { relPath: string }).relPath).toMatch(/MEMORY\.md$/)
    const indexContent = (indexCall[1] as { content: string }).content
    expect(indexContent).toContain('# 项目记忆 v4')
    // 未在本次 update 提及的 identity.md 也出现在索引里
    expect(indexContent).toContain('identity.md')
  })

  it('单文件写失败 → 回滚已写的 file（有 backup → 回写旧版）', async () => {
    mockInvoke
      // backup: list → a.md 已存在
      .mockResolvedValueOnce([
        { name: 'a.md', is_dir: false, size: 50, modified_ms: 1000 },
      ])
      .mockResolvedValueOnce('# old a content') // read a.md raw backup
      // write a.md OK
      .mockResolvedValueOnce(undefined)
      // write b.md FAIL
      .mockRejectedValueOnce(new Error('disk full'))
      // rollback a.md → write old content back
      .mockResolvedValueOnce(undefined)

    const update = {
      version: 1,
      index_md: '# v1',
      focus: '',
      files: [
        { filename: 'a.md', type: 'identity', name: 'A', description: '', body: 'a' },
        { filename: 'b.md', type: 'note', name: 'B', description: '', body: 'b' },
      ],
    }
    const r = await applyMemoryUpdate('proj-1', null, update)
    expect(r.written).toBe(0)
    expect(r.failed).toEqual(['b.md'])
    expect(r.rolledBack).toBe(true)

    // 回滚 a.md 用 fs_write_text 写旧内容（因为 backup 存在）
    const writeCalls = mockInvoke.mock.calls.filter((c) => c[0] === 'fs_write_text')
    const rollbackCall = writeCalls[writeCalls.length - 1]
    expect((rollbackCall[1] as { content: string }).content).toBe('# old a content')
  })

  it('MEMORY.md rebuild 失败 → MEMORY.md 加到 failed，但 detail files 已写不撤回', async () => {
    mockInvoke
      // backup: list → empty (无 MEMORY.md backup)
      .mockResolvedValueOnce([])
      // write a.md OK
      .mockResolvedValueOnce(undefined)
      // rebuild: list fails → 进 catch
      .mockRejectedValueOnce(new Error('list failed'))

    const update = {
      version: 1,
      index_md: '# v1',
      focus: '',
      files: [{ filename: 'a.md', type: 'identity', name: 'A', description: '', body: 'a' }],
    }
    const r = await applyMemoryUpdate('proj-1', null, update)
    expect(r.written).toBe(1)
    expect(r.failed).toEqual(['MEMORY.md'])
    expect(r.rolledBack).toBe(true)

    // 因 MEMORY.md backup 不存在，不应额外写入 MEMORY.md
    const writeCalls = mockInvoke.mock.calls.filter((c) => c[0] === 'fs_write_text')
    expect(writeCalls).toHaveLength(1)  // 仅 a.md 那次
  })

  it('回滚：file 1 OK + file 2 失败 → file 1 无 backup 时应被 delete', async () => {
    mockInvoke
      // backup: list → empty (c.md 是新文件，没有 backup)
      .mockResolvedValueOnce([])
      // write c.md OK
      .mockResolvedValueOnce(undefined)
      // write d.md FAIL
      .mockRejectedValueOnce(new Error('permission denied'))
      // rollback c.md → delete（无 backup）
      .mockResolvedValueOnce(undefined)

    const update = {
      version: 2,
      index_md: '# v2',
      focus: '',
      files: [
        { filename: 'c.md', type: 'identity', name: 'C', description: '', body: 'c' },
        { filename: 'd.md', type: 'note', name: 'D', description: '', body: 'd' },
      ],
    }
    const r = await applyMemoryUpdate('proj-1', null, update)
    expect(r.written).toBe(0)
    expect(r.failed).toEqual(['d.md'])
    expect(r.rolledBack).toBe(true)

    // 回滚 c.md 用 fs_remove（因无 backup）
    const removeCalls = mockInvoke.mock.calls.filter((c) => c[0] === 'fs_remove')
    expect(removeCalls).toHaveLength(1)
    expect((removeCalls[0][1] as { relPath: string }).relPath).toMatch(/c\.md$/)
  })
})

describe('rebuildMemoryIndex', () => {
  it('列出所有本地 .md（含上轮未提及的）并生成索引', async () => {
    mockInvoke
      // list → 3 个 detail + MEMORY.md
      .mockResolvedValueOnce([
        { name: 'MEMORY.md', is_dir: false, size: 50, modified_ms: 1000 },
        { name: 'identity.md', is_dir: false, size: 80, modified_ms: 2000 },
        { name: 'round_1.md', is_dir: false, size: 90, modified_ms: 3000 },
        { name: 'feedback_pref.md', is_dir: false, size: 60, modified_ms: 4000 },
      ])
      // read each detail
      .mockResolvedValueOnce('---\nname: 研究身份\ndescription: 核心方向\nupdated_at: 2000\n---\n\nbody')
      .mockResolvedValueOnce('---\nname: 第一轮摘要\ndescription: 10 篇\nupdated_at: 3000\n---\n\nbody')
      .mockResolvedValueOnce('---\nname: 偏好设置\ndescription: 优先 arXiv\nupdated_at: 4000\n---\n\nbody')
      // write MEMORY.md
      .mockResolvedValueOnce(undefined)

    await rebuildMemoryIndex('proj-1', null, 5, '量子计算')

    const writeCalls = mockInvoke.mock.calls.filter((c) => c[0] === 'fs_write_text')
    expect(writeCalls).toHaveLength(1)
    const content = (writeCalls[0][1] as { content: string }).content

    expect(content).toContain('# 项目记忆 v5')
    expect(content).toContain('_当前研究方向：量子计算_')
    // 3 个 detail 都出现（含上轮未提及的 identity.md）
    expect(content).toContain('identity.md')
    expect(content).toContain('round_1.md')
    expect(content).toContain('feedback_pref.md')
    // MEMORY.md 自身不出现在列表中
    expect(content).not.toContain('[MEMORY.md]')
    // 按 updated_at 倒序：偏好设置(4000) > 第一轮摘要(3000) > 研究身份(2000)
    const prefIdx = content.indexOf('偏好设置')
    const roundIdx = content.indexOf('第一轮摘要')
    const identIdx = content.indexOf('研究身份')
    expect(prefIdx).toBeLessThan(roundIdx)
    expect(roundIdx).toBeLessThan(identIdx)
  })
})

describe('ensureMemoryIndex', () => {
  it('不存在时写骨架', async () => {
    mockInvoke
      .mockResolvedValueOnce(false) // fs_exists → false
      .mockResolvedValueOnce(undefined) // fs_write_text
    await ensureMemoryIndex('proj-1', 'My Research')

    expect(mockInvoke).toHaveBeenCalledTimes(2)
    const writeCall = mockInvoke.mock.calls[1]
    expect(writeCall[0]).toBe('fs_write_text')
    const content = (writeCall[1] as { content: string }).content
    expect(content).toContain('My Research')
    expect(content).toContain('# 项目记忆')
  })

  it('已存在 → no-op，不调用 fs_write_text', async () => {
    mockInvoke.mockResolvedValueOnce(true) // fs_exists → true
    await ensureMemoryIndex('proj-1', 'Whatever')
    expect(mockInvoke).toHaveBeenCalledTimes(1) // 只查 exists 不写
  })
})

// ──────────────── User-level memory（audit fix bug #2，2026-05-08）────────────────

describe('writeUserMemoryMd / readUserMemoryMd', () => {
  it('writeUserMemoryMd 写到 users/<userId>/memory/MEMORY.md', async () => {
    mockInvoke.mockResolvedValue(undefined)
    await writeUserMemoryMd('user-1', '# 用户记忆\n\nbody')
    expect(mockInvoke).toHaveBeenCalledWith('fs_write_text', {
      relPath: 'users/user-1/memory/MEMORY.md',
      content: '# 用户记忆\n\nbody',
    })
  })

  it('writeUserMemoryMd 空 userId → throw', async () => {
    await expect(writeUserMemoryMd('', 'x')).rejects.toThrow(/userId required/)
  })

  it('readUserMemoryMd 不存在 → 空字符串（不抛）', async () => {
    mockInvoke.mockResolvedValue(null)
    expect(await readUserMemoryMd('user-1')).toBe('')
  })

  it('writeUserMemoryMd 拒绝路径符号 userId', async () => {
    await expect(writeUserMemoryMd('../escape', 'x')).rejects.toThrow(/invalid userId/)
    await expect(writeUserMemoryMd('a/b', 'x')).rejects.toThrow(/invalid userId/)
  })
})

describe('appendUserMemoryEntry', () => {
  it('文件不存在 → 写骨架 + entry', async () => {
    mockInvoke
      .mockResolvedValueOnce(null)         // fs_read_text returns null
      .mockResolvedValueOnce(undefined)    // fs_write_text
    await appendUserMemoryEntry('user-1', {
      topic: '研究身份',
      content: '专注 LLM scaling',
      weight: 1.0,
      addedAt: 1715000000000, // 2024-05-06 UTC
    })
    const writeCall = mockInvoke.mock.calls[1]
    expect(writeCall[0]).toBe('fs_write_text')
    const content = (writeCall[1] as { content: string }).content
    expect(content).toContain('# 用户记忆（跨项目）')
    expect(content).toContain('## 研究身份')
    expect(content).toContain('weight=1.00')
    expect(content).toContain('专注 LLM scaling')
  })

  it('文件存在 → append entry（保留旧内容）', async () => {
    const existing = '# 用户记忆（跨项目）\n\n> 已有 entry\n\n## 旧 entry (2024-01-01, weight=0.50)\n\n旧内容\n'
    mockInvoke
      .mockResolvedValueOnce(existing)      // fs_read_text returns existing
      .mockResolvedValueOnce(undefined)     // fs_write_text
    await appendUserMemoryEntry('user-1', {
      topic: '新 entry',
      content: '新内容',
      weight: 0.8,
      addedAt: 1715000000000,
    })
    const writeCall = mockInvoke.mock.calls[1]
    const content = (writeCall[1] as { content: string }).content
    expect(content).toContain('## 旧 entry')   // 保留
    expect(content).toContain('## 新 entry')   // 新增
    expect(content).toContain('weight=0.80')
  })

  it('空 userId → throw', async () => {
    await expect(appendUserMemoryEntry('', { topic: 'x', content: 'y' })).rejects.toThrow(/userId required/)
  })
})

describe('applyMemoryUpdate scope=user → no-op', () => {
  it('scope=user → 0/[]/false 不写任何文件', async () => {
    const update = {
      version: 1,
      index_md: '# v1',
      focus: '',
      files: [{ filename: 'a.md', type: 'identity', name: 'A', description: '', body: 'a' }],
    }
    const r = await applyMemoryUpdate('proj-1', null, update, 'user')
    expect(r).toEqual({ written: 0, failed: [], rolledBack: false })
    // 不应有任何 fs_* 调用
    expect(mockInvoke).not.toHaveBeenCalled()
  })

  it('scope=project（默认）→ 仍走原逻辑', async () => {
    mockInvoke
      .mockResolvedValueOnce([])               // backup list empty
      .mockResolvedValueOnce(undefined)        // write a.md
      .mockResolvedValueOnce([                  // rebuild list
        { name: 'a.md', is_dir: false, size: 50, modified_ms: 1000 },
      ])
      .mockResolvedValueOnce('---\nname: A\n---\n\nbody')  // read for rebuild
      .mockResolvedValueOnce(undefined)        // write MEMORY.md

    const update = {
      version: 1,
      index_md: '# v1',
      focus: '',
      files: [{ filename: 'a.md', type: 'identity', name: 'A', description: '', body: 'a' }],
    }
    const r = await applyMemoryUpdate('proj-1', null, update)
    expect(r.written).toBe(1)
    expect(r.rolledBack).toBe(false)
  })
})

describe('promoteToUserMemory（用户主动升级项目记忆 → 跨项目画像）', () => {
  it('提升 1 个 entry → 1 promoted', async () => {
    // promoteToUserMemory 调用顺序：
    //   readMemoryFile(identity.md) → fs_read_text
    //   appendUserMemoryEntry → fs_read_text(user MEMORY.md) → fs_write_text
    mockInvoke
      .mockResolvedValueOnce('---\nname: 研究方向\ndescription: LLM 研究\ntype: identity\n---\n\n大模型 scaling laws')
      .mockResolvedValueOnce(null)       // user MEMORY.md 不存在
      .mockResolvedValueOnce(undefined)  // fs_write_text user MEMORY.md
    const r = await promoteToUserMemory('user-1', 'proj-1', ['identity.md'], 'My Project')
    expect(r.promoted).toBe(1)
    expect(r.skipped).toEqual([])
    // 验证写到 user 路径
    const writeCall = mockInvoke.mock.calls[2]
    expect(writeCall[0]).toBe('fs_write_text')
    expect((writeCall[1] as { relPath: string }).relPath).toBe('users/user-1/memory/MEMORY.md')
    const content = (writeCall[1] as { content: string }).content
    expect(content).toContain('研究方向')
    expect(content).toContain('大模型 scaling laws')
    expect(content).toContain('weight=1.00')  // identity → 1.0
  })

  it('文件不存在 → skipped', async () => {
    mockInvoke.mockResolvedValueOnce(null)  // readMemoryFile → null
    const r = await promoteToUserMemory('user-1', 'proj-1', ['missing.md'])
    expect(r.promoted).toBe(0)
    expect(r.skipped).toEqual(['missing.md'])
  })

  it('多 entry 部分成功部分失败', async () => {
    mockInvoke
      .mockResolvedValueOnce('---\nname: A\ntype: identity\n---\n\nbody A')  // a.md OK
      .mockResolvedValueOnce(null)                                            // append: read user MEMORY.md
      .mockResolvedValueOnce(undefined)                                       // append: write user MEMORY.md
      .mockResolvedValueOnce(null)                                            // b.md missing
    const r = await promoteToUserMemory('user-1', 'proj-1', ['a.md', 'b.md'])
    expect(r.promoted).toBe(1)
    expect(r.skipped).toEqual(['b.md'])
  })

  it('空 userId → throw', async () => {
    await expect(promoteToUserMemory('', 'proj-1', ['a.md'])).rejects.toThrow(/userId required/)
  })

  it('空 projectId → throw', async () => {
    await expect(promoteToUserMemory('user-1', '', ['a.md'])).rejects.toThrow(/projectId required/)
  })

  it('frontmatter type=preference → weight=0.8', async () => {
    mockInvoke
      .mockResolvedValueOnce('---\nname: 偏好\ntype: preference\n---\n\n偏好内容')
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(undefined)
    const r = await promoteToUserMemory('user-1', 'proj-1', ['preferred.md'])
    expect(r.promoted).toBe(1)
    const writeCall = mockInvoke.mock.calls[2]
    const content = (writeCall[1] as { content: string }).content
    expect(content).toContain('weight=0.80')
  })
})
