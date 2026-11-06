import { Fragment, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ToastPortal, type ToastPortalState } from '../../shared/ui/ToastPortal';

import { getSettings, updateSettings } from '../../api/settings';
import { getActiveConnectionId, navigateTo } from '../../api/http';
import { connectionHome, listClusters, type BackendClusters } from '../../api/webui';
import { addConnectionHref, nodeLink } from '../connections/lib/clusterView';
import {
  addDirectory,
  analyzeDatabase,
  controlRuntimePower,
  getAllBackends,
  getBackendStatus,
  getDatabaseOverview,
  cancelDatabaseOperation,
  getDrives,
  reindexDatabase,
  removeDirectory,
  updateDirectoryConfig,
  vacuumDatabase,
} from '../../api/system';
import type {
  AddDirectoryResponse,
  DatabaseOverview,
  DatabaseVacuumRequest,
  DirectoryConfigRequest,
  DirectoryConfigResponse,
  DriveInfo,
  RemoveDirectoryResponse,
  RuntimePowerAction,
  RuntimeServiceTarget,
} from '../../api/types/system';
import type { SettingsResponse, SettingsUpdate } from '../../api/types/settings';
import {
  OperationsNotice,
  OperationsState,
} from '../../shared/ui/operations/OperationsChrome';
import { formatBytes } from '../../shared/lib/format';
import { ConfirmDialog } from '../../shared/ui/ConfirmDialog';
import { WorkspacePageHeader } from '../../shared/ui/WorkspacePageHeader';
import { RestartRuntimeModal } from './RestartRuntimeModal';
import {
  DatabaseInspectionModal,
  type PendingDatabaseOp,
  type DatabaseStatusNotice,
} from './components/DatabaseInspectionModal';
import { DatabaseVacuumModal } from './components/DatabaseVacuumModal';
import { DriveConfigModal } from './components/DriveConfigModal';
import { RemoteConfigModal } from './components/RemoteConfigModal';
import { mergeConfiguredDrivesWithInventory } from './lib/systemUtils';
import {
  buildRegisterBackends,
  type RegisterBackend,
  type RegisterHealth,
  type RegisterMount,
  type RegisterWorker,
  type RegisterWorkerState,
} from './systemFleetRegisterData';
import './SystemFleetRegisterPage.css';
import { followInApp, sectionOnBackend } from '../connections/lib/navigation';
import { formatRowCount, ROW_ESTIMATE_TITLE } from './lib/rowCounts';
import { ClusterSection } from './components/ClusterSection';
import '../connections/connections.css';
import { OperationPanel } from '../connections/DeploymentsSection';
import { ACTION_LABELS, type Action as DeploymentAction } from '../connections/lib/deploymentActions';
import {
  getConnectionTicket,
  listDeployments,
  listWebUIClients,
  registerExistingInstall,
  revokeWebUIClient,
  scanHostKey,
  type Deployment,
  type HostKey,
} from '../../api/webui';
import { copyText } from '../../utils/clipboard';

type RegisterTab = 'cluster' | 'backends' | 'workers' | 'clients' | 'mounts' | 'database';
type RegisterFilter = 'all' | 'attention' | 'healthy' | 'warning' | 'offline' | 'running' | 'idle';
const POWER_COPY: Record<RuntimePowerAction, { button: string; title: string; description: string; pending: string; done: string }> = {
  restart: {
    button: 'Restart runtime',
    title: 'Restart UltimaScraper?',
    description: 'Stop the API, database writer, worker pool, plugins and this web UI, then start them again. Running tasks are interrupted and resume from their last checkpoint.',
    pending: 'Restarting UltimaScraper',
    done: 'Every service is stopping and will start again. This page reconnects when the web UI is back.',
  },
  shutdown: {
    button: 'Shut down',
    title: 'Shut down UltimaScraper?',
    description: 'Stop the API, database writer, worker pool, plugins and this web UI. Nothing restarts it from here; start it again on the machine that runs it.',
    pending: 'UltimaScraper is shutting down',
    done: 'Every service, including this web UI, is stopping. Start it again on the machine that runs it.',
  },
};

type RegisterInspectTarget =
  | { kind: 'backend'; backendId: string }
  | { kind: 'worker'; backendId: string; workerId: string }
  | null;

function formatAge(age: number | null): string {
  if (age === null) return 'Unknown';
  if (age < 5) return 'Just now';
  if (age < 60) return `${age}s ago`;
  return `${Math.floor(age / 60)}m ago`;
}

function stateLabel(state: RegisterHealth | RegisterWorkerState): string {
  return state === 'healthy' ? 'Healthy'
    : state === 'running' ? 'Running'
      : state === 'idle' ? 'Idle'
        : state === 'warning' ? 'Needs attention'
          : 'Offline';
}

function StateBadge({ state, label }: { state: RegisterHealth | RegisterWorkerState; label?: string }) {
  return <span className={`fleet-register-state fleet-register-state--${state}`}><i aria-hidden="true" />{label ?? stateLabel(state)}</span>;
}

function LoadMeter({ value, label }: { value: number; label: string }) {
  const boundedValue = Math.min(100, Math.max(0, value));
  return <div className="fleet-register-meter" role="meter" aria-label={label} aria-valuenow={Number(boundedValue.toFixed(1))} aria-valuemin={0} aria-valuemax={100}><i style={{ width: `${boundedValue}%` }} /></div>;
}

function mountHealth(mount: RegisterMount, ownerHealth: RegisterHealth): RegisterHealth {
  if (!mount.isAvailable || ownerHealth === 'offline') return 'offline';
  return mount.percentUsed >= 90 ? 'warning' : 'healthy';
}

function BackendComparison({ selected }: { selected: RegisterBackend[] }) {
  const properties: Array<[string, (backend: RegisterBackend) => string | number]> = [
    ['Identity', (backend) => backend.backendId],
    ['State', (backend) => stateLabel(backend.health)],
    ['Runtime version', (backend) => backend.version],
    ['Workers busy / capacity', (backend) => `${backend.activeWorkers} / ${backend.maxWorkers || '—'}`],
    ['Observed worker records', (backend) => backend.workers.length],
    ['Pending jobs', (backend) => backend.pendingJobs],
    ['Heartbeat age', (backend) => formatAge(backend.heartbeatAge)],
    ['Mounts', (backend) => backend.mounts.length],
  ];

  return <section className="fleet-register-panel fleet-register-comparison" aria-labelledby="fleet-register-comparison-title">
    <header className="fleet-register-panel-header"><div><span className="fleet-register-kicker">Observed state</span><h2 id="fleet-register-comparison-title">Backend comparison</h2></div><span className="fleet-register-panel-meta">Side-by-side resource view</span></header>
    <div className="fleet-register-table-scroll"><table className="fleet-register-table fleet-register-comparison-table"><thead><tr><th scope="col">Property</th>{selected.map((backend) => <th scope="col" key={backend.backendId}>{backend.label}</th>)}</tr></thead><tbody>{properties.map(([label, value]) => <tr key={label}><th scope="row">{label}</th>{selected.map((backend) => <td key={backend.backendId}>{label === 'State' ? <StateBadge state={backend.health} /> : value(backend)}</td>)}</tr>)}</tbody></table></div>
  </section>;
}

function WorkerCells({ workers, label }: { workers: RegisterWorker[]; label: string }) {
  if (workers.length === 0) return <p className="fleet-register-muted">No worker records returned for this backend.</p>;
  return <div className="fleet-register-worker-cells" aria-label={`${label} worker states`}>{workers.map((worker, index) => <span className={`fleet-register-worker-cell fleet-register-worker-cell--${worker.status}`} key={worker.workerId} title={`${worker.workerId}: ${stateLabel(worker.status)}`}>{String(index + 1).padStart(2, '0')}</span>)}</div>;
}

/** Behind the WebUI server, each node opens through its own connection. */
function NodeConnectionLink({ backendId, clusters }: { backendId: string; clusters: BackendClusters | undefined }) {
  if (!clusters) return null;
  const link = nodeLink(backendId, clusters);
  if (link.kind === 'open') {
    if (link.connectionId === getActiveConnectionId()) return null;
    return <a className="fleet-register-link" href={connectionHome(link.connectionId)} onClick={(event) => followInApp(event, connectionHome(link.connectionId))}>Open this backend ↗</a>;
  }
  return <a className="fleet-register-link" href={addConnectionHref(link.name, link.apiUrl)} onClick={(event) => followInApp(event, addConnectionHref(link.name, link.apiUrl))}>Add this backend to the WebUI ↗</a>;
}

function BackendExpansion({ backend, onConfigure, clusters }: { backend: RegisterBackend; onConfigure: (backendId: string) => void; clusters: BackendClusters | undefined }) {
  const completed = backend.workers.reduce((total, worker) => total + worker.jobsCompleted, 0);
  return <tr className="fleet-register-expansion"><td colSpan={8}><div className="fleet-register-expanded-grid">
    <div><div className="fleet-register-row fleet-register-row--start"><h3>Workers on {backend.backendId}</h3><StateBadge state={backend.health} label={backend.isLocal ? 'Local backend' : backend.status} /></div><WorkerCells workers={backend.workers} label={backend.label} /><div className="fleet-register-row fleet-register-muted"><span>{backend.activeWorkers} active of {backend.maxWorkers || 'unknown'} capacity</span><span>{completed.toLocaleString()} tasks completed</span></div><div className="fleet-register-mini-ledger">{backend.workers.slice(0, 5).map((worker) => <div className="fleet-register-row" key={worker.workerId}><code>{worker.workerId}</code><StateBadge state={worker.status} /><code>{worker.currentJob ?? 'No active task'}</code></div>)}</div><button type="button" className="fleet-register-link" onClick={() => onConfigure(backend.backendId)}>Open backend configuration ↗</button><NodeConnectionLink backendId={backend.backendId} clusters={clusters} /></div>
    <div><div className="fleet-register-row fleet-register-row--start"><h3>Owned mounts</h3><span className="fleet-register-panel-meta">{backend.mounts.length} assigned</span></div><div className="fleet-register-mount-stack">{backend.mounts.length === 0 ? <p className="fleet-register-muted">No mount records returned.</p> : backend.mounts.map((mount) => <div className="fleet-register-mount-summary" key={mount.id}><div className="fleet-register-row"><strong>{mount.path}</strong><StateBadge state={mountHealth(mount, backend.health)} /></div><small>{mount.device} · {mount.configuredDirectories.length} {mount.configuredDirectories.length === 1 ? 'configured directory' : 'configured directories'}</small></div>)}</div></div>
  </div></td></tr>;
}

