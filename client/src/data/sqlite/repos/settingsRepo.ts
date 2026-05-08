import { getDatabase } from '../connection'

export async function setSetting(key: string, value: string): Promise<void> {
  const db = getDatabase()
  await db.execute(
    `INSERT INTO settings (key, value, updated_at) VALUES (?,?,?)
     ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at`,
    [key, value, Date.now()],
  )
}

export async function getSetting(key: string): Promise<string | null> {
  const db = getDatabase()
  const rows = await db.select<{ value: string }>(
    'SELECT value FROM settings WHERE key = ?', [key],
  )
  return rows[0]?.value ?? null
}

export async function deleteSetting(key: string): Promise<void> {
  const db = getDatabase()
  await db.execute('DELETE FROM settings WHERE key = ?', [key])
}
