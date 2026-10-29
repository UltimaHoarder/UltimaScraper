import { useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';

import { getClusterHosts, revokeClusterClient, type ClusterHost, type ClusterNode } from '../../../api/webui';
import { ClusterHostsTable } from './ClusterHostsTable';

/**
 * One cluster in the clusters list: its name, health and actions, and when
 * expanded its hosts. The cluster this page was opened on passes its fuller
 * view (telemetry, workers, storage) as children.
 */
export function ClusterItem({
  clusterId,
  name,
  isMain,
  open,
  onToggle,
  onManage,
  onMakeMain,
  onOpen,
  onEditHost,
  onConfigureBackend,
  onInspectBackend,
  onInspectDatabase,
  children,
}: {
  clusterId: string;
  name: string;
  isMain: boolean;
  open: boolean;
  onToggle: () => void;
  onManage: () => void;
  onMakeMain?: () => void;
  /** Switch the page to this cluster; absent for the one it shows. */
  onOpen?: () => void;
  onEditHost: (host: ClusterHost) => void;
  onConfigureBackend: (backendId: string) => void;
  onInspectBackend: (backendId: string) => void;
  onInspectDatabase?: () => void;
  children?: ReactNode;
}) {
  const [copied, setCopied] = useState(false);
  const hostsQuery = useQuery({
    queryKey: ['webui', 'cluster-hosts', clusterId],
    queryFn: () => getClusterHosts(clusterId),
    refetchInterval: 15_000,
    retry: false,
  });
  const hosts = hostsQuery.data?.hosts ?? null;
  const healthy = hosts?.filter((host) => host.state === 'healthy').length ?? 0;
  const state = !hosts
    ? 'unknown'
    : hosts.some((host) => host.state === 'offline')
      ? 'offline'
      : hosts.some((host) => host.state === 'warning')
        ? 'warning'
        : 'healthy';

  const removeWebUI = async (node: ClusterNode) => {
    if (!node.client_id || !window.confirm(`${node.name} will lose access to ${name}. Remove it?`)) return;
    await revokeClusterClient(clusterId, node.client_id);
    void hostsQuery.refetch();
  };

  const copyId = () => {
    void navigator.clipboard?.writeText(clusterId);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section className={`cluster-item${open ? ' is-open' : ''}`} aria-label={`Cluster ${name}`}>
      <div className="cluster-item-header">
        <button type="button" className="cluster-item-toggle" aria-expanded={open} onClick={onToggle}>
          <span aria-hidden="true">{open ? '−' : '+'}</span>
          <h3 className="cluster-item-title">{name}</h3>
        </button>
        <button type="button" className="cluster-id-pill" onClick={copyId} title={`Copy the cluster id ${clusterId}`}>
          <code>{clusterId.slice(0, 8)}</code>
          <span className="cluster-id-pill-action">{copied ? '✓ Copied' : '⎘ Copy'}</span>
        </button>
        {hosts && (
          <span className={`fleet-register-state fleet-register-state--${state === 'unknown' ? 'idle' : state}`}>
            <i aria-hidden="true" />
            {healthy} / {hosts.length} hosts healthy
          </span>
        )}
        {isMain ? (
          <span className="cluster-main-badge" title="This WebUI opens on this cluster">
            Main cluster
          </span>
        ) : (
          onMakeMain && (
            <button
              type="button"
              className="fleet-register-link"
              title="Open this WebUI on this cluster, for everyone who signs in"
              onClick={onMakeMain}
            >
              Make main
            </button>
          )
        )}
        <div className="cluster-item-actions">
          {onOpen && (
            <button type="button" className="fleet-register-button cluster-action-btn" onClick={onOpen}>
              Open
            </button>
          )}
          <button
            type="button"
            className="fleet-register-button fleet-register-button--primary cluster-action-btn"
            onClick={onManage}
          >
            Manage cluster
          </button>
        </div>
      </div>

      {open &&
        (children ?? (
          <div className="cluster-item-body">
            {hostsQuery.data?.error && <p className="connections-hint">{hostsQuery.data.error}</p>}
            {hosts ? (
              <ClusterHostsTable
                hosts={hosts}
                onConfigureBackend={onConfigureBackend}
                onInspectBackend={onInspectBackend}
                onInspectDatabase={onInspectDatabase}
                onRenamed={() => void hostsQuery.refetch()}
                onEditHost={onEditHost}
                onRemoveWebUI={(node) => void removeWebUI(node)}
              />
            ) : (
              <p className="connections-hint">
                {hostsQuery.isLoading ? 'Asking the cluster…' : 'None of its backends answered.'}
              </p>
            )}
          </div>
        ))}
    </section>
  );
}
