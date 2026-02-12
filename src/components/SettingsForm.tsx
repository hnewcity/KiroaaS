import { useState, useEffect } from 'react';
import { useI18n } from '@/hooks/useI18n';
import type { AppConfig, AuthMethod } from '@/lib/config';
import { scanAllCredentials, type CredentialScanResult, /* installUpdate, */ getAppVersion } from '@/lib/tauri';
import { checkVersionUpdate, type UpdateInfo } from '@/lib/versionCheck';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { CheckCircle, Sparkles, X, Shuffle, Save, Shield, Key, Database, FileText, Network } from 'lucide-react';
import { Loader2 } from 'lucide-react';

export type SettingsHintKey = 'auth_cli_db' | 'auth_creds_file' | 'auth_refresh_token' | 'proxy_api_key' | 'generate' | 'check_update' | 'save' | null;

interface SettingsFormProps {
    config: AppConfig;
    onSave: (config: AppConfig) => Promise<void>;
    isRunning?: boolean;
    onRestart?: () => Promise<void>;
    onHintChange?: (hint: SettingsHintKey) => void;
}

export function SettingsForm({ config, onSave, isRunning, onRestart, onHintChange }: SettingsFormProps) {
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
    // const [isInstalling, setIsInstalling] = useState(false); // TODO: 恢复 Tauri 原生更新时启用
    const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null);
    const [updateError, setUpdateError] = useState<string | null>(null);

    // Get app version on mount
    useEffect(() => {
        getAppVersion().then(setAppVersion).catch(console.error);
    }, []);

    // Sync formData when config prop changes (e.g. after useConfig auto-initialization)
    useEffect(() => {
        setFormData(config);
    }, [config]);

    // Auto-scan on mount (for displaying detected path chips)
    useEffect(() => {
        const autoScan = async () => {
            try {
                const result = await scanAllCredentials();
                setScanResult(result);
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
            const data = await checkVersionUpdate(config, 'manual');
            if (data) {
                setUpdateInfo(data);
            } else {
                setUpdateError(t('updateCheckFailed'));
            }
        } catch (err) {
            setUpdateError(t('updateCheckFailed'));
        } finally {
            setIsCheckingUpdate(false);
        }
    };

    const handleInstallUpdate = async () => {
        // TODO: 恢复 Tauri 原生更新逻辑
        // setIsInstalling(true);
        // try {
        //     await installUpdate();
        // } catch (err) {
        //     setUpdateError(t('updateCheckFailed'));
        // } finally {
        //     setIsInstalling(false);
        // }

        // 临时：跳转官网下载
        window.open('https://kiroaas.hnew.city', '_blank');
    };

    const hintEnter = (key: SettingsHintKey) => () => onHintChange?.(key);
    const hintLeave = () => onHintChange?.(null);

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
                        { id: 'cli_db', icon: Database, label: t('authCliDb'), hint: 'auth_cli_db' as SettingsHintKey },
                        { id: 'creds_file', icon: FileText, label: t('authCredsFile'), hint: 'auth_creds_file' as SettingsHintKey },
                        { id: 'refresh_token', icon: Key, label: t('authRefreshToken'), hint: 'auth_refresh_token' as SettingsHintKey },
                    ].map((option) => (
                        <div
                            key={option.id}
                            onClick={() => updateField('auth_method', option.id as AuthMethod)}
                            onMouseEnter={hintEnter(option.hint)}
                            onMouseLeave={hintLeave}
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
                            <div className="relative flex-1" onMouseEnter={hintEnter('proxy_api_key')} onMouseLeave={hintLeave}>
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
                                onMouseEnter={hintEnter('generate')}
                                onMouseLeave={hintLeave}
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

            {/* 2.5 Server Settings Section */}
            <div className="space-y-6 pt-4">
                <div className="flex items-center gap-3 pb-2 border-b border-stone-100">
                    <div className="h-10 w-10 rounded-full bg-stone-100 flex items-center justify-center">
                        <Network className="h-5 w-5 text-stone-600" />
                    </div>
                    <div>
                        <h3 className="text-lg font-bold text-[#111]">{t('serverSettings')}</h3>
                        <p className="text-sm text-stone-500">{t('serverPortDesc')}</p>
                    </div>
                </div>

                <div className="bg-[#F8F8F8] p-6 rounded-[24px] space-y-6">
                    <div className="space-y-3">
                        <Label className="text-sm font-semibold text-[#111] pl-1">{t('serverPort')}</Label>
                        <Input
                            type="number"
                            min={1}
                            max={65535}
                            value={formData.server_port || 8000}
                            onChange={(e) => updateField('server_port', parseInt(e.target.value, 10) || 8000)}
                            className="h-12 rounded-xl bg-white border-stone-200 focus:ring-black focus:border-black font-mono text-sm"
                            placeholder="8000"
                        />
                    </div>
                </div>
            </div>

            {/* 3. About Section */}
            <div className="space-y-6 pt-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Version Card */}
                    <div className="bg-[#111] text-white p-6 rounded-[24px] flex flex-col justify-between relative overflow-hidden">
                        <div className="absolute top-0 right-0 w-32 h-32 bg-stone-800 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2 opacity-60" />
                        <div className="relative z-10">
                            <span className="text-stone-400 font-semibold text-[10px] tracking-wider uppercase">{t('about')}</span>
                            <div className="text-3xl font-bold tracking-tight mt-1">v{appVersion}</div>
                            <p className="text-stone-400 text-xs mt-2 font-medium">KiroaaS</p>
                        </div>
                    </div>

                    {/* Update Check Card */}
                    <div
                        className={`p-6 rounded-[24px] flex flex-col justify-between ${updateInfo?.hasUpdate ? 'bg-[#EBFD93]' : 'bg-[#F8F8F8]'}`}
                        onMouseEnter={hintEnter('check_update')}
                        onMouseLeave={hintLeave}
                    >
                        <div>
                            <span className={`font-semibold text-[10px] tracking-wider uppercase ${updateInfo?.hasUpdate ? 'text-lime-800' : 'text-stone-400'}`}>
                                {t('checkForUpdates')}
                            </span>
                            <div className="mt-1">
                                {updateInfo?.hasUpdate ? (
                                    <p className="text-lg font-bold text-lime-950">
                                        v{updateInfo.latestVersion}
                                    </p>
                                ) : updateInfo && !updateInfo.hasUpdate ? (
                                    <p className="text-sm font-medium text-stone-500 mt-1">{t('noUpdateAvailable')}</p>
                                ) : updateError ? (
                                    <p className="text-sm text-red-500 mt-1">{updateError}</p>
                                ) : (
                                    <p className="text-sm text-stone-400 mt-1">{t('checkForUpdates')}</p>
                                )}
                            </div>
                        </div>
                        <div className="flex gap-2 mt-4">
                            {updateInfo?.hasUpdate && (
                                <Button
                                    type="button"
                                    onClick={handleInstallUpdate}
                                    size="sm"
                                    className="rounded-xl bg-black text-white hover:bg-stone-800 text-xs"
                                >
                                    {t('downloadUpdate')}
                                </Button>
                            )}
                            <Button
                                type="button"
                                variant={updateInfo?.hasUpdate ? 'outline' : 'default'}
                                onClick={handleCheckUpdate}
                                disabled={isCheckingUpdate}
                                size="sm"
                                className={`rounded-xl text-xs ${updateInfo?.hasUpdate ? 'border-lime-800/20 text-lime-950 hover:bg-lime-200/50' : 'bg-[#111] text-white hover:bg-black'}`}
                            >
                                {isCheckingUpdate ? (
                                    <>
                                        <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                                        {t('checkingForUpdates')}
                                    </>
                                ) : (
                                    t('checkForUpdates')
                                )}
                            </Button>
                        </div>
                    </div>
                </div>

                {/* Changelog */}
                {updateInfo?.hasUpdate && updateInfo.changelog && updateInfo.changelog.length > 0 && (
                    <div className="bg-[#F8F8F8] p-6 rounded-[24px]">
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
                    onMouseEnter={hintEnter('save')}
                    onMouseLeave={hintLeave}
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
