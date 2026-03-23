import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { AlertCircle, Calendar } from 'lucide-react';
import { useI18n } from '@/hooks/useI18n';

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
  trialQuota?: number;
  trialUsage?: number;
  freeQuota?: number;
  freeUsage?: number;
  bonusQuota?: number;
  bonusUsage?: number;
  bonusRemaining?: number;
  accountStatus?: string;
  resetDate?: string;
  overageEnabled?: boolean;
}

interface AccountCardProps {
  data: AccountData | null;
  loading: boolean;
  error: string | null;
}

export function AccountCard({ data, loading, error }: AccountCardProps) {
  const { t } = useI18n();

  if (loading && !data) {
    return (
      <div className="space-y-4">
        <div className="animate-pulse space-y-3">
          <div className="h-6 w-48 bg-stone-200 rounded" />
          <div className="h-4 w-64 bg-stone-200 rounded" />
          <div className="grid grid-cols-2 gap-4 mt-6">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="h-20 bg-stone-200 rounded-lg" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-3 p-4 bg-red-50 rounded-lg border border-red-200">
        <AlertCircle className="h-5 w-5 text-red-500 flex-shrink-0" />
        <div>
          <p className="text-sm font-medium text-red-900">{t('accountLoadFailed')}</p>
          <p className="text-xs text-red-700 mt-1">{error}</p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="text-center py-8">
        <p className="text-stone-500 font-medium">{t('noAccountData')}</p>
      </div>
    );
  }

  const fmtNum = (n: number | undefined) => n ? n.toLocaleString() : '—';
  const fmtDate = (dateStr: string | undefined) => {
    if (!dateStr) return '—';
    try {
      const date = new Date(dateStr);
      return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    } catch {
      return dateStr;
    }
  };

  const getStatusColor = (status: string | undefined) => {
    if (!status) return 'bg-stone-100 text-stone-700';
    if (status === 'Trial') return 'bg-blue-100 text-blue-700';
    if (status === 'Active') return 'bg-green-100 text-green-700';
    return 'bg-stone-100 text-stone-700';
  };

  return (
    <div className="space-y-6">
      {/* Account Header with Provider */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-2xl font-bold text-[#111]">
            {data.email || t('account')}
          </h2>
          {data.accountStatus && (
            <Badge className={`${getStatusColor(data.accountStatus)} rounded-full px-3 py-1`}>
              {data.accountStatus}
            </Badge>
          )}
        </div>
        {data.provider && (
          <p className="text-xs text-stone-400">{t('signedInWith')} {data.provider}</p>
        )}
      </div>

      {/* Plan and Trial Info */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-stone-600 uppercase tracking-wide">
            {t('plan')}
          </span>
          <Badge className="bg-[#111] text-white rounded-full px-3 py-1">
            {data.planType || data.subscriptionTitle || 'Free'}
          </Badge>
        </div>

        {/* Trial Info */}
        {data.isTrial && data.trialExpiryDate && (
          <div className="flex items-center gap-2 p-3 bg-blue-50 rounded-lg border border-blue-200">
            <Calendar className="h-4 w-4 text-blue-600 flex-shrink-0" />
            <div className="text-sm">
              <p className="font-medium text-blue-900">{t('trialPlan')}</p>
              <p className="text-xs text-blue-700">{t('expiresOn')}: {fmtDate(data.trialExpiryDate)}</p>
            </div>
          </div>
        )}

        {/* Subscription Expiry */}
        {!data.isTrial && data.subscriptionExpiryDate && (
          <div className="flex items-center gap-2 p-3 bg-amber-50 rounded-lg border border-amber-200">
            <Calendar className="h-4 w-4 text-amber-600 flex-shrink-0" />
            <div className="text-sm">
              <p className="font-medium text-amber-900">{t('subscriptionExpiry')}</p>
              <p className="text-xs text-amber-700">{fmtDate(data.subscriptionExpiryDate)}</p>
            </div>
          </div>
        )}
      </div>

      {/* Usage Progress */}
      {data.usagePercentage !== undefined && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-stone-600 uppercase tracking-wide">
              {t('usageProgress')}
            </span>
            <span className="text-sm font-medium text-stone-700">{data.usagePercentage}%</span>
          </div>
          <div className="w-full bg-stone-200 rounded-full h-2">
            <div
              className={`h-2 rounded-full transition-all ${
                data.usagePercentage! > 90 ? 'bg-red-500' :
                data.usagePercentage! > 70 ? 'bg-amber-500' :
                'bg-green-500'
              }`}
              style={{ width: `${Math.min(data.usagePercentage!, 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Quota Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Total Quota (Trial + Free) */}
        <Card className="bg-white border-0 shadow-sm rounded-2xl">
          <CardContent className="p-4">
            <p className="text-xs font-semibold text-stone-500 uppercase tracking-wide mb-2">
              {t('totalQuota')}
            </p>
            <p className="text-2xl font-bold text-[#111]">
              {fmtNum(data.totalQuota)}
            </p>
            {data.trialQuota !== undefined && data.freeQuota !== undefined && (
              <p className="text-xs text-stone-400 mt-1">
                {fmtNum(data.trialQuota)} + {fmtNum(data.freeQuota)}
              </p>
            )}
          </CardContent>
        </Card>

        {/* Current Usage */}
        <Card className="bg-white border-0 shadow-sm rounded-2xl">
          <CardContent className="p-4">
            <p className="text-xs font-semibold text-stone-500 uppercase tracking-wide mb-2">
              {t('currentUsage')}
            </p>
            <p className="text-2xl font-bold text-[#111]">
              {fmtNum(data.currentUsage)}
            </p>
          </CardContent>
        </Card>

        {/* Remaining Quota */}
        <Card className="bg-white border-0 shadow-sm rounded-2xl">
          <CardContent className="p-4">
            <p className="text-xs font-semibold text-stone-500 uppercase tracking-wide mb-2">
              {t('remainingQuota')}
            </p>
            <p className="text-2xl font-bold text-[#111]">
              {fmtNum(data.remainingQuota)}
            </p>
          </CardContent>
        </Card>

        {/* Trial Quota */}
        {data.trialQuota !== undefined && (
          <Card className="bg-blue-50 border border-blue-200 shadow-sm rounded-2xl">
            <CardContent className="p-4">
              <p className="text-xs font-semibold text-blue-600 uppercase tracking-wide mb-2">
                {t('trialPlan')} {t('quota')}
              </p>
              <p className="text-2xl font-bold text-blue-900">
                {fmtNum(data.trialQuota)}
              </p>
              <p className="text-xs text-blue-700 mt-1">
                {fmtNum(data.trialUsage)} / {fmtNum(data.trialQuota)}
              </p>
            </CardContent>
          </Card>
        )}

        {/* Free Quota */}
        {data.freeQuota !== undefined && (
          <Card className="bg-amber-50 border border-amber-200 shadow-sm rounded-2xl">
            <CardContent className="p-4">
              <p className="text-xs font-semibold text-amber-600 uppercase tracking-wide mb-2">
                {t('plan')} {t('quota')}
              </p>
              <p className="text-2xl font-bold text-amber-900">
                {fmtNum(data.freeQuota)}
              </p>
              <p className="text-xs text-amber-700 mt-1">
                {fmtNum(data.freeUsage)} / {fmtNum(data.freeQuota)}
              </p>
            </CardContent>
          </Card>
        )}

        {/* Bonus Credits */}
        {data.bonusQuota !== undefined && (
          <Card className="bg-green-50 border border-green-200 shadow-sm rounded-2xl">
            <CardContent className="p-4">
              <p className="text-xs font-semibold text-green-600 uppercase tracking-wide mb-2">
                {t('bonusCredits')}
              </p>
              <p className="text-2xl font-bold text-green-900">
                {fmtNum(data.bonusRemaining)}
              </p>
              <p className="text-xs text-green-700 mt-1">
                {fmtNum(data.bonusUsage)} / {fmtNum(data.bonusQuota)}
              </p>
            </CardContent>
          </Card>
        )}

        {/* Reset Date */}
        {data.resetDate && (
          <Card className="bg-white border-0 shadow-sm rounded-2xl">
            <CardContent className="p-4">
              <p className="text-xs font-semibold text-stone-500 uppercase tracking-wide mb-2">
                {t('resetDate')}
              </p>
              <p className="text-sm font-bold text-[#111]">
                {fmtDate(data.resetDate)}
              </p>
            </CardContent>
          </Card>
        )}

        {/* Overage Status */}
        {data.overageEnabled !== undefined && (
          <Card className="bg-white border-0 shadow-sm rounded-2xl">
            <CardContent className="p-4">
              <p className="text-xs font-semibold text-stone-500 uppercase tracking-wide mb-2">
                {t('overageStatus')}
              </p>
              <Badge className={data.overageEnabled ? 'bg-green-100 text-green-700' : 'bg-stone-100 text-stone-700'}>
                {data.overageEnabled ? t('enabled') : t('disabled')}
              </Badge>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