function DatabaseExpansion({
  database,
  onInspect,
  onVacuum,
  isVacuuming,
  disabled,
}: {
  database: DatabaseOverview;
  onInspect: (database: DatabaseOverview) => void;
  onVacuum: (site: string) => void;
  isVacuuming?: boolean;
  disabled?: boolean;
}) {
  const topTables = [...database.tables].slice(0, 5);
  return (
    <tr className="fleet-register-expansion">
      <td colSpan={9}>
        <div className="fleet-register-expanded-grid">
          <div>
            <div className="fleet-register-row fleet-register-row--start">
              <h3>Largest Tables in {database.site}</h3>
              <StateBadge
                state={database.status}
                label={
                  database.status === 'healthy'
                    ? 'Healthy'
                    : database.status === 'warning'
                      ? 'Needs vacuum'
                      : 'Offline'
                }
              />
            </div>
            <div className="fleet-register-mini-ledger">
              {topTables.length === 0 ? (
                <p className="fleet-register-muted">No tables recorded.</p>
              ) : (
                topTables.map((tbl) => (
                  <div className="fleet-register-row" key={tbl.table_name}>
                    <code>{tbl.table_name}</code>
                    <span title={database.row_counts_estimated ? ROW_ESTIMATE_TITLE : undefined}>
                      {formatRowCount(tbl.live_tuples, database.row_counts_estimated)} rows
                    </span>
                    <strong>{formatBytes(tbl.total_bytes)}</strong>
                  </div>
                ))
              )}
            </div>
            <button
              type="button"
              className="fleet-register-link"
              onClick={() => onInspect(database)}
            >
              Open database inspection ↗
            </button>
          </div>
          <div>
            <div className="fleet-register-row fleet-register-row--start">
              <h3>Database Information</h3>
              <span className="fleet-register-panel-meta">{database.tables.length} tables</span>
            </div>
            <div className="fleet-register-mount-stack">
              <div className="fleet-register-mount-summary">
                <div className="fleet-register-row">
                  <strong>{database.database_name}</strong>
                  <StateBadge state={database.status} />
                </div>
                <small>
                  {database.host}
                  {database.port ? `:${database.port}` : ''} · Schema: {database.schema_name}
                </small>
                <small>
                  Bloat: {database.bloat_percent}% · {database.total_dead_tuples.toLocaleString()} dead tuples
                </small>
              </div>
            </div>
            <div style={{ marginTop: 12 }}>
              <button
                type="button"
                className={`fleet-register-button${isVacuuming ? ' is-busy' : ''}`}
                disabled={disabled}
                onClick={() => onVacuum(database.site)}
              >
                {isVacuuming && <span className="database-op-spinner" aria-hidden="true" />}
                {isVacuuming ? `Vacuuming ${database.site}…` : `Vacuum ${database.site}`}
              </button>
            </div>
          </div>
        </div>
      </td>
    </tr>
  );
}

function InspectionMetric({ label, value }: { label: string; value: string | number }) {
  return <div className="fleet-register-inspection-metric"><span>{label}</span><strong>{value}</strong></div>;
}

