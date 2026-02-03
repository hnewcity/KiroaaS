import { useState, useEffect } from 'react';
import { SettingsForm } from './components/SettingsForm';
import { AdvancedSettings } from './components/AdvancedSettings';
import { LogViewer } from './components/LogViewer';
import { useConfig } from './hooks/useConfig';
import { useI18n } from './hooks/useI18n';
import { useServerStatus } from './hooks/useServerStatus';
import { startServer, stopServer, getServerLogs } from './lib/tauri';
import { Language } from './lib/i18n';

// UI Components
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  LayoutDashboard,
  Settings,
  Globe,
  Loader2,
  Play,
  Square,
  Terminal,
  Zap,
  Activity,
  Box,
  Fingerprint,
  ShieldCheck,
  ChevronDown
} from 'lucide-react';
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select';

type View = 'dashboard' | 'settings' | 'logs';

export default function App() {
  const { config, saveConfig, isLoading: isConfigLoading, error: configError } = useConfig();
  const { status } = useServerStatus();
  const { t, lang, setLang } = useI18n();

  const [currentView, setCurrentView] = useState<View>('dashboard');
  const [logs, setLogs] = useState<string[]>([]);
  const [pendingAction, setPendingAction] = useState<'start' | 'stop' | null>(null);
  const [tempConfig, setTempConfig] = useState(config);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // Derive loading states from server status and pending action
  const isRunning = status.status === 'running';
  const isStarting = pendingAction === 'start' || status.status === 'starting';
  const isStopping = pendingAction === 'stop';
  const isProcessing = isStarting || isStopping;

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
    <div className="flex h-screen w-full bg-[#111111] font-sans overflow-hidden p-2 gap-2">

      {/* Sidebar Navigation - Left Rail */}
      <aside className="w-[80px] lg:w-[240px] flex-shrink-0 bg-[#111111] text-white flex flex-col justify-between rounded-l-[32px] py-6 transition-all duration-300">
        <div className="flex flex-col items-center lg:items-start lg:px-6">
          {/* Logo Area */}
          <div className="mb-10 flex items-center gap-3">
            <div className="h-10 w-10 rounded-full bg-[#2A2A2A] flex items-center justify-center border border-[#333]">
              <Zap className="h-5 w-5 text-lime-400 fill-current" />
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
              label={t('appTitle') || "Overview"}
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
          <div className="w-10 h-10 lg:w-full lg:h-auto overflow-hidden">
            <Select value={lang} onValueChange={(v) => setLang(v as Language)}>
              <SelectTrigger className="w-full bg-[#1A1A1A] border-none text-stone-400 hover:text-white rounded-full h-10 px-0 lg:px-3 justify-center lg:justify-between focus:ring-0">
                <Globe className="h-4 w-4 lg:mr-2" />
                <span className="hidden lg:block text-xs">{lang === 'en' ? 'English' : '中文'}</span>
              </SelectTrigger>
              <SelectContent className="dark border-[#333] bg-[#1A1A1A] text-stone-300">
                <SelectItem value="zh">中文</SelectItem>
                <SelectItem value="en">English</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="hidden lg:flex items-center gap-3 pt-4 border-t border-[#222] w-full">
            <div className="h-8 w-8 rounded-full bg-gradient-to-tr from-lime-400 to-emerald-500" />
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-white truncate">{t('administrator')}</p>
              <p className="text-[10px] text-stone-500 truncate">v1.0.0 Stable</p>
            </div>
          </div>
        </div>
      </aside>

      {/* Main Content Area - Card Style */}
      <main className="flex-1 bg-[#F3F3F2] rounded-[32px] overflow-hidden flex flex-col relative shadow-2xl">

        {/* Decorative background element */}
        <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-gradient-to-bl from-stone-200/50 to-transparent rounded-full -translate-y-1/2 translate-x-1/2 pointer-events-none" />

        {/* Top Header */}
        <header className="px-8 lg:px-10 py-5 flex items-start justify-between flex-shrink-0 z-10 min-h-[70px]">
          <div className="pt-2">
            <div className="flex items-center gap-3 mb-1">
              <h1 className="text-2xl font-bold text-[#111] tracking-tight">
                {currentView === 'dashboard' && t('operations')}
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
            )}
          </div>
        </header>

        {/* Scrollable Content */}
        <div className="flex-1 overflow-y-auto overflow-x-hidden p-8 lg:px-10 pt-0 z-0 scroll-smooth">

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
                      <p className={`mt-1 font-medium text-xs ${isRunning ? 'text-lime-800' : 'text-stone-400'}`}>
                        {isRunning ? t('servingOnPort').replace('{port}', String(config.server_port)) : t('readyToInitialize')}
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
                  <Card className="flex-1 bg-white border-0 shadow-sm rounded-[32px] p-4 flex flex-col justify-center">
                    <span className="text-stone-400 font-semibold text-[10px] tracking-wider uppercase mb-1">{t('listeningPort')}</span>
                    <div className="text-2xl font-bold text-[#111]">{config.server_port}</div>
                  </Card>

                  {/* Auth Mode */}
                  <Card className="flex-1 bg-[#111] text-white border-0 shadow-sm rounded-[32px] p-4 flex flex-col justify-center relative overflow-hidden">
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

              {/* Terminal View */}
              <div className="flex-1 min-h-0">
                <div className="bg-white rounded-[32px] p-5 shadow-sm h-full flex flex-col">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <div className="h-7 w-7 rounded-full bg-stone-100 flex items-center justify-center">
                        <Terminal className="h-3.5 w-3.5 text-stone-600" />
                      </div>
                      <h3 className="text-base font-bold text-[#111]">{t('liveActivity')}</h3>
                    </div>
                    <Button variant="outline" size="sm" onClick={() => setCurrentView('logs')} className="h-7 text-xs rounded-full px-3 border-stone-200 hover:bg-stone-50">
                      {t('expand')}
                    </Button>
                  </div>

                  <div className="flex-1 bg-[#F8F8F8] rounded-2xl overflow-hidden min-h-0">
                    <div className="h-full overflow-auto p-3 space-y-1 font-mono text-[11px] text-stone-600">
                      {logs.length === 0 ? (
                        <div className="flex h-full items-center justify-center text-stone-400 italic">
                          {t('waitingForEvents')}
                        </div>
                      ) : (
                        logs.slice(-15).map((log, i) => (
                          <div key={i} className="break-all border-l-2 border-stone-200 pl-2 py-0.5">
                            {log.replace(/\x1B\[[0-9;]*[a-zA-Z]/g, '')}
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </div>
              </div>

            </div>
          )}

          {currentView === 'settings' && (
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 max-w-7xl pb-10">
              <div className="lg:col-span-8 space-y-6">
                <div className="bg-white rounded-[32px] p-8 shadow-sm">
                  <SettingsForm config={tempConfig} onSave={handleSaveConfig} />
                </div>
              </div>
              <div className="lg:col-span-4 space-y-6">
                <div className="bg-white rounded-[32px] p-6 shadow-sm">
                  <button
                    type="button"
                    onClick={() => setAdvancedOpen(!advancedOpen)}
                    className="w-full text-lg font-bold mb-4 flex items-center justify-between gap-2 hover:text-stone-600 transition-colors"
                  >
                    <div className="flex items-center gap-2">
                      <Box className="h-5 w-5 text-stone-400" />
                      {t('advanced')}
                    </div>
                    <ChevronDown className={`h-5 w-5 text-stone-400 transition-transform duration-200 ${advancedOpen ? 'rotate-180' : ''}`} />
                  </button>
                  {advancedOpen && (
                    <div className="bg-[#FAFAFA] rounded-2xl p-1 mb-2">
                      <AdvancedSettings config={tempConfig} onChange={setTempConfig} />
                    </div>
                  )}
                </div>

                <div className="bg-[#EBFD93] rounded-[32px] p-8 relative overflow-hidden">
                  <Fingerprint className="h-32 w-32 absolute -right-6 -bottom-6 text-lime-400/50 rotate-12" />
                  <h3 className="text-lg font-bold text-lime-950 mb-2 relative z-10">{t('proTip')}</h3>
                  <p className="text-sm text-lime-900 font-medium relative z-10">
                    {t('proTipDesc')}
                  </p>
                </div>
              </div>
            </div>
          )}

          {currentView === 'logs' && (
            <div className="h-full pb-8">
              <div className="h-full rounded-[32px] overflow-hidden shadow-sm border-0">
                <LogViewer logs={logs} onLogsCleared={() => setLogs([])} />
              </div>
            </div>
          )}

        </div>
      </main>
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
