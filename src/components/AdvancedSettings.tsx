import type { AppConfig } from '@/lib/config';
import { useI18n } from '@/hooks/useI18n';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Globe, Timer, Server } from 'lucide-react';

interface AdvancedSettingsProps {
    config: AppConfig;
    onChange: (config: AppConfig) => void;
}

export function AdvancedSettings({ config, onChange }: AdvancedSettingsProps) {
    const { t } = useI18n();

    const updateField = <K extends keyof AppConfig>(
        field: K,
        value: AppConfig[K]
    ) => {
        onChange({ ...config, [field]: value });
    };

    return (
        <div className="space-y-4">
            {/* 1. Network / Proxy */}
            <div className="space-y-3">
                <div className="flex items-center gap-2 text-stone-800 font-semibold text-sm">
                    <Globe className="h-4 w-4 text-stone-400" />
                    {t('vpnProxyTunnel')}
                </div>
                <Input
                    value={config.vpn_proxy_url || ''}
                    onChange={(e) => updateField('vpn_proxy_url', e.target.value || undefined)}
                    placeholder="http://127.0.0.1:7890"
                    className="h-10 rounded-lg bg-white border-stone-200 text-sm"
                />
            </div>

            {/* 2. Timeouts */}
            <div className="space-y-3 pt-2">
                <div className="flex items-center gap-2 text-stone-800 font-semibold text-sm">
                    <Timer className="h-4 w-4 text-stone-400" />
                    {t('timeoutsSeconds')}
                </div>
                <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1">
                        <Label className="text-xs text-stone-500">{t('firstToken')}</Label>
                        <Input
                            type="number"
                            value={config.first_token_timeout}
                            onChange={(e) => updateField('first_token_timeout', parseFloat(e.target.value))}
                            className="h-10 rounded-lg bg-white border-stone-200 text-sm"
                        />
                    </div>
                    <div className="space-y-1">
                        <Label className="text-xs text-stone-500">{t('streamRead')}</Label>
                        <Input
                            type="number"
                            value={config.streaming_read_timeout}
                            onChange={(e) => updateField('streaming_read_timeout', parseFloat(e.target.value))}
                            className="h-10 rounded-lg bg-white border-stone-200 text-sm"
                        />
                    </div>
                </div>
            </div>

            {/* 3. Server */}
            <div className="space-y-3 pt-2">
                <div className="flex items-center gap-2 text-stone-800 font-semibold text-sm">
                    <Server className="h-4 w-4 text-stone-400" />
                    {t('serverPort')}
                </div>
                <Input
                    type="number"
                    value={config.server_port}
                    onChange={(e) => updateField('server_port', parseInt(e.target.value))}
                    className="h-10 rounded-lg bg-white border-stone-200 text-sm"
                />
            </div>
        </div>
    );
}
