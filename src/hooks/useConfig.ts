import { useState, useEffect } from 'react';
import { loadConfig, saveConfig, scanAllCredentials } from '@/lib/tauri';
import type { AppConfig, AuthMethod } from '@/lib/config';
import { DEFAULT_CONFIG } from '@/lib/config';

function generateApiKey(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  const key = Array.from({ length: 32 }, () => chars[Math.floor(Math.random() * chars.length)]).join('');
  return `sk-${key}`;
}

/**
 * Hook for managing application configuration
 */
export function useConfig() {
  const [config, setConfig] = useState<AppConfig>(DEFAULT_CONFIG);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load config on mount, auto-initialize missing fields
  useEffect(() => {
    const load = async () => {
      try {
        const loadedConfig = await loadConfig();
        let needsSave = false;

        // Issue 1: Ensure stable client_id
        if (!loadedConfig.client_id) {
          loadedConfig.client_id = crypto.randomUUID();
          needsSave = true;
        }

        // Issue 2: Auto-generate proxy_api_key if empty
        if (!loadedConfig.proxy_api_key) {
          loadedConfig.proxy_api_key = generateApiKey();
          needsSave = true;
        }

        // Issue 3: Auto-apply detected credentials if none configured
        const hasCredential = loadedConfig.refresh_token || loadedConfig.kiro_creds_file || loadedConfig.kiro_cli_db_file;
        if (!hasCredential) {
          try {
            const scan = await scanAllCredentials();
            if (scan.recommended_method && scan.recommended_path) {
              loadedConfig.auth_method = scan.recommended_method as AuthMethod;
              if (scan.recommended_method === 'cli_db') {
                loadedConfig.kiro_cli_db_file = scan.recommended_path;
              } else {
                loadedConfig.kiro_creds_file = scan.recommended_path;
              }
              needsSave = true;
            }
          } catch (scanErr) {
            console.error('Auto-scan credentials failed:', scanErr);
          }
        }

        if (needsSave) {
          await saveConfig(loadedConfig);
        }

        setConfig(loadedConfig);
        setIsLoading(false);
      } catch (err) {
        console.error('Failed to load config:', err);
        setError(err instanceof Error ? err.message : 'Failed to load config');
        setIsLoading(false);
      }
    };

    load();
  }, []);

  // Save config function
  const save = async (newConfig: AppConfig) => {
    try {
      await saveConfig(newConfig);
      setConfig(newConfig);
      setError(null);
    } catch (err) {
      console.error('Failed to save config:', err);
      setError(err instanceof Error ? err.message : 'Failed to save config');
      throw err;
    }
  };

  return {
    config,
    setConfig,
    saveConfig: save,
    isLoading,
    error,
  };
}
