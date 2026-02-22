// Prevents additional console window on Windows in release builds
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod config;
mod conversations;
mod server;

use config::{AppConfig, load_config, save_config};
use conversations::{Conversation, ConversationsData, load_conversations, save_conversations};
use server::{ServerManager, ServerStatus};
use tauri::{Manager, RunEvent, State, SystemTray, SystemTrayEvent, SystemTrayMenu, CustomMenuItem};
use tokio::sync::Mutex;

/// Global server manager state
struct AppState {
    server_manager: Mutex<ServerManager>,
    conversations_lock: Mutex<()>,
}

/// Start the Python server with the given configuration
#[tauri::command]
async fn start_server(
    config: AppConfig,
    state: State<'_, AppState>,
) -> Result<ServerStatus, String> {
    // Validate that credentials are configured for the selected auth method
    let has_credentials = match &config.auth_method {
        crate::config::AuthMethod::RefreshToken => {
            config.refresh_token.as_ref().map_or(false, |t| !t.is_empty())
        }
        crate::config::AuthMethod::CredsFile => {
            config.kiro_creds_file.as_ref().map_or(false, |f| !f.is_empty())
        }
        crate::config::AuthMethod::CliDb => {
            config.kiro_cli_db_file.as_ref().map_or(false, |d| !d.is_empty())
        }
    };

    if !has_credentials {
        return Err("No credentials configured. Please set up authentication in Settings first.".to_string());
    }

    let mut manager = state.server_manager.lock().await;
    manager.start(config).await
}

/// Stop the running Python server
#[tauri::command]
async fn stop_server(state: State<'_, AppState>) -> Result<(), String> {
    let mut manager = state.server_manager.lock().await;
    manager.stop().await
}

/// Get the current server status
#[tauri::command]
async fn get_server_status(state: State<'_, AppState>) -> Result<ServerStatus, String> {
    let manager = state.server_manager.lock().await;
    Ok(manager.get_status())
}

/// Get server logs
#[tauri::command]
async fn get_server_logs(state: State<'_, AppState>) -> Result<Vec<String>, String> {
    let manager = state.server_manager.lock().await;
    Ok(manager.get_logs())
}

/// Check for application updates
#[tauri::command]
async fn check_for_updates(app: tauri::AppHandle) -> Result<bool, String> {
    match app.updater().check().await {
        Ok(update) => {
            if update.is_update_available() {
                Ok(true)
            } else {
                Ok(false)
            }
        }
        Err(e) => Err(format!("Failed to check for updates: {}", e)),
    }
}

/// Get the application version
#[tauri::command]
fn get_app_version(app: tauri::AppHandle) -> String {
    app.package_info().version.to_string()
}

/// Get the device model name
#[tauri::command]
fn get_device_model() -> String {
    #[cfg(target_os = "macos")]
    {
        use std::process::Command;
        if let Ok(output) = Command::new("sysctl").arg("-n").arg("hw.model").output() {
            if output.status.success() {
                return String::from_utf8_lossy(&output.stdout).trim().to_string();
            }
        }
        "Unknown Mac".to_string()
    }
    #[cfg(target_os = "linux")]
    {
        if let Ok(model) = std::fs::read_to_string("/sys/devices/virtual/dmi/id/product_name") {
            return model.trim().to_string();
        }
        "Unknown Linux Device".to_string()
    }
    #[cfg(target_os = "windows")]
    {
        use std::process::Command;
        use std::os::windows::process::CommandExt;
        if let Ok(output) = Command::new("wmic")
            .args(["computersystem", "get", "model"])
            .creation_flags(0x08000000)
            .output()
        {
            if output.status.success() {
                let text = String::from_utf8_lossy(&output.stdout);
                let model = text.lines().nth(1).unwrap_or("").trim();
                if !model.is_empty() {
                    return model.to_string();
                }
            }
        }
        "Unknown Windows Device".to_string()
    }
}

/// Install pending update and restart
#[tauri::command]
async fn install_update(app: tauri::AppHandle) -> Result<(), String> {
    match app.updater().check().await {
        Ok(update) => {
            if update.is_update_available() {
                update.download_and_install().await
                    .map_err(|e| format!("Failed to install update: {}", e))?;
                Ok(())
            } else {
                Err("No update available".to_string())
            }
        }
        Err(e) => Err(format!("Failed to check for updates: {}", e)),
    }
}

