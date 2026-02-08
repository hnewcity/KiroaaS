/**
 * Configuration types for Kiro Gateway
 */

export type AuthMethod = 'refresh_token' | 'creds_file' | 'cli_db';

export type ServerStatus = 'stopped' | 'starting' | 'running' | 'error';

export interface AppConfig {
  // Authentication (one required)
  auth_method: AuthMethod;
  refresh_token?: string;
  kiro_creds_file?: string;
  kiro_cli_db_file?: string;

  // Required
  proxy_api_key: string;

  // Server
  server_host: string;
  server_port: number;
  kiro_region: string;

  // Advanced
  vpn_proxy_url?: string;
  first_token_timeout: number;
  streaming_read_timeout: number;
  fake_reasoning: boolean;
  fake_reasoning_max_tokens: number;
  truncation_recovery: boolean;
  log_level: string;
  debug_mode: string;

  // Client identity
  client_id?: string;
}

export const DEFAULT_CONFIG: AppConfig = {
  auth_method: 'refresh_token',
  proxy_api_key: '',
  server_host: '127.0.0.1',
  server_port: 8000,
  kiro_region: 'us-east-1',
  first_token_timeout: 15,
  streaming_read_timeout: 300,
  fake_reasoning: true,
  fake_reasoning_max_tokens: 4000,
  truncation_recovery: true,
  log_level: 'INFO',
  debug_mode: 'off',
};

export interface ServerStatusInfo {
  status: ServerStatus;
  port?: number;
  error?: string;
}

export const VERSION_CHECK_API = 'https://api.kiroaas.hnew.city/version';
