// 单测启动钩子 — 目前留空，预留给将来注册全局 mock
import { afterEach } from 'vitest'
import { setTestDb } from '@/data/sqlite/connection'

afterEach(() => {
  setTestDb(null)
})
