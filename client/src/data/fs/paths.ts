/**
 * 客户端文件系统约定（spec §4.2）：
 *
 *   <AppData>/scholarpilot/
 *   ├── projects/
 *   │   └── <project_id>/
 *   │       ├── pdfs/<doc_id>.pdf
 *   │       ├── full_text/<doc_id>.txt
 *   │       ├── notes/<doc_id>.md
 *   │       └── exports/
 *   ├── cache/
 *   │   └── thumbnails/<doc_id>.png
 *   ├── logs/
 *   └── scholarpilot.db
 *
 * 这个文件返回**相对**路径（相对 app_data_dir），调用方传给 fs_* commands。
 * 永远用 forward slash — Tauri 在 Windows 上会自动转。
 */

import { pdfFilename, htmlFilename, projectFolderName } from '@/utils/slug'

/**
 * 项目根: 传 projectTitle 用 slug 命名 `<slug>__<id6>`, 不传退 UUID。
 * 用户在 explorer 看 projects/ 一眼能识别哪个是哪个项目。
 */
function _projRoot(projectId: string, projectTitle?: string | null): string {
  return projectTitle
    ? `projects/${projectFolderName(projectTitle, projectId)}`
    : `projects/${projectId}`
}

/** 老 UUID 项目根 (fs_exists 兜底用) */
function _projRootLegacy(projectId: string): string {
  return `projects/${projectId}`
}

export const PATHS = {
  projectRoot: (projectId: string, projectTitle?: string | null) =>
    _projRoot(projectId, projectTitle),
  projectRootLegacy: (projectId: string) => _projRootLegacy(projectId),
  /** PDF 文件路径 (4 种命名兼容 fs_exists 兜底):
   * - 全 slug: projects/<projslug>__<pid6>/pdfs/<docslug>__<did6>.pdf  (新版, 最美观)
   * - 项目 UUID + 文档 slug: projects/<UUID>/pdfs/<docslug>__<did6>.pdf  (兼容 2026-05-03 改 PDF slug 但项目还是 UUID 的中间产物)
   * - 全 UUID: projects/<UUID>/pdfs/<docId>.pdf  (兼容 2026-05-03 之前)
   *
   * 设计选择：PDF **不在** `library/` 子目录下（而是与 `library/` 同级在
   * `projects/<id>/pdfs/`），原因：
   *   1. 下载频率高，silentPdfReconciler / pdf_fetcher.rs 频繁扫这个路径
   *   2. 保留兼容旧版本（2026-05-03 之前已有用户的 PDF 在这里）
   *   3. PRD §4.3.2 已修正与代码对齐（audit 2026-05-08）
   * `library/` 仅用于 markdown workspace（docs / index.md / graph）。 */
  pdfFile: (
    projectId: string,
    docId: string,
    docTitle?: string | null,
    projectTitle?: string | null,
  ) =>
    `${_projRoot(projectId, projectTitle)}/pdfs/${docTitle ? pdfFilename(docTitle, docId) : docId + '.pdf'}`,
  pdfFileLegacy: (projectId: string, docId: string) =>
    `${_projRootLegacy(projectId)}/pdfs/${docId}.pdf`,
  htmlFile: (
    projectId: string,
    docId: string,
    docTitle?: string | null,
    projectTitle?: string | null,
  ) =>
    `${_projRoot(projectId, projectTitle)}/pdfs/${docTitle ? htmlFilename(docTitle, docId) : docId + '.html'}`,
  htmlFileLegacy: (projectId: string, docId: string) =>
    `${_projRootLegacy(projectId)}/pdfs/${docId}.html`,
  fulltextFile: (projectId: string, docId: string, projectTitle?: string | null) =>
    `${_projRoot(projectId, projectTitle)}/full_text/${docId}.txt`,
  noteFile: (projectId: string, docId: string, projectTitle?: string | null) =>
    `${_projRoot(projectId, projectTitle)}/notes/${docId}.md`,
  exportDir: (projectId: string, projectTitle?: string | null) =>
    `${_projRoot(projectId, projectTitle)}/exports`,
  /** 项目记忆目录（学 Claude Code MEMORY.md 模式：索引 + 多个 .md 详情） */
  memoryDir: (projectId: string, projectTitle?: string | null) =>
    `${_projRoot(projectId, projectTitle)}/memory`,
  memoryDirLegacy: (projectId: string) => `${_projRootLegacy(projectId)}/memory`,
  memoryFile: (projectId: string, filename: string, projectTitle?: string | null) =>
    `${_projRoot(projectId, projectTitle)}/memory/${filename}`,
  memoryFileLegacy: (projectId: string, filename: string) =>
    `${_projRootLegacy(projectId)}/memory/${filename}`,
  thumbnail: (docId: string) => `cache/thumbnails/${docId}.png`,
  log: (filename: string) => `logs/${filename}`,
} as const

/** 校验 docId / projectId 不含路径符号 — 防止 SQL 里的 id 被人为污染后绕过 sandbox */
export function isSafeId(id: string): boolean {
  return /^[A-Za-z0-9._\-]+$/.test(id)
}

export function assertSafeId(id: string, label = 'id'): void {
  if (!isSafeId(id)) {
    throw new Error(`Unsafe ${label}: ${id}`)
  }
}
