import { useState, useEffect } from 'react';
import { useI18n } from '@/hooks/useI18n';
import { platform, arch } from '@tauri-apps/api/os';
import type { AppConfig, AuthMethod } from '@/lib/config';
import { VERSION_CHECK_API } from '@/lib/config';
import { scanAllCredentials, type CredentialScanResult, installUpdate, getAppVersion } from '@/lib/tauri';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { CheckCircle, Sparkles, X, Shuffle, Save, Shield, Key, Database, FileText, Info } from 'lucide-react';
import { Loader2 } from 'lucide-react';

interface SettingsFormProps {
    config: AppConfig;
    onSave: (config: AppConfig) => Promise<void>;
    isRunning?: boolean;
    onRestart?: () => Promise<void>;
}

export function SettingsForm({ config, onSave, isRunning, onRestart }: SettingsFormProps) {
    const { t } = useI18n();
    const [formData, setFormData] = useState<AppConfig>(config);
    const [isSaving, setIsSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState(false);
    const [showRestartPrompt, setShowRestartPrompt] = useState(false);
    const [isRestarting, setIsRestarting] = useState(false);
    const [scanResult, setScanResult] = useState<CredentialScanResult | null>(null);
    const [showApiKey, setShowApiKey] = useState(false);

    // Update check state
    const [appVersion, setAppVersion] = useState('');
    const [isCheckingUpdate, setIsCheckingUpdate] = useState(false);
    const [isInstalling, setIsInstalling] = useState(false);
    const [updateInfo, setUpdateInfo] = useState<{
        hasUpdate: boolean;
        latestVersion?: string;
        currentVersion?: string;
        downloadUrl?: string;
        changelog?: Array<{ version: string; changes: string[] }>;
    } | null>(null);
    const [updateError, setUpdateError] = useState<string | null>(null);

    // Get app version on mount
    useEffect(() => {
        getAppVersion().then(setAppVersion).catch(console.error);
    }, []);

    // Auto-scan on mount
    useEffect(() => {
        const autoScan = async () => {
            try {
                const result = await scanAllCredentials();
                setScanResult(result);
                if (result.recommended_method && !config.refresh_token && !config.kiro_creds_file && !config.kiro_cli_db_file) {
                    // Auto-apply logic
                    setFormData(prev => ({
                        ...prev,
                        auth_method: result.recommended_method as any,
                        ...(result.recommended_method === 'cli_db'
                            ? { kiro_cli_db_file: result.recommended_path || '' }
                            : { kiro_creds_file: result.recommended_path || '' }
                        )
                    }));
                }
            } catch (err) {
                console.error('Auto-scan failed:', err);
            }
        };
        autoScan();
    }, []);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setIsSaving(true);
        setError(null);
        setSuccess(false);

        try {
            await onSave(formData);
            setSuccess(true);
            // If server is running, show restart prompt
            if (isRunning && onRestart) {
                setShowRestartPrompt(true);
            } else {
                setTimeout(() => setSuccess(false), 3000);
            }
        } catch (err) {
            setError(err instanceof Error ? err.message : t('saveFailed'));
        } finally {
            setIsSaving(false);
        }
    };

    const handleRestart = async () => {
        if (!onRestart) return;
        setIsRestarting(true);
        try {
            await onRestart();
            setShowRestartPrompt(false);
            setSuccess(false);
        } catch (err) {
            setError(err instanceof Error ? err.message : t('startServerFailed'));
        } finally {
            setIsRestarting(false);
        }
    };

    const handleSkipRestart = () => {
        setShowRestartPrompt(false);
        setTimeout(() => setSuccess(false), 3000);
    };

    const updateField = <K extends keyof AppConfig>(
        field: K,
        value: AppConfig[K]
    ) => {
        setFormData((prev) => ({ ...prev, [field]: value }));
    };

    const generateApiKey = () => {
        const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
        const key = Array.from({ length: 32 }, () => chars[Math.floor(Math.random() * chars.length)]).join('');
        updateField('proxy_api_key', `sk-${key}`);
    };

    const handleCheckUpdate = async () => {
        setIsCheckingUpdate(true);
        setUpdateError(null);
        setUpdateInfo(null);

        try {
            // Get or create client ID for tracking
            let clientId = localStorage.getItem('kiroaas_client_id');
            if (!clientId) {
                clientId = crypto.randomUUID();
                localStorage.setItem('kiroaas_client_id', clientId);
            }

            // Get platform and arch dynamically
            const currentPlatform = await platform();
            const currentArch = await arch();

            const response = await fetch(VERSION_CHECK_API, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    currentVersion: appVersion,
                    platform: currentPlatform,
                    arch: currentArch,
                    clientId,
                    trigger: 'manual',
                }),
            });
            const data = await response.json();
            setUpdateInfo(data);
        } catch (err) {
            setUpdateError(t('updateCheckFailed'));
        } finally {
            setIsCheckingUpdate(false);
        }
    };

    const handleInstallUpdate = async () => {
        setIsInstalling(true);
        try {
            await installUpdate();
        } catch (err) {
            setUpdateError(t('updateCheckFailed'));
        } finally {
            setIsInstalling(false);
        }
    };

    return (
        <form onSubmit={handleSubmit} className="space-y-8">

            {/* 1. Authentication Section */}
            <div className="space-y-6">
                <div className="flex items-center gap-3 pb-2 border-b border-stone-100">
                    <div className="h-10 w-10 rounded-full bg-stone-100 flex items-center justify-center">
                        <Shield className="h-5 w-5 text-stone-600" />
                    </div>
                    <div>
                        <h3 className="text-lg font-bold text-[#111]">{t('authenticationMethod')}</h3>
                        <p className="text-sm text-stone-500">{t('howGatewayConnects')}</p>
                    </div>
                </div>

                {/* Grid of Auth Cards */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                    {[
                        { id: 'cli_db', icon: Database, label: t('authCliDb') },
                        { id: 'creds_file', icon: FileText, label: t('authCredsFile') },
                        { id: 'refresh_token', icon: Key, label: t('authRefreshToken') },
                    ].map((option) => (
                        <div
                            key={option.id}
                            onClick={() => updateField('auth_method', option.id as AuthMethod)}
                            className={`cursor-pointer relative p-4 rounded-2xl border-2 transition-all duration-200 flex flex-col gap-3 hover:border-black/10 hover:bg-stone-50 ${formData.auth_method === option.id
                                    ? 'border-black bg-stone-50'
                                    : 'border-transparent bg-[#F8F8F8]'
                                }`}
                        >
                            <div className="flex justify-between items-start">
                                <option.icon className={`h-6 w-6 ${formData.auth_method === option.id ? 'text-black' : 'text-stone-400'}`} />
                                {formData.auth_method === option.id && (
                                    <div className="h-4 w-4 rounded-full bg-black flex items-center justify-center">
                                        <span className="h-1.5 w-1.5 bg-white rounded-full" />
                                    </div>
                                )}
                            </div>
                            <span className={`font-semibold text-sm ${formData.auth_method === option.id ? 'text-black' : 'text-stone-500'}`}>
                                {option.label}
                            </span>
                        </div>
                    ))}
                </div>

                {/* Dynamic Fields based on Auth Method */}
                <div className="bg-[#F8F8F8] p-6 rounded-[24px] space-y-6">
                    {formData.auth_method === 'cli_db' && (
                        <div className="space-y-3">
                            <Label className="text-sm font-semibold text-[#111] pl-1">{t('sqliteDatabasePath')}</Label>
                            <div className="flex gap-2">
                                <Input
                                    value={formData.kiro_cli_db_file || ''}
                                    onChange={(e) => updateField('kiro_cli_db_file', e.target.value)}
                                    className="h-12 rounded-xl bg-white border-stone-200 focus:ring-black focus:border-black font-mono text-sm"
                                    placeholder="~/.local/share/kiro-cli/data.sqlite3"
                                />
                            </div>
                            {scanResult?.cli_dbs && scanResult.cli_dbs.length > 0 && (
                                <div className="flex gap-2 flex-wrap mt-2">
                                    {scanResult.cli_dbs.map(path => (
                                        <span
                                            key={path}
                                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white border border-stone-200 text-xs font-medium cursor-pointer hover:border-lime-500 hover:bg-lime-50 transition-colors"
                                            onClick={() => updateField('kiro_cli_db_file', path)}
                                        >
                                            <Sparkles className="h-3 w-3 text-lime-600" />
                                            {path}
                                        </span>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {formData.auth_method === 'creds_file' && (
                        <div className="space-y-3">
                            <Label className="text-sm font-semibold text-[#111] pl-1">{t('credentialsFilePath')}</Label>
                            <Input
                                value={formData.kiro_creds_file || ''}
                                onChange={(e) => updateField('kiro_creds_file', e.target.value)}
                                className="h-12 rounded-xl bg-white border-stone-200 focus:ring-black focus:border-black font-mono text-sm"
                                placeholder="~/.aws/sso/cache/kiro-auth-token.json"
                            />
                            {scanResult?.creds_files && scanResult.creds_files.length > 0 && (
                                <div className="flex gap-2 flex-wrap mt-2">
                                    {scanResult.creds_files.map(path => (
                                        <span
                                            key={path}
                                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-white border border-stone-200 text-xs font-medium cursor-pointer hover:border-lime-500 hover:bg-lime-50 transition-colors"
                                            onClick={() => updateField('kiro_creds_file', path)}
                                        >
                                            <Sparkles className="h-3 w-3 text-lime-600" />
                                            {path}
                                        </span>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {formData.auth_method === 'refresh_token' && (
                        <div className="space-y-3">
                            <Label className="text-sm font-semibold text-[#111] pl-1">{t('refreshToken')}</Label>
                            <div className="relative">
                                <Input
                                    type="password"
                                    value={formData.refresh_token || ''}
                                    onChange={(e) => updateField('refresh_token', e.target.value)}
                                    className="h-12 rounded-xl bg-white border-stone-200 focus:ring-black focus:border-black font-mono text-sm pr-10"
                                    placeholder="ey..."
                                />
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* 2. Proxy Security Section */}
            <div className="space-y-6 pt-4">
                <div className="flex items-center gap-3 pb-2 border-b border-stone-100">
                    <div className="h-10 w-10 rounded-full bg-stone-100 flex items-center justify-center">
                        <Key className="h-5 w-5 text-stone-600" />
                    </div>
                    <div>
                        <h3 className="text-lg font-bold text-[#111]">{t('security')}</h3>
                        <p className="text-sm text-stone-500">{t('protectEndpoint')}</p>
                    </div>
                </div>

                <div className="bg-[#F8F8F8] p-6 rounded-[24px] space-y-6">
                    <div className="space-y-3">
                        <div className="flex justify-between">
                            <Label className="text-sm font-semibold text-[#111] pl-1">{t('proxyApiKey')}</Label>
                            <button type="button" onClick={() => setShowApiKey(!showApiKey)} className="text-xs font-medium text-stone-500 hover:text-black">
                                {showApiKey ? t('hide') : t('show')} {t('realValue')}
                            </button>
                        </div>
                        <div className="flex gap-3">
                            <div className="relative flex-1">
                                <Input
                                    type={showApiKey ? "text" : "password"}
                                    value={formData.proxy_api_key || ''}
                                    onChange={(e) => updateField('proxy_api_key', e.target.value)}
                                    className="h-12 rounded-xl bg-white border-stone-200 focus:ring-black focus:border-black font-mono text-sm pr-10"
                                    placeholder="sk-..."
                                />
                            </div>
                            <Button
                                type="button"
                                variant="outline"
                                onClick={generateApiKey}
                                className="h-12 px-6 rounded-xl border-stone-200 hover:bg-white hover:border-black hover:text-black transition-all"
                            >
                                <Shuffle className="mr-2 h-4 w-4" />
                                {t('generate')}
                            </Button>
                        </div>
                        <p className="text-xs text-stone-500 pl-1">
                            {t('clientsIncludeKey')}
                        </p>
                    </div>
                </div>
            </div>

            {/* 3. About Section */}
            <div className="space-y-6 pt-4">
                <div className="flex items-center gap-3 pb-2 border-b border-stone-100">
                    <div className="h-10 w-10 rounded-full bg-stone-100 flex items-center justify-center">
                        <Info className="h-5 w-5 text-stone-600" />
                    </div>
                    <div>
                        <h3 className="text-lg font-bold text-[#111]">{t('about')}</h3>
                        <p className="text-sm text-stone-500">v{appVersion}</p>
                    </div>
                </div>

                <div className="bg-[#F8F8F8] p-6 rounded-[24px] space-y-4">
                    <div className="flex items-center justify-between">
                        <div>
                            {updateInfo?.hasUpdate && (
                                <p className="text-sm text-lime-600 font-medium">
                                    {t('updateAvailable').replace('{version}', updateInfo.latestVersion || '')}
                                </p>
                            )}
                            {updateInfo && !updateInfo.hasUpdate && (
                                <p className="text-sm text-stone-500">{t('noUpdateAvailable')}</p>
                            )}
                            {updateError && (
                                <p className="text-sm text-red-500">{updateError}</p>
                            )}
                        </div>
                        <div className="flex gap-3">
                            {updateInfo?.hasUpdate && (
                                <Button
                                    type="button"
                                    onClick={handleInstallUpdate}
                                    disabled={isInstalling}
                                    className="h-10 px-4 rounded-xl bg-lime-500 hover:bg-lime-600 text-black"
                                >
                                    {isInstalling ? (
                                        <>
                                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                            {t('installing')}
                                        </>
                                    ) : (
                                        t('downloadUpdate')
                                    )}
                                </Button>
                            )}
                            <Button
                                type="button"
                                variant="outline"
                                onClick={handleCheckUpdate}
                                disabled={isCheckingUpdate}
                                className="h-10 px-4 rounded-xl"
                            >
                                {isCheckingUpdate ? (
                                    <>
                                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                        {t('checkingForUpdates')}
                                    </>
                                ) : (
                                    t('checkForUpdates')
                                )}
                            </Button>
                        </div>
                    </div>
                    {updateInfo?.hasUpdate && updateInfo.changelog && updateInfo.changelog.length > 0 && (
                        <div className="border-t border-stone-200 pt-4 mt-4">
                            <p className="text-sm font-semibold text-[#111] mb-3">{t('changelog')}</p>
                            <div className="space-y-3 max-h-48 overflow-y-auto">
                                {updateInfo.changelog.map((entry) => (
                                    <div key={entry.version} className="text-sm">
                                        <p className="font-medium text-stone-700">v{entry.version}</p>
                                        <ul className="list-disc list-inside text-stone-500 ml-2">
                                            {entry.changes.map((change, idx) => (
                                                <li key={idx}>{change}</li>
                                            ))}
                                        </ul>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Action Bar */}
            <div className="rounded-xl pt-6 flex justify-end gap-4">
                {error && (
                    <div className="flex items-center text-red-500 bg-red-50 px-4 py-2 rounded-full text-sm font-medium animate-in fade-in">
                        <X className="w-4 h-4 mr-2" />
                        {error}
                    </div>
                )}
                {success && !showRestartPrompt && (
                    <div className="flex items-center text-lime-700 bg-lime-100 px-4 py-2 rounded-full text-sm font-medium animate-in fade-in">
                        <CheckCircle className="w-4 h-4 mr-2" />
                        {t('savedSuccessfully')}
                    </div>
                )}
                {showRestartPrompt && (
                    <div className="flex items-center gap-3 animate-in fade-in">
                        <span className="text-sm text-stone-600">{t('configSavedRestartPrompt')}</span>
                        <Button
                            type="button"
                            variant="outline"
                            onClick={handleSkipRestart}
                            disabled={isRestarting}
                            className="h-10 px-4 rounded-full"
                        >
                            {t('skipRestart')}
                        </Button>
                        <Button
                            type="button"
                            onClick={handleRestart}
                            disabled={isRestarting}
                            className="h-10 px-6 rounded-full bg-lime-500 hover:bg-lime-600 text-black font-semibold"
                        >
                            {isRestarting ? (
                                <>
                                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                    {t('starting')}
                                </>
                            ) : (
                                t('restartServer')
                            )}
                        </Button>
                    </div>
                )}

                <Button
                    type="submit"
                    disabled={isSaving}
                    className="h-14 px-8 rounded-full bg-[#111] hover:bg-black text-white text-base font-semibold shadow-xl shadow-black/10 transition-transform active:scale-95"
                >
                    {isSaving ? (
                        <>
                            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                            {t('savingChanges')}
                        </>
                    ) : (
                        <>
                            <Save className="mr-2 h-5 w-5" />
                            {t('saveConfiguration')}
                        </>
                    )}
                </Button>
            </div>

        </form>
    );
}
