import { useCallback, useEffect, useState, type FormEvent } from 'react';

import {
  addConnection,
  connectionHome,
  getConnectionTicket,
  isClusterInvite,
  listClusters,
  listConnections,
  removeConnection,
  setPluginTrust,
  signOutOfWebUI,
  testConnection,
  type BackendClusters,
  type BackendConnection,
  type BackendConnectionTest,
  type BackendCluster,
} from '../../api/webui';
import { DeploymentsSection } from './DeploymentsSection';
import { WebUIUpdateCard } from './WebUIUpdateCard';
import { ClusterPanel } from './ClusterPanel';
import { defaultClusterName, groupConnections, reachableAlternative } from './lib/clusterView';
import { parseTicketString } from './lib/ticket';
import './connections.css';
import { followInApp } from './lib/navigation';
import { copyText } from '../../utils/clipboard';

type TestState = BackendConnectionTest | 'testing' | undefined;

const EMPTY_FORM = { name: '', base_url: '', token: '', tls_verify: true };

function TestStatus({ state }: { state: TestState }) {
  if (state === undefined) return null;
  if (state === 'testing') {
    return <span className="connections-status is-pending">Testing…</span>;
  }
  const ok = state.reachable && state.authenticated;
  return (
    <span className={`connections-status ${ok ? 'is-ok' : 'is-error'}`}>
      {ok ? '✓' : '✗'} {state.message}
      {ok && state.latency_ms != null && ` (${state.latency_ms} ms)`}
    </span>
  );
}

/** The add form, prefilled from ?add=NAME&url=URL (the fleet page links here). */
function initialForm(): typeof EMPTY_FORM {
  const query = new URLSearchParams(window.location.search);
  const name = query.get('add');
  return name ? { ...EMPTY_FORM, name, base_url: query.get('url') ?? '' } : EMPTY_FORM;
}

/** Backend ids reported by more than one running backend. */
function ClusterNotes({ cluster }: { cluster: BackendCluster }) {
  if (cluster.conflicting_backend_ids.length === 0) return null;
  return (
    <p className="connections-error" role="alert">
      More than one running backend uses the id {cluster.conflicting_backend_ids.join(', ')}. They share one set of
      settings and overwrite each other&apos;s registration. Give each its own BACKEND_ID.
    </p>
  );
}

/** The version a backend last reported about itself. */
function BackendVersion({ connectionId, clusters }: { connectionId: string; clusters: BackendClusters | null }) {
  const version = clusters?.members.find((member) => member.connection_id === connectionId)?.identity?.version;
  if (!version) return null;
  return (
    <span className="connections-tag" title="The version this backend reports">
      v{version}
    </span>
  );
}

/** While a backend is down, points at a reachable one with the same data. */
function Alternative({
  connectionId,
  clusters,
  connections,
}: {
  connectionId: string;
  clusters: BackendClusters | null;
  connections: BackendConnection[];
}) {
  const alternative = reachableAlternative(connectionId, clusters);
  const name = connections.find((entry) => entry.id === alternative)?.name;
  if (!alternative || !name) return null;
  return (
    <span className="connections-hint">
      Unreachable. <a href={connectionHome(alternative)} onClick={(event) => followInApp(event, connectionHome(alternative))}>Open {name}</a> instead; it shares this backend&apos;s data.
    </span>
  );
}

export interface ConnectionsPageProps {
  onClose?: () => void;
  onSelectBackend?: (connectionId: string) => void;
  initialAdd?: boolean;
}

