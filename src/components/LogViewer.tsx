import { useState, useEffect, useRef } from 'react';
import { useI18n } from '@/hooks/useI18n';
import { clearServerLogs } from '@/lib/tauri';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Download, Trash2, ScrollText, Terminal, PlayCircle } from 'lucide-react';

// Strip ANSI escape codes from log text
function stripAnsi(text: string): string {
    // eslint-disable-next-line no-control-regex
    return text.replace(/\x1B\[[0-9;]*[a-zA-Z]/g, '');
}

interface LogViewerProps {
    logs?: string[];
    onLogsCleared?: () => void;
}

export function LogViewer({ logs = [], onLogsCleared }: LogViewerProps) {
    const { t } = useI18n();
    const [autoScroll, setAutoScroll] = useState(true);
    const viewportRef = useRef<HTMLDivElement>(null);

    // Auto-scroll logic
    useEffect(() => {
        if (autoScroll && viewportRef.current) {
            viewportRef.current.scrollTo({
                top: viewportRef.current.scrollHeight,
                behavior: 'smooth'
            });
        }
    }, [logs, autoScroll]);

    const handleClear = async () => {
        try {
            await clearServerLogs();
            if (onLogsCleared) {
                onLogsCleared();
            }
        } catch (err) {
            console.error('Failed to clear logs:', err);
        }
    };

    const handleExport = () => {
        const logText = logs.map(stripAnsi).join('\n');
        const blob = new Blob([logText], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `kiro-gateway-logs-${Date.now()}.txt`;
        a.click();
        URL.revokeObjectURL(url);
    };

    return (
        <div className="flex flex-col h-full bg-[#1e1e1e] text-stone-300 font-mono text-sm relative group overflow-hidden">
            {/* Header Toolbar */}
            <div className="flex items-center justify-between px-6 py-4 bg-[#252526] border-b border-[#333] z-10">
                <div className="flex items-center gap-3">
                    <div className="h-8 w-8 rounded-lg bg-[#333] flex items-center justify-center">
                        <Terminal className="h-4 w-4 text-stone-400" />
                    </div>
                    <div>
                        <h3 className="text-white font-medium text-sm tracking-wide">{t('systemOutput')}</h3>
                        <p className="text-xs text-stone-500">{t('eventsCaptured').replace('{count}', String(logs.length))}</p>
                    </div>
                </div>

                <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2 bg-[#333] rounded-full px-3 py-1.5 border border-[#444]">
                        <Switch
                            id="auto-scroll"
                            checked={autoScroll}
                            onCheckedChange={setAutoScroll}
                            className="scale-75 data-[state=checked]:bg-lime-500"
                        />
                        <Label htmlFor="auto-scroll" className="text-xs font-medium cursor-pointer text-stone-400 select-none">
                            {autoScroll ? t('live') : t('paused')}
                        </Label>
                    </div>

                    <div className="h-4 w-px bg-[#444]" />

                    <div className="flex gap-2">
                        <Button
                            variant="ghost"
                            size="sm"
                            onClick={handleExport}
                            disabled={logs.length === 0}
                            className="h-8 w-8 p-0 rounded-full hover:bg-[#333] hover:text-white text-stone-400"
                            title={t('export')}
                        >
                            <Download className="h-4 w-4" />
                        </Button>
                        <Button
                            variant="ghost"
                            size="sm"
                            onClick={handleClear}
                            disabled={logs.length === 0}
                            className="h-8 w-8 p-0 rounded-full hover:bg-red-900/20 hover:text-red-400 text-stone-400"
                            title={t('clear')}
                        >
                            <Trash2 className="h-4 w-4" />
                        </Button>
                    </div>
                </div>
            </div>

            {/* Terminal Viewport */}
            <div
                ref={viewportRef}
                className="flex-1 overflow-auto px-6 pt-6 pb-0 space-y-1 custom-scrollbar scroll-smooth relative"
            >
                {logs.length === 0 ? (
                    <div className="h-full flex flex-col items-center justify-center text-stone-600 space-y-4">
                        <div className="bg-[#252526] p-4 rounded-full">
                            <ScrollText className="h-8 w-8 opacity-50" />
                        </div>
                        <p>{t('noLogsAvailable')}</p>
                    </div>
                ) : (
                    logs.map((log, i) => (
                        <div key={i} className="flex gap-3 hover:bg-[#2a2a2a] -mx-2 px-2 py-0.5 rounded transition-colors group/line">
                            <span className="text-stone-600 text-xs select-none w-[80px] flex-shrink-0 text-right font-mono opacity-50">
                                {new Date().toLocaleTimeString().split(' ')[0]}
                            </span>
                            <span className="break-all whitespace-pre-wrap flex-1 text-stone-300 group-hover/line:text-white transition-colors">
                                {stripAnsi(log)}
                            </span>
                        </div>
                    ))
                )}
            </div>

            {/* Scroll to bottom indicator if paused */}
            {!autoScroll && logs.length > 0 && (
                <div className="absolute bottom-6 right-6 z-20 animate-in fade-in slide-in-from-bottom-2">
                    <Button
                        onClick={() => setAutoScroll(true)}
                        className="rounded-full bg-lime-400 text-black hover:bg-lime-500 shadow-xl font-medium"
                    >
                        <PlayCircle className="mr-2 h-4 w-4" />
                        {t('resumeFeed')}
                    </Button>
                </div>
            )}
        </div>
    );
}
