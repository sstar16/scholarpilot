/**
 * applyMemoryPhase — 画像学习闭环的实现入口（audit fix 2026-05-08，bug #1）。
 *
 * **触发位置**：`stores/search.ts.submitFeedback` fire-and-forget 调用（不挂主流程）。
 *
 * 之前断链原因：search store 写 4-bucket 到 SQLite 后只 `void applyMemoryUpdate`，
 * MemoryAgent + memoryRepo 实现完整但生产 0 调用点 → 下轮 scoring 看到的 memorySnapshot
 * 永远是空 → AI 不学习。
 *
 * 设计选择：
 * - 抽成独立 phase 而不是 inline 进 search store —— 让 round orchestrator 也能复用
 *   （比如未来 awaiting_feedback → complete 自动触发，不依赖用户点提交）
 * - 不进 11-phase pipeline runner（只在 round 主流程跑）—— 这是 round **完成后** 的
 *   异步 hook，不该卡 round 状态机
 * - 失败 graceful return false —— memory 不是关键路径
 *
 * 数据流：
 *   feedbacks → MemoryAgent.update(prompt 含 currentSnapshot) → MemoryUpdate
 *     → applyMemoryUpdate(scope='project') → 写 fs + rebuildMemoryIndex
 *     → 下轮 LoadMemoryPhase 读到新版
 */
import { MemoryAgent, type FeedbackEntry, type LLMGenerator } from '@/data/agents/memoryAgent'
import {
  applyMemoryUpdate,
  readCombinedMemoryForAgents,
} from '@/data/memory/memoryRepo'
import { getProject } from '@/data/sqlite/repos/projectRepo'

export interface ApplyMemoryPhaseInput {
  projectId: string
  /** roundId 仅日志用，不进 memory（memoryRepo 不按 round 切片）*/
  roundId: string
  /** 4-bucket 反馈条目（docId / bucket / docTitle / docAbstract / source）*/
  feedbacks: FeedbackEntry[]
  /** LLM generator 接口；search.ts 传 llmManager 进来。可选（无 → graceful skip）*/
  llm?: LLMGenerator | null
  /** 测试注入：跳过实际 LLM / 直接用预制 update（绕过 MemoryAgent） */
  _testOverrideAgent?: MemoryAgent
}

export interface ApplyMemoryPhaseResult {
  /** 是否真的调到了 LLM 并写盘（false = 跳过 / 失败了 / 没 llm）*/
  applied: boolean
  /** memory_version 升到的新值（applied=false → -1）*/
  newVersion: number
  /** 写入了几个 detail .md（applied=false → 0）*/
  filesWritten: number
  /** 升级失败 → 哪些文件回滚了（applied=false → []）*/
  rolledBack: boolean
  /** 错误原因（debug 用）*/
  reason?: string
}

/**
 * 跑一轮记忆更新。
 *
 * 调用方应 fire-and-forget（不 await）—— UI 立即返回，memory 异步落盘；
 * 或 await 但用 try/catch 兜底（已内置 graceful，本函数不抛）。
 */
export async function applyMemoryPhase(
  input: ApplyMemoryPhaseInput,
): Promise<ApplyMemoryPhaseResult> {
  const { projectId, feedbacks, llm } = input

  if (!projectId) {
    return { applied: false, newVersion: -1, filesWritten: 0, rolledBack: false, reason: 'no projectId' }
  }
  if (!feedbacks || feedbacks.length === 0) {
    return { applied: false, newVersion: -1, filesWritten: 0, rolledBack: false, reason: 'no feedbacks' }
  }
  if (!llm && !input._testOverrideAgent) {
    return { applied: false, newVersion: -1, filesWritten: 0, rolledBack: false, reason: 'no llm' }
  }

  // ── 1. 取项目基础信息 + 拼当前 snapshot ──
  let projectTitle: string | null = null
  let projectDescription = ''
  let memoryVersion = 0
  try {
    const project = await getProject(projectId)
    projectTitle = project?.title ?? null
    projectDescription = project?.description ?? ''
    // 项目记忆没有专门 version 字段，用 search_config 里读（如果 caller 写过）；
    // 当前 V1 兜底 0 — MemoryAgent 内部 increment 后 applyMemoryUpdate 会用新值
    const cfg = project?.search_config as Record<string, unknown> | null | undefined
    if (cfg && typeof cfg === 'object' && typeof cfg.memory_version === 'number') {
      memoryVersion = cfg.memory_version as number
    }
  } catch (e) {
    console.warn('[applyMemoryPhase] getProject failed (continuing with defaults):', e)
  }

  // 取 user+project 两份 MEMORY.md 拼成 snapshot 喂 LLM
  // userId 走 lazy auth import（避免 pipeline 循环依赖；测试环境无 pinia 时返空）
  let memorySnapshot = ''
  try {
    const userId = await _resolveUserId()
    const r = await readCombinedMemoryForAgents(userId, projectId, projectTitle)
    memorySnapshot = r.combined
  } catch (e) {
    console.warn('[applyMemoryPhase] readCombinedMemoryForAgents failed (using empty):', e)
  }

  // ── 2. 调 MemoryAgent ──
  let agent: MemoryAgent
  if (input._testOverrideAgent) {
    agent = input._testOverrideAgent
  } else {
    agent = new MemoryAgent(llm as LLMGenerator)
  }

  let update: Awaited<ReturnType<MemoryAgent['update']>>
  try {
    update = await agent.update({
      currentMemorySnapshot: memorySnapshot || '（首次，无历史记忆）',
      memoryVersion,
      feedbacks,
      projectDescription,
    })
  } catch (e) {
    console.warn('[applyMemoryPhase] MemoryAgent.update raised (graceful skip):', e)
    return { applied: false, newVersion: -1, filesWritten: 0, rolledBack: false, reason: 'agent threw' }
  }

  if (!update.files || update.files.length === 0) {
    return {
      applied: false,
      newVersion: memoryVersion,
      filesWritten: 0,
      rolledBack: false,
      reason: 'agent returned 0 files',
    }
  }

  // ── 3. 写盘 ──
  let writeRes: Awaited<ReturnType<typeof applyMemoryUpdate>>
  try {
    writeRes = await applyMemoryUpdate(
      projectId,
      projectTitle,
      {
        version: update.version,
        index_md: update.indexMd,
        focus: update.focus,
        files: update.files.map((f) => ({
          filename: f.filename,
          type: f.type,
          name: f.name,
          description: f.description,
          body: f.body,
        })),
      },
      'project',
    )
  } catch (e) {
    console.warn('[applyMemoryPhase] applyMemoryUpdate raised:', e)
    return { applied: false, newVersion: memoryVersion, filesWritten: 0, rolledBack: false, reason: 'write threw' }
  }

  return {
    applied: !writeRes.rolledBack,
    newVersion: writeRes.rolledBack ? memoryVersion : update.version,
    filesWritten: writeRes.written,
    rolledBack: writeRes.rolledBack,
    reason: writeRes.rolledBack ? `rollback: failed=${writeRes.failed.join(',')}` : undefined,
  }
}

/** 与 loadMemoryPhase._resolveUserId 同样的 lazy 模式 — 避免 pipeline 循环依赖 */
async function _resolveUserId(): Promise<string> {
  try {
    const { useAuthStore } = await import('@/stores/auth')
    const auth = useAuthStore()
    return auth.user?.id ? String(auth.user.id) : ''
  } catch {
    return ''
  }
}
