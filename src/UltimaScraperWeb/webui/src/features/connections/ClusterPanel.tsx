import { useEffect, useState, type FormEvent } from 'react';

import {
  connectionHome,
  getClusterOverview,
  listClusterClients,
  renameCluster,
  revokeClusterClient,
  type BackendCluster,
  type BackendClusters,
  type ClusterClient,
  type ClusterOverview,
} from '../../api/webui';
import { getActiveConnectionId } from '../../api/http';
import { defaultClusterName, pickClusterMember } from './lib/clusterView';
import { followInApp } from './lib/navigation';
import { useClusterInvite } from './lib/useClusterInvite';
import { ClusterInviteResult } from './ClusterInviteResult';


function healthLine(overview: ClusterOverview): string {
  const workers = overview.worker_hosts.reduce((sum, host) => sum + host.max_workers, 0);
  const active = overview.worker_hosts.reduce((sum, host) => sum + host.active_workers, 0);
  const down = overview.backends.filter((backend) => ['unreachable', 'offline'].includes(backend.status)).length;
  const parts = [
    `${overview.backends.length} backend${overview.backends.length === 1 ? '' : 's'}`,
    `${active}/${workers} workers busy on ${overview.worker_hosts.length} host${overview.worker_hosts.length === 1 ? '' : 's'}`,
  ];
  parts.push(down ? `${down} unreachable` : 'healthy');
  return parts.join(' · ');
}

/**
 * The cluster as a whole: its name, health, members and workers, opening it
 * on a healthy member, and inviting another WebUI into it.
 */
