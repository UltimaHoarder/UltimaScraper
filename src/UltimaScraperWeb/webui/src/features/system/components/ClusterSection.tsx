import { useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { BackendClusters } from '../../../api/webui';
import type { DatabaseOverview } from '../../../api/types/system';
import type { SettingsResponse } from '../../../api/types/settings';
import { formatBytes } from '../../../shared/lib/format';
import { followInApp } from '../../connections/lib/navigation';
import { nodeLink } from '../../connections/lib/clusterView';
import { getActiveConnectionId } from '../../../api/http';
import {
  connectionHome,
  getClusterHosts,
  getConnectionTicket,
  listClusterClients,
  revokeClusterClient,
  setMainCluster,
  type ClusterClient,
  type ClusterHost,
} from '../../../api/webui';
import { AddHostModal } from './AddHostModal';
import { ClusterHostsTable } from './ClusterHostsTable';
import { ArchitectureModal } from './ArchitectureModal';
import { ClusterItem } from './ClusterItem';
import { EditHostModal } from './EditHostModal';
import { ManageClusterModal } from './ManageClusterModal';
import type {
  RegisterBackend,
  RegisterHealth,
  RegisterWorker,
  RegisterWorkerState,
} from '../systemFleetRegisterData';
import { ClusterUpgradeModal } from './ClusterUpgradeModal';
import { summarizeStoragePool } from '../lib/storagePool';
import './ClusterSection.css';
import { copyText } from '../../../utils/clipboard';

export interface AvailableCluster {
  clusterId: string;
  nodeCount: number;
  connectionId?: string | null;
  label?: string;
  isCurrent?: boolean;
}

interface ClusterSectionProps {
  backends: RegisterBackend[];
  clusterId: string | null;
  availableClusters?: AvailableCluster[];
  onSelectCluster?: (clusterId: string, connectionId?: string | null) => void;
  clustersData: BackendClusters | undefined;
  databases: DatabaseOverview[];
  settingsData: SettingsResponse | undefined;
  serverVersion?: string | null;
  isRedisConnected?: boolean;
  onConfigureBackend: (backendId: string) => void;
  onInspectBackend: (backendId: string) => void;
  onInspectWorker: (backendId: string, workerId: string) => void;
  onNavigateToTab: (tab: 'backends' | 'workers' | 'mounts' | 'database') => void;
  onNodeAdded?: () => void;
}

function stateLabel(state: RegisterHealth | RegisterWorkerState): string {
  return state === 'healthy'
    ? 'Healthy'
    : state === 'running'
      ? 'Running'
      : state === 'idle'
        ? 'Idle'
        : state === 'warning'
          ? 'Needs attention'
          : 'Offline';
}

function StateBadge({
  state,
  label,
}: {
  state: RegisterHealth | RegisterWorkerState;
  label?: string;
}) {
  return (
    <span className={`fleet-register-state fleet-register-state--${state}`}>
      <i aria-hidden="true" />
      {label ?? stateLabel(state)}
    </span>
  );
}

function LoadMeter({ value, label }: { value: number; label: string }) {
  const boundedValue = Math.min(100, Math.max(0, value));
  return (
    <div
      className="fleet-register-meter"
      role="meter"
      aria-label={label}
      aria-valuenow={Number(boundedValue.toFixed(1))}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <i style={{ width: `${boundedValue}%` }} />
    </div>
  );
}

function formatAge(age: number | null): string {
  if (age === null) return 'Unknown';
  if (age < 5) return 'Just now';
  if (age < 60) return `${age}s ago`;
  return `${Math.floor(age / 60)}m ago`;
}

function NodeConnectionLink({
  backendId,
  clusters,
}: {
  backendId: string;
  clusters: BackendClusters | undefined;
}) {
  if (!clusters) return null;
  const link = nodeLink(backendId, clusters);
  if (link.kind === 'open') {
    if (link.connectionId === getActiveConnectionId()) return null;
    return (
      <a
        className="fleet-register-link"
        href={connectionHome(link.connectionId)}
        onClick={(event) => followInApp(event, connectionHome(link.connectionId))}
      >
        Open this backend ↗
      </a>
    );
  }
  return null;
}

function WorkerCells({ workers, label }: { workers: RegisterWorker[]; label: string }) {
  if (workers.length === 0)
    return <p className="fleet-register-muted">No worker records returned for this backend.</p>;
  return (
    <div className="fleet-register-worker-cells" aria-label={`${label} worker states`}>
      {workers.map((worker, index) => (
        <span
          className={`fleet-register-worker-cell fleet-register-worker-cell--${worker.status}`}
          key={worker.workerId}
          title={`${worker.workerId}: ${stateLabel(worker.status)}`}
        >
          {String(index + 1).padStart(2, '0')}
        </span>
      ))}
    </div>
  );
}

export function ClusterSection({
  backends,
  clusterId,
  availableClusters = [],
  onSelectCluster,
  clustersData,
  databases,
  settingsData,
  serverVersion,
  isRedisConnected = true,
  onConfigureBackend,
  onInspectBackend,
  onInspectWorker,
  onNavigateToTab,
  onNodeAdded,
}: ClusterSectionProps) {
  const [copiedNodeId, setCopiedNodeId] = useState<string | null>(null);
  const [nodeTicketError, setNodeTicketError] = useState<string | null>(null);
  const [nodeTicketWarning, setNodeTicketWarning] = useState<string | null>(null);
  const [expandedBackendId, setExpandedBackendId] = useState<string | null>(null);
  // Which clusters are expanded; until one is toggled, the main one (or the first).
  const [expanded, setExpanded] = useState<Set<string> | null>(null);
  const [manageFor, setManageFor] = useState<string | null>(null);
  const [addHostFor, setAddHostFor] = useState<string | null>(null);
  const [upgradeFor, setUpgradeFor] = useState<string | null>(null);
  const [editHost, setEditHost] = useState<ClusterHost | null>(null);
  const [architectureOpen, setArchitectureOpen] = useState(false);
  const { clients: webuis, checkedAt: now } = useClusterWebUIs(clusterId);
  const queryClient = useQueryClient();
  const hostsQuery = useQuery({
    queryKey: ['webui', 'cluster-hosts', clusterId],
    queryFn: () => getClusterHosts(clusterId as string),
    enabled: Boolean(clusterId),
    refetchInterval: 15_000,
    // Without the WebUI server (a backend opened directly) the node table stays.
    retry: false,
  });
  const mainClusterId = clustersData?.main_cluster_id ?? null;
  const makeMain = useMutation({
    mutationFn: (target: string | null) => setMainCluster(target),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['webui', 'clusters'] }),
  });

  const handleCopyNodeTicket = async (backend: RegisterBackend) => {
    try {
      setNodeTicketError(null);
      const member = clustersData?.members.find((m) => m.identity?.backend_id === backend.backendId);
      const targetId =
        member?.connection_id ?? (backend.isLocal ? (getActiveConnectionId() ?? 'default') : backend.backendId);
      const res = await getConnectionTicket(targetId);
      await copyText(res.ticket);
      setNodeTicketWarning(res.warning);
      setCopiedNodeId(backend.backendId);
      setTimeout(() => setCopiedNodeId((curr) => (curr === backend.backendId ? null : curr)), 2500);
    } catch (err) {
      setNodeTicketError(err instanceof Error ? err.message : 'Could not export ticket for node.');
    }
  };


  const clusterBackends = backends.filter(
    (b) => !clusterId || b.clusterId === clusterId || (!b.clusterId && b.isLocal),
  );

  const totalWorkers = clusterBackends.reduce(
    (acc, b) => acc + (b.maxWorkers || b.workers.length),
    0,
  );
  const activeWorkers = clusterBackends.reduce((acc, b) => acc + b.activeWorkers, 0);
  const totalPendingJobs = clusterBackends.reduce(
    (acc, b) => Math.max(acc, b.pendingJobs),
    0,
  );
  const storagePool = summarizeStoragePool(clusterBackends.flatMap((b) => b.mounts));
  const { totalBytes: totalStorageBytes, usedBytes: usedStorageBytes, freeBytes: freeStorageBytes } = storagePool;
  const storagePercent =
    totalStorageBytes > 0 ? (usedStorageBytes / totalStorageBytes) * 100 : 0;

  const primaryDb = databases[0];
  const dbHost = primaryDb ? `${primaryDb.host}${primaryDb.port ? `:${primaryDb.port}` : ''}` : null;
  const dbName = primaryDb?.database_name ?? 'ultima_archive';

  const redisHost = settingsData?.redis?.host
    ? `${settingsData.redis.host}:${settingsData.redis.port ?? 6379}`
    : null;

  const clusterDetails = clustersData?.clusters?.find((c) => c.cluster_id === clusterId);
  const conflictingBackendIds = clusterDetails?.conflicting_backend_ids ?? [];

  const hosts = hostsQuery.data?.hosts ?? null;
  // A backend with a database is always in a cluster, if only of one host.
  const clusterTitle =
    hostsQuery.data?.name ??
    clusterDetails?.name ??
    (clusterId ? `Cluster ${clusterId.slice(0, 8)}` : 'Not in a cluster yet');



  // Every cluster this WebUI manages; the one this page was opened on shows in full.
  const listed: { clusterId: string; label?: string; connectionId?: string | null }[] = availableClusters.length
    ? availableClusters
    : clusterId
      ? [{ clusterId }]
      : [];
  if (clusterId && !listed.some((item) => item.clusterId === clusterId)) listed.unshift({ clusterId });
  const items = listed.map((item) => {
    const known = clustersData?.clusters.find((entry) => entry.cluster_id === item.clusterId);
    return {
      clusterId: item.clusterId,
      name:
        item.clusterId === clusterId
          ? clusterTitle
          : known?.name || item.label || `Cluster ${item.clusterId.slice(0, 8)}`,
      connectionId: item.connectionId ?? known?.connection_ids[0] ?? null,
      isActive: item.clusterId === clusterId,
    };
  });
  const firstOpen = items.find((item) => item.clusterId === mainClusterId)?.clusterId ?? items[0]?.clusterId;
  const openClusters = expanded ?? new Set(firstOpen ? [firstOpen] : []);
  const toggle = (id: string) => {
    const next = new Set(openClusters);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setExpanded(next);
  };
  const itemFor = (id: string | null) => items.find((item) => item.clusterId === id) ?? null;
  const connectionFor = (id: string) =>
    id === clusterId
      ? (hostsQuery.data?.answered_by ??
        clusterDetails?.connection_ids.find((connection) => connection === getActiveConnectionId()) ??
        clusterDetails?.connection_ids[0] ??
        getActiveConnectionId())
      : (itemFor(id)?.connectionId ?? null);

  const body = (
    <>
      {/* High-Density KPI Telemetry Bar */}
        <div className="cluster-telemetry-bar">
          <div className="cluster-telemetry-item">
            <span className="cluster-telemetry-label">Total Worker Capacity</span>
            <div className="cluster-telemetry-value">
              <strong>{totalWorkers}</strong>
              <small>workers pool</small>
            </div>
            <div className="cluster-telemetry-meter">
              <LoadMeter
                value={totalWorkers > 0 ? (activeWorkers / totalWorkers) * 100 : 0}
                label="Cluster worker load"
              />
            </div>
            <span className="cluster-telemetry-sub">
              {activeWorkers} active · {Math.max(0, totalWorkers - activeWorkers)} idle
            </span>
          </div>
  
          <div className="cluster-telemetry-item">
            <span className="cluster-telemetry-label">Distributed Queue</span>
            <div className="cluster-telemetry-value">
              <strong>{totalPendingJobs}</strong>
              <small>pending tasks</small>
            </div>
            <span className="cluster-telemetry-sub">
              across the cluster
            </span>
          </div>
  
          <div className="cluster-telemetry-item">
            <span className="cluster-telemetry-label">Cluster Storage Pool</span>
            <div className="cluster-telemetry-value">
              <strong>{formatBytes(totalStorageBytes)}</strong>
              <small>total capacity</small>
            </div>
            <div className="cluster-telemetry-meter">
              <LoadMeter value={storagePercent} label="Cluster storage load" />
            </div>
            <span className="cluster-telemetry-sub">
              {formatBytes(usedStorageBytes)} used · {formatBytes(freeStorageBytes)} free ({storagePercent.toFixed(1)}%)
            </span>
            <span className="cluster-telemetry-sub" title="A disk or export mounted more than once counts once; NAS datasets sharing a pool count its free space once.">
              {storagePool.mountCount} mounts · {storagePool.storageCount} distinct disks or pools
            </span>
          </div>
        </div>
  
        {/* PostgreSQL and Redis are nodes in the hosts list; this is for a backend opened directly. */}
        {!hosts && (
        <div className="cluster-backbone-panel">
          <div className="cluster-backbone-header">
            <span className="cluster-header-kicker">Cluster Shared Backbones</span>
            <h3 className="cluster-backbone-title">Shared Services &amp; Network Datastores</h3>
          </div>
  
          <div className="cluster-backbone-grid">
            {/* PostgreSQL Card */}
            <div className="cluster-backbone-card">
              <div className="cluster-backbone-card-top">
                <div className="cluster-backbone-card-identity">
                  <span className="cluster-backbone-card-tag">RDBMS</span>
                  <div>
                    <strong>PostgreSQL Archive Database</strong>
                    <small>
                      {serverVersion
                        ? serverVersion.split(' ')[0] + ' ' + (serverVersion.split(' ')[1] || '')
                        : 'PostgreSQL 18+'}
                    </small>
                  </div>
                </div>
                <StateBadge state="healthy" label="Operational" />
              </div>
  
              <div className="cluster-backbone-specs">
                <div className="cluster-spec-line">
                  <span>Database Host</span>
                  <code>{dbHost ?? '—'}</code>
                </div>
                <div className="cluster-spec-line">
                  <span>Database Name</span>
                  <code>{dbName}</code>
                </div>
              </div>
  
              <div className="cluster-backbone-card-footer">
                <button
                  type="button"
                  className="fleet-register-link cluster-backbone-action"
                  onClick={() => onNavigateToTab('database')}
                >
                  Inspect database tables &amp; bloat ↗
                </button>
              </div>
            </div>
  
            {/* Redis Card */}
            <div className="cluster-backbone-card">
              <div className="cluster-backbone-card-top">
                <div className="cluster-backbone-card-identity">
                  <span className="cluster-backbone-card-tag cluster-backbone-card-tag--redis">BROKER</span>
                  <div>
                    <strong>Redis Distributed Broker</strong>
                    <small>Pub/Sub &amp; Key-Value Broker</small>
                  </div>
                </div>
                <StateBadge
                  state={isRedisConnected ? 'healthy' : 'offline'}
                  label={isRedisConnected ? 'Connected' : 'Disconnected'}
                />
              </div>
  
              <div className="cluster-backbone-specs">
                <div className="cluster-spec-line">
                  <span>Redis Host</span>
                  <code>{redisHost ?? '—'}</code>
                </div>
                <div className="cluster-spec-line">
                  <span>Scaling Pub/Sub</span>
                  <code>ultimascraper:config:events</code>
                </div>
              </div>
  
              <div className="cluster-backbone-card-footer">
                <span className="cluster-backbone-status-text">
                  Real-time events: <strong>Active</strong>
                </span>
              </div>
            </div>
          </div>
        </div>
        )}
  
        {/* Suggested or Conflicting Nodes Warnings */}
        {conflictingBackendIds.length > 0 && (
          <div className="cluster-alert cluster-alert--warning" role="alert">
            <strong>Backend ID Collision Detected:</strong> More than one node uses{' '}
            <code>{conflictingBackendIds.join(', ')}</code>. Each node must have a unique identifier.
          </div>
        )}
        {nodeTicketError && (
          <div className="cluster-alert cluster-alert--warning" role="alert">
            <strong>Could not export connection ticket:</strong> {nodeTicketError}
          </div>
        )}
        {nodeTicketWarning && (
          <div className="cluster-alert cluster-alert--warning" role="status">
            <strong>Ticket copied, but</strong> {nodeTicketWarning}
          </div>
        )}
  
        {makeMain.isError && (
          <div className="cluster-alert cluster-alert--warning" role="alert">
            <strong>Could not change the main cluster:</strong>{' '}
            {makeMain.error instanceof Error ? makeMain.error.message : 'it did not answer.'}
          </div>
        )}
  
        {hostsQuery.data ? (
          <div className="cluster-nodes-panel">
            <div className="fleet-register-panel-header">
              <div>
                <span className="fleet-register-kicker">Machines</span>
                <h3>Hosts ({hostsQuery.data.hosts.length})</h3>
              </div>
              <span className="fleet-register-panel-meta">
                Expand a host for its nodes: backend, workers, WebUI, PostgreSQL, Redis
              </span>
            </div>
            {hostsQuery.data.error && (
              <div className="cluster-alert cluster-alert--warning" role="status">
                {hostsQuery.data.error} Showing what this WebUI installed.
              </div>
            )}
            <ClusterHostsTable
              hosts={hostsQuery.data.hosts}
              onInspectDatabase={() => onNavigateToTab('database')}
              onConfigureBackend={onConfigureBackend}
              onInspectBackend={onInspectBackend}
              onRenamed={() => void hostsQuery.refetch()}
              onEditHost={setEditHost}
              onRemoveWebUI={(node) => {
                if (!clusterId || !node.client_id) return;
                if (!window.confirm(`${node.name} will lose access to ${clusterTitle}. Remove it?`)) return;
                void revokeClusterClient(clusterId, node.client_id).then(() => hostsQuery.refetch());
              }}
            />
          </div>
        ) : (
        /* Cluster Nodes Fleet Table */
        <div className="cluster-nodes-panel">
          <div className="fleet-register-panel-header">
            <div>
              <span className="fleet-register-kicker">Member Hardware</span>
              <h3>
                Cluster Fleet Nodes ({clusterBackends.length})
                {webuis.length > 0 && ` · WebUIs (${webuis.length})`}
              </h3>
            </div>
            <span className="fleet-register-panel-meta">
              Hardware-specific configurations &amp; allocations
            </span>
          </div>
  
          <div className="fleet-register-table-scroll">
            <table className="fleet-register-table cluster-nodes-table">
              <thead>
                <tr>
                  <th scope="col">Node / Hostname</th>
                  <th scope="col">Role</th>
                  <th scope="col">State</th>
                  <th scope="col">Worker Allocation</th>
                  <th scope="col">Storage Pool</th>
                  <th scope="col">Heartbeat</th>
                  <th scope="col">Node Config</th>
                  <th scope="col">Inspect</th>
                </tr>
              </thead>
              <tbody>
                {clusterBackends.map((backend) => {
                  const isExpanded = expandedBackendId === backend.backendId;
                  const nodeWorkers = backend.maxWorkers || backend.workers.length;
                  const nodePool = summarizeStoragePool(backend.mounts);
  
                  return (
                    <ReactNodeFragment key={backend.backendId}>
                      <tr className={isExpanded ? 'is-selected' : ''}>
                        <th scope="row" data-label="Node / Hostname">
                          <button
                            type="button"
                            className="fleet-register-name"
                            aria-expanded={isExpanded}
                            onClick={() =>
                              setExpandedBackendId((curr) =>
                                curr === backend.backendId ? null : backend.backendId,
                              )
                            }
                          >
                            <span aria-hidden="true">{isExpanded ? '−' : '+'}</span>
                            <span>
                              <strong>{backend.label}</strong>
                              <small>
                                <code>{backend.backendId}</code> · {backend.isLocal ? 'LOCAL' : backend.hostname}
                              </small>
                            </span>
                          </button>
                        </th>
                        <td data-label="Role">
                          <span
                            className={`cluster-role-badge cluster-role-badge--${backend.isLocal ? 'primary' : 'worker'}`}
                          >
                            {backend.isLocal ? 'Control Plane + Worker' : 'Remote Worker'}
                          </span>
                        </td>
                        <td data-label="State">
                          <StateBadge state={backend.health} />
                        </td>
                        <td data-label="Worker Allocation">
                          <div className="fleet-register-load">
                            <strong>
                              {backend.activeWorkers}
                              <small> / {nodeWorkers || '—'} workers</small>
                            </strong>
                            <LoadMeter
                              value={
                                nodeWorkers > 0 ? (backend.activeWorkers / nodeWorkers) * 100 : 0
                              }
                              label={`${backend.label} worker load`}
                            />
                          </div>
                        </td>
                        <td data-label="Storage Pool">
                          <strong>{backend.mounts.length} drives</strong>
                          <small style={{ display: 'block', color: 'var(--color-text-tertiary)' }}>
                            {formatBytes(nodePool.freeBytes)} free / {formatBytes(nodePool.totalBytes)}
                          </small>
                        </td>
                        <td
                          data-label="Heartbeat"
                          className={backend.health === 'offline' ? 'fleet-register-text-offline' : ''}
                        >
                          {formatAge(backend.heartbeatAge)}
                        </td>
                        <td data-label="Node Config">
                          <button
                            type="button"
                            className="fleet-register-link"
                            onClick={() => onConfigureBackend(backend.backendId)}
                          >
                            Edit Config ↗
                          </button>
                        </td>
                        <td data-label="Inspect">
                          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                            <button
                              type="button"
                              className="fleet-register-icon-button"
                              aria-label={`Copy connection ticket for ${backend.label}`}
                              title={
                                copiedNodeId === backend.backendId
                                  ? '✓ Ticket copied to clipboard'
                                  : `Copy connection ticket for ${backend.label}`
                              }
                              onClick={() => void handleCopyNodeTicket(backend)}
                            >
                              {copiedNodeId === backend.backendId ? '✓' : '⎘'}
                            </button>
                            <button
                              type="button"
                              className="fleet-register-icon-button"
                              aria-label={`Inspect ${backend.label}`}
                              title={`Inspect ${backend.label}`}
                              onClick={() => onInspectBackend(backend.backendId)}
                            >
                              ↗
                            </button>
                          </div>
                        </td>
                      </tr>
  
                      {/* Compact Expanded details */}
                      {isExpanded && (
                        <tr className="fleet-register-expansion">
                          <td colSpan={8}>
                            <div className="fleet-register-expanded-grid">
                              <div>
                                <div className="fleet-register-row fleet-register-row--start">
                                  <h3>Workers on {backend.backendId}</h3>
                                  <StateBadge
                                    state={backend.health}
                                    label={backend.isLocal ? 'Local Control' : backend.status}
                                  />
                                </div>
                                <WorkerCells workers={backend.workers} label={backend.label} />
                                <div className="fleet-register-row fleet-register-muted">
                                  <span>
                                    {backend.activeWorkers} active of {nodeWorkers} configured
                                  </span>
                                  <span>
                                    {backend.workers
                                      .reduce((sum, w) => sum + w.jobsCompleted, 0)
                                      .toLocaleString()}{' '}
                                    tasks completed
                                  </span>
                                </div>
                                <div className="fleet-register-mini-ledger">
                                  {backend.workers.slice(0, 5).map((worker) => (
                                    <div className="fleet-register-row" key={worker.workerId}>
                                      <code>{worker.workerId}</code>
                                      <StateBadge state={worker.status} />
                                      <code>{worker.currentJob ?? 'No active task'}</code>
                                      <button
                                        type="button"
                                        className="fleet-register-icon-button"
                                        aria-label={`Inspect ${worker.workerId}`}
                                        title={`Inspect ${worker.workerId}`}
                                        onClick={() => onInspectWorker(backend.backendId, worker.workerId)}
                                      >
                                        ↗
                                      </button>
                                    </div>
                                  ))}
                                </div>
                                <div style={{ display: 'flex', gap: 12, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                                  <button
                                    type="button"
                                    className="fleet-register-link"
                                    onClick={() => onConfigureBackend(backend.backendId)}
                                  >
                                    Open backend configuration ↗
                                  </button>
                                  <NodeConnectionLink backendId={backend.backendId} clusters={clustersData} />
                                  <button
                                    type="button"
                                    className="fleet-register-link"
                                    onClick={() => void handleCopyNodeTicket(backend)}
                                  >
                                    {copiedNodeId === backend.backendId
                                      ? '✓ Connection ticket copied'
                                      : 'Copy connection ticket ⎘'}
                                  </button>
                                </div>
                              </div>
  
                              <div>
                                <div className="fleet-register-row fleet-register-row--start">
                                  <h3>Storage Mounts</h3>
                                  <span className="fleet-register-panel-meta">
                                    {backend.mounts.length} assigned
                                  </span>
                                </div>
                                <div className="fleet-register-mount-stack">
                                  {backend.mounts.length === 0 ? (
                                    <p className="fleet-register-muted">No mount records returned.</p>
                                  ) : (
                                    backend.mounts.map((mount) => (
                                      <div className="fleet-register-mount-summary" key={mount.id}>
                                        <div className="fleet-register-row">
                                          <strong>{mount.path}</strong>
                                          <small>{mount.device}</small>
                                        </div>
                                        <small>
                                          {formatBytes(mount.freeBytes)} free of{' '}
                                          {formatBytes(mount.totalBytes)} ({mount.percentUsed.toFixed(1)}% used)
                                        </small>
                                      </div>
                                    ))
                                  )}
                                </div>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </ReactNodeFragment>
                  );
                })}
                {webuis.map((client) => (
                  <tr key={`webui-${client.id}`}>
                    <th scope="row" data-label="Node / Hostname">
                      <span className="fleet-register-name">
                        <span aria-hidden="true" />
                        <span>
                          <strong>{client.name}</strong>
                          <small>
                            {client.is_self ? 'THIS WEBUI' : (client.last_address ?? 'Address unknown')}
                            {client.version ? ` · ${client.version}` : ''}
                          </small>
                        </span>
                      </span>
                    </th>
                    <td data-label="Role">
                      <span className="cluster-role-badge cluster-role-badge--client">WebUI · client</span>
                    </td>
                    <td data-label="State">
                      <StateBadge state={webuiState(client, now)} />
                    </td>
                    <td data-label="Worker Allocation">—</td>
                    <td data-label="Storage Pool">—</td>
                    <td data-label="Heartbeat">{formatAge(webuiAge(client, now))}</td>
                    <td data-label="Node Config">—</td>
                    <td data-label="Inspect">—</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        )}
    </>
  );

  return (
    <div className="cluster-section" aria-label="Clusters">
      <div className="clusters-page-header">
        <div className="cluster-header-titles">
          <span className="cluster-header-kicker">Infrastructure</span>
          <h2 className="cluster-header-title">Clusters</h2>
        </div>
        <div className="cluster-item-actions">
        <button
          type="button"
          className="fleet-register-button cluster-action-btn"
          onClick={() => setArchitectureOpen(true)}
        >
          Architecture
        </button>
        <a
          className={`fleet-register-button cluster-action-btn${items.length ? '' : ' fleet-register-button--primary'}`}
          href="/setup"
          title="Create another cluster, or join one another WebUI invited you to"
          onClick={(event) => followInApp(event, '/setup')}
        >
          Create or join a cluster
        </a>
        </div>
      </div>

      {items.length === 0 ? (
        body
      ) : (
        <div className="clusters-list">
          {items.map((item) => (
            <ClusterItem
              key={item.clusterId}
              clusterId={item.clusterId}
              name={item.name}
              isMain={item.clusterId === mainClusterId}
              open={openClusters.has(item.clusterId)}
              onToggle={() => toggle(item.clusterId)}
              onManage={() => setManageFor(item.clusterId)}
              onMakeMain={clustersData ? () => makeMain.mutate(item.clusterId) : undefined}
              onOpen={item.isActive ? undefined : () => onSelectCluster?.(item.clusterId, item.connectionId)}
              onEditHost={setEditHost}
              onConfigureBackend={item.isActive ? onConfigureBackend : () => onSelectCluster?.(item.clusterId, item.connectionId)}
              onInspectBackend={item.isActive ? onInspectBackend : () => onSelectCluster?.(item.clusterId, item.connectionId)}
              onInspectDatabase={item.isActive ? () => onNavigateToTab('database') : undefined}
            >
              {item.isActive ? body : undefined}
            </ClusterItem>
          ))}
        </div>
      )}

      {manageFor && (
        <ManageClusterModal
          clusterId={manageFor}
          clusterName={itemFor(manageFor)?.name ?? 'Cluster'}
          isMain={manageFor === mainClusterId}
          onMakeMain={() => {
            makeMain.mutate(manageFor);
            setManageFor(null);
          }}
          onAddHost={() => {
            setAddHostFor(manageFor);
            setManageFor(null);
          }}
          onUpgrade={() => {
            setUpgradeFor(manageFor);
            setManageFor(null);
          }}
          onClose={() => setManageFor(null)}
        />
      )}
      {addHostFor && (
        <AddHostModal
          clusterId={addHostFor}
          clusterName={itemFor(addHostFor)?.name ?? 'Cluster'}
          connectionId={connectionFor(addHostFor)}
          onClose={() => setAddHostFor(null)}
          onChanged={() => {
            onNodeAdded?.();
            void queryClient.invalidateQueries({ queryKey: ['webui', 'cluster-hosts'] });
          }}
        />
      )}
      {architectureOpen && <ArchitectureModal backends={clusterBackends} onClose={() => setArchitectureOpen(false)} />}
      {upgradeFor && <ClusterUpgradeModal clusterId={upgradeFor} onClose={() => setUpgradeFor(null)} />}
      {editHost && (
        <EditHostModal
          host={editHost}
          onClose={() => setEditHost(null)}
          onChanged={() => {
            onNodeAdded?.();
            void queryClient.invalidateQueries({ queryKey: ['webui', 'cluster-hosts'] });
          }}
        />
      )}
    </div>
  );
}

// A WebUI checks in every minute; three missed check-ins and it counts as gone.
const WEBUI_STALE_SECONDS = 180;

function webuiState(client: ClusterClient, now: number): RegisterHealth {
  if (client.revoked_at || !client.last_seen_at) return 'offline';
  return now - Date.parse(client.last_seen_at) > WEBUI_STALE_SECONDS * 1000 ? 'offline' : 'healthy';
}

function webuiAge(client: ClusterClient, now: number): number | null {
  return client.last_seen_at ? Math.max(0, Math.round((now - Date.parse(client.last_seen_at)) / 1000)) : null;
}

/** The WebUIs that joined the cluster: its clients, listed with its nodes. */
function useClusterWebUIs(clusterId: string | null): { clients: ClusterClient[]; checkedAt: number } {
  const query = useQuery({
    queryKey: ['webui', 'cluster-clients', clusterId],
    queryFn: () => listClusterClients(clusterId as string),
    enabled: Boolean(clusterId),
    refetchInterval: 30_000,
    // Backends from before cluster clients list none.
    retry: false,
  });
  return {
    clients: clusterId ? (query.data ?? []).filter((client) => !client.revoked_at) : [],
    checkedAt: query.dataUpdatedAt,
  };
}

function ReactNodeFragment({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
