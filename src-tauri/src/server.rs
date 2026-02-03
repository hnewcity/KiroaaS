use crate::config::AppConfig;
use serde::{Deserialize, Serialize};
use std::process::{Child, Command, Stdio};
use std::io::{BufRead, BufReader};
use std::sync::{Arc, Mutex};
use std::thread;

/// Server status information
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerStatus {
    pub status: String,
    pub port: Option<u16>,
    pub error: Option<String>,
}

/// Server manager for controlling the Python backend
pub struct ServerManager {
    process: Option<Child>,
    status: ServerStatus,
    logs: Arc<Mutex<Vec<String>>>,
}

impl ServerManager {
    /// Create a new server manager
    pub fn new() -> Self {
        Self {
            process: None,
            status: ServerStatus {
                status: "stopped".to_string(),
                port: None,
                error: None,
            },
            logs: Arc::new(Mutex::new(Vec::new())),
        }
    }

    /// Get server logs
    pub fn get_logs(&self) -> Vec<String> {
        self.logs.lock().unwrap().clone()
    }

    /// Clear server logs
    pub fn clear_logs(&mut self) {
        self.logs.lock().unwrap().clear();
    }

    /// Start the Python server with the given configuration
    pub async fn start(&mut self, config: AppConfig) -> Result<ServerStatus, String> {
        // Stop existing server if running
        if self.process.is_some() {
            self.stop().await?;
        }

        // Update status to starting
        self.status = ServerStatus {
            status: "starting".to_string(),
            port: None,
            error: None,
        };

        // Get the Python executable path
        let python_exe = self.get_python_executable_path()?;

        // Build environment variables from config
        let mut cmd = Command::new(&python_exe);

        // In development mode, run main.py directly
        #[cfg(debug_assertions)]
        {
            cmd.arg("../python-backend/main.py");
        }

        cmd.env("TAURI_MANAGED", "true")
            .env("PROXY_API_KEY", &config.proxy_api_key)
            .env("SERVER_HOST", &config.server_host)
            .env("SERVER_PORT", config.server_port.to_string())
            .env("KIRO_REGION", &config.kiro_region)
            .env("FIRST_TOKEN_TIMEOUT", config.first_token_timeout.to_string())
            .env("STREAMING_READ_TIMEOUT", config.streaming_read_timeout.to_string())
            .env("FAKE_REASONING", config.fake_reasoning.to_string())
            .env("FAKE_REASONING_MAX_TOKENS", config.fake_reasoning_max_tokens.to_string())
            .env("TRUNCATION_RECOVERY", config.truncation_recovery.to_string())
            .env("LOG_LEVEL", &config.log_level)
            .env("DEBUG_MODE", &config.debug_mode);

        // Set authentication method
        match config.auth_method {
            crate::config::AuthMethod::RefreshToken => {
                if let Some(token) = &config.refresh_token {
                    cmd.env("REFRESH_TOKEN", token);
                }
            }
            crate::config::AuthMethod::CredsFile => {
                if let Some(file) = &config.kiro_creds_file {
                    cmd.env("KIRO_CREDS_FILE", file);
                }
            }
            crate::config::AuthMethod::CliDb => {
                if let Some(db) = &config.kiro_cli_db_file {
                    cmd.env("KIRO_CLI_DB_FILE", db);
                }
            }
        }

        // Set VPN proxy if configured
        if let Some(proxy) = &config.vpn_proxy_url {
            cmd.env("VPN_PROXY_URL", proxy);
        }

        // Configure stdio
        cmd.stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .stdin(Stdio::null());

        // Clear old logs
        self.logs.lock().unwrap().clear();

        // Log the executable path for debugging
        if let Ok(mut logs) = self.logs.lock() {
            logs.push(format!("[Debug] Starting server with executable: {}", python_exe));
        }

        // Spawn the process
        let mut child = cmd.spawn().map_err(|e| {
            if let Ok(mut logs) = self.logs.lock() {
                logs.push(format!("[Error] Failed to spawn: {}", e));
            }
            format!("Failed to start server: {}", e)
        })?;

        // Capture stdout for logs and ready signal
        if let Some(stdout) = child.stdout.take() {
            let logs = self.logs.clone();
            let reader = BufReader::new(stdout);
            thread::spawn(move || {
                for line in reader.lines() {
                    if let Ok(line) = line {
                        println!("[Server] {}", line);
                        if let Ok(mut logs) = logs.lock() {
                            logs.push(line.clone());
                            // Keep only last 1000 lines
                            if logs.len() > 1000 {
                                logs.remove(0);
                            }
                        }
                    }
                }
            });
        }

        // Capture stderr for logs
        if let Some(stderr) = child.stderr.take() {
            let logs = self.logs.clone();
            let reader = BufReader::new(stderr);
            thread::spawn(move || {
                for line in reader.lines() {
                    if let Ok(line) = line {
                        eprintln!("[Server Error] {}", line);
                        if let Ok(mut logs) = logs.lock() {
                            logs.push(line.clone());
                            // Keep only last 1000 lines
                            if logs.len() > 1000 {
                                logs.remove(0);
                            }
                        }
                    }
                }
            });
        }

        // Store the process
        self.process = Some(child);

        // Update status to running
        self.status = ServerStatus {
            status: "running".to_string(),
            port: Some(config.server_port),
            error: None,
        };

        Ok(self.status.clone())
    }