/** Lists the backends this WebUI can reach, and adds or removes them. */
export function ConnectionsPage({ onClose, onSelectBackend, initialAdd }: ConnectionsPageProps = {}) {
  const [connections, setConnections] = useState<BackendConnection[] | null>(null);
  const [clusters, setClusters] = useState<BackendClusters | null>(null);
  const [tests, setTests] = useState<Record<string, TestState>>({});
  const [form, setForm] = useState(initialForm);
  const [adding, setAdding] = useState(() => Boolean(initialAdd || form !== EMPTY_FORM));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [ticketWarning, setTicketWarning] = useState<string | null>(null);
  const [ticketInput, setTicketInput] = useState('');
  const [ticketMessage, setTicketMessage] = useState<string | null>(null);
  // What each cluster is called, as its panel learns it.
  const [clusterNames, setClusterNames] = useState<Record<string, string>>({});
  const nameCluster = useCallback(
    (clusterId: string, name: string) =>
      setClusterNames((current) => (current[clusterId] === name ? current : { ...current, [clusterId]: name })),
    [],
  );

  const copyTicket = async (id: string) => {
    try {
      const res = await getConnectionTicket(id);
      await copyText(res.ticket);
      setTicketWarning(res.warning);
      setCopiedId(id);
      setTimeout(() => setCopiedId((curr) => (curr === id ? null : curr)), 2500);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not export connection ticket.');
    }
  };

  const handleTicketInput = (val: string) => {
    setTicketInput(val);
    if (!val.trim()) {
      setTicketMessage(null);
      return;
    }
    if (isClusterInvite(val)) {
      setTicketMessage('This is a cluster invite: use it in Set up, under Join a cluster.');
      return;
    }
    const parsed = parseTicketString(val);
    if (parsed) {
      setForm((prev) => ({
        ...prev,
        name: parsed.name || prev.name,
        base_url: parsed.base_url || prev.base_url,
        token: parsed.token ?? '',
        tls_verify: parsed.tls_verify,
      }));
      setTicketMessage(`Imported settings for "${parsed.name}".`);
    } else {
      setTicketMessage('Unrecognized ticket format.');
    }
  };

  useEffect(() => {
    if (!onClose) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const runTest = useCallback(async (id: string) => {
    // A retest keeps the last result on screen instead of flashing "Testing…".
    setTests((current) => (current[id] && current[id] !== 'testing' ? current : { ...current, [id]: 'testing' }));
    try {
      const result = await testConnection(id);
      setTests((current) => ({ ...current, [id]: result }));
    } catch (testError) {
      setTests((current) => ({
        ...current,
        [id]: {
          reachable: false,
          authenticated: false,
          message: testError instanceof Error ? testError.message : 'Test failed.',
          latency_ms: null,
        },
      }));
    }
  }, []);

  const load = useCallback(async () => {
    try {
      const loaded = await listConnections();
      // A later successful load clears an earlier failure (e.g. the server restarting).
      setError('');
      setConnections(loaded);
      setAdding((current) => current || loaded.length === 0);
      loaded.forEach((connection) => void runTest(connection.id));
      // Asking every backend who it is takes longer; the list shows first.
      listClusters().then(setClusters, () => setClusters(null));
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Could not load the backends.');
    }
  }, [runTest]);

  useEffect(() => {
    void load();
  }, [load]);

  // Stable, so a finished operation reloads the list once rather than on every render.
  const reload = useCallback(() => void load(), [load]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError('');
    try {
      const created = await addConnection({
        name: form.name.trim(),
        base_url: form.base_url.trim(),
        token: form.token.trim() || null,
        tls_verify: form.tls_verify,
      });
      setForm(EMPTY_FORM);
      setAdding(false);
      setConnections((current) => [...(current ?? []), created]);
      void runTest(created.id);
      listClusters().then(setClusters, () => undefined);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Could not add the backend.');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (connection: BackendConnection) => {
    if (!window.confirm(`Remove ${connection.name} from this WebUI? The backend itself is not changed.`)) return;
    try {
      await removeConnection(connection.id);
      setConnections((current) => current?.filter((entry) => entry.id !== connection.id) ?? null);
    } catch (removeError) {
      setError(removeError instanceof Error ? removeError.message : 'Could not remove the backend.');
    }
  };

  const changeTrust = async (connection: BackendConnection, trusted: boolean) => {
    if (
      trusted &&
      !window.confirm(
        `Let ${connection.name}'s native plugins run code in this WebUI? That code can act on every backend ` +
          'you have connected here. Only trust backends you control.',
      )
    ) {
      return;
    }
    try {
      const updated = await setPluginTrust(connection.id, trusted);
      setConnections((current) => current?.map((entry) => (entry.id === updated.id ? updated : entry)) ?? null);
    } catch (trustError) {
      setError(trustError instanceof Error ? trustError.message : 'Could not change plugin trust.');
    }
  };

  const prefill = (name: string, apiUrl: string | null) => {
    setForm({ ...EMPTY_FORM, name, base_url: apiUrl ?? '' });
    setAdding(true);
    window.requestAnimationFrame(() => document.getElementById('connections-add')?.scrollIntoView?.({ block: 'start' }));
  };

  const groups = connections ? groupConnections(connections, clusters) : [];

  const clustered = groups.some((group) => group.cluster !== null);

  const signOut = async () => {
    await signOutOfWebUI();
    window.location.assign('/');
  };

  const bodyContent = (
    <>
      <WebUIUpdateCard />
      {error && <p className="connections-error" role="alert">{error}</p>}
      {ticketWarning && (
        <p className="connections-hint" role="status">
          Ticket copied, but {ticketWarning}
        </p>
      )}
      {connections === null && !error && <p className="connections-copy">Loading…</p>}

      {groups.map((group) => (
        <section
          key={group.cluster?.cluster_id ?? 'standalone'}
          className={`connections-group${group.cluster ? ' is-cluster' : ''}`}
          aria-label={
            group.cluster
              ? (clusterNames[group.cluster.cluster_id] ?? defaultClusterName(group.cluster.cluster_id))
              : 'Independent backends'
          }
        >
          {group.cluster ? (
            <header className="connections-group-header">
              <ClusterPanel
                cluster={group.cluster}
                clusters={clusters}
                onSelectBackend={onSelectBackend}
                onAdd={prefill}
                onNamed={(name) => nameCluster(group.cluster!.cluster_id, name)}
              />
              <h3 className="cluster-panel-subhead">Backends</h3>
            </header>
          ) : (
            clustered && (
              <header className="connections-group-header">
                <h2>Independent backends</h2>
              </header>
            )
          )}
          <ul className="connections-list">
            {group.connections.map((connection) => (
              <li key={connection.id} className="connections-row">
                <div className="connections-row-main">
                  <strong>{connection.name}</strong>
                  {connection.managed && (
                    <span className="connections-tag" title="Set by this deployment (USR_WEBUI_DEFAULT_BACKEND_URL)">
                      Deployment
                    </span>
                  )}
                  {!connection.has_token && <span className="connections-tag">No token</span>}
                  <BackendVersion connectionId={connection.id} clusters={clusters} />
                  <code className="connections-url">{connection.base_url}</code>
                  <TestStatus state={tests[connection.id]} />
                  <Alternative connectionId={connection.id} clusters={clusters} connections={connections ?? []} />
                  <label
                    className="connections-checkbox connections-trust"
                    title="Native plugins run their own code in this page. Without trust, their screens stay hidden; sandboxed plugins and plugin actions still work."
                  >
                    <input
                      type="checkbox"
                      checked={connection.trust_plugins}
                      onChange={(event) => void changeTrust(connection, event.target.checked)}
                    />
                    <span>Trust native plugins from this backend</span>
                  </label>
                </div>
                <div className="connections-actions">
                  <a
                    className="connections-button is-primary"
                    href={connectionHome(connection.id)}
                    onClick={(event) => {
                      if (onSelectBackend) {
                        event.preventDefault();
                        onSelectBackend(connection.id);
                      } else {
                        followInApp(event, connectionHome(connection.id));
                      }
                    }}
                  >
                    Open
                  </a>
                  <button type="button" className="connections-button" onClick={() => void runTest(connection.id)}>
                    Test
                  </button>
                  <button
                    type="button"
                    className="connections-button"
                    title="Copy connection ticket to clipboard"
                    onClick={() => void copyTicket(connection.id)}
                  >
                    {copiedId === connection.id ? 'Copied!' : 'Copy Ticket'}
                  </button>
                  {!connection.managed && (
                    <button type="button" className="connections-button" onClick={() => void remove(connection)}>
                      Remove
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
          {group.cluster && <ClusterNotes cluster={group.cluster} />}
        </section>
      ))}

      <DeploymentsSection onChanged={reload} />

      {adding && connections?.length === 0 && (
        <div className="connections-empty">
          <p className="connections-copy">This WebUI has no backends yet. Install one, or connect to one you already run.</p>
          <a
            className="connections-button is-primary"
            href="/setup"
            onClick={(event) => {
              if (onClose) onClose();
              followInApp(event, '/setup');
            }}
          >
            Install a backend
          </a>
        </div>
      )}

      {adding ? (
        <form id="connections-add" className="connections-form" onSubmit={submit}>
          <h2>{connections?.length === 0 ? 'Or connect a running backend' : 'Connect a backend'}</h2>
          <div className="connections-ticket-field">
            <label>
              <span>Import from ticket</span>
              <div className="connections-ticket-input-row">
                <input
                  value={ticketInput}
                  onChange={(event) => handleTicketInput(event.target.value)}
                  placeholder="Paste usr://ticket/... or usr://token@host:port"
                  spellCheck={false}
                />
                {ticketInput && (
                  <button
                    type="button"
                    className="connections-button"
                    onClick={() => handleTicketInput('')}
                  >
                    Clear
                  </button>
                )}
              </div>
              {ticketMessage ? (
                <small className={ticketMessage.startsWith('Imported') ? 'connections-ticket-success' : 'connections-ticket-error'}>
                  {ticketMessage}
                </small>
              ) : (
                <small>Paste a ticket to automatically fill the fields below.</small>
              )}
            </label>
          </div>
          <label>
            <span>Name</span>
            <input
              value={form.name}
              onChange={(event) => setForm({ ...form, name: event.target.value })}
              placeholder="NAS"
              required
              maxLength={80}
            />
          </label>
          <label>
            <span>Address</span>
            <input
              value={form.base_url}
              onChange={(event) => setForm({ ...form, base_url: event.target.value })}
              placeholder="https://nas.example.test:21121"
              required
              spellCheck={false}
            />
            <small>The backend&apos;s API address, as this WebUI server can reach it.</small>
          </label>
          <label>
            <span>Admin token</span>
            <input
              type="password"
              autoComplete="off"
              value={form.token}
              onChange={(event) => setForm({ ...form, token: event.target.value })}
            />
            <small>
              That backend&apos;s USR_ADMIN_TOKEN. It is stored encrypted here and never sent to
              browsers. On Docker, read it with{' '}
              <code>docker compose exec backend cat /home/ultimascraper/.config/ultima_scraper_verse/secrets/USR_ADMIN_TOKEN</code>
            </small>
          </label>
          <label className="connections-checkbox">
            <input
              type="checkbox"
              checked={form.tls_verify}
              onChange={(event) => setForm({ ...form, tls_verify: event.target.checked })}
            />
            <span>Verify the TLS certificate</span>
          </label>
          <div className="connections-actions">
            <button type="submit" className="connections-button is-primary" disabled={saving}>
              {saving ? 'Connecting…' : 'Connect'}
            </button>
            {connections && connections.length > 0 && (
              <button type="button" className="connections-button" onClick={() => setAdding(false)}>
                Cancel
              </button>
            )}
          </div>
        </form>
      ) : (
        <div className="connections-actions">
          <button type="button" className="connections-button" onClick={() => setAdding(true)}>
            + Connect a backend
          </button>
          <a
            className="connections-button"
            href="/setup"
            onClick={(event) => {
              if (onClose) onClose();
              followInApp(event, '/setup');
            }}
          >
            Install a backend
          </a>
        </div>
      )}
    </>
  );

  if (onClose) {
    return (
      <div className="modal-overlay" onClick={onClose}>
        <section
          className="modal-content modal-content--wide manage-backends-modal"
          role="dialog"
          aria-modal="true"
          aria-labelledby="connections-title"
          onClick={(event) => event.stopPropagation()}
        >
          <div className="modal-header">
            <div>
              <p className="connections-eyebrow">05 // Infrastructure</p>
              <h2 id="connections-title">Manage clusters</h2>
              <p className="connections-copy">
                A cluster is the backends that share one database. Open one to work with it, invite
                another WebUI into it, or add a single backend by its address and admin token.
              </p>
            </div>
            <button
              type="button"
              className="modal-close"
              aria-label="Close"
              onClick={onClose}
            >
              ×
            </button>
          </div>
          <div className="modal-body">
            {bodyContent}
          </div>
        </section>
      </div>
    );
  }

  return (
    <main className="connections-page">
      <section className="connections-card" aria-labelledby="connections-title">
        <header className="connections-header">
          <div>
            <p className="connections-eyebrow">05 // Infrastructure</p>
            <h1 id="connections-title">Clusters</h1>
            <p className="connections-copy">
              A cluster is the backends that share one database. Open one to work with it, invite
              another WebUI into it, or add a single backend by its address and admin token.
            </p>
          </div>
          <button type="button" className="connections-link" onClick={() => void signOut()}>
            Sign out
          </button>
        </header>
        {bodyContent}
      </section>
    </main>
  );
}

export function ManageBackendsModal(props: ConnectionsPageProps & { onClose: () => void }) {
  return <ConnectionsPage {...props} />;
}
