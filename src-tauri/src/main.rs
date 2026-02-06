// Prevents additional console window on Windows in release builds
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod config;
mod conversations;
mod server;

use config::{AppConfig, load_config, save_config};
use conversations::{Conversation, ConversationsData, load_conversations, save_conversations};
use server::{ServerManager, ServerStatus};
use tauri::{Manager, State};
use tokio::sync::Mutex;

/// Global server manager state
struct AppState {
    server_manager: Mutex<ServerManager>,
}

/// Start the Python server with the given configuration
#[tauri::command]
async fn start_server(
    config: AppConfig,
    state: State<'_, AppState>,
) -> Result<ServerStatus, String> {
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
async fn save_conversations_cmd(data: ConversationsData) -> Result<(), String> {
    save_conversations(&data).await
}

/// Create a new conversation
#[tauri::command]
async fn create_conversation(conversation: Conversation) -> Result<(), String> {
    let mut data = load_conversations().await?;
    data.conversations.insert(0, conversation);
    save_conversations(&data).await
}

/// Update an existing conversation
#[tauri::command]
async fn update_conversation(conversation: Conversation) -> Result<(), String> {
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
async fn delete_conversation(id: String) -> Result<(), String> {
    let mut data = load_conversations().await?;
    data.conversations.retain(|c| c.id != id);
    save_conversations(&data).await
}

/// Rename a conversation
#[tauri::command]
async fn rename_conversation(id: String, title: String) -> Result<(), String> {
    let mut data = load_conversations().await?;
    if let Some(conv) = data.conversations.iter_mut().find(|c| c.id == id) {
        conv.title = title;
        save_conversations(&data).await
    } else {
        Err("Conversation not found".to_string())
    }
}

fn main() {
    tauri::Builder::default()
        .manage(AppState {
            server_manager: Mutex::new(ServerManager::new()),
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
            load_conversations_cmd,
            save_conversations_cmd,
            create_conversation,
            update_conversation,
            delete_conversation,
            rename_conversation,
        ])
        .on_window_event(|event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event.event() {
                // Stop the server when window is closing
                let app_handle = event.window().app_handle();
                let state: State<AppState> = app_handle.state();

                // Use blocking to stop the server synchronously
                if let Ok(mut manager) = state.server_manager.try_lock() {
                    // Manually kill the process since we can't use async here
                    ServerManager::kill_process(&mut manager);
                };
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