/// Clear server logs
#[tauri::command]
async fn clear_server_logs(state: State<'_, AppState>) -> Result<(), String> {
    let mut manager = state.server_manager.lock().await;
    manager.clear_logs();
    Ok(())
}

/// Save configuration to disk
#[tauri::command]
async fn save_config_cmd(config: AppConfig) -> Result<(), String> {
    save_config(&config).await
}

/// Load configuration from disk
#[tauri::command]
async fn load_config_cmd() -> Result<AppConfig, String> {
    load_config().await
}

/// Validate credentials (placeholder for now)
#[tauri::command]
async fn validate_credentials(_auth_method: String) -> Result<bool, String> {
    // TODO: Implement actual credential validation
    // For now, just return true
    Ok(true)
}

/// Scan for credential files in common locations
#[tauri::command]
async fn scan_credentials(auth_method: String) -> Result<Vec<String>, String> {
    use std::path::PathBuf;

    let mut found_paths = Vec::new();

    if auth_method == "creds_file" {
        // Common locations for kiro-credentials.json
        let home = dirs::home_dir().ok_or("Failed to get home directory")?;
        let search_paths = vec![
            home.join(".aws/sso/cache/kiro-auth-token.json"),
            home.join(".config/kiro/kiro-credentials.json"),
            home.join(".kiro/kiro-credentials.json"),
            home.join("kiro-credentials.json"),
            PathBuf::from("/etc/kiro/kiro-credentials.json"),
        ];

        for path in search_paths {
            if path.exists() {
                if let Some(path_str) = path.to_str() {
                    found_paths.push(path_str.to_string());
                }
            }
        }
    } else if auth_method == "cli_db" {
        // Common locations for kiro-cli database
        let home = dirs::home_dir().ok_or("Failed to get home directory")?;
        let data_dir = dirs::data_local_dir().ok_or("Failed to get data directory")?;
        let search_paths = vec![
            data_dir.join("kiro-cli/data.sqlite3"),
            home.join(".local/share/kiro-cli/data.sqlite3"),
            home.join(".config/kiro-cli/data.sqlite3"),
            home.join(".kiro-cli/data.sqlite3"),
        ];

        for path in search_paths {
            if path.exists() {
                if let Some(path_str) = path.to_str() {
                    found_paths.push(path_str.to_string());
                }
            }
        }
    }

    Ok(found_paths)
}

/// Scan all credential types and return what's available
#[derive(serde::Serialize)]
struct CredentialScanResult {
    creds_files: Vec<String>,
    cli_dbs: Vec<String>,
    recommended_method: Option<String>,
    recommended_path: Option<String>,
}

#[tauri::command]
async fn scan_all_credentials() -> Result<CredentialScanResult, String> {
    use std::path::PathBuf;

    let home = dirs::home_dir().ok_or("Failed to get home directory")?;
    let data_dir = dirs::data_local_dir().ok_or("Failed to get data directory")?;

    // Scan for credentials files
    let mut creds_files = Vec::new();
    let creds_search_paths = vec![
        home.join(".aws/sso/cache/kiro-auth-token.json"),
        home.join(".config/kiro/kiro-credentials.json"),
        home.join(".kiro/kiro-credentials.json"),
        home.join("kiro-credentials.json"),
        PathBuf::from("/etc/kiro/kiro-credentials.json"),
    ];

    for path in creds_search_paths {
        if path.exists() {
            if let Some(path_str) = path.to_str() {
                creds_files.push(path_str.to_string());
            }
        }
    }

    // Scan for CLI databases
    let mut cli_dbs = Vec::new();
    let cli_search_paths = vec![
        data_dir.join("kiro-cli/data.sqlite3"),
        home.join(".local/share/kiro-cli/data.sqlite3"),
        home.join(".config/kiro-cli/data.sqlite3"),
        home.join(".kiro-cli/data.sqlite3"),
    ];

    for path in cli_search_paths {
        if path.exists() {
            if let Some(path_str) = path.to_str() {
                cli_dbs.push(path_str.to_string());
            }
        }
    }

    // Determine recommendation (prefer CLI DB > Creds File)
    let (recommended_method, recommended_path) = if !cli_dbs.is_empty() {
        (Some("cli_db".to_string()), Some(cli_dbs[0].clone()))
    } else if !creds_files.is_empty() {
        (Some("creds_file".to_string()), Some(creds_files[0].clone()))
    } else {
        (None, None)
    };

    Ok(CredentialScanResult {
        creds_files,
        cli_dbs,
        recommended_method,
        recommended_path,
    })
}

