import { useState, useEffect, useRef } from 'react';
import { SettingsForm } from './components/SettingsForm';
import type { SettingsHintKey, SettingsFormHandle, SettingsFormStatus } from './components/SettingsForm';
import { LogViewer } from './components/LogViewer';
import { LanguageSwitcher } from './components/LanguageSwitcher';
import { ApiExamples } from './components/ApiExamples';
import { CCSwitchImport } from './components/CCSwitchImport';
import { ChatView } from './components/ChatView';
import { useConfig } from './hooks/useConfig';
import { useI18n } from './hooks/useI18n';
import { useServerStatus } from './hooks/useServerStatus';
import { useConversations } from './hooks/useConversations';
import { startServer, stopServer, getServerLogs, getAppVersion, getDeviceModel } from './lib/tauri';
import { checkVersionUpdate } from './lib/versionCheck';
import { platform, arch, version } from '@tauri-apps/api/os';

// UI Components
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  LayoutDashboard,
  Settings,
  Loader2,
  Play,
  Square,
  Activity,
  Fingerprint,
  ShieldCheck,
  MessageCircle,
  RotateCw,
  Save,
  AlertTriangle,
  CheckCircle,
  X,
} from 'lucide-react';

type View = 'dashboard' | 'settings' | 'logs' | 'chat';

