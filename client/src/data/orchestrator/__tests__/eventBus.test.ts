/**
 * EventBus 单测 — 验证：
 *   1. publish/subscribe 基本行为
 *   2. unsubscribe 解绑
 *   3. 多 listener 互相不干扰
 *   4. channel 隔离（订阅 round:abc 不收 round:def）
 *   5. prefix 订阅匹配前缀
 *   6. listener 抛异常不影响其它 listener
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { ClientEventBus, _resetEventBusForTesting, getEventBus } from '../eventBus'

beforeEach(() => {
  _resetEventBusForTesting()
})

describe('ClientEventBus', () => {
  it('publish 发到 subscribe 的 listener', () => {
    const bus = new ClientEventBus()
    const fn = vi.fn()
    bus.subscribe('round:abc', fn)
    bus.publish('round:abc', 'round_status', { progress: 0.5 })
    expect(fn).toHaveBeenCalledTimes(1)
    expect(fn.mock.calls[0][0]).toMatchObject({
      channel: 'round:abc',
      event: 'round_status',
      data: { progress: 0.5 },
    })
    expect(typeof fn.mock.calls[0][0].timestamp).toBe('number')
  })

  it('unsubscribe 后不再收事件', () => {
    const bus = new ClientEventBus()
    const fn = vi.fn()
    const unsub = bus.subscribe('round:abc', fn)
    bus.publish('round:abc', 'e1', null)
    unsub()
    bus.publish('round:abc', 'e2', null)
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('channel 隔离：订阅 round:abc 不收 round:def', () => {
    const bus = new ClientEventBus()
    const fn = vi.fn()
    bus.subscribe('round:abc', fn)
    bus.publish('round:def', 'round_status', null)
    expect(fn).not.toHaveBeenCalled()
  })

  it('多 listener 都收到', () => {
    const bus = new ClientEventBus()
    const fn1 = vi.fn()
    const fn2 = vi.fn()
    bus.subscribe('ch', fn1)
    bus.subscribe('ch', fn2)
    bus.publish('ch', 'e', null)
    expect(fn1).toHaveBeenCalledTimes(1)
    expect(fn2).toHaveBeenCalledTimes(1)
  })

  it('listener 抛异常不影响其它 listener', () => {
    const bus = new ClientEventBus()
    const broken = vi.fn(() => { throw new Error('boom') })
    const ok = vi.fn()
    bus.subscribe('ch', broken)
    bus.subscribe('ch', ok)
    bus.publish('ch', 'e', null)
    expect(broken).toHaveBeenCalledTimes(1)
    expect(ok).toHaveBeenCalledTimes(1)
  })

  it('subscribeChannel prefix 匹配所有 round:*', () => {
    const bus = new ClientEventBus()
    const fn = vi.fn()
    bus.subscribeChannel('round:', fn)
    bus.publish('round:abc', 'e1', null)
    bus.publish('round:def', 'e2', null)
    bus.publish('session:xyz', 'e3', null)
    expect(fn).toHaveBeenCalledTimes(2)
  })

  it('exact + prefix 混订都触发', () => {
    const bus = new ClientEventBus()
    const exactFn = vi.fn()
    const prefixFn = vi.fn()
    bus.subscribe('round:abc', exactFn)
    bus.subscribeChannel('round:', prefixFn)
    bus.publish('round:abc', 'e', null)
    expect(exactFn).toHaveBeenCalledTimes(1)
    expect(prefixFn).toHaveBeenCalledTimes(1)
  })

  it('getEventBus 单例', () => {
    const a = getEventBus()
    const b = getEventBus()
    expect(a).toBe(b)
  })
})