export function ClusterPanel({
  cluster,
  clusters,
  onSelectBackend,
  onAdd,
  onNamed,
}: {
  cluster: BackendCluster;
  clusters: BackendClusters | null;
  onSelectBackend?: (connectionId: string) => void;
  onAdd: (name: string, apiUrl: string | null) => void;
  onNamed?: (name: string) => void;
}) {
  const [overview, setOverview] = useState<ClusterOverview | null>(null);
  const [overviewError, setOverviewError] = useState('');
  const [editing, setEditing] = useState(false);
  const [draftName, setDraftName] = useState('');
  const { invite, error: inviteError, copy: copyInvite } = useClusterInvite(cluster.cluster_id);
  const [clients, setClients] = useState<ClusterClient[]>([]);
  const [clientsError, setClientsError] = useState('');
  const name = overview?.name ?? (cluster.name || defaultClusterName(cluster.cluster_id));

  useEffect(() => {
    let active = true;
    getClusterOverview(cluster.cluster_id).then(
      (loaded) => {
        if (!active) return;
        setOverview(loaded);
        onNamed?.(loaded.name);
      },
      (error) => active && setOverviewError(error instanceof Error ? error.message : 'The cluster did not answer.'),
    );
    // Backends from before invites list none.
    listClusterClients(cluster.cluster_id).then(
      (loaded) => active && setClients(loaded),
      () => undefined,
    );
    return () => {
      active = false;
    };
    // onNamed is a callback from the parent; reloading on its identity would loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cluster.cluster_id]);

  const target = pickClusterMember(cluster, clusters, getActiveConnectionId());

  const saveName = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      const saved = await renameCluster(cluster.cluster_id, draftName);
      setOverview((current) => (current ? { ...current, name: saved.name } : current));
      onNamed?.(saved.name);
      setEditing(false);
    } catch (error) {
      setOverviewError(error instanceof Error ? error.message : 'Could not rename the cluster.');
    }
  };


  const revoke = async (client: ClusterClient) => {
    const warning = client.is_self
      ? 'This WebUI will lose its own access to the cluster. Revoke it?'
      : `${client.name} will lose access to the cluster. Revoke it?`;
    if (!window.confirm(warning)) return;
    setClientsError('');
    try {
      await revokeClusterClient(cluster.cluster_id, client.id);
      setClients(await listClusterClients(cluster.cluster_id));
    } catch (error) {
      setClientsError(error instanceof Error ? error.message : 'Could not revoke it.');
    }
  };

  const unconnected = overview?.backends.filter((backend) => backend.connection_id === null) ?? [];

  return (
    <div className="cluster-panel">
      <div className="cluster-panel-head">
        {editing ? (
          <form className="cluster-panel-rename" onSubmit={saveName}>
            <input
              aria-label="Cluster name"
              value={draftName}
              maxLength={80}
              onChange={(event) => setDraftName(event.target.value)}
              autoFocus
            />
            <button type="submit" className="connections-button is-primary">
              Save
            </button>
            <button type="button" className="connections-button" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </form>
        ) : (
          <h2>
            {name}{' '}
            <button
              type="button"
              className="connections-link"
              aria-label="Rename cluster"
              onClick={() => {
                setDraftName(name);
                setEditing(true);
              }}
            >
              Rename
            </button>
          </h2>
        )}
        <code className="connections-url" title="Cluster id">
          {cluster.cluster_id.slice(0, 8)}
        </code>
        {overview && <span className="connections-hint">{healthLine(overview)}</span>}
        <div className="connections-actions">
          {target && (
            <a
              className="connections-button is-primary"
              href={connectionHome(target)}
              aria-label={`Open ${name}`}
              onClick={(event) => {
                if (onSelectBackend) {
                  event.preventDefault();
                  onSelectBackend(target);
                } else {
                  followInApp(event, connectionHome(target));
                }
              }}
            >
              Open cluster
            </a>
          )}
          <button type="button" className="connections-button" onClick={() => void copyInvite()}>
            Invite a WebUI
          </button>
        </div>
      </div>
      <p className="connections-copy">
        These backends share one database, so jobs, settings and content are the same on each. Drives and workers
        belong to each machine.
      </p>

      {overviewError && <p className="connections-hint">{overviewError}</p>}
      {overview?.error && <p className="connections-hint">{overview.error}</p>}

      <ClusterInviteResult invite={invite} error={inviteError} />

      {unconnected.length > 0 && (
        <div className="cluster-panel-section">
          <h3>Other backends in this cluster</h3>
          <ul className="cluster-panel-list">
            {unconnected.map((backend) => (
              <li key={backend.backend_id}>
                <strong>{backend.name}</strong>
                {backend.address && <code className="connections-url">{backend.address}</code>}
                {backend.version && <span className="connections-tag">v{backend.version}</span>}
                <button type="button" className="connections-button" onClick={() => onAdd(backend.backend_id, backend.address)}>
                  Add
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {clients.length > 0 && (
        <div className="cluster-panel-section">
          <h3>WebUIs</h3>
          <ul className="cluster-panel-list" aria-label={`WebUIs in ${name}`}>
            {clients.map((client) => (
              <li key={client.id}>
                <strong>{client.name}</strong>
                {client.is_self && <span className="connections-tag">This WebUI</span>}
                {client.last_address && <code className="connections-url">{client.last_address}</code>}
                {client.version && <span className="connections-tag">{client.version}</span>}
                {client.revoked_at ? (
                  <span className="connections-tag">Revoked</span>
                ) : (
                  <>
                    {client.last_seen_at && (
                      <span className="connections-hint">
                        seen {new Date(client.last_seen_at).toLocaleString()}
                      </span>
                    )}
                    <button type="button" className="connections-button" onClick={() => void revoke(client)}>
                      Revoke
                    </button>
                  </>
                )}
              </li>
            ))}
          </ul>
          {clientsError && (
            <p className="connections-error" role="alert">
              {clientsError}
            </p>
          )}
        </div>
      )}

      {overview && overview.worker_hosts.length > 0 && (
        <div className="cluster-panel-section">
          <h3>Workers</h3>
          <table className="cluster-panel-table" aria-label={`Workers in ${name}`}>
            <thead>
              <tr>
                <th scope="col">Host</th>
                <th scope="col">Busy</th>
                <th scope="col">Pending jobs</th>
                <th scope="col">Version</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {overview.worker_hosts.map((host) => (
                <tr key={host.backend_id}>
                  <th scope="row">{host.name}</th>
                  <td>
                    {host.active_workers}/{host.max_workers}
                  </td>
                  <td>{host.pending_jobs}</td>
                  <td>{host.version || '—'}</td>
                  <td>{host.status || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
