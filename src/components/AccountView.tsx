import { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { RotateCw, Loader2 } from 'lucide-react';
import { useI18n } from '@/hooks/useI18n';
import { AccountCard } from './AccountCard';

interface AccountViewProps {
  host: string;
  port: number;
  apiKey: string;
  isRunning: boolean;
}

interface AccountData {
  accountName?: string;
  email?: string;
  provider?: string;
  planType?: string;
  subscriptionTitle?: string;
  isTrial?: boolean;
  trialExpiryDate?: string;
  subscriptionExpiryDate?: string;
  totalQuota?: number;
  currentUsage?: number;
  remainingQuota?: number;
  usagePercentage?: number;
  bonusQuota?: number;
  bonusUsage?: number;
  bonusRemaining?: number;
  accountStatus?: string;
  resetDate?: string;
  overageEnabled?: boolean;
}

// Module-level cache so data survives component unmount/remount
let cachedAccount: AccountData | null = null;

export function AccountView({ host, port, apiKey, isRunning }: AccountViewProps) {
  const { t } = useI18n();
  const [account, setAccount] = useState<AccountData | null>(cachedAccount);
  const [loading, setLoading] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchAccount = useCallback(async (): Promise<boolean> => {
    if (!isRunning || !apiKey) return false;
    if (!cachedAccount) setLoading(true);
    setError(null);
    try {
      // Call our backend /account endpoint which calls Kiro Portal API
      const fetchHost = host === '0.0.0.0' ? '127.0.0.1' : host;
      const res = await fetch(`http://${fetchHost}:${port}/account`, {
        headers: { Authorization: `Bearer ${apiKey}` },
      });

      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(`HTTP ${res.status}: ${errorText}`);
      }

      const data: AccountData = await res.json();
      setAccount(data);
      cachedAccount = data;
      return true;
    } catch (e) {
      if (!cachedAccount) {
        setError(e instanceof Error ? e.message : 'error');
      }
      return false;
    } finally {
      setLoading(false);
    }
  }, [host, port, apiKey, isRunning]);

  useEffect(() => {
    if (!isRunning) {
      setAccount(null);
      setError(null);
      setRetrying(false);
      cachedAccount = null;
      return;
    }

    let retries = 0;
    const MAX_RETRIES = 5;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let intervalTimer: ReturnType<typeof setInterval> | null = null;

    const tryInitialFetch = async () => {
      setRetrying(false);
      const ok = await fetchAccount();
      if (ok) {
        intervalTimer = setInterval(fetchAccount, 10 * 60 * 1000);
      } else if (retries < MAX_RETRIES) {
        retries++;
        setError(null);
        setRetrying(true);
        retryTimer = setTimeout(tryInitialFetch, 3000);
      }
    };

    tryInitialFetch();

    return () => {
      if (retryTimer) clearTimeout(retryTimer);
      if (intervalTimer) clearInterval(intervalTimer);
    };
  }, [isRunning, fetchAccount]);

  return (
    <div className="space-y-6 pb-4">
      {/* Header with Refresh Button */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-stone-600">
            {t('accountInformation')}
          </span>
          {isRunning && (
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0 rounded-full hover:bg-stone-100"
              onClick={fetchAccount}
              disabled={loading}
            >
              {loading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-stone-400" />
              ) : (
                <RotateCw className="h-3.5 w-3.5 text-stone-400" />
              )}
            </Button>
          )}
        </div>
      </div>

      {/* Content */}
      {!isRunning ? (
        <div className="p-6 bg-stone-50 rounded-lg border border-stone-200 text-center">
          <p className="text-sm text-stone-500 font-medium">{t('accountServerOffline')}</p>
        </div>
      ) : (
        <div className="bg-white rounded-[32px] p-8 shadow-sm">
          <AccountCard data={account} loading={loading || retrying} error={error} />
        </div>
      )}
    </div>
  );
}