export default function App() {
  const { config, saveConfig, isLoading: isConfigLoading, error: configError } = useConfig();
  const { status } = useServerStatus();
  const { t } = useI18n();
  const {
    conversations,
    currentConversationId,
    messages,
    updateMessages,
    deleteConversation,
    renameConversation,
    selectConversation,
    startNewChat,
  } = useConversations();

  const [currentView, setCurrentView] = useState<View>('dashboard');
  const [logs, setLogs] = useState<string[]>([]);
  const [pendingAction, setPendingAction] = useState<'start' | 'stop' | null>(null);
  const [tempConfig, setTempConfig] = useState(config);
  const [typewriterText, setTypewriterText] = useState('');
  const [settingsHint, setSettingsHint] = useState<SettingsHintKey>(null);
  const [isRestarting, setIsRestarting] = useState(false);
  const [isMac, setIsMac] = useState(true);
  const [settingsStatus, setSettingsStatus] = useState<SettingsFormStatus | null>(null);
  const settingsFormRef = useRef<SettingsFormHandle>(null);
  const lastLogLineRef = useRef('');
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Derive loading states from server status and pending action
  const isRunning = status.status === 'running';
  const isStarting = pendingAction === 'start' || status.status === 'starting';
  const isStopping = pendingAction === 'stop';
  const isProcessing = isStarting || isStopping;

  // Detect platform
  useEffect(() => {
    platform().then(p => setIsMac(p === 'darwin'));
  }, []);

  // Clear pending action when server status changes to a stable state
  useEffect(() => {
    if (pendingAction === 'start' && status.status === 'running') {
      setPendingAction(null);
    } else if (pendingAction === 'stop' && status.status === 'stopped') {
      setPendingAction(null);
    } else if (status.status === 'error') {
      setPendingAction(null);
    }
  }, [status.status, pendingAction]);

  // Sync temp config
  useEffect(() => {
    setTempConfig(config);
  }, [config]);

  // Auto version check: on app start + every 6 hours
  useEffect(() => {
    if (isConfigLoading) return;

    // Cache device info for beforeunload
    let cachedInfo = { currentVersion: '', platform: '', arch: '', osVersion: '', deviceModel: '' };
    Promise.all([getAppVersion(), platform(), arch(), version(), getDeviceModel()])
      .then(([v, p, a, o, d]) => {
        cachedInfo = { currentVersion: v, platform: p, arch: a, osVersion: o, deviceModel: d };
      })
      .catch(() => {});

    // 1. App start
    checkVersionUpdate(config, 'app_start').catch(() => {});

    // 3. Scheduled every 6 hours
    const SIX_HOURS = 6 * 60 * 60 * 1000;
    const interval = setInterval(() => {
      checkVersionUpdate(config, 'scheduled').catch(() => {});
    }, SIX_HOURS);

    // 2. App close (beforeunload)
    const handleBeforeUnload = () => {
      const body = JSON.stringify({
        ...cachedInfo,
        clientId: config.client_id || '',
        trigger: 'app_close',
      });
      navigator.sendBeacon?.('https://api.kiroaas.hnew.city/version', body);
    };
    window.addEventListener('beforeunload', handleBeforeUnload);

    return () => {
      clearInterval(interval);
      window.removeEventListener('beforeunload', handleBeforeUnload);
    };
  }, [isConfigLoading]);

  // Logs Polling
  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    if (currentView === 'logs' || currentView === 'dashboard') {
      const fetchLogs = async () => {
        try {
          const serverLogs = await getServerLogs();
          setLogs(serverLogs);
        } catch (err) {
          console.error('Failed to fetch logs:', err);
        }
      };
      fetchLogs(); // Initial
      interval = setInterval(fetchLogs, 2000);
    }
    return () => clearInterval(interval);
  }, [currentView]);

  // Typewriter effect for latest log
  useEffect(() => {
    if (!isRunning) {
      lastLogLineRef.current = '';
      setTypewriterText('');
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }
    const latestLog = logs.length > 0
      ? logs[logs.length - 1].replace(/\x1B\[[0-9;]*[a-zA-Z]/g, '')
      : t('servingOnPort').replace('{port}', String(config.server_port));

    if (latestLog !== lastLogLineRef.current) {
      lastLogLineRef.current = latestLog;
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
      let index = 0;
      setTypewriterText('');
      timerRef.current = setInterval(() => {
        index++;
        if (index <= latestLog.length) {
          setTypewriterText(latestLog.slice(0, index));
        } else {
          if (timerRef.current) {
            clearInterval(timerRef.current);
            timerRef.current = null;
          }
        }
      }, 30);
    }
  }, [logs, isRunning, config.server_port, t]);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
      }
    };
  }, []);

  const handleStart = async () => {
    setPendingAction('start');
    try {
      await startServer(config);
    } catch (err) {
      console.error(err);
      setPendingAction(null);
    }
  };

  const handleStop = async () => {
    setPendingAction('stop');
    try {
      await stopServer();
    } catch (err) {
      console.error(err);
      setPendingAction(null);
    }
  };

  const handleSaveConfig = async (newConfig: typeof config) => {
    await saveConfig(newConfig);
    setTempConfig(newConfig);
  };

  const handleRestartServer = async () => {
    setIsRestarting(true);
    setPendingAction('stop');
    try {
      await stopServer();
      // Wait a bit for the server to fully stop
      await new Promise(resolve => setTimeout(resolve, 500));
      setPendingAction('start');
      await startServer(config);
    } catch (err) {
      console.error(err);
      setPendingAction(null);
      throw err;
    } finally {
      setIsRestarting(false);
    }
  };

  if (isConfigLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#F2F2F2]">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-12 w-12 animate-spin text-black" />
          <p className="text-stone-500 font-medium tracking-tight ">{t('loadingConfig')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen w-full bg-[#111111] font-sans overflow-hidden">
      {/* Title Bar Drag Region */}
      <div data-tauri-drag-region className={`${isMac ? 'h-8' : 'h-2'} w-full flex-shrink-0`} />

      <div className="flex flex-1 p-2 pt-0 gap-2 overflow-hidden">

        {/* Sidebar Navigation - Left Rail */}
        <aside className="w-[80px] lg:w-[240px] flex-shrink-0 bg-[#111111] text-white flex flex-col justify-between rounded-l-[32px] pt-4 pb-6 transition-all duration-300">
          <div className="flex flex-col items-center lg:items-start lg:px-6">
            {/* Logo Area */}
            <div className="mb-10 flex items-center gap-3">
              <div className="h-10 w-10 rounded-full bg-[#2A2A2A] flex items-center justify-center border-2 border-white overflow-hidden">
                <img src="/icon.png" alt="KiroaaS" className="h-10 w-10 object-cover" />
              </div>
              <div className="hidden lg:block">
                <span className="text-white font-bold text-xl tracking-tight block leading-none">KiroaaS</span>
                <span className="text-stone-500 text-xs font-medium tracking-wide">Kiro as a Service
                </span>
              </div>
            </div>

            {/* Nav Items */}
            <nav className="space-y-3 w-full">
              <NavButton
                active={currentView === 'dashboard'}
                onClick={() => setCurrentView('dashboard')}
                icon={LayoutDashboard}
                label={t('dashboard') || "Dashboard"}
              />
              <NavButton
                active={currentView === 'chat'}
                onClick={() => setCurrentView('chat')}
                icon={MessageCircle}
                label={t('tabChat')}
                badge={isRunning}
              />
              <NavButton
                active={currentView === 'logs'}
                onClick={() => setCurrentView('logs')}
                icon={Activity}
                label={t('tabLogs')}
                badge={isRunning}
              />
              <NavButton
                active={currentView === 'settings'}
                onClick={() => setCurrentView('settings')}
                icon={Settings}
                label={t('tabSettings')}
              />
            </nav>
          </div>

          {/* Footer Area */}
          <div className="flex flex-col items-center lg:items-start lg:px-6 space-y-4">
            {/* Language Switcher - Compact */}
            <div className="flex justify-center lg:justify-start lg:w-full">
              <LanguageSwitcher variant="sidebar" />
            </div>
          </div>
        </aside>

        {/* Main Content Area - Card Style */}
        <main className="flex-1 bg-[#F3F3F2] rounded-[32px] overflow-hidden flex flex-col relative shadow-2xl">

          {/* Decorative background element */}
          <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-gradient-to-bl from-stone-200/50 to-transparent rounded-full -translate-y-1/2 translate-x-1/2 pointer-events-none" />

          {/* Top Header - hidden in chat view for immersive experience */}
          {currentView !== 'chat' && (
            <header data-tauri-drag-region className="px-8 lg:px-10 py-5 flex items-start justify-between flex-shrink-0 z-10 min-h-[70px]">
              <div className="pt-2">
                <div className="flex items-center gap-3 mb-1">
                  <h1 className="text-2xl font-bold text-[#111] tracking-tight">
                    {currentView === 'dashboard' && t('dashboard')}
                    {currentView === 'settings' && t('tabSettings')}
                    {currentView === 'logs' && t('systemLogs')}
                  </h1>
                  {configError && (
                    <Badge variant="destructive" className="rounded-full px-3 py-1">{t('configurationError')}</Badge>
                  )}
                </div>
                <p className="text-stone-500 font-medium">
                  {currentView === 'dashboard' && t('dashboardDesc')}
                  {currentView === 'settings' && t('settingsDesc')}
                  {currentView === 'logs' && t('logsDesc')}
                </p>
              </div>

              <div className="flex items-center gap-4">
                {/* Main Action Button */}
                {currentView === 'dashboard' && (
                  <>
                  <Button
                    className={`h-12 rounded-full px-6 font-semibold shadow-lg transition-all duration-300 ${isRunning
                      ? 'bg-black text-white hover:bg-stone-800'
                      : 'bg-black text-white hover:bg-stone-800'
                      }`}
                    onClick={isRunning ? handleStop : handleStart}
                    disabled={isProcessing || (!isRunning && !config.proxy_api_key)}
                  >
                    {isStarting || isStopping ? (
                      <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                    ) : isRunning ? (
                      <Square className="mr-2 h-5 w-5 fill-current" />
                    ) : (
                      <Play className="mr-2 h-5 w-5 fill-current" />
                    )}
                    {isRunning ? (isStopping ? t('stopping') : t('stopServer')) : (isStarting ? t('starting') : t('startServer'))}
                  </Button>
                  {isRunning && (
                    <Button
                      variant="outline"
                      className="h-12 rounded-full px-6 font-semibold border-stone-300 hover:bg-stone-100 transition-all duration-300"
                      onClick={handleRestartServer}
                      disabled={isProcessing}
                    >
                      {isRestarting ? (
                        <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                      ) : (
                        <RotateCw className="mr-2 h-5 w-5" />
                      )}
                      {isRestarting ? t('starting') : t('restartServer')}
                    </Button>
                  )}
                  </>
                )}

                {/* Settings Save Button in Header */}
                {currentView === 'settings' && (
                  <div className="flex items-center gap-3">
                    {settingsStatus?.hasChanges && isRunning && !settingsStatus.showRestartPrompt && (
                      <div className="flex items-center text-amber-700 bg-amber-50 px-3 py-1.5 rounded-full text-xs font-medium animate-in fade-in">
                        <AlertTriangle className="w-3.5 h-3.5 mr-1.5" />
                        {t('configChangeHint')}
                      </div>
                    )}
                    {settingsStatus?.error && (
                      <div className="flex items-center text-red-500 bg-red-50 px-3 py-1.5 rounded-full text-xs font-medium animate-in fade-in">
                        <X className="w-3.5 h-3.5 mr-1.5" />
                        {settingsStatus.error}
                      </div>
                    )}
                    {settingsStatus?.success && !settingsStatus.showRestartPrompt && (
                      <div className="flex items-center text-lime-700 bg-lime-100 px-3 py-1.5 rounded-full text-xs font-medium animate-in fade-in">
                        <CheckCircle className="w-3.5 h-3.5 mr-1.5" />
                        {t('savedSuccessfully')}
                      </div>
                    )}
                    {settingsStatus?.showRestartPrompt && (
                      <div className="flex items-center gap-2 animate-in fade-in">
                        <span className="text-xs text-stone-600">{t('configSavedRestartPrompt')}</span>
                        <Button
                          type="button"
                          variant="outline"
                          onClick={() => settingsFormRef.current?.skipRestart()}
                          disabled={settingsStatus.isRestarting}
                          className="h-9 px-3 rounded-full text-xs"
                        >
                          {t('skipRestart')}
                        </Button>
                        <Button
                          type="button"
                          onClick={() => settingsFormRef.current?.restart()}
                          disabled={settingsStatus.isRestarting}
                          className="h-9 px-4 rounded-full bg-lime-500 hover:bg-lime-600 text-black text-xs font-semibold"
                        >
                          {settingsStatus.isRestarting ? (
                            <><Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />{t('starting')}</>
                          ) : t('restartServer')}
                        </Button>
                      </div>
                    )}
                    <Button
                      onClick={() => settingsFormRef.current?.submit()}
                      disabled={settingsStatus?.isSaving}
                      className="h-12 rounded-full px-6 font-semibold bg-[#111] hover:bg-black text-white shadow-lg transition-all duration-300"
                    >
                      {settingsStatus?.isSaving ? (
                        <><Loader2 className="mr-2 h-5 w-5 animate-spin" />{t('savingChanges')}</>
                      ) : (
                        <><Save className="mr-2 h-5 w-5" />{t('saveConfiguration')}</>
                      )}
                    </Button>
                  </div>
                )}
              </div>
            </header>
          )}

          {/* Scrollable Content */}
          <div className={`flex-1 overflow-y-auto overflow-x-hidden z-0 scroll-smooth ${currentView === 'chat' ? 'p-0' : 'p-8 lg:px-10 pt-0'}`}>

            {currentView === 'dashboard' && (
              <div className="flex flex-col h-full gap-4 pb-4">

                {/* Top Cards Row */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">

                  {/* Status Card - Primary */}
                  <Card className={`md:col-span-2 border-0 shadow-sm rounded-[32px] overflow-hidden relative transition-all duration-500 ${isRunning ? 'bg-[#EBFD93]' : 'bg-white'}`}>
                    <CardContent className="p-6 flex flex-col justify-between h-[180px] relative z-10">
                      <div className="flex justify-between items-start">
                        <div className="flex items-center gap-3">
                          <div className={`p-2 rounded-xl ${isRunning ? 'bg-black/5' : 'bg-stone-100'}`}>
                            <Activity className={`h-4 w-4 ${isRunning ? 'text-lime-900' : 'text-stone-400'}`} />
                          </div>
                          <span className={`font-semibold tracking-wide text-xs ${isRunning ? 'text-lime-900' : 'text-stone-500'}`}>{t('gatewayStatus')}</span>
                        </div>
                        <div className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider ${isRunning ? 'bg-black text-[#D9F99D]' : 'bg-stone-100 text-stone-500'}`}>
                          {isRunning ? t('active') : t('offline')}
                        </div>
                      </div>

                      <div>
                        <h2 className={`text-4xl lg:text-5xl font-bold tracking-tighter ${isRunning ? 'text-lime-950' : 'text-stone-300'}`}>
                          {isRunning ? t('online') : t('stopped')}
                        </h2>
                        <p className={`mt-1 font-medium text-xs h-[18px] ${isRunning ? 'text-lime-800' : 'text-stone-400'} font-mono flex items-center`}>
                          {isRunning ? (
                            <>
                              <span>
                                {typewriterText.length > 50 ? typewriterText.slice(-50) : typewriterText}
                              </span>
                              <span className="inline-block w-[2px] h-[14px] bg-lime-800 ml-0.5 animate-pulse" />
                            </>
                          ) : t('readyToInitialize')}
                        </p>
                      </div>
                    </CardContent>
                    {isRunning && (
                      <div className="absolute right-0 bottom-0 opacity-10">
                        <Activity className="h-48 w-48 -mb-8 -mr-8" />
                      </div>
                    )}
                  </Card>

                  {/* Right Column - Port & Auth */}
                  <div className="flex flex-col gap-4">
                    {/* Port Config */}
                    <Card className="flex-1 bg-white border-0 shadow-sm rounded-[32px] px-6 py-4 flex flex-col justify-center">
                      <span className="text-stone-400 font-semibold text-[10px] tracking-wider uppercase mb-1">{t('listeningPort')}</span>
                      <div className="text-2xl font-bold text-[#111]">{config.server_port}</div>
                    </Card>

                    {/* Auth Mode */}
                    <Card className="flex-1 bg-[#111] text-white border-0 shadow-sm rounded-[32px] px-6 py-4 flex flex-col justify-center relative overflow-hidden">
                      <div className="absolute top-0 right-0 w-24 h-24 bg-stone-800 rounded-full blur-2xl -translate-y-1/2 translate-x-1/2 opacity-50" />
                      <div className="flex items-center gap-2 mb-1">
                        <ShieldCheck className="h-3 w-3 text-stone-400" />
                        <span className="text-stone-400 font-semibold text-[10px] tracking-wider uppercase">{t('auth')}</span>
                      </div>
                      <div className="text-sm font-bold tracking-wide">
                        {config.auth_method ? config.auth_method.replace(/_/g, ' ').toUpperCase() : t('auto')}
                      </div>
                    </Card>
                  </div>

                </div>

                {/* API Examples and CC Switch Import */}
                <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {/* API Examples Card */}
                  <div className="bg-white rounded-[32px] p-5 shadow-sm flex flex-col lg:min-h-[280px]">
                    <ApiExamples
                      host={config.server_host}
                      port={config.server_port}
                      apiKey={config.proxy_api_key}
                    />
                  </div>

                  {/* CC Switch Import Card */}
                  <div className="bg-white rounded-[32px] p-5 shadow-sm flex flex-col lg:min-h-[280px]">
                    <CCSwitchImport
                      host={config.server_host}
                      port={config.server_port}
                      apiKey={config.proxy_api_key}
                    />
                  </div>
                </div>

              </div>
            )}

            {currentView === 'settings' && (
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 max-w-7xl pb-10">
                <div className="lg:col-span-8 space-y-6 order-2 lg:order-1">
                  <div className="bg-white rounded-[32px] p-8 shadow-sm">
                    <SettingsForm
                      ref={settingsFormRef}
                      config={tempConfig}
                      onSave={handleSaveConfig}
                      isRunning={isRunning}
                      onRestart={handleRestartServer}
                      onHintChange={setSettingsHint}
                      hideActionBar
                      onStatusChange={setSettingsStatus}
                    />
                  </div>
                </div>
                <div className="lg:col-span-4 space-y-6 order-1 lg:order-2 sticky top-0 lg:static z-10">
                  <div className="bg-[#EBFD93] rounded-[32px] p-8 relative overflow-hidden transition-all duration-300">
                    <Fingerprint className="h-32 w-32 absolute -right-6 -bottom-6 text-lime-400/50 rotate-12" />
                    <h3 className="text-lg font-bold text-lime-950 mb-2 relative z-10">{t('proTip')}</h3>
                    <p className="text-sm text-lime-900 font-medium relative z-10 transition-opacity duration-200">
                      {settingsHint ? t((`tooltip_${settingsHint}`) as any) : t('proTipDesc')}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {currentView === 'logs' && (
              <div className="h-full pb-4">
                <div className="h-full bg-[#252526] rounded-[32px] px-3 pt-3 pb-[4px] shadow-sm border-0">
                  <div className="h-full rounded-[20px] overflow-hidden">
                    <LogViewer logs={logs} onLogsCleared={() => setLogs([])} />
                  </div>
                </div>
              </div>
            )}

            {currentView === 'chat' && (
              <div className="h-full">
                <ChatView
                  host={config.server_host}
                  port={config.server_port}
                  apiKey={config.proxy_api_key}
                  isRunning={isRunning}
                  messages={messages}
                  onMessagesChange={updateMessages}
                  conversations={conversations}
                  currentConversationId={currentConversationId}
                  onSelectConversation={selectConversation}
                  onNewChat={startNewChat}
                  onDeleteConversation={deleteConversation}
                  onRenameConversation={renameConversation}
                />
              </div>
            )}

          </div>
        </main>
      </div>
    </div>
  );
}

// Updated NavButton Component
function NavButton({ active, onClick, icon: Icon, label, badge }: { active: boolean, onClick: () => void, icon: any, label: string, badge?: boolean }) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center lg:gap-4 p-3 rounded-2xl transition-all duration-300 group relative
        ${active
          ? 'bg-[#2A2A2A] text-white shadow-lg shadow-black/20'
          : 'text-stone-400 hover:text-white hover:bg-[#1A1A1A]'
        }
        justify-center lg:justify-start
        `}
    >
      <div className="relative">
        <Icon className={`h-6 w-6 transition-transform duration-300 ${active ? 'scale-110' : 'group-hover:scale-110'}`} />
        {badge && active && (
          <span className="absolute -top-1 -right-1 h-2.5 w-2.5 bg-lime-400 rounded-full border-2 border-[#2A2A2A]" />
        )}
      </div>
      <span className={`hidden lg:block font-medium text-sm tracking-wide ${active ? 'text-white' : ''}`}>
        {label}
      </span>

      {active && <div className="absolute left-0 top-1/2 -translate-y-1/2 h-8 w-1 bg-lime-400 rounded-r-full lg:hidden" />}
    </button>
  );
}
