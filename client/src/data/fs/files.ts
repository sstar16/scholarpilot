import { invoke } from '@tauri-apps/api/core'

export interface AppPaths {
  app_data_dir: string
  db_path: string
  projects_root: string
}

export async function getAppPaths(): Promise<AppPaths> {
  return invoke<AppPaths>('get_app_paths')
}

export async function writeText(relPath: string, content: string): Promise<void> {
  await invoke('fs_write_text', { relPath, content })
}

export async function readText(relPath: string): Promise<string | null> {
  return (await invoke<string | null>('fs_read_text', { relPath })) ?? null
}

export async function writeBytes(relPath: string, bytes: Uint8Array): Promise<void> {
  // base64 编码
  let binary = ''
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  const b64 = btoa(binary)
  await invoke('fs_write_bytes_b64', { relPath, base64: b64 })
}

export async function readBytes(relPath: string): Promise<Uint8Array | null> {
  const b64 = (await invoke<string | null>('fs_read_bytes_b64', { relPath })) ?? null
  if (!b64) return null
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes
}

export async function fileExists(relPath: string): Promise<boolean> {
  return invoke<boolean>('fs_exists', { relPath })
}

export async function fileSize(relPath: string): Promise<number | null> {
  return (await invoke<number | null>('fs_size', { relPath })) ?? null
}

export async function removePath(relPath: string): Promise<void> {
  await invoke('fs_remove', { relPath })
}

export interface DirEntry {
  name: string
  is_dir: boolean
  size: number
  modified_ms: number
}

/** 列目录（不递归）；目录不存在 → []；非目录 → 抛错（FsError 来自 Rust 端） */
export async function listDir(relPath: string): Promise<DirEntry[]> {
  return (await invoke<DirEntry[]>('fs_list_dir', { relPath })) ?? []
}

/** 工具：把 fetch Response 的 body 写入 fs（流式不行，因为 invoke 一次性传 base64；
 *  PDF 通常 < 50 MB，base64 编码后 < 70 MB 内存可接受） */
export async function downloadToFile(
  url: string,
  relPath: string,
  fetchInit?: RequestInit,
): Promise<{ size: number }> {
  const res = await fetch(url, fetchInit)
  if (!res.ok) {
    throw new Error(`download failed: HTTP ${res.status}`)
  }
  const buf = await res.arrayBuffer()
  const bytes = new Uint8Array(buf)
  await writeBytes(relPath, bytes)
  return { size: bytes.byteLength }
}

// 重新 export 给业务方便
export { PATHS, assertSafeId } from './paths'
