import { describe, it, expect, afterEach } from 'vitest'

import { createInMemoryDb } from '../../_helpers/inMemoryDb'
import { getDatabase, setTestDb } from '@/data/sqlite/connection'

describe('connection', () => {
  let testDb: ReturnType<typeof createInMemoryDb>

  afterEach(async () => {
    if (testDb) await testDb.raw.close()
    setTestDb(null)
  })

  it('提供单例 DbHandle', async () => {
    testDb = createInMemoryDb()
    const handle = getDatabase()
    expect(handle).toBeDefined()
    const rows = await handle.select<{ key: string; value: string }>(
      "SELECT key, value FROM meta_kv WHERE key='schema_version'"
    )
    expect(rows[0]?.value).toBe('1')
  })
})
