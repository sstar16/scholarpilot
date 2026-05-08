/**
 * runState 单测 — 验证 transition 表 + terminal/interruptible 集合。
 */
import { describe, it, expect } from 'vitest'

import {
  INTERRUPTIBLE_STATUSES,
  TERMINAL_STATUSES,
  assertTransition,
  isInterruptible,
  isTerminal,
  isTransitionAllowed,
} from '../runState'

describe('isTransitionAllowed', () => {
  it('legal transitions 返回 true', () => {
    expect(isTransitionAllowed('pending', 'awaiting_keywords')).toBe(true)
    expect(isTransitionAllowed('awaiting_keywords', 'searching')).toBe(true)
    expect(isTransitionAllowed('searching', 'scoring')).toBe(true)
    expect(isTransitionAllowed('scoring', 'saving')).toBe(true)
    expect(isTransitionAllowed('saving', 'summarizing')).toBe(true)
    expect(isTransitionAllowed('summarizing', 'awaiting_feedback')).toBe(true)
    expect(isTransitionAllowed('awaiting_feedback', 'complete')).toBe(true)
  })

  it('任意非终态 → cancelled / failed 都允许', () => {
    for (const s of ['pending', 'searching', 'scoring', 'saving', 'summarizing'] as const) {
      expect(isTransitionAllowed(s, 'cancelled')).toBe(true)
      expect(isTransitionAllowed(s, 'failed')).toBe(true)
    }
  })

  it('terminal → 任何 status 都禁止（除自己）', () => {
    for (const t of ['complete', 'failed', 'cancelled'] as const) {
      expect(isTransitionAllowed(t, 'pending')).toBe(false)
      expect(isTransitionAllowed(t, 'searching')).toBe(false)
      // 自身 idempotent
      expect(isTransitionAllowed(t, t)).toBe(true)
    }
  })

  it('illegal forward transitions 返 false', () => {
    expect(isTransitionAllowed('pending', 'complete')).toBe(false)
    expect(isTransitionAllowed('searching', 'pending')).toBe(false)
    expect(isTransitionAllowed('summarizing', 'searching')).toBe(false)
  })
})

describe('assertTransition', () => {
  it('illegal 抛错', () => {
    expect(() => assertTransition('pending', 'complete')).toThrowError(/illegal round transition/)
  })

  it('legal 不抛', () => {
    expect(() => assertTransition('pending', 'awaiting_keywords')).not.toThrow()
  })
})

describe('isTerminal / isInterruptible', () => {
  it('TERMINAL set = {complete, failed, cancelled}', () => {
    expect([...TERMINAL_STATUSES].sort()).toEqual(['cancelled', 'complete', 'failed'])
    expect(isTerminal('complete')).toBe(true)
    expect(isTerminal('failed')).toBe(true)
    expect(isTerminal('cancelled')).toBe(true)
    expect(isTerminal('searching')).toBe(false)
  })

  it('INTERRUPTIBLE set 包含所有非终态运行中状态', () => {
    expect([...INTERRUPTIBLE_STATUSES].sort()).toEqual([
      'awaiting_keywords',
      'pending',
      'saving',
      'scoring',
      'searching',
      'summarizing',
    ])
    expect(isInterruptible('awaiting_feedback')).toBe(false) // 等用户反馈不算 interrupted
    expect(isInterruptible('complete')).toBe(false)
  })
})
