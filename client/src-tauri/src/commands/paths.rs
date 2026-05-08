use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Manager};

#[derive(Serialize)]
pub struct AppPaths {
    pub app_data_dir: String,
    pub db_path: String,
    pub projects_root: String,
}

#[derive(Serialize)]
pub struct PathError {
    pub message: String,
}

#[tauri::command]
pub fn get_app_paths(app: AppHandle) -> Result<AppPaths, PathError> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| PathError { message: e.to_string() })?;
    let db = dir.join("scholarpilot.db");
    let projects = dir.join("projects");
    Ok(AppPaths {
        app_data_dir: dir.to_string_lossy().into_owned(),
        db_path: db.to_string_lossy().into_owned(),
        projects_root: projects.to_string_lossy().into_owned(),
    })
}

/// 启动时 ensure 必要目录骨架（让 `ls AppData/.../top.scholarpilot.client/` 一眼能看到结构）。
///
/// 创建一组固定相对子目录（projects/cache/thumbnails/logs/exports/memory），
/// 已存在的不动。返回成功创建/已存在的绝对路径列表，供 main.ts bootstrap 验证。
#[tauri::command]
pub fn fs_ensure_app_dirs(app: AppHandle) -> Result<Vec<String>, PathError> {
    let root = app
        .path()
        .app_data_dir()
        .map_err(|e| PathError { message: e.to_string() })?;
    // app_data_dir 本身可能还没创建（首次启动），先 ensure
    fs::create_dir_all(&root).map_err(|e| PathError {
        message: format!("create app_data_dir {:?} failed: {}", root, e),
    })?;
    let dirs = [
        "projects",
        "cache/thumbnails",
        "logs",
        "exports",
        "memory",
    ];
    let mut created = Vec::new();
    for d in dirs.iter() {
        let p = root.join(d);
        fs::create_dir_all(&p).map_err(|e| PathError {
            message: format!("mkdir {:?} failed: {}", p, e),
        })?;
        created.push(p.to_string_lossy().into_owned());
    }
    Ok(created)
}

// ─── accounts.json: 多账号注册表 (仿 Obsidian / VS Code Profile 模式) ───
//
// 用途: 让客户端记住"我登录过哪些账号", 登录页能直接显示"上次登录: yjr@example.com"。
// 永远只存元数据 (email + display_name + user_id + last_login_at), **绝不**存
// 密码 / token (那些走 OS keychain via secure_storage)。
//
// 切账号流程 (Figma / Standard Notes 模式):
// - logout: closeDatabase + fs_remove(scholarpilot.db / projects / cache) + accounts_clear_active
// - login: secureSet(token) + accounts_remember_user(email, ...)
//
// 后续多账号并存(M1+) 改造时, 这个注册表会演化成 active_user_email 决定
// app_data_dir/users/<id>/scholarpilot.db 子目录路由的入口。

#[derive(Serialize, Deserialize, Clone, Default)]
pub struct AccountEntry {
    pub email: String,
    pub display_name: Option<String>,
    pub user_id: Option<String>,
    pub last_login_at: u64, // unix ms
}

#[derive(Serialize, Deserialize, Default)]
pub struct AccountsRegistry {
    pub version: u32,
    pub active_user_email: Option<String>,
    pub users: HashMap<String, AccountEntry>,
}

fn accounts_path(app: &AppHandle) -> Result<PathBuf, PathError> {
    let root = app
        .path()
        .app_data_dir()
        .map_err(|e| PathError { message: e.to_string() })?;
    Ok(root.join("accounts.json"))
}

fn read_accounts(app: &AppHandle) -> AccountsRegistry {
    let Ok(p) = accounts_path(app) else {
        return AccountsRegistry { version: 1, ..Default::default() };
    };
    if !p.exists() {
        return AccountsRegistry { version: 1, ..Default::default() };
    }
    fs::read_to_string(&p)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_else(|| AccountsRegistry { version: 1, ..Default::default() })
}