function RegisterInspectionModal({
  kicker,
  title,
  onClose,
  children,
}: {
  kicker: string;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return <div className="modal-overlay" onClick={onClose}>
    <section className="modal-content fleet-register-inspect-modal" role="dialog" aria-modal="true" aria-labelledby="fleet-register-inspection-title" onClick={(event) => event.stopPropagation()}>
      <div className="modal-header"><div><span className="fleet-register-kicker">{kicker}</span><h3 id="fleet-register-inspection-title">{title}</h3></div><button type="button" className="modal-close" aria-label="Close inspection" onClick={onClose}>×</button></div>
      <div className="modal-body fleet-register-inspection-body">{children}</div>
    </section>
  </div>;
}

function BackendInspection({
  backend,
  onClose,
  onInspectWorker,
  deployments,
  clusters,
  onDeploymentChanged,
}: {
  backend: RegisterBackend;
  onClose: () => void;
  onInspectWorker: (workerId: string) => void;
  deployments?: Deployment[];
  clusters?: BackendClusters;
  onDeploymentChanged?: () => void;
}) {
  const [activeAction, setActiveAction] = useState<DeploymentAction | null>(null);
  // Its address when the backend reports one; its name is often only a container's.
  const [targetHost, setTargetHost] = useState(backend.address || '');
  const [targetPort, setTargetPort] = useState(22);
  const [targetInstallDir, setTargetInstallDir] = useState('~/ultimascraper');
  const [targetUsername, setTargetUsername] = useState('root');
  const [targetPassword, setTargetPassword] = useState('');
  const [targetPrivateKey, setTargetPrivateKey] = useState('');
  const [targetSudoPassword, setTargetSudoPassword] = useState('');
  const [authMethod, setAuthMethod] = useState<'password' | 'key'>('password');
  const [isRegistering, setIsRegistering] = useState(false);
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [registeredDeployment, setRegisteredDeployment] = useState<Deployment | null>(null);
  const [hostKey, setHostKey] = useState<HostKey | null>(null);

  const member = clusters?.members.find((m) => m.identity?.backend_id === backend.backendId);
  const connectionId = member?.connection_id;
  const [ticketString, setTicketString] = useState<string>('');
  const [ticketLoading, setTicketLoading] = useState(false);
  const [ticketCopied, setTicketCopied] = useState(false);
  const [ticketError, setTicketError] = useState<string | null>(null);

  const effectiveConnectionId =
    connectionId || (backend.isLocal ? (getActiveConnectionId() ?? 'default') : backend.backendId);

  useEffect(() => {
    let active = true;
    if (!effectiveConnectionId || typeof getConnectionTicket !== 'function') return;
    setTicketLoading(true);
    Promise.resolve(getConnectionTicket(effectiveConnectionId))
      .then((res) => {
        if (active && res?.ticket) {
          setTicketString(res.ticket);
          setTicketError(null);
        }
      })
      .catch((err) => {
        if (active) {
          setTicketError(err instanceof Error ? err.message : 'Could not generate connection ticket.');
        }
      })
      .finally(() => {
        if (active) setTicketLoading(false);
      });
    return () => {
      active = false;
    };
  }, [effectiveConnectionId]);

  const copyTicket = async () => {
    try {
      let ticketToCopy = ticketString;
      if (!ticketToCopy && effectiveConnectionId) {
        setTicketLoading(true);
        const res = await getConnectionTicket(effectiveConnectionId);
        ticketToCopy = res.ticket;
        setTicketString(res.ticket);
      }
      if (!ticketToCopy) {
        throw new Error('No ticket available for this backend.');
      }
      await copyText(ticketToCopy);
      setTicketCopied(true);
      setTimeout(() => setTicketCopied(false), 2500);
    } catch (err) {
      setTicketError(err instanceof Error ? err.message : 'Failed to copy ticket.');
    } finally {
      setTicketLoading(false);
    }
  };
  const matchingDeployment =
    registeredDeployment ||
    deployments?.find(
      (d) =>
        (connectionId && d.connection_id === connectionId) ||
        d.name === backend.label ||
        d.name === backend.backendId ||
        (backend.hostname && (d.target === backend.hostname || d.details.host === backend.hostname)) ||
        (backend.address && d.details.host === backend.address),
    ) ||
    null;

  const handleRegisterAndOperate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!targetHost.trim() || !targetInstallDir.trim()) {
      setRegisterError('Host and install directory are required.');
      return;
    }
    setIsRegistering(true);
    setRegisterError(null);
    try {
      let host = targetHost.trim();
      let port = targetPort || 22;
      if (host.includes(':') && !host.startsWith('[')) {
        const parts = host.split(':');
        host = parts[0];
        const parsed = parseInt(parts[1], 10);
        if (!isNaN(parsed) && parsed > 0) port = parsed;
      }
      let key = hostKey?.key;
      if (!key) {
        try {
          const scanned = await scanHostKey(host, port);
          setHostKey(scanned);
          key = scanned.key;
        } catch {
          // The backend open_target will also attempt to auto-scan if omitted
        }
      }
      const reg = await registerExistingInstall({
        name: backend.label || backend.backendId,
        target: {
          kind: 'ssh',
          host,
          port,
          username: targetUsername.trim() || 'root',
          password: authMethod === 'password' ? targetPassword : undefined,
          private_key: authMethod === 'key' ? targetPrivateKey : undefined,
          host_key: key,
          sudo_password: targetSudoPassword || undefined,
        },
        install_dir: targetInstallDir.trim(),
      });
      setRegisteredDeployment(reg);
      onDeploymentChanged?.();
    } catch (err) {
      setRegisterError(err instanceof Error ? err.message : 'Failed to register remote deployment.');
    } finally {
      setIsRegistering(false);
    }
  };

  return (
    <RegisterInspectionModal
      kicker={backend.isLocal ? 'Local backend inspection' : 'Remote backend inspection'}
      title={backend.label}
      onClose={onClose}
    >
      <div className="fleet-register-inspection-status">
        <StateBadge state={backend.health} label={backend.isLocal ? 'Local backend' : backend.status} />
        <code>{backend.backendId}</code>
      </div>

      <div className="fleet-register-inspection-metrics">
        <InspectionMetric label="Runtime version" value={backend.version} />
        <InspectionMetric label="Worker load" value={`${backend.activeWorkers} / ${backend.maxWorkers || '—'}`} />
        <InspectionMetric label="Pending jobs" value={backend.pendingJobs} />
        <InspectionMetric label="Heartbeat" value={formatAge(backend.heartbeatAge)} />
      </div>
 
      {/* Connection Ticket */}
      <section className="fleet-register-inspection-section" data-testid="connection-ticket-section">
        <div className="fleet-register-row">
          <h4>Connection Ticket</h4>
          <span className="fleet-register-panel-meta">Shareable pairing credential</span>
        </div>
        <p className="fleet-register-inspection-copy">
          Copy this connection ticket to easily pair and connect another WebUI instance (such as a NAS) to this backend.
        </p>
        {ticketError && <p className="connections-error" role="alert">{ticketError}</p>}
        <div className="fleet-register-ticket-box">
          <input
            type="text"
            readOnly
            value={ticketString || (ticketLoading ? 'Generating ticket…' : 'usr://ticket/…')}
            className="fleet-register-ticket-input"
            onClick={(e) => (e.target as HTMLInputElement).select()}
            placeholder="Generating ticket…"
          />
          <button
            type="button"
            className="fleet-register-button fleet-register-button--primary"
            onClick={() => void copyTicket()}
            disabled={ticketLoading}
          >
            {ticketCopied ? '✓ Copied' : ticketLoading ? 'Exporting…' : 'Copy Ticket'}
          </button>
        </div>
      </section>

      {/* Remote Backend Lifecycle Operations */}
      {(!backend.isLocal || Boolean(matchingDeployment)) && (
        <section className="fleet-register-inspection-section" data-testid="remote-operations-section">
          <div className="fleet-register-row">
            <h4>Remote Operations</h4>
            <span className="fleet-register-panel-meta">Host lifecycle management</span>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.25rem' }}>
            <button
              type="button"
              className={`fleet-register-button ${activeAction === 'repair' ? 'is-active' : ''}`}
              onClick={() => setActiveAction(activeAction === 'repair' ? null : 'repair')}
            >
              Repair
            </button>
            <button
              type="button"
              className={`fleet-register-button ${activeAction === 'upgrade' ? 'is-active' : ''}`}
              onClick={() => setActiveAction(activeAction === 'upgrade' ? null : 'upgrade')}
            >
              Upgrade
            </button>
            <button
              type="button"
              className={`fleet-register-button fleet-register-button--danger ${activeAction === 'uninstall' ? 'is-active' : ''}`}
              style={{
                color: 'var(--color-error)',
                borderColor: 'rgb(var(--color-error-rgb) / 0.4)',
                background:
                  activeAction === 'uninstall'
                    ? 'rgb(var(--color-error-rgb) / 0.2)'
                    : 'rgb(var(--color-error-rgb) / 0.08)',
              }}
              onClick={() => setActiveAction(activeAction === 'uninstall' ? null : 'uninstall')}
            >
              Uninstall
            </button>
          </div>

          {activeAction && matchingDeployment && (
            <div style={{ marginTop: '0.75rem', borderTop: '1px solid var(--color-border-primary, #333)', paddingTop: '0.75rem' }}>
              <OperationPanel
                key={`${matchingDeployment.id}-${activeAction}`}
                deployment={matchingDeployment}
                action={activeAction}
                initialCredentials={{
                  authMethod,
                  password: targetPassword,
                  privateKey: targetPrivateKey,
                  sudoPassword: targetSudoPassword,
                }}
                onClose={() => setActiveAction(null)}
                onFinished={() => {
                  setActiveAction(null);
                  onDeploymentChanged?.();
                }}
              />
            </div>
          )}

          {activeAction && !matchingDeployment && (
            <div
              className="deployment-panel"
              style={{
                marginTop: '0.75rem',
                borderTop: '1px solid var(--color-border-primary, #333)',
                paddingTop: '0.75rem',
              }}
            >
              <p className="connections-copy" style={{ marginBottom: '0.75rem' }}>
                This remote backend is not yet linked to a deployment record. To run{' '}
                <strong>{ACTION_LABELS[activeAction]}</strong>, provide its SSH connection details:
              </p>
              {registerError && <p className="connections-error" role="alert">{registerError}</p>}
              <form onSubmit={(e) => void handleRegisterAndOperate(e)} className="connections-form">
                <div style={{ display: 'flex', gap: '0.75rem' }}>
                  <label style={{ flex: 1 }}>
                    <span>Target Host / IP</span>
                    <input
                      type="text"
                      value={targetHost}
                      onChange={(e) => setTargetHost(e.target.value)}
                      placeholder={backend.hostname || '192.168.1.50'}
                      required
                    />
                  </label>
                  <label style={{ width: '6rem' }}>
                    <span>Port</span>
                    <input
                      type="number"
                      min={1}
                      max={65535}
                      value={targetPort}
                      onChange={(e) => setTargetPort(Number(e.target.value) || 22)}
                    />
                  </label>
                </div>
                <label>
                  <span>Install Directory</span>
                  <input
                    type="text"
                    value={targetInstallDir}
                    onChange={(e) => setTargetInstallDir(e.target.value)}
                    placeholder="~/ultimascraper"
                    required
                  />
                </label>
                <div className="deploy-choice">
                  <label className="connections-checkbox">
                    <input type="radio" checked={authMethod === 'password'} onChange={() => setAuthMethod('password')} />
                    <span>SSH password</span>
                  </label>
                  <label className="connections-checkbox">
                    <input type="radio" checked={authMethod === 'key'} onChange={() => setAuthMethod('key')} />
                    <span>Private key</span>
                  </label>
                </div>
                <label>
                  <span>SSH Username</span>
                  <input
                    type="text"
                    value={targetUsername}
                    onChange={(e) => setTargetUsername(e.target.value)}
                    placeholder="root"
                    required
                  />
                </label>
                {authMethod === 'password' ? (
                  <label>
                    <span>SSH Password</span>
                    <input
                      type="password"
                      value={targetPassword}
                      onChange={(e) => setTargetPassword(e.target.value)}
                      placeholder="Enter SSH password"
                      required
                    />
                  </label>
                ) : (
                  <label>
                    <span>Private Key</span>
                    <textarea
                      rows={3}
                      value={targetPrivateKey}
                      onChange={(e) => setTargetPrivateKey(e.target.value)}
                      placeholder="Paste private key"
                      required
                    />
                  </label>
                )}
                <label>
                  <span>sudo password (optional)</span>
                  <input
                    type="password"
                    value={targetSudoPassword}
                    onChange={(e) => setTargetSudoPassword(e.target.value)}
                    placeholder="Leave empty if passwordless sudo"
                  />
                </label>
                <div className="connections-actions" style={{ marginTop: '0.5rem' }}>
                  <button type="submit" className="connections-button is-primary" disabled={isRegistering}>
                    {isRegistering ? 'Connecting…' : `Connect & ${ACTION_LABELS[activeAction]}`}
                  </button>
                  <button type="button" className="connections-button" onClick={() => setActiveAction(null)}>
                    Cancel
                  </button>
                </div>
              </form>
            </div>
          )}
        </section>
      )}

      <section className="fleet-register-inspection-section">
        <div className="fleet-register-row">
          <h4>Workers</h4>
          <span className="fleet-register-panel-meta">{backend.workers.length} observed</span>
        </div>
        <div className="fleet-register-inspection-list">
          {backend.workers.length === 0 ? (
            <p className="fleet-register-muted">No worker records returned.</p>
          ) : (
            backend.workers.map((worker) => (
              <button
                type="button"
                className="fleet-register-inspection-list-item"
                key={worker.workerId}
                onClick={() => onInspectWorker(worker.workerId)}
              >
                <span>
                  <code>{worker.workerId}</code>
                  <small>{worker.currentJob ?? 'No active task'}</small>
                </span>
                <StateBadge state={worker.status} />
                <span className="fleet-register-inspection-arrow">Inspect ↗</span>
              </button>
            ))
          )}
        </div>
      </section>

      <section className="fleet-register-inspection-section">
        <div className="fleet-register-row">
          <h4>Owned mounts</h4>
          <span className="fleet-register-panel-meta">{backend.mounts.length} assigned</span>
        </div>
        <div className="fleet-register-inspection-list">
          {backend.mounts.length === 0 ? (
            <p className="fleet-register-muted">No mount records returned.</p>
          ) : (
            backend.mounts.map((mount) => (
              <div
                className="fleet-register-inspection-list-item fleet-register-inspection-list-item--static"
                key={mount.id}
              >
                <span>
                  <strong>{mount.path}</strong>
                  <small>{mount.device}</small>
                </span>
                <StateBadge state={mountHealth(mount, backend.health)} />
              </div>
            ))
          )}
        </div>
      </section>
    </RegisterInspectionModal>
  );
}

function WorkerInspection({
  worker,
  owner,
  onClose,
  onInspectBackend,
}: {
  worker: RegisterWorker;
  owner: RegisterBackend;
  onClose: () => void;
  onInspectBackend: () => void;
}) {
  return <RegisterInspectionModal kicker="Worker inspection" title={worker.workerId} onClose={onClose}>
    <div className="fleet-register-inspection-status"><StateBadge state={worker.status} /><span>Observed worker record</span></div>
    <div className="fleet-register-inspection-metrics"><InspectionMetric label="Current job / task" value={worker.currentJob ?? 'No active task'} /><InspectionMetric label="Tasks completed" value={worker.jobsCompleted.toLocaleString()} /><InspectionMetric label="Owner" value={owner.label} /><InspectionMetric label="Backend state" value={stateLabel(owner.health)} /></div>
    <section className="fleet-register-inspection-section"><div className="fleet-register-row"><h4>Owning backend</h4><StateBadge state={owner.health} /></div><p className="fleet-register-inspection-copy">{owner.hostname} · <code>{owner.backendId}</code></p><button type="button" className="fleet-register-link" onClick={onInspectBackend}>Inspect backend ↗</button></section>
  </RegisterInspectionModal>;
}

