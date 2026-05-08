// Tauri 2 application library entry. main.rs delegates to run() so the same
// codepath can be reused by mobile entry points (when we eventually add them).

mod commands;
mod pdf_fetcher;

use commands::secure_storage::{secure_set, secure_get, secure_delete};
use tauri::Manager;
use tauri_plugin_log::{Target, TargetKind};
use tauri_plugin_sql::{Migration, MigrationKind};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let migrations = vec![
        Migration {
            version: 1,
            description: "M2 initial local schema (projects/rounds/documents/conversation/notebook/settings/sync_state)",
            sql: include_str!("../migrations/v1_initial.sql"),
            kind: MigrationKind::Up,
        },
        Migration {
            version: 2,
            description: "M3 Phase B: add llm_run_jobs table for resumable LLM queue",
            sql: include_str!("../migrations/v2_llm_run_jobs.sql"),
            kind: MigrationKind::Up,
        },
    ];

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(
            tauri_plugin_sql::Builder::default()
                .add_migrations("sqlite:scholarpilot.db", migrations)
                .build(),
        )
        // 文件日志: 按日期分文件
        //   <app_data_dir>/logs/ScholarPilot-<YYYY-MM-DD>.log     (info+)
        //   <app_data_dir>/logs/ScholarPilot-errors-<YYYY-MM-DD>.log (warn+)
        //   stderr (vite/cargo terminal 同步可见)
        // 启动时按本地日期生成 file_name; 跨天运行的客户端继续写当前文件,
        // 下次启动新文件 (折中方案: plugin-log 不支持 midnight rotate)。
        .setup(|app| {
            let log_dir = app
                .path()
                .app_data_dir()
                .expect("app_data_dir resolve failed")
                .join("logs");
            std::fs::create_dir_all(&log_dir).ok();
            let today = chrono::Local::now().format("%Y-%m-%d").to_string();
            let log_plugin = tauri_plugin_log::Builder::new()
                .targets([
                    Target::new(TargetKind::Folder {
                        path: log_dir.clone(),
                        file_name: Some(format!("ScholarPilot-{}", today)),
                    }),
                    Target::new(TargetKind::Folder {
                        path: log_dir,
                        file_name: Some(format!("ScholarPilot-errors-{}", today)),
                    })
                    .filter(|m| m.level() <= log::Level::Warn),
                    Target::new(TargetKind::Stderr),
                ])
                .level(log::LevelFilter::Info)
                .build();
            app.handle().plugin(log_plugin)?;
            log::info!("[startup] ScholarPilot client booted");
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            secure_set,
            secure_get,
            secure_delete,
            commands::paths::get_app_paths,
            commands::paths::fs_ensure_app_dirs,
            commands::paths::accounts_remember_user,
            commands::paths::accounts_clear_active,
            commands::paths::accounts_get_recent,
            commands::paths::accounts_get_active,
            commands::paths::log_webview_error,
            commands::fs::fs_write_text,
            commands::fs::fs_read_text,
            commands::fs::fs_write_bytes_b64,
            commands::fs::fs_read_bytes_b64,
            commands::fs::fs_exists,
            commands::fs::fs_remove,
            commands::fs::fs_size,
            commands::fs::fs_list_dir,
            commands::db::get_db_info,
            pdf_fetcher::pdf_fetch_direct,
            pdf_fetcher::pdf_fetch_via_resolve_url,
            pdf_fetcher::pdf_fetch_via_proxy,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
