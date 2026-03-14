import { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { RotateCw, Loader2, AlertCircle } from 'lucide-react';
import { useI18n } from '@/hooks/useI18n';
import { updateTrayUsage } from '@/lib/tauri';

interface UsageCardProps {
  host: string;
  port: number;
  apiKey: string;
  isRunning: boolean;
}

interface UsageBreakdown {
  usageLimit?: number;
  currentUsage?: number;
  currentUsageWithPrecision?: number;
  usageLimitWithPrecision?: number;
  displayName?: string;
  overageRate?: number;
  currentOverages?: number;
  resourceType?: string;
}

interface UsageData {
  usageBreakdownList?: UsageBreakdown[];
  subscriptionInfo?: { subscriptionTitle?: string; type?: string };
  overageConfiguration?: { overageStatus?: string };
  nextDateReset?: number;
  [key: string]: unknown;
}

// Module-level cache so data survives component unmount/remount
let cachedUsage: UsageData | null = null;

export function UsageCard({ host, port, apiKey, isRunning }: UsageCardProps) {
  const { t } = useI18n();
  const [usage, setUsage] = useState<UsageData | null>(cachedUsage);
  const [loading, setLoading] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchUsage = useCallback(async (): Promise<boolean> => {
    if (!isRunning || !apiKey) return false;
    // Only show loading skeleton when there's no existing data
    if (!cachedUsage) setLoading(true);
    setError(null);
    try {
      const fetchHost = host === '0.0.0.0' ? '127.0.0.1' : host;
      const res = await fetch(`http://${fetchHost}:${port}/usage`, {
        headers: { Authorization: `Bearer ${apiKey}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: UsageData = await res.json();
      setUsage(data);
      cachedUsage = data;
      // Sync tray menu
      const bd = data.usageBreakdownList?.[0];
      const lim = bd?.usageLimitWithPrecision ?? bd?.usageLimit ?? 0;
      const cur = bd?.currentUsageWithPrecision ?? bd?.currentUsage ?? 0;
      if (lim > 0) {
        const p = Math.min(100, Math.round((cur / lim) * 100));
        updateTrayUsage(`Credit: ${cur.toLocaleString()} / ${lim.toLocaleString()} (${p}%)`).catch(() => {});
      }
      return true;
    } catch (e) {
      // Only show error if there's no existing data to display
      if (!cachedUsage) {
        setError(e instanceof Error ? e.message : 'error');
      }
      return false;
    } finally {
      setLoading(false);
    }
  }, [host, port, apiKey, isRunning]);

  useEffect(() => {
    if (!isRunning) {
      setUsage(null); setError(null); setRetrying(false);
      cachedUsage = null;
      updateTrayUsage('Credit: --').catch(() => {});
      return;
    }

    let retries = 0;
    const MAX_RETRIES = 5;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let intervalTimer: ReturnType<typeof setInterval> | null = null;

    const tryInitialFetch = async () => {
      setRetrying(false);
      const ok = await fetchUsage();
      if (ok) {
        intervalTimer = setInterval(fetchUsage, 10 * 60 * 1000);
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
  }, [isRunning, fetchUsage]);

  const breakdown = usage?.usageBreakdownList?.[0];
  const limit = breakdown?.usageLimitWithPrecision ?? breakdown?.usageLimit ?? 0;
  const used = breakdown?.currentUsageWithPrecision ?? breakdown?.currentUsage ?? 0;
  const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  const plan = usage?.subscriptionInfo?.subscriptionTitle;
  const resetDate = usage?.nextDateReset
    ? new Date(usage.nextDateReset * 1000).toLocaleDateString()
    : null;

  const fmtNum = (n: number) => n.toLocaleString();

  return (
    <div className="flex items-center gap-4">
      {/* Title + Refresh */}
      <div className="flex items-center gap-2 shrink-0">
        <span className="text-sm font-semibold text-stone-600">
          {t('creditUsage')}
        </span>
        {isRunning && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 p-0 rounded-full hover:bg-stone-100"
            onClick={fetchUsage}
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

      {/* Content */}
      {!isRunning ? (
        <p className="text-xs text-stone-400 font-medium">{t('usageServerOffline')}</p>
      ) : (loading || retrying) && !usage ? (
        <div className="flex items-center gap-3 flex-1 min-w-0 animate-pulse">
          <div className="h-5 w-16 rounded-full bg-stone-200 shrink-0" />
          <div className="flex items-center gap-3 flex-1 min-w-0">
            <div className="flex-1 h-2 bg-stone-200 rounded-full" />
            <div className="h-3 w-24 bg-stone-200 rounded shrink-0" />
            <div className="h-3 w-8 bg-stone-200 rounded shrink-0" />
          </div>
        </div>
      ) : error ? (
        <div className="flex items-center gap-1.5">
          <AlertCircle className="h-3.5 w-3.5 text-red-400" />
          <p className="text-xs text-red-400 font-medium">{t('usageLoadFailed')}</p>
        </div>
      ) : usage ? (
        <>
          {/* Plan badge */}
          {plan && (
            <span className="px-2.5 py-0.5 rounded-full bg-[#111] text-white text-[10px] font-bold uppercase tracking-wider shrink-0">
              {plan}
            </span>
          )}

          {/* Usage bar */}
          {limit > 0 && (
            <div className="flex items-center gap-3 flex-1 min-w-0">
              <div className="flex-1 min-w-0">
                <div className="h-2 bg-stone-200 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${
                      pct >= 90 ? 'bg-red-500' : pct >= 70 ? 'bg-amber-500' : 'bg-lime-500'
                    }`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
              <span className="text-xs font-bold text-[#111] shrink-0">
                {fmtNum(used)} <span className="text-stone-400 font-normal">/ {fmtNum(limit)}</span>
              </span>
              <span className="text-[10px] text-stone-400 shrink-0">{pct}%</span>
            </div>
          )}

          {/* Reset date */}
          {resetDate && (
            <span className="text-[10px] text-stone-400 shrink-0">{t('usageResets')} {resetDate}</span>
          )}

          {/* Overage */}
          {usage.overageConfiguration?.overageStatus && (
            <div className="flex items-center gap-1.5 shrink-0">
              <div className={`h-1.5 w-1.5 rounded-full ${usage.overageConfiguration.overageStatus === 'ENABLED' ? 'bg-amber-400' : 'bg-stone-300'}`} />
              <span className="text-[10px] text-stone-400 font-medium">
                {t('usageOverage')}: {usage.overageConfiguration.overageStatus === 'ENABLED' ? t('usageOverageOn') : t('usageOverageOff')}
              </span>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
