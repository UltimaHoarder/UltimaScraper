import { useState, type FormEvent, type ReactNode } from 'react';

import { renameHost, type ClusterHost, type ClusterNode, type NodeRole, type NodeState } from '../../../api/webui';

const ROLE_LABELS: Record<NodeRole, string> = {
  backend: 'Backend',
  workers: 'Workers',
  webui: 'WebUI',
  postgres: 'PostgreSQL',
  redis: 'Redis',
};

const STATE_LABELS: Record<NodeState, string> = {
  healthy: 'Healthy',
  warning: 'Needs attention',
  offline: 'Offline',
  unknown: 'Not reporting',
};

function Badge({ state }: { state: NodeState }) {
  // The register's styles know offline, warning and healthy; unknown reads as idle.
  const style = state === 'unknown' ? 'idle' : state;
  return (
    <span className={`fleet-register-state fleet-register-state--${style}`}>
      <i aria-hidden="true" />
      {STATE_LABELS[state]}
    </span>
  );
}

function seen(value: string | null): string {
  if (!value) return '—';
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(value)) / 1000));
  if (Number.isNaN(seconds)) return '—';
  if (seconds < 5) return 'Just now';
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

function NodeActions({
  node,
  onInspectDatabase,
  onRemoveWebUI,
}: {
  node: ClusterNode;
  onInspectDatabase?: () => void;
  onRemoveWebUI?: (node: ClusterNode) => void;
}) {
  if (node.role === 'postgres' && onInspectDatabase) {
    return (
      <button type="button" className="fleet-register-link" onClick={onInspectDatabase}>
        Inspect database ↗
      </button>
    );
  }
  if (node.role === 'webui' && node.is_self) return <span className="connections-tag">This WebUI</span>;
  if (node.role === 'webui' && node.client_id && onRemoveWebUI) {
    return (
      <button
        type="button"
        className="fleet-register-link"
        title="Revoke its access to the cluster: it is no longer listed"
        onClick={() => onRemoveWebUI(node)}
      >
        Remove
      </button>
    );
  }
  return null;
}

function RenameHost({ host, onRenamed, onCancel }: { host: ClusterHost; onRenamed: () => void; onCancel: () => void }) {
  const [name, setName] = useState(host.name);
  const [error, setError] = useState('');
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      await renameHost(host.key, name);
      onRenamed();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not rename it.');
    }
  };
  return (
    <form className="cluster-host-rename" onSubmit={save}>
      <input aria-label={`Name for ${host.address ?? host.name}`} value={name} maxLength={80} onChange={(event) => setName(event.target.value)} autoFocus />
      <button type="submit" className="fleet-register-button">
        Save
      </button>
      <button type="button" className="fleet-register-button" onClick={onCancel}>
        Cancel
      </button>
      {error && <span className="connections-error">{error}</span>}
    </form>
  );
}

/**
 * The cluster's machines, each with the roles it serves. Expanding a host
 * lists its nodes: each service, with its own state and actions.
 */
