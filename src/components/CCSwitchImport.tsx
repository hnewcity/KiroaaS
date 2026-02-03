import { useState } from 'react';
import { ExternalLink, Import, Check, Zap, Eye, EyeOff } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useI18n } from '@/hooks/useI18n';
import { open } from '@tauri-apps/api/shell';

interface CCSwitchImportProps {
  host: string;
  port: number;
  apiKey: string;
}

export function CCSwitchImport({ host, port, apiKey }: CCSwitchImportProps) {
  const { t } = useI18n();
  const [importing, setImporting] = useState(false);
  const [imported, setImported] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);

  const endpoint = `http://${host}:${port}`;

  const handleImport = async () => {
    if (!apiKey) {
      return;
    }

    setImporting(true);

    // Build the ccswitch:// deep link URL
    const params = new URLSearchParams({
      resource: 'provider',
      app: 'claude',
      name: 'KiroaaS',
      endpoint: endpoint,
      apiKey: apiKey,
    });

    const deepLinkUrl = `ccswitch://v1/import?${params.toString()}`;

    try {
      // Use Tauri shell API to open the deep link
      await open(deepLinkUrl);
      setImported(true);
      setTimeout(() => setImported(false), 3000);
    } catch (err) {
      console.error('Failed to open CC Switch:', err);
    } finally {
      setImporting(false);
    }
  };

  const handleOpenGithub = async () => {
    try {
      await open('https://github.com/farion1231/cc-switch');
    } catch (err) {
      console.error('Failed to open GitHub:', err);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-stone-600">{t('ccSwitchImport')}</span>
      </div>

      {/* CC Switch Tip Card - white with gray border */}
      <button
        onClick={handleOpenGithub}
        className="group bg-white border border-stone-200 rounded-2xl p-3 mb-3 text-left relative overflow-hidden hover:border-stone-300 hover:bg-stone-50 transition-colors"
      >
        <Zap className="h-16 w-16 absolute -right-2 -bottom-2 text-stone-100 rotate-12" />
        <div className="flex items-start gap-2.5 relative z-10">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-xs font-bold text-stone-800">CC Switch</span>
              <svg className="h-3 w-3 text-stone-400 group-hover:text-stone-600 transition-colors" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
              </svg>
            </div>
            <p className="text-[11px] text-stone-500 leading-relaxed font-medium">
              {t('ccSwitchIntro')}
            </p>
          </div>
        </div>
      </button>

      {/* Description */}
      <p className="text-xs text-stone-500 mb-3 leading-relaxed">
        {t('ccSwitchImportDesc')}
      </p>

      {/* Import config preview */}
      <div className="bg-stone-50 rounded-xl p-4 mb-4">
        <div className="space-y-2 text-xs font-mono">
          <div className="flex items-start gap-2">
            <span className="text-stone-400 w-24 flex-shrink-0">Provider:</span>
            <span className="text-stone-700">KiroaaS</span>
          </div>
          <div className="flex items-start gap-2">
            <span className="text-stone-400 w-24 flex-shrink-0">Endpoint:</span>
            <span className="text-stone-700 break-all">{endpoint}</span>
          </div>
          <div className="flex items-start gap-2">
            <span className="text-stone-400 w-24 flex-shrink-0">API Key:</span>
            <span className="text-stone-700 flex items-center gap-1.5">
              {apiKey ? (
                <>
                  <span>{showApiKey ? apiKey : '••••••••'}</span>
                  <button
                    onClick={() => setShowApiKey(!showApiKey)}
                    className="text-stone-400 hover:text-stone-600 transition-colors"
                  >
                    {showApiKey ? <EyeOff className="h-3 w-3" /> : <Eye className="h-3 w-3" />}
                  </button>
                </>
              ) : (
                t('notConfigured')
              )}
            </span>
          </div>
        </div>
      </div>

      {/* Import button */}
      <Button
        onClick={handleImport}
        disabled={!apiKey || importing}
        className="w-full h-11 rounded-xl bg-black hover:bg-stone-800 text-white font-medium gap-2"
      >
        {imported ? (
          <>
            <Check className="h-4 w-4" />
            {t('importSuccess')}
          </>
        ) : importing ? (
          <>
            <Import className="h-4 w-4 animate-pulse" />
            {t('importing')}
          </>
        ) : (
          <>
            <ExternalLink className="h-4 w-4" />
            {t('importToCCSwitch')}
          </>
        )}
      </Button>

      {!apiKey && (
        <p className="text-xs text-amber-600 mt-2 text-center">
          {t('configureApiKeyFirst')}
        </p>
      )}
    </div>
  );
}
