/**
 * Shared agent types — 把 agent 模块对外/对内依赖收口在这里。
 */
import type { GenerateOptions, LLMResult } from '../llm/types'

/** 任意可被 agent 注入的 LLM manager（manager.ts 的具名导出 / 测试 mock 都满足）。 */
export interface LLMManagerLike {
  generate(prompt: string, options?: GenerateOptions): Promise<LLMResult | string | null>
}
