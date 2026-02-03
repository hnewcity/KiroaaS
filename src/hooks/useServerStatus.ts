import { useState, useEffect } from 'react';
import { getServerStatus } from '@/lib/tauri';
import type { ServerStatusInfo } from '@/lib/config';

/**
 * Hook for monitoring server status
 * Polls the server status every 2 seconds
 */
export function useServerStatus() {
  const [status, setStatus] = useState<ServerStatusInfo>({
    status: 'stopped',
    port: undefined,
    error: undefined,
  });
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    let intervalId: number;

    const fetchStatus = async () => {
      try {
        const newStatus = await getServerStatus();
        if (mounted) {
          setStatus(newStatus);
          setIsLoading(false);
        }
      } catch (error) {
        console.error('Failed to fetch server status:', error);
        if (mounted) {
          setIsLoading(false);
        }
      }
    };

    // Initial fetch
    fetchStatus();

    // Poll every 2 seconds
    intervalId = window.setInterval(fetchStatus, 2000);

    return () => {
      mounted = false;
      window.clearInterval(intervalId);
    };
  }, []);

  return { status, isLoading };
}
