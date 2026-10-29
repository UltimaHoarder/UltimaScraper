import { useCallback, useState } from 'react';
import { LogViewer, type LogViewerStats } from '../../../../components/logs/LogViewer';
import { WorkspacePageHeader } from '../../../../shared/ui/WorkspacePageHeader';
import './LogsPage.css';

export function LogsPage() {
  const [stats, setStats] = useState<LogViewerStats>({
    total: 0,
    filtered: 0,
    errors: 0,
    warnings: 0,
    info: 0,
    debug: 0,
    isConnected: false,
    isPaused: false,
  });

  const handleStatsChange = useCallback((newStats: LogViewerStats) => {
    setStats(newStats);
  }, []);

  const streamStatus = stats.isPaused
    ? 'PAUSED'
    : stats.isConnected
      ? 'LIVE'
      : 'OFFLINE';
  const streamTone = stats.isPaused
    ? ('warning' as const)
    : stats.isConnected
      ? ('success' as const)
      : ('danger' as const);

  return (
    <div className="logs-page logs-page-v2">
      <WorkspacePageHeader
        eyebrow="01 // Telemetry"
        title="Runtime Logs"
        subtitle="Real-time event stream, subsystem telemetry, and error diagnostics across acquisition workers and server pipelines."
        badges={[
          {
            label: 'Buffered Events',
            value: `${stats.total} / 2000`,
            tone: 'neutral',
          },
          {
            label: 'Errors',
            value: String(stats.errors),
            tone: stats.errors > 0 ? 'danger' : 'neutral',
          },
          {
            label: 'Warnings',
            value: String(stats.warnings),
            tone: stats.warnings > 0 ? 'warning' : 'neutral',
          },
          {
            label: 'Stream Status',
            value: streamStatus,
            tone: streamTone,
          },
        ]}
        icon="≋"
      />

      <div className="logs-viewer-shell">
        <LogViewer onStatsChange={handleStatsChange} />
      </div>
    </div>
  );
}
