import { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { RotateCw, Loader2, AlertCircle, ChevronDown, Calendar, Mail } from 'lucide-react';
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
  currentOveragesWithPrecision?: number;
  overageCap?: number;
  overageCapWithPrecision?: number;
  resourceType?: string;
  resetDate?: string;
  freeTrialInfo?: {
    usageLimit?: number;
    usageLimitWithPrecision?: number;
    currentUsage?: number;
    currentUsageWithPrecision?: number;
    freeTrialStatus?: string;
    freeTrialExpiry?: number;
  };
}

interface UsageData {
  usageBreakdownList?: UsageBreakdown[];
  userInfo?: { email?: string; provider?: string };
  subscriptionInfo?: {
    subscriptionTitle?: string;
    type?: string;
    status?: string;
    expiryDate?: string;
    subscriptionExpiryDate?: string;
  };
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
  const [expanded, setExpanded] = useState(false);

  const fetchUsage = useCallback(async (): Promise<boolean> => {
    if (!isRunning || !apiKey) return false;
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

      const bd = data.usageBreakdownList?.[0];
      const bonusBd = data.usageBreakdownList?.[1];
      const ft = bd?.freeTrialInfo;
      const tLim = ft?.usageLimitWithPrecision ?? ft?.usageLimit ?? 0;
      const tUsed = ft?.currentUsageWithPrecision ?? ft?.currentUsage ?? 0;
      const fLim = bd?.usageLimitWithPrecision ?? bd?.usageLimit ?? 0;
      const fUsed = bd?.currentUsageWithPrecision ?? bd?.currentUsage ?? 0;
      const bLim = bonusBd?.usageLimitWithPrecision ?? bonusBd?.usageLimit ?? 0;
      const bUsed = bonusBd?.currentUsageWithPrecision ?? bonusBd?.currentUsage ?? 0;
      const totalLim = tLim + fLim + bLim;
      const totalUsed = tUsed + fUsed + bUsed;
      if (totalLim > 0) {
        const p = Math.min(100, Math.round((totalUsed / totalLim) * 100));
        updateTrayUsage(`Credit: ${totalUsed.toLocaleString()} / ${totalLim.toLocaleString()} (${p}%)`).catch(() => {});
      }
      return true;
    } catch (e) {
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
  const bonusBreakdown = usage?.usageBreakdownList?.[1];
  const freeTrialInfo = breakdown?.freeTrialInfo;

  // Trial credits
  const trialLimit = freeTrialInfo?.usageLimitWithPrecision ?? freeTrialInfo?.usageLimit ?? 0;
  const trialUsed = freeTrialInfo?.currentUsageWithPrecision ?? freeTrialInfo?.currentUsage ?? 0;

  // Free credits
  const freeLimit = breakdown?.usageLimitWithPrecision ?? breakdown?.usageLimit ?? 0;
  const freeUsed = breakdown?.currentUsageWithPrecision ?? breakdown?.currentUsage ?? 0;

  // Bonus credits
  const bonusLimit = bonusBreakdown?.usageLimitWithPrecision ?? bonusBreakdown?.usageLimit ?? 0;
  const bonusUsed = bonusBreakdown?.currentUsageWithPrecision ?? bonusBreakdown?.currentUsage ?? 0;

  // Total credits (trial + free + bonus)
  const totalLimit = trialLimit + freeLimit + bonusLimit;
  const totalUsed = trialUsed + freeUsed + bonusUsed;
  const pct = totalLimit > 0 ? Math.min(100, Math.round((totalUsed / totalLimit) * 100)) : 0;

  // Overage caps are additional credits, separate from the included quota.
  const overageStatus = usage?.overageConfiguration?.overageStatus;
  const overageCap = breakdown?.overageCapWithPrecision ?? breakdown?.overageCap;
  const overageUsed = breakdown?.currentOveragesWithPrecision ?? breakdown?.currentOverages;
  const hasOverageCap = overageCap !== undefined && Number.isFinite(overageCap) && overageCap >= 0;
  const hasOverageUsed = overageUsed !== undefined && Number.isFinite(overageUsed) && overageUsed >= 0;
  const remainingOverage = overageStatus === 'DISABLED'
    ? 0
    : overageStatus === 'ENABLED' && hasOverageCap && hasOverageUsed
      ? Math.max(0, overageCap - overageUsed)
      : null;

  const plan = usage?.subscriptionInfo?.subscriptionTitle;
  const email = usage?.userInfo?.email;
  const provider = usage?.userInfo?.provider;
  const isTrial = freeTrialInfo?.freeTrialStatus === 'ACTIVE';
  const trialExpiry = freeTrialInfo?.freeTrialExpiry
    ? new Date(freeTrialInfo.freeTrialExpiry * 1000)
    : null;
  const subscriptionExpiryRaw =
    usage?.subscriptionInfo?.expiryDate || usage?.subscriptionInfo?.subscriptionExpiryDate;
  const subscriptionStatus = usage?.subscriptionInfo?.status;

  const resetDate = usage?.nextDateReset
    ? new Date(usage.nextDateReset * 1000).toLocaleDateString()
    : breakdown?.resetDate
      ? new Date(breakdown.resetDate).toLocaleDateString()
      : null;

  const fmtNum = (n: number) => n.toLocaleString();
  const fmtDate = (d: Date | string | null | undefined) => {
    if (!d) return null;
    try {
      const date = d instanceof Date ? d : new Date(d);
      return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    } catch {
      return typeof d === 'string' ? d : null;
    }
  };

  const accountStatus = isTrial ? 'Trial' : subscriptionStatus || 'Active';

  return (
    <div className="flex flex-col">
      {/* Header row */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-sm font-semibold text-stone-600">
            {t('accountInformation')}
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
            {plan && (
              <span className="px-2.5 py-0.5 rounded-full bg-[#111] text-white text-[10px] font-bold uppercase tracking-wider shrink-0">
                {plan}
              </span>
            )}

            {totalLimit > 0 && (
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
                  {fmtNum(totalUsed)} <span className="text-stone-400 font-normal">/ {fmtNum(totalLimit)}</span>
                </span>
                <span className="text-[10px] text-stone-400 shrink-0">{pct}%</span>
              </div>
            )}

            {resetDate && (
              <span className="text-[10px] text-stone-400 shrink-0">{t('usageResets')} {resetDate}</span>
            )}

            {usage.overageConfiguration?.overageStatus && (
              <div className="flex items-center gap-1.5 shrink-0">
                <div className={`h-1.5 w-1.5 rounded-full ${usage.overageConfiguration.overageStatus === 'ENABLED' ? 'bg-amber-400' : 'bg-stone-300'}`} />
                <span className="text-[10px] text-stone-400 font-medium">
                  {t('usageOverage')}: {usage.overageConfiguration.overageStatus === 'ENABLED' ? t('usageOverageOn') : t('usageOverageOff')}
                </span>
              </div>
            )}

            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0 rounded-full hover:bg-stone-100 ml-auto shrink-0"
              onClick={() => setExpanded(v => !v)}
              aria-label={expanded ? 'Collapse' : 'Expand'}
            >
              <ChevronDown
                className={`h-4 w-4 text-stone-400 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
              />
            </Button>
          </>
        ) : null}
      </div>

      {/* Expanded detail panel */}
      <div
        className="grid transition-[grid-template-rows] duration-300 ease-out"
        style={{ gridTemplateRows: expanded && usage ? '1fr' : '0fr' }}
      >
        <div className="overflow-hidden">
          <div className="border-t border-stone-100 pt-4 space-y-4">
            {/* Identity row */}
            <div
              className={`flex flex-wrap items-center gap-x-6 gap-y-2 transition-all duration-300 ease-out ${
                expanded ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-1'
              }`}
              style={{ transitionDelay: expanded ? '40ms' : '0ms' }}
            >
              {email && (
                <div className="flex items-center gap-2 min-w-0">
                  <Mail className="h-3.5 w-3.5 text-stone-400 shrink-0" />
                  <span className="text-sm font-semibold text-[#111] truncate">{email}</span>
                </div>
              )}
              {provider && (
                <span className="text-xs text-stone-400">
                  {t('signedInWith')} <span className="text-stone-600 font-medium">{provider}</span>
                </span>
              )}
              {accountStatus && (
                <span
                  className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                    isTrial
                      ? 'bg-blue-100 text-blue-700'
                      : 'bg-green-100 text-green-700'
                  }`}
                >
                  {accountStatus}
                </span>
              )}
            </div>

            {/* Expiry notices */}
            {((isTrial && trialExpiry) || (!isTrial && subscriptionExpiryRaw)) && (
              <div
                className={`flex flex-wrap gap-2 transition-all duration-300 ease-out ${
                  expanded ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-1'
                }`}
                style={{ transitionDelay: expanded ? '80ms' : '0ms' }}
              >
                {isTrial && trialExpiry && (
                  <div className="flex items-center gap-2 px-3 py-1.5 bg-blue-50 rounded-lg border border-blue-100">
                    <Calendar className="h-3.5 w-3.5 text-blue-600 shrink-0" />
                    <span className="text-xs text-blue-900">
                      <span className="font-semibold">{t('trialPlan')}</span>
                      <span className="text-blue-700"> · {t('expiresOn')} {fmtDate(trialExpiry)}</span>
                    </span>
                  </div>
                )}
                {!isTrial && subscriptionExpiryRaw && (
                  <div className="flex items-center gap-2 px-3 py-1.5 bg-amber-50 rounded-lg border border-amber-100">
                    <Calendar className="h-3.5 w-3.5 text-amber-600 shrink-0" />
                    <span className="text-xs text-amber-900">
                      <span className="font-semibold">{t('subscriptionExpiry')}</span>
                      <span className="text-amber-700"> · {fmtDate(subscriptionExpiryRaw)}</span>
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* Quota breakdown grid */}
            <div className="grid auto-rows-fr grid-cols-2 md:grid-cols-4 gap-3">
              {[
                trialLimit > 0 && (
                  <QuotaTile
                    key="trial"
                    label={`${t('trialPlan')} ${t('quota')}`}
                    used={trialUsed}
                    limit={trialLimit}
                    tone="blue"
                  />
                ),
                freeLimit > 0 && (
                  <QuotaTile
                    key="free"
                    label={`${t('plan')} ${t('quota')}`}
                    used={freeUsed}
                    limit={freeLimit}
                    tone="stone"
                  />
                ),
                bonusLimit > 0 && (
                  <QuotaTile
                    key="bonus"
                    label={t('bonusCredits')}
                    used={bonusUsed}
                    limit={bonusLimit}
                    tone="green"
                  />
                ),
                <QuotaTile
                  key="remaining"
                  label={t('remainingQuota')}
                  value={fmtNum(Math.max(0, totalLimit - totalUsed))}
                  tone="black"
                />,
                <QuotaTile
                  key="overage"
                  label={t('usageOverageRemaining')}
                  value={remainingOverage === null ? '--' : fmtNum(remainingOverage)}
                  description={overageStatus === 'DISABLED'
                    ? t('usageOverageOff')
                    : overageStatus !== 'ENABLED'
                      ? t('usageOverageUnknown')
                      : `${t('usageOverageUsed')} ${hasOverageUsed ? fmtNum(overageUsed) : '--'} / ${t('usageOverageLimit')} ${hasOverageCap ? fmtNum(overageCap) : '--'}`}
                  tone="stone"
                />,
              ]
                .filter(Boolean)
                .map((tile, i) => (
                  <div
                    key={(tile as { key?: string }).key ?? i}
                    className={`min-w-0 transition-all ease-out ${
                      expanded ? 'opacity-100 translate-y-0' : 'opacity-0 -translate-y-1'
                    }`}
                    style={{
                      transitionDuration: '280ms',
                      transitionDelay: expanded ? `${120 + i * 45}ms` : '0ms',
                    }}
                  >
                    {tile}
                  </div>
                ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function QuotaTile({
  label,
  used,
  limit,
  value,
  description,
  tone,
}: {
  label: string;
  used?: number;
  limit?: number;
  value?: string;
  description?: string;
  tone: 'blue' | 'stone' | 'green' | 'black';
}) {
  const toneMap = {
    blue: 'bg-blue-50 text-blue-900 border-blue-100',
    stone: 'bg-stone-50 text-stone-900 border-stone-100',
    green: 'bg-green-50 text-green-900 border-green-100',
    black: 'bg-[#111] text-white border-transparent',
  } as const;
  const subToneMap = {
    blue: 'text-blue-600',
    stone: 'text-stone-500',
    green: 'text-green-600',
    black: 'text-stone-400',
  } as const;

  const fmt = (n?: number) => (n ?? 0).toLocaleString();

  return (
    <div className={`h-full min-w-0 rounded-2xl border px-4 py-3 break-words ${toneMap[tone]}`}>
      <p className={`text-[10px] font-bold uppercase tracking-wider ${subToneMap[tone]}`}>
        {label}
      </p>
      <p className="text-xl font-bold mt-1">{value ?? fmt(limit)}</p>
      {(description !== undefined || value === undefined) && (
        <p className={`text-[11px] mt-0.5 ${subToneMap[tone]}`}>
          {description ?? `${fmt(used)} / ${fmt(limit)}`}
        </p>
      )}
    </div>
  );
}
