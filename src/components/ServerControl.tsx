import { useServerStatus } from '@/hooks/useServerStatus';
import { useI18n } from '@/hooks/useI18n';
import { startServer, stopServer } from '@/lib/tauri';
import { useState } from 'react';
import type { AppConfig } from '@/lib/config';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Play, Square, Loader2, AlertCircle } from 'lucide-react';

interface ServerControlProps {
  config: AppConfig;
}

// Check if credentials are configured based on auth method
function hasCredentials(config: AppConfig): boolean {
  switch (config.auth_method) {
    case 'refresh_token':
      return !!config.refresh_token;
    case 'creds_file':
      return !!config.kiro_creds_file;
    case 'cli_db':
      return !!config.kiro_cli_db_file;
    default:
      return false;
  }
}

export function ServerControl({ config }: ServerControlProps) {
  const { status } = useServerStatus();
  const { t } = useI18n();
  const [isStarting, setIsStarting] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canStart = hasCredentials(config);

  const handleStart = async () => {
    setIsStarting(true);
    setError(null);
    try {
      await startServer(config);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('startServerFailed'));
    } finally {
      setIsStarting(false);
    }
  };

  const handleStop = async () => {
    setIsStopping(true);
    setError(null);
    try {
      await stopServer();
    } catch (err) {
      setError(err instanceof Error ? err.message : t('stopServerFailed'));
    } finally {
      setIsStopping(false);
    }
  };

  const isRunning = status.status === 'running';
  const isProcessing = isStarting || isStopping;

  return (
    <Card>
      <CardHeader className="pb-4">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>{t('serverControl')}</CardTitle>
            <CardDescription>{t('serverControlDesc')}</CardDescription>
          </div>
          <StatusBadge status={status.status} />
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="flex items-center gap-4">
          {isRunning ? (
            <Button
              variant="destructive"
              onClick={handleStop}
              disabled={isProcessing}
            >
              {isStopping ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t('stopping')}
                </>
              ) : (
                <>
                  <Square className="h-4 w-4" />
                  {t('stopServer')}
                </>
              )}
            </Button>
          ) : (
            <Button
              onClick={handleStart}
              disabled={isProcessing || !canStart}
            >
              {isStarting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t('starting')}
                </>
              ) : (
                <>
                  <Play className="h-4 w-4" />
                  {t('startServer')}
                </>
              )}
            </Button>
          )}

          {status.port && (
            <div className="text-sm text-muted-foreground">
              {t('runningOnPort')} <span className="font-mono font-semibold">{status.port}</span>
            </div>
          )}
        </div>

        {!canStart && !isRunning && (
          <p className="text-sm text-muted-foreground">
            {t('configureApiKeyFirst')}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n();

  const variants: Record<string, 'default' | 'secondary' | 'destructive' | 'outline' | 'success' | 'warning'> = {
    stopped: 'secondary',
    starting: 'warning',
    running: 'success',
    error: 'destructive',
  };

  const labels: Record<string, string> = {
    stopped: t('statusStopped'),
    starting: t('statusStarting'),
    running: t('statusRunning'),
    error: t('statusError'),
  };

  return (
    <Badge variant={variants[status] || 'secondary'}>
      <span className={`mr-1.5 h-2 w-2 rounded-full ${
        status === 'running' ? 'bg-emerald-500 animate-pulse' :
        status === 'starting' ? 'bg-amber-500 animate-pulse' :
        status === 'error' ? 'bg-red-500' : 'bg-gray-400'
      }`} />
      {labels[status] || status}
    </Badge>
  );
}
