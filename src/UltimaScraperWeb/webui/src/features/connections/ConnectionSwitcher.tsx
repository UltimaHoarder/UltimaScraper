import { useEffect, useRef, useState } from 'react';

import { getActiveConnectionId } from '../../api/http';
import {
  connectionHome,
  listClusters,
  listConnections,
  signOutOfWebUI,
  type BackendClusters,
  type BackendConnection,
} from '../../api/webui';
import { groupConnections, pickClusterMember } from './lib/clusterView';
import { followInApp, sectionOnBackend } from './lib/navigation';
import { ManageBackendsModal } from './ConnectionsPage';
import './connections.css';

/**
 * Shows which backend the app is working with and switches to another, on the
 * same section. Backends that share a database are listed together under
 * their cluster. A switch remounts the app for that backend without reloading
 * the page; each backend keeps its own cache and live connections.
 */
export function ConnectionSwitcher() {
  const [connections, setConnections] = useState<BackendConnection[]>([]);
  // Asking every backend who it is is slower, so it waits for the menu.
  const [clusters, setClusters] = useState<BackendClusters | null>(null);
  const [open, setOpen] = useState(false);
  const [manageOpen, setManageOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const activeId = getActiveConnectionId();

  const refreshConnections = () => {
    listConnections().then(setConnections, () => setConnections([]));
  };

  useEffect(() => {
    refreshConnections();
  }, []);

  useEffect(() => {
    if (!open) return;
    let current = true;
    listClusters().then((result) => current && setClusters(result), () => undefined);
    return () => {
      current = false;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === 'Escape' : !containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', close);
    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('keydown', close);
    };
  }, [open]);

  if (activeId === null) return null;

  const active = connections.find((connection) => connection.id === activeId);
  const groups = groupConnections(connections, clusters);
  const grouped = groups.some((group) => group.cluster !== null);
  const unreachable = new Set(
    clusters?.members.filter((member) => !member.reachable).map((member) => member.connection_id) ?? [],
  );

  return (
    <div className="connection-switcher" ref={containerRef}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        title="Switch backend"
        onClick={() => setOpen(!open)}
      >
        <span>{active?.name ?? activeId}</span>
        <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <ul className="connection-switcher-menu" role="menu">
          {groups.map((group) => [
            grouped && (
              <li key={`group-${group.cluster?.cluster_id ?? 'independent'}`} role="presentation" className="connection-switcher-group">
                {group.cluster ? (group.cluster.name || `Cluster ${group.cluster.cluster_id.slice(0, 8)}`) : 'Independent'}
              </li>
            ),
            group.cluster && grouped && (
              <li key={`open-${group.cluster.cluster_id}`} role="none">
                <a
                  role="menuitem"
                  className="is-cluster-member"
                  href={connectionHome(pickClusterMember(group.cluster, clusters, activeId) ?? activeId)}
                  onClick={(event) => {
                    setOpen(false);
                    const target = pickClusterMember(group.cluster!, clusters, activeId);
                    if (!target || target === activeId) event.preventDefault();
                    else followInApp(event, sectionOnBackend(target));
                  }}
                >
                  Open cluster
                </a>
              </li>
            ),
            ...group.connections.map((connection) => (
              <li key={connection.id} role="none">
                <a
                  role="menuitem"
                  href={connectionHome(connection.id)}
                  aria-current={connection.id === activeId ? 'true' : undefined}
                  className={grouped && group.cluster ? 'is-cluster-member' : undefined}
                  onClick={(event) => {
                    setOpen(false);
                    if (connection.id === activeId) event.preventDefault();
                    else followInApp(event, sectionOnBackend(connection.id));
                  }}
                >
                  {connection.name}
                  {unreachable.has(connection.id) && <span className="connection-switcher-note"> · unreachable</span>}
                </a>
              </li>
            )),
          ])}
          <li role="none"><hr /></li>
          <li role="none">
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                setManageOpen(true);
              }}
            >
              Manage clusters
            </button>
          </li>
          <li role="none">
            <button
              type="button"
              role="menuitem"
              onClick={() => void signOutOfWebUI().finally(() => window.location.assign('/'))}
            >
              Sign out
            </button>
          </li>
        </ul>
      )}
      {manageOpen && (
        <ManageBackendsModal
          onClose={() => {
            setManageOpen(false);
            refreshConnections();
          }}
          onSelectBackend={(connectionId) => {
            setManageOpen(false);
            followInApp(null, sectionOnBackend(connectionId));
          }}
        />
      )}
    </div>
  );
}