    /// Stop the running server
    pub async fn stop(&mut self) -> Result<(), String> {
        if let Some(mut child) = self.process.take() {
            // Try graceful shutdown first
            #[cfg(unix)]
            {
                unsafe {
                    libc::kill(child.id() as i32, libc::SIGTERM);
                }
            }

            #[cfg(windows)]
            {
                let _ = child.kill();
            }

            // Wait for process to exit (with timeout)
            let timeout = std::time::Duration::from_secs(10);
            let start = std::time::Instant::now();

            loop {
                match child.try_wait() {
                    Ok(Some(_)) => break,
                    Ok(None) => {
                        if start.elapsed() > timeout {
                            // Force kill if timeout
                            let _ = child.kill();
                            break;
                        }
                        std::thread::sleep(std::time::Duration::from_millis(100));
                    }
                    Err(e) => {
                        return Err(format!("Error waiting for process: {}", e));
                    }
                }
            }
        }

        // Update status
        self.status = ServerStatus {
            status: "stopped".to_string(),
            port: None,
            error: None,
        };

        Ok(())
    }

    /// Get the current server status
    pub fn get_status(&self) -> ServerStatus {
        self.status.clone()
    }

    /// Get the path to the Python executable
    fn get_python_executable_path(&self) -> Result<String, String> {
        // In production, the Python executable is bundled with the app
        // In development, we use the system Python

        #[cfg(debug_assertions)]
        {
            // Development: use python from system
            Ok("python3".to_string())
        }

        #[cfg(not(debug_assertions))]
        {
            // Production: use bundled executable
            let exe_name = if cfg!(windows) {
                "kiro-gateway.exe"
            } else {
                "kiro-gateway"
            };

            // On macOS, resources are in Contents/Resources/resources/
            // On other platforms, resources are next to the executable
            #[cfg(target_os = "macos")]
            let resource_dir = std::env::current_exe()
                .map_err(|e| format!("Failed to get current exe path: {}", e))?
                .parent() // MacOS/
                .ok_or("Failed to get parent directory")?
                .parent() // Contents/
                .ok_or("Failed to get Contents directory")?
                .join("Resources")
                .join("resources")
                .join(exe_name);

            #[cfg(not(target_os = "macos"))]
            let resource_dir = std::env::current_exe()
                .map_err(|e| format!("Failed to get current exe path: {}", e))?
                .parent()
                .ok_or("Failed to get parent directory")?
                .join("resources")
                .join(exe_name);

            if !resource_dir.exists() {
                return Err(format!("Python executable not found at: {:?}", resource_dir));
            }

            Ok(resource_dir.to_string_lossy().to_string())
        }
    }
}

impl Drop for ServerManager {
    fn drop(&mut self) {
        // Ensure server is stopped when manager is dropped
        if let Some(mut child) = self.process.take() {
            let _ = child.kill();
        }
    }
}
