use serde::Serialize;
use tauri::AppHandle;

use super::paths::{get_app_paths, PathError};

#[derive(Serialize)]
pub struct DbInfo {
    pub path: String,
    pub size_bytes: u64,
}

#[derive(Serialize)]
pub struct DbError {
    pub message: String,
}

impl From<PathError> for DbError {
    fn from(e: PathError) -> Self {
        Self { message: e.message }
    }
}

#[tauri::command]
pub async fn get_db_info(app: AppHandle) -> Result<DbInfo, DbError> {
    let paths = get_app_paths(app).map_err(DbError::from)?;
    let path_buf = std::path::PathBuf::from(&paths.db_path);
    let size = if path_buf.exists() {
        std::fs::metadata(&path_buf).map(|m| m.len()).unwrap_or(0)
    } else {
        0
    };
    Ok(DbInfo {
        path: paths.db_path,
        size_bytes: size,
    })
}
