/**
 * Client EventBus — in-memory 进程内事件总线。
 *
 * 移植自 backend `app/services/event_bus.py`（Redis pub/sub），但客户端单进程不需要
 * 跨进程，纯内存即可。
 *
 * 设计：
 * - channel：`round:<round_id>` / `session:<session_id>` / `agent:phase` 等约定字符串
 * - publish(channel, event, data) → 调用所有订阅这个 channel 的 listener
 * - subscribe(channel, listener) → 返回 unsub 函数
 * - subscribeChannel(prefix, listener) → 订阅一个前缀，所有匹配 channel 都触发
 *
 * 不依赖 Tauri rust event：客户端进程内 emitter 即可。
 */

/** 单个事件的载荷。 */
export interface BusEvent<T = unknown> {
  channel: string
  event: string
  data: T
  /** epoch ms（默认 Date.now()）。 */
  timestamp: number
}

export type EventListener = (e: BusEvent) => void

export class ClientEventBus {
  private readonly _exact = new Map<string, Set<EventListener>>()
  private readonly _prefix = new Map<string, Set<EventListener>>()

  /** 发布事件到一个 channel。 */
  publish<T = unknown>(channel: string, event: string, data: T): void {
    const evt: BusEvent<T> = {
      channel,
      event,
      data,
      timestamp: Date.now(),
    }

    // exact match
    const exact = this._exact.get(channel)
    if (exact) {
      for (const fn of exact) {
        try {
          fn(evt as BusEvent)
        } catch (e) {
          console.warn(`[EventBus] listener for '${channel}' threw:`, e)
        }
      }
    }

    // prefix match — channel.startsWith(prefix)
    for (const [prefix, set] of this._prefix) {
      if (channel.startsWith(prefix)) {
        for (const fn of set) {
          try {
            fn(evt as BusEvent)
          } catch (e) {
            console.warn(`[EventBus] prefix listener for '${prefix}' threw:`, e)
          }
        }
      }
    }
  }

  /** 订阅一个 exact channel；返回 unsubscribe 函数。 */
  subscribe(channel: string, listener: EventListener): () => void {
    let set = this._exact.get(channel)
    if (!set) {
      set = new Set()
      this._exact.set(channel, set)
    }
    set.add(listener)
    return () => {
      const s = this._exact.get(channel)
      if (s) {
        s.delete(listener)
        if (s.size === 0) this._exact.delete(channel)
      }
    }
  }

  /** 订阅一个 channel 前缀；返回 unsubscribe 函数。
   *
   *  例：`subscribeChannel('round:', l)` 收到所有 `round:<id>` 的事件。
   */
  subscribeChannel(prefix: string, listener: EventListener): () => void {
    let set = this._prefix.get(prefix)
    if (!set) {
      set = new Set()
      this._prefix.set(prefix, set)
    }
    set.add(listener)
    return () => {
      const s = this._prefix.get(prefix)
      if (s) {
        s.delete(listener)
        if (s.size === 0) this._prefix.delete(prefix)
      }
    }
  }

  /** 当前 exact 订阅数（DevTools / 测试用）。 */
  get exactChannelCount(): number {
    return this._exact.size
  }

  /** 当前 prefix 订阅数（DevTools / 测试用）。 */
  get prefixChannelCount(): number {
    return this._prefix.size
  }

  /** 清空所有订阅。仅测试用。 */
  _resetForTesting(): void {
    this._exact.clear()
    this._prefix.clear()
  }
}

// ─────────────── 单例 ───────────────

let _instance: ClientEventBus | null = null

export function getEventBus(): ClientEventBus {
  if (!_instance) _instance = new ClientEventBus()
  return _instance
}

/** 测试用：重置单例。 */
export function _resetEventBusForTesting(): void {
  _instance = null
}
