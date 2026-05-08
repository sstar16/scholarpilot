/**
 * LoadMemoryPhase — 装配 QueryPlanAgent / ScoringAgent 喂的 user/project memory bundle。
 *
 * 移植自 backend `phases/load_memory.py:9-54`，差异：
 * - 客户端无 user_profiles 表，改读 memoryRepo .md frontmatter
 * - prev_stats 从 roundRepo 上一轮 source_stats_json 读
 *
 * Memory 接通（C 阶段）：调 `memoryRepo.readCombinedMemoryForAgents(userId, projectId)`，
 * 读 `<AppData>/scholarpilot/users/<userId>/memory/MEMORY.md` + `projects/<id>/memory/MEMORY.md`
 * 拼成给 LLM 的 combined markdown。userId 从客户端 auth store 取（无登录态返空字符串占位）。
 *
 * preferred_keywords / excluded_keywords 仍占位 [] / []，未来 B8 改造可读
 * `memory/preferences.md` frontmatter。
 */
import type { LocalProject } from '@/types/local'
import { readCombinedMemoryForAgents } from '@/data/memory/memoryRepo'
import { listRoundsByProject } from '@/data/sqlite/repos/roundRepo'

import type { RoundContext } from '../context'
import type { Phase } from '../runner'

import type { LoadRoundOutput } from './loadRound'

export interface LoadMemoryOutput {
  preferredKeywords: string[]
  excludedKeywords: string[]
  combinedMd: string
  prevStats: Record<string, unknown>
}

export const loadMemoryPhase: Phase = {
  name: 'load_memory',
  deps: ['load_round'],
  progressRange: [0.10, 0.13] as const,

  async execute(ctx: RoundContext): Promise<LoadMemoryOutput> {
    const loaded = ctx.get<LoadRoundOutput>('load_round')
    const project = loaded.project
    const round = loaded.round

    const userId = await _resolveUserId()
    const projectTitle = (project as { title?: string | null })?.title ?? null
    let combinedMd = ''
    try {
      const r = await readCombinedMemoryForAgents(userId, project.id, projectTitle)
      combinedMd = r.combined
    } catch (e) {
      // memory 读失败不阻塞 phase（fs 不存在 / 权限错都会进这里）
      console.warn('[LoadMemoryPhase] readCombinedMemoryForAgents failed (fallback to project notes):', e)
      combinedMd = await _loadCombinedMemoryStub(project)
    }
    if (!combinedMd) {
      // 两份 .md 都不存在 → 退回 project.research_note_md 占位
      combinedMd = await _loadCombinedMemoryStub(project)
    }
    ctx.memorySnapshot = combinedMd

    const { preferredKeywords, excludedKeywords } = await _readKeywordsFromMemory(project)

    let prevStats: Record<string, unknown> = {}
    if (round.round_number > 1) {
      const all = await listRoundsByProject(project.id)
      const prev = all.find((r) => r.round_number === round.round_number - 1)
      if (prev?.source_stats && typeof prev.source_stats === 'object') {
        prevStats = prev.source_stats as Record<string, unknown>
      }
    }

    return {
      preferredKeywords,
      excludedKeywords,
      combinedMd,
      prevStats,
    }
  },
}

/**
 * 从客户端 auth store 取当前 userId（无登录返空字符串）。
 *
 * 用 lazy dynamic import 避免 pipeline 模块循环依赖（auth store 间接依赖 pinia + Vue runtime）。
 */
async function _resolveUserId(): Promise<string> {
  try {
    const { useAuthStore } = await import('@/stores/auth')
    const auth = useAuthStore()
    return auth.user?.id ? String(auth.user.id) : ''
  } catch {
    // pipeline 在测试环境跑（无 pinia）时走这里
    return ''
  }
}

/**
 * 兜底：当 user/project memory MEMORY.md 都不存在时拼 project.research_note_md 当 stub。
 * 与 readCombinedMemoryForAgents 互补 —— 不替换它。
 */
async function _loadCombinedMemoryStub(project: LocalProject): Promise<string> {
  const note = (project.research_note_md || '').trim()
  if (!note) return ''
  return `# 项目笔记\n\n${note}`
}

/**
 * Stub：从 memory 读 preferred / excluded keywords。
 *
 * **TODO（B8 接通点）**：B8 完成后改为读 `memory/preferences.md` frontmatter 的
 * `preferred_keywords` / `excluded_keywords` 数组。
 * 当前从 search_config 里兜底取（如果 caller 写过的话）。
 */
async function _readKeywordsFromMemory(
  project: LocalProject,
): Promise<{ preferredKeywords: string[]; excludedKeywords: string[] }> {
  const cfg = project.search_config
  const out = { preferredKeywords: [] as string[], excludedKeywords: [] as string[] }
  if (cfg && typeof cfg === 'object') {
    const c = cfg as Record<string, unknown>
    if (Array.isArray(c.preferred_keywords)) {
      out.preferredKeywords = c.preferred_keywords.filter((s) => typeof s === 'string') as string[]
    }
    if (Array.isArray(c.excluded_keywords)) {
      out.excludedKeywords = c.excluded_keywords.filter((s) => typeof s === 'string') as string[]
    }
  }
  return out
}