export function ClusterHostsTable({
  hosts,
  onConfigureBackend,
  onInspectBackend,
  onInspectDatabase,
  onRenamed,
  onEditHost,
  onRemoveWebUI,
}: {
  hosts: ClusterHost[];
  onConfigureBackend: (backendId: string) => void;
  onInspectBackend: (backendId: string) => void;
  onInspectDatabase?: () => void;
  onRenamed: () => void;
  /** Change the services on a host this WebUI installed, or on its own host. */
  onEditHost?: (host: ClusterHost) => void;
  /** Revoke another WebUI's access to the cluster. */
  onRemoveWebUI?: (node: ClusterNode) => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);

  return (
    <div className="fleet-register-table-scroll">
      <table className="fleet-register-table cluster-nodes-table" aria-label="Hosts">
        <thead>
          <tr>
            <th scope="col">Host</th>
            <th scope="col">Roles</th>
            <th scope="col">State</th>
            <th scope="col">Nodes</th>
            <th scope="col">Config</th>
            <th scope="col">Inspect</th>
            <th scope="col">Services</th>
            <th scope="col">Name</th>
          </tr>
        </thead>
        <tbody>
          {hosts.map((host) => {
            const isExpanded = expanded === host.key;
            const backendId = host.nodes.find((n) => n.backend_id)?.backend_id;
            return (
              <HostRows key={host.key}>
                <tr className={isExpanded ? 'is-selected' : ''}>
                  <th scope="row" data-label="Host">
                    <button
                      type="button"
                      className="fleet-register-name"
                      aria-expanded={isExpanded}
                      onClick={() => setExpanded((current) => (current === host.key ? null : host.key))}
                    >
                      <span aria-hidden="true">{isExpanded ? '−' : '+'}</span>
                      <span>
                        <strong>{host.name}</strong>
                        <small>{host.address ?? 'Address unknown'}</small>
                      </span>
                    </button>
                  </th>
                  <td data-label="Roles">
                    <span className="cluster-host-roles">
                      {host.roles.map((role) => (
                        <span key={role} className={`cluster-role-badge cluster-role-badge--${role}`}>
                          {ROLE_LABELS[role]}
                        </span>
                      ))}
                    </span>
                  </td>
                  <td data-label="State">
                    <Badge state={host.state} />
                  </td>
                  <td data-label="Nodes">{host.nodes.length}</td>
                  <td data-label="Config">
                    {backendId ? (
                      <button
                        type="button"
                        className="fleet-register-link"
                        onClick={() => onConfigureBackend(backendId)}
                      >
                        Edit config ↗
                      </button>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td data-label="Inspect">
                    {backendId ? (
                      <button
                        type="button"
                        className="fleet-register-icon-button"
                        aria-label={`Inspect ${host.name}`}
                        title={`Inspect ${host.name}`}
                        onClick={() => onInspectBackend(backendId)}
                      >
                        ↗
                      </button>
                    ) : (
                      '—'
                    )}
                  </td>
                  <td data-label="Services">
                    {onEditHost && (host.deployment_id || host.local_services) ? (
                      <button
                        type="button"
                        className="fleet-register-link"
                        aria-label={`Edit ${host.name}`}
                        onClick={() => onEditHost(host)}
                      >
                        Edit
                      </button>
                    ) : (
                      <span title="Installed elsewhere: change it where it was installed">—</span>
                    )}
                  </td>
                  <td data-label="Name">
                    {renaming === host.key ? (
                      <RenameHost
                        host={host}
                        onCancel={() => setRenaming(null)}
                        onRenamed={() => {
                          setRenaming(null);
                          onRenamed();
                        }}
                      />
                    ) : (
                      <button
                        type="button"
                        className="fleet-register-link"
                        aria-label={`Rename ${host.name}`}
                        onClick={() => setRenaming(host.key)}
                      >
                        Rename
                      </button>
                    )}
                  </td>
                </tr>
                {isExpanded && (
                  <tr className="fleet-register-expansion">
                    <td colSpan={8}>
                      <table className="cluster-host-nodes" aria-label={`Nodes on ${host.name}`}>
                        <thead>
                          <tr>
                            <th scope="col">Role</th>
                            <th scope="col">Node</th>
                            <th scope="col">State</th>
                            <th scope="col">Version</th>
                            <th scope="col">Details</th>
                            <th scope="col">Last check-in</th>
                            <th scope="col">Actions</th>
                          </tr>
                        </thead>
                        <tbody>
                          {host.nodes.map((node, index) => {
                            const action = (
                              <NodeActions
                                node={node}
                                onInspectDatabase={onInspectDatabase}
                                onRemoveWebUI={onRemoveWebUI}
                              />
                            );
                            return (
                              <tr key={`${node.role}-${node.name}-${index}`}>
                                <td data-label="Role">
                                  <span className={`cluster-role-badge cluster-role-badge--${node.role}`}>
                                    {ROLE_LABELS[node.role]}
                                  </span>
                                </td>
                                <th scope="row" data-label="Node">{node.name}</th>
                                <td data-label="State">
                                  <Badge state={node.state} />
                                </td>
                                <td data-label="Version">{node.version ?? '—'}</td>
                                <td data-label="Details">{node.detail ?? '—'}</td>
                                <td data-label="Last check-in">
                                  {node.role === 'postgres' || node.role === 'redis' ? '—' : seen(node.last_seen)}
                                </td>
                                <td data-label="Actions">{action ?? '—'}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                )}
              </HostRows>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function HostRows({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