fn write_accounts(app: &AppHandle, reg: &AccountsRegistry) -> Result<(), PathError> {
    let p = accounts_path(app)?;
    if let Some(parent) = p.parent() {
        fs::create_dir_all(parent).map_err(|e| PathError {
            message: format!("create_dir_all {:?}: {}", parent, e),
        })?;
    }
    let s = serde_json::to_string_pretty(reg)
        .map_err(|e| PathError { message: format!("serialize accounts: {}", e) })?;
    fs::write(&p, s).map_err(|e| PathError {
        message: format!("write {:?}: {}", p, e),
    })?;
    Ok(())
}

#[tauri::command]
pub fn accounts_remember_user(
    app: AppHandle,
    email: String,
    display_name: Option<String>,
    user_id: Option<String>,
) -> Result<(), PathError> {
    let mut reg = read_accounts(&app);
    if reg.version == 0 {
        reg.version = 1;
    }
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0);
    reg.users.insert(
        email.clone(),
        AccountEntry { email: email.clone(), display_name, user_id, last_login_at: now },
    );
    reg.active_user_email = Some(email);
    write_accounts(&app, &reg)
}

#[tauri::command]
pub fn accounts_clear_active(app: AppHandle) -> Result<(), PathError> {
    let mut reg = read_accounts(&app);
    reg.active_user_email = None;
    write_accounts(&app, &reg)
}

#[tauri::command]
pub fn accounts_get_recent(
    app: AppHandle,
    limit: Option<usize>,
) -> Result<Vec<AccountEntry>, PathError> {
    let reg = read_accounts(&app);
    let mut v: Vec<AccountEntry> = reg.users.into_values().collect();
    v.sort_by(|a, b| b.last_login_at.cmp(&a.last_login_at));
    let n = limit.unwrap_or(5);
    v.truncate(n);
    Ok(v)
}

#[tauri::command]
pub fn accounts_get_active(app: AppHandle) -> Result<Option<String>, PathError> {
    Ok(read_accounts(&app).active_user_email)
}

/// 让 webview 把 JS 错误 / unhandledrejection / console.error 转发到 Rust log,
/// 写到 <app_data_dir>/logs/ScholarPilot.log。打包后 .msi 用户也能 ls log 看错。
#[tauri::command]
pub fn log_webview_error(level: String, message: String, source: Option<String>) {
    let src = source.unwrap_or_else(|| "webview".to_string());
    match level.as_str() {
        "error" => log::error!("[webview/{}] {}", src, message),
        "warn" => log::warn!("[webview/{}] {}", src, message),
        _ => log::info!("[webview/{}] {}", src, message),
    }
}

/// 把"相对 app_data_dir"的路径转成绝对路径，并校验未逃出 root（防 `../` 攻击）。
///
/// 纯 Path component 检查 —— 不依赖 `canonicalize()`（要求文件已存在），
/// 也避开 Windows `\\?\` UNC 前缀跟普通路径前缀不一致的坑。
/// 拒绝：绝对路径（is_absolute）、含 `..` 段（ParentDir）、Windows drive prefix。
pub(crate) fn resolve_safe(app: &AppHandle, rel: &str) -> Result<std::path::PathBuf, PathError> {
    let rel_path = std::path::Path::new(rel);
    if rel_path.is_absolute() {
        return Err(PathError {
            message: format!("path escape detected: {}", rel),
        });
    }
    for component in rel_path.components() {
        match component {
            std::path::Component::ParentDir
            | std::path::Component::Prefix(_)
            | std::path::Component::RootDir => {
                return Err(PathError {
                    message: format!("path escape detected: {}", rel),
                });
            }
            _ => {}
        }
    }
    let root = app
        .path()
        .app_data_dir()
        .map_err(|e| PathError { message: e.to_string() })?;
    Ok(root.join(rel))
}
