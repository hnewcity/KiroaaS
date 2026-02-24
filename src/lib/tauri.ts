/**
 * Tauri API wrapper functions
 *
 * These functions wrap Tauri commands for type safety and easier usage.
 */

import { invoke } from '@tauri-apps/api/tauri';
import type { AppConfig, ServerStatusInfo } from './config';

export async function startServer(config: AppConfig): Promise<ServerStatusInfo> {
  return await invoke('start_server', { config });
}

export async function stopServer(): Promise<void> {
  return await invoke('stop_server');
}

export async function getServerStatus(): Promise<ServerStatusInfo> {
  return await invoke('get_server_status');
}

export async function saveConfig(config: AppConfig): Promise<void> {
  return await invoke('save_config_cmd', { config });
}

export async function loadConfig(): Promise<AppConfig> {
  return await invoke('load_config_cmd');
}

export async function validateCredentials(authMethod: string): Promise<boolean> {
  return await invoke('validate_credentials', { authMethod });
}

export async function scanCredentials(authMethod: string): Promise<string[]> {
  return await invoke('scan_credentials', { authMethod });
}

export interface CredentialScanResult {
  creds_files: string[];
  cli_dbs: string[];
  recommended_method: string | null;
  recommended_path: string | null;
}

export async function scanAllCredentials(): Promise<CredentialScanResult> {
  return await invoke('scan_all_credentials');
}

export async function getServerLogs(): Promise<string[]> {
  return await invoke('get_server_logs');
}

export async function clearServerLogs(): Promise<void> {
  return await invoke('clear_server_logs');
}

export async function checkForUpdates(): Promise<boolean> {
  return await invoke('check_for_updates');
}

export async function installUpdate(): Promise<void> {
  return await invoke('install_update');
}

export async function getAppVersion(): Promise<string> {
  return await invoke('get_app_version');
}

export async function getDeviceModel(): Promise<string> {
  return await invoke('get_device_model');
}

// Conversation management
import type { Conversation, ConversationsData } from './conversations';

export async function loadConversations(): Promise<ConversationsData> {
  return await invoke('load_conversations_cmd');
}

export async function saveConversations(data: ConversationsData): Promise<void> {
  return await invoke('save_conversations_cmd', { data });
}

export async function createConversation(conversation: Conversation): Promise<void> {
  return await invoke('create_conversation', { conversation });
}

export async function updateConversation(conversation: Conversation): Promise<void> {
  return await invoke('update_conversation', { conversation });
}

export async function deleteConversation(id: string): Promise<void> {
  return await invoke('delete_conversation', { id });
}

export async function renameConversation(id: string, title: string): Promise<void> {
  return await invoke('rename_conversation', { id, title });
}

export async function updateTrayLanguage(labels: {
  startServerLabel: string;
  stopServerLabel: string;
  restartServerLabel: string;
  showWindowLabel: string;
  hideWindowLabel: string;
  quitLabel: string;
}): Promise<void> {
  return await invoke('update_tray_language', labels);
}
