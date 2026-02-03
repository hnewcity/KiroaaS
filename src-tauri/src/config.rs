use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tokio::fs;

/// Authentication method
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AuthMethod {
    RefreshToken,
    CredsFile,
    CliDb,
}

/// Application configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    // Authentication
    pub auth_method: AuthMethod,
    pub refresh_token: Option<String>,
    pub kiro_creds_file: Option<String>,
    pub kiro_cli_db_file: Option<String>,

    // Required
    pub proxy_api_key: String,

    // Server
    pub server_host: String,
    pub server_port: u16,
    pub kiro_region: String,

    // Advanced
    pub vpn_proxy_url: Option<String>,
    pub first_token_timeout: f32,
    pub streaming_read_timeout: f32,
    pub fake_reasoning: bool,
    pub fake_reasoning_max_tokens: u32,
    pub truncation_recovery: bool,
    pub log_level: String,
    pub debug_mode: String,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            auth_method: AuthMethod::RefreshToken,
            refresh_token: None,
            kiro_creds_file: None,
            kiro_cli_db_file: None,
            proxy_api_key: String::new(),
            server_host: "127.0.0.1".to_string(),
            server_port: 8000,
            kiro_region: "us-east-1".to_string(),
            vpn_proxy_url: None,
            first_token_timeout: 15.0,
            streaming_read_timeout: 300.0,
            fake_reasoning: true,
            fake_reasoning_max_tokens: 4000,
            truncation_recovery: true,
            log_level: "INFO".to_string(),
            debug_mode: "off".to_string(),
        }
    }
}

/// Get the config file path
fn get_config_path() -> Result<PathBuf, String> {
    let app_dir = dirs::data_dir()
        .ok_or("Failed to get app data directory")?
        .join("kiroaas");

    Ok(app_dir.join("config.json"))
}

/// Load configuration from disk
pub async fn load_config() -> Result<AppConfig, String> {
    let config_path = get_config_path()?;

    if !config_path.exists() {
        // Return default config if file doesn't exist
        return Ok(AppConfig::default());
    }

    let content = fs::read_to_string(&config_path)
        .await
        .map_err(|e| format!("Failed to read config file: {}", e))?;

    let config: AppConfig = serde_json::from_str(&content)
        .map_err(|e| format!("Failed to parse config file: {}", e))?;

    Ok(config)
}

/// Save configuration to disk
pub async fn save_config(config: &AppConfig) -> Result<(), String> {
    let config_path = get_config_path()?;

    // Create parent directory if it doesn't exist
    if let Some(parent) = config_path.parent() {
        fs::create_dir_all(parent)
            .await
            .map_err(|e| format!("Failed to create config directory: {}", e))?;
    }

    let content = serde_json::to_string_pretty(config)
        .map_err(|e| format!("Failed to serialize config: {}", e))?;

    fs::write(&config_path, content)
        .await
        .map_err(|e| format!("Failed to write config file: {}", e))?;

    Ok(())
}
