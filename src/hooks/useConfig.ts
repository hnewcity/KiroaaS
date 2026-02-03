import { useState, useEffect } from 'react';
import { loadConfig, saveConfig } from '@/lib/tauri';
import type { AppConfig } from '@/lib/config';
import { DEFAULT_CONFIG } from '@/lib/config';

/**
 * Hook for managing application configuration
 */
export function useConfig() {
  const [config, setConfig] = useState<AppConfig>(DEFAULT_CONFIG);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load config on mount
  useEffect(() => {
    const load = async () => {
      try {
        const loadedConfig = await loadConfig();
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
