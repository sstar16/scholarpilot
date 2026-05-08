use base64::{engine::general_purpose::STANDARD as B64, Engine as _};
use serde::Serialize;
use tauri::AppHandle;
use tokio::fs;
use tokio::io::AsyncWriteExt;

use super::paths::{resolve_safe, PathError};

#[derive(Serialize)]
pub struct FsError {
    pub message: String,
}

// stable Rust 不支持 specialization，所以不能写 generic `impl<E: Display> From<E>`。
// 给每个我们实际触发的错误源手写一次 From。
impl From<PathError> for FsError {
    fn from(e: PathError) -> Self {
        Self { message: e.message }
    }
}
impl From<std::io::Error> for FsError {
    fn from(e: std::io::Error) -> Self {
        Self { message: e.to_string() }
    }
}
impl From<base64::DecodeError> for FsError {
    fn from(e: base64::DecodeError) -> Self {
        Self { message: format!("invalid base64: {e}") }
    }
}

async fn ensure_parent(path: &std::path::Path) -> Result<(), FsError> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).await?;
    }
    Ok(())
}

#[tauri::command]
pub async fn fs_write_text(
    app: AppHandle,
    rel_path: String,
    content: String,
) -> Result<(), FsError> {
    let abs = resolve_safe(&app, &rel_path)?;
    ensure_parent(&abs).await?;
    fs::write(&abs, content).await?;
    Ok(())
}

#[tauri::command]
pub async fn fs_read_text(
    app: AppHandle,
    rel_path: String,
) -> Result<Option<String>, FsError> {
    let abs = resolve_safe(&app, &rel_path)?;
    if !abs.exists() {
        return Ok(None);
    }
    let body = fs::read_to_string(&abs).await?;
    Ok(Some(body))
}

#[tauri::command]
pub async fn fs_write_bytes_b64(
    app: AppHandle,
    rel_path: String,
    base64: String,
) -> Result<(), FsError> {
    let abs = resolve_safe(&app, &rel_path)?;
    ensure_parent(&abs).await?;
    let bytes = B64.decode(base64.as_bytes())?;
    let mut f = fs::File::create(&abs).await?;
    f.write_all(&bytes).await?;
    Ok(())
}

#[tauri::command]
pub async fn fs_read_bytes_b64(
    app: AppHandle,
    rel_path: String,
) -> Result<Option<String>, FsError> {
    let abs = resolve_safe(&app, &rel_path)?;
    if !abs.exists() {
        return Ok(None);
    }
    let bytes = fs::read(&abs).await?;
    Ok(Some(B64.encode(bytes)))
}

#[tauri::command]
pub async fn fs_exists(app: AppHandle, rel_path: String) -> Result<bool, FsError> {
    let abs = resolve_safe(&app, &rel_path)?;
    Ok(abs.exists())
}

#[tauri::command]
pub async fn fs_remove(app: AppHandle, rel_path: String) -> Result<(), FsError> {
    let abs = resolve_safe(&app, &rel_path)?;
    if abs.is_dir() {
        fs::remove_dir_all(&abs).await?;
    } else if abs.exists() {
        fs::remove_file(&abs).await?;
    }
    Ok(())
}

#[tauri::command]
pub async fn fs_size(app: AppHandle, rel_path: String) -> Result<Option<u64>, FsError> {
    let abs = resolve_safe(&app, &rel_path)?;
    if !abs.exists() {
        return Ok(None);
    }
    let meta = fs::metadata(&abs).await?;
    Ok(Some(meta.len()))
}

#[derive(Serialize)]
pub struct FsDirEntry {
    pub name: String,
    pub is_dir: bool,
    pub size: u64,
    pub modified_ms: u64,
}

/// 列出 sandboxed 相对路径目录下的直接子项（不递归）。
/// 目录不存在 → 返回空 Vec（让调用方少一次 fs_exists）。
/// 不是目录 → 返回 FsError。
#[tauri::command]
pub async fn fs_list_dir(
    app: AppHandle,
    rel_path: String,
) -> Result<Vec<FsDirEntry>, FsError> {
    let abs = resolve_safe(&app, &rel_path)?;
    if !abs.exists() {
        return Ok(Vec::new());
    }
    if !abs.is_dir() {
        return Err(FsError {
            message: format!("not a directory: {}", rel_path),
        });
    }
    let mut out = Vec::new();
    let mut rd = fs::read_dir(&abs).await?;
    while let Some(entry) = rd.next_entry().await? {
        let meta = entry.metadata().await?;
        let name = entry.file_name().to_string_lossy().into_owned();
        let modified_ms = meta
            .modified()
            .ok()
            .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
            .map(|d| d.as_millis() as u64)
            .unwrap_or(0);
        out.push(FsDirEntry {
            name,
            is_dir: meta.is_dir(),
            size: meta.len(),
            modified_ms,
        });
    }
    out.sort_by(|a, b| a.name.cmp(&b.name));
    Ok(out)
}
