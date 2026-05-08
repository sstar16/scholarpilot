/**
 * RerankPhase — 可选 LLM rerank（gated on project.search_config.enable_llm_rerank）。
 *
 * 移植自 backend `phases/rerank.py:9-33`，差异：
 * - 删除 `can_interrupt = True`（PRD 决策 10）
 * - llmReranker 走客户端版（**TODO（B6 接通后）**：`client/src/data/agents/llmReranker.ts` 还未移植）
 * - 当前 stub：直接 return docs 透传
 */
import type { RoundContext } from '../context'
import { PhaseSkipped } from '../context'
import type { Phase } from '../runner'

import type { FetchOutput } from './fetch'
import type { LoadRoundOutput } from './loadRound'

export interface RerankOutput {
  selectedDocs: FetchOutput['selectedDocs']
  reranked: boolean
}

/**
 * 鸭子接口：caller 可注入 llmReranker 实现。
 *
 * **TODO（B6 接通点）**：B6 完成后改为 `import { llmRerank } from '@/data/agents/llmReranker'`，
 * 删除 setLlmReranker 注入逻辑。
 */
export interface LlmRerankerLike {
  rerank(params: {
    docs: FetchOutput['selectedDocs']
    projectDescription: string
    llmManager: unknown
  }): Promise<FetchOutput['selectedDocs']>
}

const _RERANKER_HOLDER: { current: LlmRerankerLike | null } = { current: null }

export function setLlmReranker(impl: LlmRerankerLike | null): void {
  _RERANKER_HOLDER.current = impl
}

export const rerankPhase: Phase = {
  name: 'rerank',
  deps: ['fetch'],
  progressRange: [0.40, 0.42] as const,

  async execute(ctx: RoundContext): Promise<RerankOutput> {
    const fetchOut = ctx.get<FetchOutput>('fetch')
    const docs = fetchOut.selectedDocs
    if (docs.length === 0) {
      throw new PhaseSkipped('no docs to rerank')
    }

    const loaded = ctx.get<LoadRoundOutput>('load_round')
    const cfg = loaded.project.search_config as Record<string, unknown> | null
    const enabled = Boolean(cfg && typeof cfg === 'object' && cfg.enable_llm_rerank)
    if (!enabled) {
      return { selectedDocs: docs, reranked: false }
    }

    const reranker = _RERANKER_HOLDER.current
    if (!reranker) {
      console.warn(
        '[RerankPhase] llmReranker not configured (TODO B6); skipping rerank, returning docs as-is',
      )
      return { selectedDocs: docs, reranked: false }
    }

    const reranked = await reranker.rerank({
      docs,
      projectDescription: loaded.project.description,
      llmManager: ctx.llmManager,
    })
    return { selectedDocs: reranked, reranked: true }
  },
}