/// Load conversations from disk
#[tauri::command]
async fn load_conversations_cmd() -> Result<ConversationsData, String> {
    load_conversations().await
}

/// Save conversations to disk
#[tauri::command]
async fn save_conversations_cmd(data: ConversationsData, state: State<'_, AppState>) -> Result<(), String> {
    let _lock = state.conversations_lock.lock().await;
    save_conversations(&data).await
}

/// Create a new conversation
#[tauri::command]
async fn create_conversation(conversation: Conversation, state: State<'_, AppState>) -> Result<(), String> {
    let _lock = state.conversations_lock.lock().await;
    let mut data = load_conversations().await?;
    data.conversations.insert(0, conversation);
    save_conversations(&data).await
}

/// Update an existing conversation
#[tauri::command]
async fn update_conversation(conversation: Conversation, state: State<'_, AppState>) -> Result<(), String> {
    let _lock = state.conversations_lock.lock().await;
    let mut data = load_conversations().await?;
    if let Some(pos) = data.conversations.iter().position(|c| c.id == conversation.id) {
        data.conversations[pos] = conversation;
        save_conversations(&data).await
    } else {
        Err("Conversation not found".to_string())
    }
}

/// Delete a conversation
#[tauri::command]
async fn delete_conversation(id: String, state: State<'_, AppState>) -> Result<(), String> {
    let _lock = state.conversations_lock.lock().await;
    let mut data = load_conversations().await?;
    data.conversations.retain(|c| c.id != id);
    save_conversations(&data).await
}

/// Rename a conversation
#[tauri::command]
async fn rename_conversation(id: String, title: String, state: State<'_, AppState>) -> Result<(), String> {
    let _lock = state.conversations_lock.lock().await;
    let mut data = load_conversations().await?;
    if let Some(conv) = data.conversations.iter_mut().find(|c| c.id == id) {
        conv.title = title;
        save_conversations(&data).await
    } else {
        Err("Conversation not found".to_string())
    }
}

fn main() {
    let show = CustomMenuItem::new("show".to_string(), "显示窗口");
    let hide = CustomMenuItem::new("hide".to_string(), "隐藏窗口");
    let quit = CustomMenuItem::new("quit".to_string(), "退出");
    let tray_menu = SystemTrayMenu::new()
        .add_item(show)
        .add_item(hide)
        .add_native_item(tauri::SystemTrayMenuItem::Separator)
        .add_item(quit);
    let system_tray = SystemTray::new().with_menu(tray_menu);

    tauri::Builder::default()
        .system_tray(system_tray)
        .on_system_tray_event(|app, event| match event {
            SystemTrayEvent::DoubleClick { .. } => {
                let window = app.get_window("main").unwrap();
                if window.is_visible().unwrap_or(false) {
                    let _ = window.hide();
                } else {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
            SystemTrayEvent::MenuItemClick { id, .. } => match id.as_str() {
                "show" => {
                    let window = app.get_window("main").unwrap();
                    let _ = window.show();
                    let _ = window.set_focus();
                }
                "hide" => {
                    let window = app.get_window("main").unwrap();
                    let _ = window.hide();
                }
                "quit" => {
                    let state: State<AppState> = app.state();
                    if let Ok(mut manager) = state.server_manager.try_lock() {
                        ServerManager::kill_process(&mut manager);
                    }
                    app.exit(0);
                }
                _ => {}
            },
            _ => {}
        })
        .manage(AppState {
            server_manager: Mutex::new(ServerManager::new()),
            conversations_lock: Mutex::new(()),
        })
        .invoke_handler(tauri::generate_handler![
            start_server,
            stop_server,
            get_server_status,
            get_server_logs,
            clear_server_logs,
            save_config_cmd,
            load_config_cmd,
            validate_credentials,
            scan_credentials,
            scan_all_credentials,
            check_for_updates,
            install_update,
            get_app_version,
            get_device_model,
            load_conversations_cmd,
            save_conversations_cmd,
            create_conversation,
            update_conversation,
            delete_conversation,
            rename_conversation,
        ])
        .on_window_event(|event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event.event() {
                // Hide the window instead of closing — service keeps running
                api.prevent_close();
                let _ = event.window().hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::Reopen { has_visible_windows, .. } = event {
                if !has_visible_windows {
                    if let Some(window) = app_handle.get_window("main") {
                        let _ = window.show();
                        let _ = window.set_focus();
                    }
                }
            }
        });
}