export function SystemFleetRegisterPage() {
  const queryClient = useQueryClient();
  const [selectedDrive, setSelectedDrive] = useState<DriveInfo | null>(null);
  const [editingBackendId, setEditingBackendId] = useState<string | null>(null);
  const [tab, setTab] = useState<RegisterTab>('cluster');
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState<RegisterFilter>('all');
  const [sort, setSort] = useState<'name' | 'load'>('name');
  const [expandedBackendId, setExpandedBackendId] = useState<string | null>(null);
  const [expandedDatabaseSite, setExpandedDatabaseSite] = useState<string | null>(null);
  const [inspectedDatabaseSite, setInspectedDatabaseSite] = useState<string | null>(null);
  const [vacuumModalState, setVacuumModalState] = useState<{
    isOpen: boolean;
    site?: string;
    table?: string;
  } | null>(null);
  const [databaseResultNotice, setDatabaseResultNotice] =
    useState<DatabaseStatusNotice | null>(null);
  const [compare, setCompare] = useState<string[]>([]);
  const [comparing, setComparing] = useState(false);
  const [inspectTarget, setInspectTarget] = useState<RegisterInspectTarget>(null);
  const [now, setNow] = useState(() => Date.now());
  const [collapsedSections, setCollapsedSections] = useState<{ assigned: boolean; unassigned: boolean }>({ assigned: false, unassigned: false });

  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, []);

  const drivesQuery = useQuery({ queryKey: ['system', 'drives'], queryFn: getDrives, refetchInterval: 30000 });
  const backendQuery = useQuery({ queryKey: ['system', 'backend'], queryFn: getBackendStatus, refetchInterval: 5000 });
  const allBackendsQuery = useQuery({ queryKey: ['system', 'all-backends'], queryFn: getAllBackends, refetchInterval: 10000 });
  // Which nodes this WebUI has connections for; each node's drives and workers open there.
  const clustersQuery = useQuery({ queryKey: ['webui', 'clusters'], queryFn: listClusters, staleTime: 60_000 });
  const deploymentsQuery = useQuery({ queryKey: ['webui', 'deployments'], queryFn: listDeployments, staleTime: 30_000 });
  const clientsQuery = useQuery({ queryKey: ['webui', 'clients'], queryFn: listWebUIClients, refetchInterval: 10_000 });
  const [confirmDisconnectSession, setConfirmDisconnectSession] = useState<{
    id: string;
    isCurrent: boolean;
    device: string;
  } | null>(null);
  const revokeClientMutation = useMutation({
    mutationFn: (id: string) => revokeWebUIClient(id),
    onSuccess: () => {
      void clientsQuery.refetch();
      if (confirmDisconnectSession?.isCurrent) {
        window.location.reload();
      }
      setConfirmDisconnectSession(null);
    },
  });
  const databaseQuery = useQuery({
    queryKey: ['system', 'database'],
    queryFn: getDatabaseOverview,
    refetchInterval: (query) => {
      const active = query.state.data?.active_operations;
      return active && active.some((op) => op.status === 'running') ? 2000 : 30000;
    },
  });
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: getSettings });

  const addDirectoryMutation = useMutation({ mutationFn: addDirectory });
  const removeDirectoryMutation = useMutation({ mutationFn: removeDirectory });
  const updateDirectoryConfigMutation = useMutation({ mutationFn: updateDirectoryConfig });
  const updateSettingsMutation = useMutation({ mutationFn: updateSettings });
  const [confirmPower, setConfirmPower] = useState<RuntimePowerAction | null>(null);
  const [restartStartedAt, setRestartStartedAt] = useState<number | null>(null);
  const powerMutation = useMutation({
    mutationFn: ({
      action,
      targets,
    }: {
      action: RuntimePowerAction;
      targets?: RuntimeServiceTarget[];
    }) => controlRuntimePower(action, targets),
    onSuccess: (result) => {
      if (result.action === 'restart') setRestartStartedAt(Date.now());
    },
  });

  const vacuumMutation = useMutation({
    mutationFn: (req: DatabaseVacuumRequest) => vacuumDatabase(req),
    onMutate: () => {
      setDatabaseResultNotice(null);
    },
    onSuccess: (res) => {
      setDatabaseResultNotice({
        tone: res.success ? 'info' : 'danger',
        title: res.success ? 'Vacuum completed' : 'Vacuum failed',
        message: res.message,
      });
      void databaseQuery.refetch();
    },
    onError: async (err) => {
      let activeOnServer = databaseQuery.data?.active_operations?.some(
        (op) => op.status === 'running' && op.operation_type === 'vacuum',
      );
      if (!activeOnServer) {
        try {
          const fresh = await databaseQuery.refetch();
          activeOnServer = fresh.data?.active_operations?.some(
            (op) => op.status === 'running' && op.operation_type === 'vacuum',
          );
        } catch {
          // ignore network failure on re-fetch
        }
      }
      if (activeOnServer) {
        setDatabaseResultNotice({
          tone: 'info',
          title: 'Vacuum running in background',
          message:
            'The client HTTP connection timed out or disconnected, but the maintenance operation is actively executing on the database server. Progress is being tracked below.',
        });
        return;
      }
      setDatabaseResultNotice({
        tone: 'danger',
        title: 'Vacuum error',
        message: err instanceof Error ? err.message : 'Vacuum failed.',
      });
    },
  });

  const analyzeMutation = useMutation({
    mutationFn: ({ site, table }: { site?: string; table?: string }) =>
      analyzeDatabase({ site, table_name: table }),
    onMutate: () => {
      setDatabaseResultNotice(null);
    },
    onSuccess: (res) => {
      setDatabaseResultNotice({
        tone: res.success ? 'info' : 'danger',
        title: res.success ? 'Analyze completed' : 'Analyze failed',
        message: res.message,
      });
      void databaseQuery.refetch();
    },
    onError: async (err) => {
      let activeOnServer = databaseQuery.data?.active_operations?.some(
        (op) => op.status === 'running' && op.operation_type === 'analyze',
      );
      if (!activeOnServer) {
        try {
          const fresh = await databaseQuery.refetch();
          activeOnServer = fresh.data?.active_operations?.some(
            (op) => op.status === 'running' && op.operation_type === 'analyze',
          );
        } catch {
          // ignore network failure on re-fetch
        }
      }
      if (activeOnServer) {
        setDatabaseResultNotice({
          tone: 'info',
          title: 'Analyze running in background',
          message:
            'The client HTTP connection timed out or disconnected, but the maintenance operation is actively executing on the database server. Progress is being tracked below.',
        });
        return;
      }
      setDatabaseResultNotice({
        tone: 'danger',
        title: 'Analyze error',
        message: err instanceof Error ? err.message : 'Analyze failed.',
      });
    },
  });

  const reindexMutation = useMutation({
    mutationFn: ({ site, table }: { site?: string; table?: string }) =>
      reindexDatabase({ site, table_name: table }),
    onMutate: () => {
      setDatabaseResultNotice(null);
    },
    onSuccess: (res) => {
      setDatabaseResultNotice({
        tone: res.success ? 'info' : 'danger',
        title: res.success ? 'Reindex completed' : 'Reindex failed',
        message: res.message,
      });
      void databaseQuery.refetch();
    },
    onError: async (err) => {
      let activeOnServer = databaseQuery.data?.active_operations?.some(
        (op) => op.status === 'running' && op.operation_type === 'reindex',
      );
      if (!activeOnServer) {
        try {
          const fresh = await databaseQuery.refetch();
          activeOnServer = fresh.data?.active_operations?.some(
            (op) => op.status === 'running' && op.operation_type === 'reindex',
          );
        } catch {
          // ignore network failure on re-fetch
        }
      }
      if (activeOnServer) {
        setDatabaseResultNotice({
          tone: 'info',
          title: 'Reindex running in background',
          message:
            'The client HTTP connection timed out or disconnected, but the maintenance operation is actively executing on the database server. Progress is being tracked below.',
        });
        return;
      }
      setDatabaseResultNotice({
        tone: 'danger',
        title: 'Reindex error',
        message: err instanceof Error ? err.message : 'Reindex failed.',
      });
    },
  });

  const cancelOpMutation = useMutation({
    mutationFn: ({ site, table }: { site?: string; table?: string }) =>
      cancelDatabaseOperation(site, table),
    onSuccess: (res) => {
      setDatabaseResultNotice({
        tone: res.success ? 'info' : 'warning',
        title: 'Operation cancelled',
        message: res.message,
      });
      void databaseQuery.refetch();
    },
    onError: (err) => {
      setDatabaseResultNotice({
        tone: 'danger',
        title: 'Cancel failed',
        message: err instanceof Error ? err.message : 'Could not cancel database operation.',
      });
    },
  });

  // Notices follow the queries' own state rather than being copied into state.
  // A closed notice stays closed until its message changes.
  const [dismissedNotices, setDismissedNotices] = useState<string[]>([]);
  const reconnected =
    restartStartedAt !== null &&
    backendQuery.dataUpdatedAt > restartStartedAt &&
    !backendQuery.isError &&
    !!backendQuery.data;
  const isRestarting = restartStartedAt !== null && !reconnected;

  const resetPower = powerMutation.reset;
  const refetchDatabase = databaseQuery.refetch;
  const refetchAllBackends = allBackendsQuery.refetch;
  const refetchDrives = drivesQuery.refetch;
  const refetchClusters = clustersQuery.refetch;
  useEffect(() => {
    if (!reconnected) return;
    resetPower();
    void refetchDatabase();
    void refetchAllBackends();
    void refetchDrives();
    void refetchClusters();
    const timer = window.setTimeout(() => setRestartStartedAt(null), 5000);
    return () => window.clearTimeout(timer);
  }, [reconnected, resetPower, refetchDatabase, refetchAllBackends, refetchDrives, refetchClusters]);

  useEffect(() => {
    if (!databaseResultNotice) return;
    const timer = window.setTimeout(() => setDatabaseResultNotice(null), 7000);
    return () => window.clearTimeout(timer);
  }, [databaseResultNotice]);

  const toasts = useMemo(() => {
    const list: ToastPortalState[] = [];
    if (isRestarting) {
      list.push({ id: 'runtime-power-status', title: POWER_COPY.restart.pending, message: POWER_COPY.restart.done, type: 'info' });
    } else if (reconnected) {
      list.push({ id: 'runtime-reconnected', title: 'UltimaScraper reconnected', message: 'Local runtime is online and responsive.', type: 'success' });
    }
    if (powerMutation.isSuccess && powerMutation.data?.action === 'shutdown') {
      list.push({ id: 'runtime-power-status', title: POWER_COPY.shutdown.pending, message: POWER_COPY.shutdown.done, type: 'warning' });
    }
    if (powerMutation.error) {
      list.push({
        id: 'runtime-power-error',
        title: 'UltimaScraper could not be restarted or stopped',
        message: powerMutation.error instanceof Error ? powerMutation.error.message : 'The launcher did not accept the request.',
        type: 'error',
      });
    }
    // While restarting, every service is expected to be unreachable.
    if (!isRestarting) {
      const telemetry: Array<[unknown, string, string, string, ToastPortalState['type']]> = [
        [databaseQuery.error, 'telemetry-database-error', 'Database telemetry unavailable', 'Database metrics could not be loaded.', 'warning'],
        [backendQuery.error, 'telemetry-backend-error', 'Local runtime telemetry unavailable', 'The local backend status could not be loaded.', 'error'],
        [allBackendsQuery.error, 'telemetry-allbackends-error', 'Remote fleet telemetry unavailable', 'Remote backend records could not be loaded.', 'warning'],
        [drivesQuery.error, 'telemetry-drives-error', 'Local storage telemetry unavailable', 'Drive records could not be loaded.', 'warning'],
      ];
      for (const [error, id, title, fallback, type] of telemetry) {
        if (error) list.push({ id, title, message: error instanceof Error ? error.message : fallback, type });
      }
    }
    if (databaseResultNotice) {
      list.push({
        id: 'database-result-notice',
        title: databaseResultNotice.title,
        message: databaseResultNotice.message,
        type: databaseResultNotice.tone === 'danger' ? 'error' : databaseResultNotice.tone === 'warning' ? 'warning' : 'info',
      });
    }
    return list.filter((toast) => !dismissedNotices.includes(`${toast.id}|${toast.message}`));
  }, [
    isRestarting, reconnected, powerMutation.isSuccess, powerMutation.data, powerMutation.error,
    databaseQuery.error, backendQuery.error, allBackendsQuery.error, drivesQuery.error,
    databaseResultNotice, dismissedNotices,
  ]);

  const dismissToast = useCallback((itemOrId?: ToastPortalState | string) => {
    const closing = itemOrId === undefined ? toasts
      : toasts.filter((toast) => (typeof itemOrId === 'string' ? toast.id === itemOrId : toast === itemOrId || toast.id === itemOrId.id));
    setDismissedNotices((prev) => [...prev, ...closing.map((toast) => `${toast.id}|${toast.message}`)]);
  }, [toasts]);

  const pendingDatabaseOp: PendingDatabaseOp | null = useMemo(() => {
    if (vacuumMutation.isPending) {
      return {
        type: 'vacuum',
        site: vacuumMutation.variables?.site,
        table: vacuumMutation.variables?.table_name,
      };
    }
    if (analyzeMutation.isPending) {
      return {
        type: 'analyze',
        site: analyzeMutation.variables?.site,
        table: analyzeMutation.variables?.table,
      };
    }
    if (reindexMutation.isPending) {
      return {
        type: 'reindex',
        site: reindexMutation.variables?.site,
        table: reindexMutation.variables?.table,
      };
    }
    return null;
  }, [
    vacuumMutation.isPending,
    vacuumMutation.variables,
    analyzeMutation.isPending,
    analyzeMutation.variables,
    reindexMutation.isPending,
    reindexMutation.variables,
  ]);

  const serverActiveOp = useMemo(() => {
    return (
      databaseQuery.data?.active_operations?.find(
        (op) => op.status === 'running',
      ) ?? null
    );
  }, [databaseQuery.data?.active_operations]);

  const effectiveDatabaseOp: PendingDatabaseOp | null = useMemo(() => {
    if (serverActiveOp) {
      return {
        type: serverActiveOp.operation_type,
        site: serverActiveOp.site,
        table: serverActiveOp.table_name || undefined,
        currentTable: serverActiveOp.current_table || undefined,
        tablesCompleted: serverActiveOp.tables_completed,
        tablesTotal: serverActiveOp.tables_total,
        phase: serverActiveOp.phase || undefined,
        progressPercent: serverActiveOp.progress_percent ?? undefined,
        message: serverActiveOp.message || undefined,
      };
    }
    return pendingDatabaseOp;
  }, [serverActiveOp, pendingDatabaseOp]);

  const drives = useMemo(() => mergeConfiguredDrivesWithInventory(drivesQuery.data?.drives ?? [], settingsQuery.data), [drivesQuery.data?.drives, settingsQuery.data]);
  const backends = useMemo(() => buildRegisterBackends(backendQuery.data, allBackendsQuery.data, drives, now), [allBackendsQuery.data, backendQuery.data, drives, now]);
  const workers = useMemo(() => backends.flatMap((backend) => backend.workers.map((worker) => ({ worker, owner: backend }))), [backends]);
  const mounts = useMemo(() => backends.flatMap((backend) => backend.mounts), [backends]);
  const databases = useMemo(() => databaseQuery.data?.databases ?? [], [databaseQuery.data?.databases]);
  const inspectedDatabase = useMemo(
    () => (inspectedDatabaseSite ? databases.find((d) => d.site === inspectedDatabaseSite) ?? null : null),
    [databases, inspectedDatabaseSite],
  );
  const localDrives = useMemo(() => new Map(drives.map((drive) => [drive.path, drive])), [drives]);
  const matches = (text: string) => text.toLowerCase().includes(query.trim().toLowerCase());
  const backendMatches = (backend: RegisterBackend) => matches(`${backend.label} ${backend.hostname} ${backend.backendId} ${backend.status}`) && (filter === 'all' || filter === 'attention' && backend.health !== 'healthy' || filter === backend.health);
  const filteredBackends = backends.filter(backendMatches).sort((left, right) => sort === 'load' ? (right.activeWorkers / Math.max(right.maxWorkers, 1)) - (left.activeWorkers / Math.max(left.maxWorkers, 1)) : left.backendId.localeCompare(right.backendId));
  const filteredWorkers = workers.filter(({ worker, owner }) => matches(`${worker.workerId} ${owner.label} ${worker.currentJob ?? ''}`) && (filter === 'all' || filter === 'attention' && worker.status !== 'idle' || filter === worker.status));
  const filteredMounts = mounts.filter((mount) => { const owner = backends.find((backend) => backend.backendId === mount.backendId); const health = mountHealth(mount, owner?.health ?? 'offline'); return matches(`${mount.path} ${mount.device} ${mount.backendId}`) && (filter === 'all' || filter === 'attention' && health !== 'healthy' || filter === health); });
  const databaseMatches = (db: DatabaseOverview) => matches(`${db.site} ${db.database_name} ${db.schema_name} ${db.host}`) && (filter === 'all' || (filter === 'attention' && db.status !== 'healthy') || filter === db.status);
  const filteredDatabases = databases.filter(databaseMatches);
  const clients = useMemo(() => clientsQuery.data ?? [], [clientsQuery.data]);
  const filteredClients = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return clients.filter((c) => {
      const isRecent = now - c.last_seen * 1000 < 300_000;
      return (
        `${c.device_info} ${c.ip_address} ${c.user_agent} ${c.id}`.toLowerCase().includes(needle) &&
        (filter === 'all' ||
          (filter === 'healthy' || filter === 'running' ? isRecent : false) ||
          (filter === 'idle' || filter === 'offline' ? !isRecent : false) ||
          (filter === 'attention' ? false : true))
      );
    });
  }, [clients, query, filter, now]);
  const assignedMounts = useMemo(() => filteredMounts.filter((mount) => mount.configuredDirectories.length > 0), [filteredMounts]);
  const unassignedMounts = useMemo(() => filteredMounts.filter((mount) => mount.configuredDirectories.length === 0), [filteredMounts]);
  const totalAssignedDirectories = useMemo(() => assignedMounts.reduce((acc, mount) => acc + mount.configuredDirectories.length, 0), [assignedMounts]);
  const selectedBackends = backends.filter((backend) => compare.includes(backend.backendId));
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null);

  const defaultClusterId = useMemo(() => {
    return (
      backends.find((b) => b.clusterId)?.clusterId ??
      allBackendsQuery.data?.backends.find((b) => b.cluster_id)?.cluster_id ??
      null
    );
  }, [backends, allBackendsQuery.data?.backends]);

  const clusterRecords = clustersQuery.data?.clusters;
  const availableClusters = useMemo(() => {
    const list: Array<{
      clusterId: string;
      nodeCount: number;
      connectionId?: string | null;
      label?: string;
      isCurrent: boolean;
    }> = [];
    const seen = new Set<string>();

    if (clusterRecords) {
      for (const c of clusterRecords) {
        if (!c.cluster_id || seen.has(c.cluster_id)) continue;
        seen.add(c.cluster_id);
        const nodesInBackend = backends.filter((b) => b.clusterId === c.cluster_id).length;
        const count = nodesInBackend > 0 ? nodesInBackend : (c.connection_ids?.length || 1);
        list.push({
          clusterId: c.cluster_id,
          nodeCount: count,
          connectionId: c.connection_ids?.[0] ?? null,
          isCurrent: c.cluster_id === (selectedClusterId || defaultClusterId),
        });
      }
    }

    for (const b of backends) {
      if (b.clusterId && !seen.has(b.clusterId)) {
        seen.add(b.clusterId);
        const count = backends.filter((item) => item.clusterId === b.clusterId).length;
        list.push({
          clusterId: b.clusterId,
          nodeCount: count,
          connectionId: null,
          isCurrent: b.clusterId === (selectedClusterId || defaultClusterId),
        });
      }
    }

    return list;
  }, [clusterRecords, backends, selectedClusterId, defaultClusterId]);

  const activeClusterId = useMemo(() => {
    if (selectedClusterId && availableClusters.some((c) => c.clusterId === selectedClusterId)) {
      return selectedClusterId;
    }
    return defaultClusterId;
  }, [selectedClusterId, availableClusters, defaultClusterId]);

  const handleSelectCluster = (targetClusterId: string, targetConnectionId?: string | null) => {
    if (targetConnectionId && targetConnectionId !== getActiveConnectionId()) {
      navigateTo(sectionOnBackend(targetConnectionId));
      return;
    }
    setSelectedClusterId(targetClusterId);
  };

  const clusterBackends = useMemo(() => {
    if (!activeClusterId) return backends;
    return backends.filter((b) => b.clusterId === activeClusterId || (!b.clusterId && b.isLocal));
  }, [backends, activeClusterId]);

  const clusterCount = useMemo(() => {
    if (availableClusters.length > 0) {
      return availableClusters.length;
    }
    return activeClusterId ? 1 : 0;
  }, [availableClusters.length, activeClusterId]);

  const count =
    tab === 'backends'
      ? filteredBackends.length
      : tab === 'cluster'
        ? clusterCount
        : tab === 'workers'
          ? filteredWorkers.length
          : tab === 'clients'
            ? filteredClients.length
            : tab === 'mounts'
              ? filteredMounts.length
              : filteredDatabases.length;
  const pendingJobs = backendQuery.data?.pending_jobs ?? backends.find((backend) => backend.isLocal)?.pendingJobs ?? 0;
  const healthyCount = backends.filter((backend) => backend.health === 'healthy').length;
  const attentionCount = backends.filter((backend) => backend.health === 'warning').length;
  const offlineCount = backends.filter((backend) => backend.health === 'offline').length;
  const registerLoading =
    tab === 'database'
      ? databaseQuery.isLoading && !databaseQuery.data
      : tab === 'cluster'
        ? allBackendsQuery.isLoading && backends.length === 0
        : tab === 'clients'
          ? clientsQuery.isLoading && !clientsQuery.data
          : backends.length === 0 &&
            (backendQuery.isLoading || allBackendsQuery.isLoading || drivesQuery.isLoading);

  const handleInspectBackend = (backendId: string) => setInspectTarget({ kind: 'backend', backendId });
  const handleInspectWorker = (backendId: string, workerId: string) => setInspectTarget({ kind: 'worker', backendId, workerId });
  const inspectedBackend = inspectTarget ? backends.find((backend) => backend.backendId === inspectTarget.backendId) : undefined;
  const inspectedWorker = inspectTarget?.kind === 'worker' && inspectedBackend
    ? inspectedBackend.workers.find((worker) => worker.workerId === inspectTarget.workerId)
    : undefined;
  const refreshSelectedDrive = async () => {
    const refreshedDrives = await getDrives();
    queryClient.setQueryData(['system', 'drives'], refreshedDrives);
    const refreshedSettings = await settingsQuery.refetch();
    if (!selectedDrive) return;
    const merged = mergeConfiguredDrivesWithInventory(refreshedDrives.drives, refreshedSettings.data ?? settingsQuery.data);
    setSelectedDrive(merged.find((drive) => drive.path === selectedDrive.path) ?? null);
  };
  const handleAddDirectory = async (path: string, setupType: 'download' | 'metadata'): Promise<AddDirectoryResponse> => {
    if (!selectedDrive || !drivesQuery.data) throw new Error('The selected drive backend is no longer available. Refresh and retry.');
    const result = await addDirectoryMutation.mutateAsync({ drive_path: selectedDrive.path, directory_path: path, setup_type: setupType, target_backend_id: drivesQuery.data.backend_id, expected_version: settingsQuery.data?.config_version ?? undefined });
    if (result.success) await settingsQuery.refetch();
    return result;
  };
  const handleRemoveDirectory = async (path: string, setupType: 'download' | 'metadata'): Promise<RemoveDirectoryResponse> => {
    if (!drivesQuery.data) throw new Error('The drive backend is no longer available. Refresh and retry.');
    const result = await removeDirectoryMutation.mutateAsync({ directory_path: path, setup_type: setupType, target_backend_id: drivesQuery.data.backend_id, expected_version: settingsQuery.data?.config_version ?? undefined });
    if (result.success) await settingsQuery.refetch();
    return result;
  };
  const handleUpdateDirectoryConfig = async (config: DirectoryConfigRequest): Promise<DirectoryConfigResponse> => {
    if (!drivesQuery.data) throw new Error('The drive backend is no longer available. Refresh and retry.');
    const result = await updateDirectoryConfigMutation.mutateAsync({ ...config, target_backend_id: drivesQuery.data.backend_id, expected_version: settingsQuery.data?.config_version ?? undefined });
    if (result.success) await settingsQuery.refetch();
    return result;
  };
  const handleSaveSettings = async (settings: Partial<SettingsResponse>): Promise<SettingsResponse> => {
    const response = await updateSettingsMutation.mutateAsync({ ...(settings as SettingsUpdate), expected_version: settingsQuery.data?.config_version ?? undefined });
    queryClient.setQueryData(['settings'], response);
    return response;
  };

  const renderMountRow = (mount: RegisterMount) => {
    const owner = backends.find((backend) => backend.backendId === mount.backendId);
    const health = mountHealth(mount, owner?.health ?? 'offline');
    const localDrive = owner?.isLocal ? localDrives.get(mount.path) : undefined;
    return (
      <tr key={mount.id}>
        <th scope="row" data-label="Mount / device">
          <strong>{mount.path}</strong>
          <small>{mount.device}</small>
        </th>
        <td data-label="Owner"><code>{mount.backendId}</code></td>
        <td data-label="State"><StateBadge state={health} /></td>
        <td data-label="Capacity used">
          {mount.isAvailable ? (
            <div className="fleet-register-load">
              <strong>{mount.percentUsed.toFixed(1)}%</strong>
              <LoadMeter value={mount.percentUsed} label={`${mount.path} capacity used`} />
            </div>
          ) : (
            'Unavailable'
          )}
        </td>
        <td data-label="Free / total">
          {mount.isAvailable ? `${formatBytes(mount.freeBytes)} / ${formatBytes(mount.totalBytes)}` : '—'}
        </td>
        <td data-label="Directories">{mount.configuredDirectories.length}</td>
        <td data-label="Policy">
          {localDrive ? (
            <button type="button" className="fleet-register-link" onClick={() => setSelectedDrive(localDrive)}>
              Configure ↗
            </button>
          ) : (
            <button type="button" className="fleet-register-link" onClick={() => setEditingBackendId(mount.backendId)}>
              Backend config ↗
            </button>
          )}
        </td>
      </tr>
    );
  };

  const renderDividerRow = (section: 'assigned' | 'unassigned', mountCount: number, isCollapsed: boolean) => {
    const isAssigned = section === 'assigned';
    return (
      <tr key={`divider-${section}`} className={`fleet-register-divider-row fleet-register-divider-row--${section}`}>
        <td colSpan={7}>
          <button
            type="button"
            className="fleet-register-divider-btn"
            aria-expanded={!isCollapsed}
            aria-label={`${isCollapsed ? 'Expand' : 'Collapse'} ${isAssigned ? 'assigned' : 'unassigned'} mounts`}
            onClick={() => setCollapsedSections((current) => ({ ...current, [section]: !current[section] }))}
          >
            <div className="fleet-register-divider-start">
              <span className="fleet-register-divider-symbol" aria-hidden="true">
                {isCollapsed ? '+' : '−'}
              </span>
              <span className={`fleet-register-divider-badge fleet-register-divider-badge--${section}`}>
                {isAssigned ? 'Assigned' : 'Unassigned'}
              </span>
              <span className="fleet-register-divider-desc">
                {isAssigned ? 'Mounts with configured directories' : 'Mounts with no configured directories'}
              </span>
            </div>
            <span className="fleet-register-divider-count">
              {mountCount} {mountCount === 1 ? 'mount' : 'mounts'}
              {isAssigned ? ` · ${totalAssignedDirectories} ${totalAssignedDirectories === 1 ? 'directory' : 'directories'}` : ''}
              {isCollapsed ? ' · hidden' : ''}
            </span>
          </button>
        </td>
      </tr>
    );
  };

  return <div className="fleet-register-page">
    <ToastPortal toasts={toasts} onDismiss={dismissToast} />
    <section className="fleet-register" aria-labelledby="fleet-register-heading">
      <WorkspacePageHeader
        eyebrow={`System / Live inventory · ${new Date(now).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`}
        title="Resource register"
        subtitle="Find, inspect, and compare any runtime resource without losing its owner or observed state."
        icon="⌘"
        headingLevel={2}
        headingId="fleet-register-heading"
        meta={<div className="fleet-register-stamp"><strong>{String(backends.length).padStart(2, '0')}</strong><span>BACKENDS<br />{workers.length} OBSERVED WORKERS</span></div>}
      />
      <div className="fleet-register-summary" aria-label="Fleet summary">
        <span><StateBadge state="healthy" label={`${healthyCount} healthy`} /></span>
        <span><StateBadge state="warning" label={`${attentionCount} needs attention`} /></span>
        <span><StateBadge state="offline" label={`${offlineCount} offline`} /></span>
        <span>{pendingJobs} pending jobs <small>shared queue</small></span>
        {activeClusterId && (
          <button
            type="button"
            className={`fleet-register-cluster-pill${tab === 'cluster' ? ' is-active' : ''}`}
            aria-label="Inspect cluster topology"
            onClick={() => {
              setTab('cluster');
              setFilter('all');
            }}
            title="Inspect cluster topology & infrastructure"
          >
            <span className="cluster-icon" aria-hidden="true">⬡</span>
            <strong>Clusters</strong>
            <code>{activeClusterId.slice(0, 8)}…</code>
            <span className="fleet-cluster-count">
              {clusterBackends.length} {clusterBackends.length === 1 ? 'node' : 'nodes'}
            </span>
          </button>
        )}
        <span className="fleet-register-summary-note">Snapshot refreshes automatically</span>
      </div>
      <div className="fleet-register-toolbar">
        <div className="fleet-register-tabs" role="group" aria-label="Resource type">
          {(['cluster', 'backends', 'workers', 'clients', 'mounts', 'database'] as const).map((resourceTab) => (
            <button
              type="button"
              key={resourceTab}
              aria-pressed={tab === resourceTab}
              onClick={() => {
                setTab(resourceTab);
                setFilter('all');
              }}
            >
              {resourceTab === 'cluster' ? 'Clusters' : resourceTab === 'clients' ? 'Clients' : resourceTab}
              <span>
                {resourceTab === 'backends'
                  ? backends.length
                  : resourceTab === 'cluster'
                    ? clusterCount
                    : resourceTab === 'workers'
                      ? workers.length
                      : resourceTab === 'clients'
                        ? clients.length
                        : resourceTab === 'mounts'
                          ? mounts.length
                          : databases.length}
              </span>
            </button>
          ))}
        </div>
        <div className="fleet-register-toolbar-actions">
          {tab !== 'database' && tab !== 'cluster' && tab !== 'clients' && (
            <button
              type="button"
              className="fleet-register-button"
              disabled={compare.length < 2}
              onClick={() => setComparing((value) => !value)}
            >
              {comparing ? 'Close comparison' : `Compare selected (${compare.length})`}
            </button>
          )}
          {(['restart', 'shutdown'] as const).map((action) => (
            <button
              type="button"
              key={action}
              className="fleet-register-button"
              data-power={action}
              disabled={powerMutation.isPending || powerMutation.isSuccess}
              onClick={() => setConfirmPower(action)}
            >
              {POWER_COPY[action].button}
            </button>
          ))}
        </div>
      </div>
      {tab !== 'cluster' && (
        <div className="fleet-register-search">
          <span aria-hidden="true">⌕</span>
          <input
            aria-label="Search fleet register"
            placeholder="Search hostname, worker, client, job, or mount…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <select
            aria-label="Filter register by state"
            value={filter}
            onChange={(event) => setFilter(event.target.value as RegisterFilter)}
          >
            <option value="all">All states</option>
            <option value="attention">Needs attention</option>
            <option value="healthy">Healthy</option>
            <option value="running">Running</option>
            <option value="idle">Idle</option>
            <option value="warning">Warning</option>
            <option value="offline">Offline</option>
          </select>
          <span className="fleet-register-record-count">{count} records</span>
        </div>
      )}
      {comparing && <BackendComparison selected={selectedBackends} />}
      {tab === 'database' && effectiveDatabaseOp && (
        <OperationsNotice
          tone="info"
          title={`${effectiveDatabaseOp.type.charAt(0).toUpperCase() + effectiveDatabaseOp.type.slice(1)} in progress`}
        >
          <div className="database-progress-banner">
            <span className="database-op-spinner" aria-hidden="true" />
            <span>
              {effectiveDatabaseOp.message ||
                (effectiveDatabaseOp.table
                  ? `Running ${effectiveDatabaseOp.type} on table "${effectiveDatabaseOp.table}" (${effectiveDatabaseOp.site ?? 'all sites'})… Large operations may take a few minutes.`
                  : `Running ${effectiveDatabaseOp.type} on database (${effectiveDatabaseOp.site ?? 'all sites'})… Large operations may take a few minutes.`)}
            </span>
            {typeof effectiveDatabaseOp.progressPercent === 'number' &&
              effectiveDatabaseOp.progressPercent > 0 && (
                <span className="database-progress-pct">
                  {effectiveDatabaseOp.progressPercent.toFixed(1)}%
                </span>
              )}
            <button
              type="button"
              className="fleet-register-button fleet-register-button--compact"
              style={{ marginLeft: 'auto' }}
              disabled={cancelOpMutation.isPending}
              onClick={() =>
                cancelOpMutation.mutate({
                  site: effectiveDatabaseOp.site,
                  table: effectiveDatabaseOp.table,
                })
              }
            >
              {cancelOpMutation.isPending ? 'Cancelling…' : 'Cancel Operation'}
            </button>
          </div>
        </OperationsNotice>
      )}
      {tab === 'cluster' ? (
        <ClusterSection
          backends={clusterBackends}
          clusterId={activeClusterId}
          availableClusters={availableClusters}
          onSelectCluster={handleSelectCluster}
          clustersData={clustersQuery.data}
          databases={databases}
          settingsData={settingsQuery.data}
          serverVersion={databaseQuery.data?.server_version}
          isRedisConnected={backendQuery.data?.redis_connected ?? true}
          onConfigureBackend={setEditingBackendId}
          onInspectBackend={handleInspectBackend}
          onInspectWorker={handleInspectWorker}
          onNavigateToTab={(targetTab) => {
            setTab(targetTab);
            setFilter('all');
          }}
          onNodeAdded={() => {
            void clustersQuery.refetch();
            void allBackendsQuery.refetch();
            void backendQuery.refetch();
          }}
        />
      ) : registerLoading ? (
        <OperationsState
          variant="loading"
          title="Loading fleet register"
          description="Reading local runtime, remote backend, worker, and storage records."
          compact
        />
      ) : (
        <div className="fleet-register-table-scroll fleet-register-table-frame">
          <table className="fleet-register-table">
            <caption className="fleet-register-sr-only">System {tab} inventory</caption>
        {tab === 'backends' && <><thead><tr><th scope="col"><span className="fleet-register-sr-only">Compare</span></th><th scope="col" aria-sort={sort === 'name' ? 'ascending' : 'none'}><button type="button" onClick={() => setSort('name')}>Backend / host {sort === 'name' ? '↑' : '↕'}</button></th><th scope="col">State</th><th scope="col" aria-sort={sort === 'load' ? 'descending' : 'none'}><button type="button" onClick={() => setSort('load')}>Worker load {sort === 'load' ? '↓' : '↕'}</button></th><th scope="col">Version</th><th scope="col">Heartbeat</th><th scope="col">Config</th><th scope="col">Inspect</th></tr></thead><tbody>{filteredBackends.map((backend) => <Fragment key={backend.backendId}><tr id={`fleet-backend-${encodeURIComponent(backend.backendId)}`} className={expandedBackendId === backend.backendId ? 'is-selected' : ''}><td data-label="Compare"><input type="checkbox" aria-label={`Compare ${backend.label}`} checked={compare.includes(backend.backendId)} onChange={(event) => setCompare((current) => event.target.checked ? [...current, backend.backendId] : current.filter((id) => id !== backend.backendId))} /></td><th scope="row" data-label="Backend / host"><button type="button" className="fleet-register-name" aria-expanded={expandedBackendId === backend.backendId} onClick={() => setExpandedBackendId((current) => current === backend.backendId ? null : backend.backendId)}><span aria-hidden="true">{expandedBackendId === backend.backendId ? '−' : '+'}</span><span><strong>{backend.label}</strong><small>{backend.backendId} · {backend.isLocal ? 'LOCAL' : backend.hostname}</small></span></button></th><td data-label="State"><StateBadge state={backend.health} /></td><td data-label="Worker load"><div className="fleet-register-load"><strong>{backend.activeWorkers}<small> / {backend.maxWorkers || '—'}</small></strong><LoadMeter value={backend.activeWorkers / Math.max(backend.maxWorkers, 1) * 100} label={`${backend.label} worker load`} /></div></td><td data-label="Version"><code>{backend.version}</code></td><td data-label="Heartbeat" className={backend.health === 'offline' ? 'fleet-register-text-offline' : ''}>{formatAge(backend.heartbeatAge)}</td><td data-label="Config"><button type="button" className="fleet-register-link" onClick={() => setEditingBackendId(backend.backendId)}>Open ↗</button></td><td data-label="Inspect"><button type="button" className="fleet-register-icon-button" aria-label={`Inspect ${backend.label}`} aria-haspopup="dialog" title={`Inspect ${backend.label}`} onClick={() => handleInspectBackend(backend.backendId)}>↗</button></td></tr>{expandedBackendId === backend.backendId && <BackendExpansion backend={backend} onConfigure={setEditingBackendId} clusters={clustersQuery.data} />}</Fragment>)}</tbody></>}
        {tab === 'workers' && <><thead><tr><th scope="col">Worker ID</th><th scope="col">Owner</th><th scope="col">State</th><th scope="col">Current job / task</th><th scope="col">Tasks completed</th><th scope="col">Inspect</th></tr></thead><tbody>{filteredWorkers.map(({ worker, owner }) => <tr key={worker.workerId}><th scope="row" data-label="Worker ID"><code>{worker.workerId}</code></th><td data-label="Owner">{owner.label}</td><td data-label="State"><StateBadge state={worker.status} /></td><td data-label="Current job / task"><code>{worker.currentJob ?? '—'}</code></td><td data-label="Tasks completed">{worker.jobsCompleted.toLocaleString()}</td><td data-label="Inspect"><button type="button" className="fleet-register-icon-button" aria-label={`Inspect ${worker.workerId}`} aria-haspopup="dialog" title={`Inspect ${worker.workerId}`} onClick={() => handleInspectWorker(owner.backendId, worker.workerId)}>↗</button></td></tr>)}</tbody></>}
        {tab === 'clients' && (
          <>
            <thead>
              <tr>
                <th scope="col">Client / Device</th>
                <th scope="col">IP Address</th>
                <th scope="col">State</th>
                <th scope="col">Connected</th>
                <th scope="col">Last Active</th>
                <th scope="col">Session</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredClients.map((client) => {
                const ageSeconds = Math.max(0, Math.round((now - client.last_seen * 1000) / 1000));
                const connectedSeconds = Math.max(0, Math.round((now - client.created_at * 1000) / 1000));
                const isActive = ageSeconds < 300;
                return (
                  <tr key={client.id} className={client.is_current ? 'is-selected' : ''}>
                    <th scope="row" data-label="Client / Device">
                      <span className="fleet-client-name">
                        <strong>{client.device_info}</strong>
                        <small title={client.user_agent}>{client.user_agent || 'Unknown browser'}</small>
                      </span>
                    </th>
                    <td data-label="IP Address">
                      <code>{client.ip_address || '—'}</code>
                      {client.is_local && (
                        <span className="fleet-register-inline-badge" title="Local network or loopback address">
                          LOCAL
                        </span>
                      )}
                    </td>
                    <td data-label="State">
                      <StateBadge
                        state={isActive ? 'healthy' : 'idle'}
                        label={isActive ? 'Active' : 'Idle'}
                      />
                    </td>
                    <td data-label="Connected">{formatAge(connectedSeconds)}</td>
                    <td data-label="Last Active">{formatAge(ageSeconds)}</td>
                    <td data-label="Session">
                      <code>{client.id}</code>
                      {client.is_current && (
                        <span className="fleet-current-pill" title="This browser session">
                          This device
                        </span>
                      )}
                    </td>
                    <td data-label="Actions">
                      <button
                        type="button"
                        className="fleet-register-button fleet-register-button--compact"
                        title={client.is_current ? 'Sign out this device' : `Disconnect ${client.device_info}`}
                        onClick={() =>
                          setConfirmDisconnectSession({
                            id: client.id,
                            isCurrent: client.is_current,
                            device: client.device_info,
                          })
                        }
                      >
                        {client.is_current ? 'Sign out' : 'Disconnect'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </>
        )}
        {tab === 'mounts' && <><thead><tr><th scope="col">Mount / device</th><th scope="col">Owner</th><th scope="col">State</th><th scope="col">Capacity used</th><th scope="col">Free / total</th><th scope="col">Directories</th><th scope="col">Policy</th></tr></thead><tbody>
          {assignedMounts.length > 0 && <>
            {renderDividerRow('assigned', assignedMounts.length, collapsedSections.assigned)}
            {!collapsedSections.assigned && assignedMounts.map(renderMountRow)}
          </>}
          {unassignedMounts.length > 0 && <>
            {renderDividerRow('unassigned', unassignedMounts.length, collapsedSections.unassigned)}
            {!collapsedSections.unassigned && unassignedMounts.map(renderMountRow)}
          </>}
          {assignedMounts.length === 0 && unassignedMounts.length > 0 && <tr className="fleet-register-divider-row fleet-register-divider-row--empty"><td colSpan={7} className="fleet-register-divider-empty-cell"><span className="fleet-register-divider-badge fleet-register-divider-badge--assigned">Assigned</span><span className="fleet-register-divider-desc">No assigned mounts configured.</span></td></tr>}
          {unassignedMounts.length === 0 && assignedMounts.length > 0 && query.trim() === '' && filter === 'all' && <tr className="fleet-register-divider-row fleet-register-divider-row--empty"><td colSpan={7} className="fleet-register-divider-empty-cell"><span className="fleet-register-divider-badge fleet-register-divider-badge--unassigned">Unassigned</span><span className="fleet-register-divider-desc">All discovered mounts have assigned directories.</span></td></tr>}
        </tbody></>}
        {tab === 'database' && <>
          <thead>
            <tr>
              <th scope="col">Site / Schema</th>
              <th scope="col">Server & Host</th>
              <th scope="col">State</th>
              <th scope="col">Size</th>
              <th scope="col">Tables / Rows</th>
              <th scope="col">Dead Tuples / Bloat</th>
              <th scope="col">Operations</th>
              <th scope="col">Inspect</th>
            </tr>
          </thead>
          <tbody>
            {filteredDatabases.map((db) => {
              const isExpanded = expandedDatabaseSite === db.site;
              const totalRows = db.tables.reduce((acc, t) => acc + t.live_tuples, 0);
              const hasWarning = db.bloat_percent > 10 || db.total_dead_tuples > 10000;
              const isRowPending =
                (effectiveDatabaseOp?.site === 'all' ||
                  effectiveDatabaseOp?.site === db.site) &&
                !effectiveDatabaseOp.table;
              const isRowVacuuming = isRowPending && effectiveDatabaseOp?.type === 'vacuum';
              const isRowAnalyzing = isRowPending && effectiveDatabaseOp?.type === 'analyze';
              const isRowReindexing = isRowPending && effectiveDatabaseOp?.type === 'reindex';
              const isAnyOpPending = Boolean(effectiveDatabaseOp);

              return (
                <Fragment key={db.site}>
                  <tr
                    id={`fleet-database-${encodeURIComponent(db.site)}`}
                    className={isExpanded ? 'is-selected' : ''}
                  >
                    <th scope="row" data-label="Site / Schema">
                      <button
                        type="button"
                        className="fleet-register-name"
                        aria-expanded={isExpanded}
                        onClick={() =>
                          setExpandedDatabaseSite((curr) =>
                            curr === db.site ? null : db.site,
                          )
                        }
                      >
                        <span aria-hidden="true">{isExpanded ? '−' : '+'}</span>
                        <span>
                          <strong>{db.site}</strong>
                          <small>
                            {db.database_name} · {db.schema_name}
                          </small>
                        </span>
                      </button>
                    </th>
                    <td data-label="Server & Host">
                      <code>
                        {databaseQuery.data?.server_version
                          ? `PostgreSQL ${databaseQuery.data.server_version.split(' ')[1] || ''}`.trim()
                          : 'PostgreSQL'}
                      </code>
                      <small style={{ display: 'block', color: 'var(--color-muted)' }}>
                        {db.host}
                        {db.port ? `:${db.port}` : ''}
                      </small>
                    </td>
                    <td data-label="State">
                      <StateBadge
                        state={db.status}
                        label={
                          db.status === 'healthy'
                            ? 'Healthy'
                            : db.status === 'warning'
                              ? 'Needs vacuum'
                              : 'Offline'
                        }
                      />
                    </td>
                    <td data-label="Size">
                      <strong>{db.total_size_pretty || formatBytes(db.total_size_bytes)}</strong>
                    </td>
                    <td data-label="Tables / Rows">
                      <strong>{db.tables.length} tables</strong>
                      <small
                        style={{ display: 'block', color: 'var(--color-muted)' }}
                        title={db.row_counts_estimated ? ROW_ESTIMATE_TITLE : undefined}
                      >
                        {formatRowCount(totalRows, db.row_counts_estimated)}{' '}
                        {db.row_counts_estimated ? 'rows (estimate)' : 'live rows'}
                      </small>
                    </td>
                    <td data-label="Dead Tuples / Bloat">
                      <span className={hasWarning ? 'database-dead-warning' : ''}>
                        <strong>{db.total_dead_tuples.toLocaleString()} dead</strong>
                        <small style={{ display: 'block' }}>
                          {db.bloat_percent}% bloat
                        </small>
                      </span>
                    </td>
                    <td data-label="Operations">
                      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                        <button
                          type="button"
                          className={`fleet-register-button fleet-register-button--compact${isRowVacuuming ? ' is-busy' : ''}`}
                          disabled={isAnyOpPending}
                          onClick={() =>
                            setVacuumModalState({ isOpen: true, site: db.site })
                          }
                        >
                          {isRowVacuuming && (
                            <span className="database-op-spinner" aria-hidden="true" />
                          )}
                          {isRowVacuuming ? 'Vacuuming…' : 'Vacuum'}
                        </button>
                        <button
                          type="button"
                          className={`fleet-register-button fleet-register-button--compact${isRowAnalyzing ? ' is-busy' : ''}`}
                          disabled={isAnyOpPending}
                          onClick={() => analyzeMutation.mutate({ site: db.site })}
                        >
                          {isRowAnalyzing && (
                            <span className="database-op-spinner" aria-hidden="true" />
                          )}
                          {isRowAnalyzing ? 'Analyzing…' : 'Analyze'}
                        </button>
                        <button
                          type="button"
                          className={`fleet-register-button fleet-register-button--compact${isRowReindexing ? ' is-busy' : ''}`}
                          disabled={isAnyOpPending}
                          onClick={() => reindexMutation.mutate({ site: db.site })}
                        >
                          {isRowReindexing && (
                            <span className="database-op-spinner" aria-hidden="true" />
                          )}
                          {isRowReindexing ? 'Reindexing…' : 'Reindex'}
                        </button>
                      </div>
                    </td>
                    <td data-label="Inspect">
                      <button
                        type="button"
                        className="fleet-register-icon-button"
                        aria-label={`Inspect ${db.site} database`}
                        aria-haspopup="dialog"
                        title={`Inspect ${db.site}`}
                        onClick={() => setInspectedDatabaseSite(db.site)}
                      >
                        ↗
                      </button>
                    </td>
                  </tr>
                  {isExpanded && (
                    <DatabaseExpansion
                      database={db}
                      onInspect={(d) => setInspectedDatabaseSite(d.site)}
                      onVacuum={(s) => setVacuumModalState({ isOpen: true, site: s })}
                      isVacuuming={isRowVacuuming}
                      disabled={isAnyOpPending}
                    />
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </>}
      </table>{!count && !registerLoading && <div className="fleet-register-empty">No matching {tab}. Try another search or state.</div>}</div>)}
      <footer className="fleet-register-footer"><span>Observed snapshot · {new Date(now).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span><span>Shared queue counted once · offline records retained for inspection</span></footer>
      <div className="fleet-register-notes"><div><strong>Observed vs configured</strong><p>Worker load and heartbeat are live observations. Configuration opens the backend-scoped settings workflow.</p></div><div><strong>One shared queue</strong><p>Pending jobs come from the local queue endpoint and are not added once per backend row.</p></div><div><strong>Offline is still useful</strong><p>Cached identity, version, assignments, and last heartbeat remain inspectable while capacity is marked unavailable.</p></div></div>
    </section>
    {selectedDrive && settingsQuery.data && drivesQuery.data && <DriveConfigModal drive={selectedDrive} backendId={drivesQuery.data.backend_id} settings={settingsQuery.data} onClose={() => setSelectedDrive(null)} onAddDirectory={handleAddDirectory} onRemoveDirectory={handleRemoveDirectory} onUpdateDirectoryConfig={handleUpdateDirectoryConfig} onSaveSettings={handleSaveSettings} onRefreshDrive={refreshSelectedDrive} />}
    {editingBackendId && <RemoteConfigModal backendId={editingBackendId} onClose={() => setEditingBackendId(null)} />}
    <RestartRuntimeModal
      isOpen={confirmPower === 'restart'}
      isPending={powerMutation.isPending}
      onClose={() => setConfirmPower(null)}
      onConfirm={(targets) => {
        powerMutation.mutate({ action: 'restart', targets });
        setConfirmPower(null);
      }}
    />
    <ConfirmDialog
      isOpen={confirmPower === 'shutdown'}
      title={POWER_COPY.shutdown.title}
      description={POWER_COPY.shutdown.description}
      confirmLabel={POWER_COPY.shutdown.button}
      tone="danger"
      isPending={powerMutation.isPending}
      onClose={() => setConfirmPower(null)}
      onConfirm={() => {
        powerMutation.mutate({ action: 'shutdown' });
        setConfirmPower(null);
      }}
    />
    <ConfirmDialog
      isOpen={confirmDisconnectSession !== null}
      title={
        confirmDisconnectSession?.isCurrent
          ? 'Sign out of WebUI?'
          : `Disconnect ${confirmDisconnectSession?.device ?? 'client'}?`
      }
      description={
        confirmDisconnectSession?.isCurrent
          ? 'This will end your current session and require you to sign in again.'
          : 'This will revoke this client’s session. That browser will immediately lose access and must sign in again.'
      }
      confirmLabel={confirmDisconnectSession?.isCurrent ? 'Sign out' : 'Disconnect client'}
      tone="danger"
      isPending={revokeClientMutation.isPending}
      onClose={() => setConfirmDisconnectSession(null)}
      onConfirm={() => {
        if (confirmDisconnectSession) {
          revokeClientMutation.mutate(confirmDisconnectSession.id);
        }
      }}
    />
    {inspectTarget?.kind === 'backend' && inspectedBackend && (
      <BackendInspection
        backend={inspectedBackend}
        onClose={() => setInspectTarget(null)}
        onInspectWorker={(workerId) => handleInspectWorker(inspectedBackend.backendId, workerId)}
        deployments={deploymentsQuery.data ?? []}
        clusters={clustersQuery.data}
        onDeploymentChanged={() => {
          void deploymentsQuery.refetch();
          void allBackendsQuery.refetch();
          void backendQuery.refetch();
        }}
      />
    )}
    {inspectTarget?.kind === 'worker' && inspectedBackend && inspectedWorker && <WorkerInspection worker={inspectedWorker} owner={inspectedBackend} onClose={() => setInspectTarget(null)} onInspectBackend={() => setInspectTarget({ kind: 'backend', backendId: inspectedBackend.backendId })} />}
    {vacuumModalState?.isOpen && (
      <DatabaseVacuumModal
        site={vacuumModalState.site}
        tableName={vacuumModalState.table}
        isOpen={vacuumModalState.isOpen}
        isPending={vacuumMutation.isPending}
        onClose={() => setVacuumModalState(null)}
        onConfirm={(req) => {
          vacuumMutation.mutate(req);
          setVacuumModalState(null);
        }}
      />
    )}
    {inspectedDatabase && (
      <DatabaseInspectionModal
        database={inspectedDatabase}
        serverVersion={databaseQuery.data?.server_version}
        pendingOp={effectiveDatabaseOp}
        statusNotice={databaseResultNotice}
        onClose={() => setInspectedDatabaseSite(null)}
        onVacuumTable={(site, table) =>
          setVacuumModalState({ isOpen: true, site, table })
        }
        onAnalyzeTable={(site, table) => analyzeMutation.mutate({ site, table })}
        onReindexTable={(site, table) => reindexMutation.mutate({ site, table })}
      />
    )}
  </div>;
}
