import { useEffect, useState, type FormEvent } from 'react';
import { NavLink } from 'react-router-dom';
import { getActiveConnectionId } from '../../../api/http';
import {
  addConnection,
  connectionHome,
  getConnectionTicket,
  listClusters,
  listConnections,
  removeConnection,
  setPluginTrust,
  testConnection,
  type BackendClusters,
  type BackendConnection,
  type BackendConnectionTest,
} from '../../../api/webui';
import { parseTicketString } from '../../connections/lib/ticket';
import { useWebUIPreferences } from '../hooks/useWebUIPreferences';

type TestState = BackendConnectionTest | 'testing' | undefined;

const EMPTY_FORM = { name: '', base_url: '', token: '', tls_verify: true };

export function ConnectionsSettingsSection() {
  const { preferences, updatePreferences } = useWebUIPreferences();
  const [connections, setConnections] = useState<BackendConnection[] | null>(null);
  const [clusters, setClusters] = useState<BackendClusters | null>(null);
  const [tests, setTests] = useState<Record<string, TestState>>({});
  const [showAddForm, setShowAddForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [ticketInput, setTicketInput] = useState('');
  const [ticketMessage, setTicketMessage] = useState<string | null>(null);

  const copyTicket = async (id: string) => {
    try {
      const res = await getConnectionTicket(id);
      await navigator.clipboard.writeText(res.ticket);
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

  const activeId = getActiveConnectionId();

  const loadData = async () => {
    try {
      const conns = await listConnections();
      setConnections(conns);
      try {
        const clus = await listClusters();
        setClusters(clus);
      } catch {
        // cluster discovery optional
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load backend connections.');
    }
  };

  useEffect(() => {
    void loadData();
  }, []);

  const runTest = async (id: string) => {
    setTests((prev) => ({ ...prev, [id]: 'testing' }));
    try {
      const result = await testConnection(id);
      setTests((prev) => ({ ...prev, [id]: result }));
    } catch (testError) {
      setTests((prev) => ({
        ...prev,
        [id]: {
          reachable: false,
          authenticated: false,
          message: testError instanceof Error ? testError.message : 'Test failed',
          latency_ms: null,
        },
      }));
    }
  };

  const handleAddSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!form.name.trim() || !form.base_url.trim()) {
      setError('Connection name and URL are required.');
      return;
    }

    setIsSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const created = await addConnection({
        name: form.name.trim(),
        base_url: form.base_url.trim(),
        token: form.token.trim() || null,
        tls_verify: form.tls_verify,
      });
      setConnections((prev) => (prev ? [...prev, created] : [created]));
      setForm(EMPTY_FORM);
      setShowAddForm(false);
      setSuccess(`Connection "${created.name}" successfully registered.`);
      void runTest(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add backend connection.');
    } finally {
      setIsSaving(false);
    }
  };

  const handleRemove = async (conn: BackendConnection) => {
    if (!window.confirm(`Remove backend connection "${conn.name}"? The scraper backend itself will not be modified.`)) {
      return;
    }

    try {
      await removeConnection(conn.id);
      setConnections((prev) => prev?.filter((c) => c.id !== conn.id) ?? []);
      setSuccess(`Removed connection "${conn.name}".`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to remove connection.');
    }
  };

  const handleTrustChange = async (conn: BackendConnection, trusted: boolean) => {
    if (trusted && !window.confirm(`Permit ${conn.name}'s native plugins to execute within this WebUI? Only trust backends you control.`)) {
      return;
    }

    try {
      const updated = await setPluginTrust(conn.id, trusted);
      setConnections((prev) => prev?.map((c) => (c.id === updated.id ? updated : c)) ?? []);
      setSuccess(`Plugin trust updated for "${conn.name}".`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update plugin trust.');
    }
  };

  return (
    <div className="settings-section" data-testid="connections-settings-section">
      <h2>Fleet Connections</h2>
      <p className="section-description">
        Manage API endpoint connections to UltimaScraper scraper backends, cluster failover rules, and plugin execution trust.
      </p>

      {/* Notice Banner to Fleet */}
      <div
        style={{
          border: '1px solid rgb(var(--color-info-rgb, 36 170 195) / 0.35)',
          background: 'rgb(var(--color-info-rgb, 36 170 195) / 0.08)',
          padding: '0.9rem 1rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '1rem',
          marginBottom: '0.5rem',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
          <strong style={{ fontSize: '0.85rem', color: 'var(--color-text-primary)' }}>
            Configuring Scraper Runtime Options?
          </strong>
          <span style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)' }}>
            Storage directories, worker pools, redis queues, and site scraping configurations are managed per node in System Fleet.
          </span>
        </div>
        <NavLink
          to="/system"
          className="btn-save"
          style={{ textDecoration: 'none', display: 'inline-block', whiteSpace: 'nowrap' }}
        >
          Open System Fleet →
        </NavLink>
      </div>

      {success && (
        <div className="test-result success" role="status">
          ✓ {success}
        </div>
      )}

      {error && (
        <div className="error-message" role="alert">
          {error}
        </div>
      )}

      {/* Connection & Failover Policies */}
      <div className="setting-item" style={{ gap: '0.75rem' }}>
        <h3 style={{ margin: 0 }}>Cluster Connection & Failover Policies</h3>
        <span className="setting-description">
          Configure how the WebUI communicates with the cluster and handles node interruptions.
        </span>

        <label style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', cursor: 'pointer', marginTop: '0.25rem' }}>
          <input
            type="checkbox"
            checked={preferences.autoFailover}
            onChange={(e) => updatePreferences({ autoFailover: e.target.checked })}
          />
          <div>
            <div style={{ fontSize: '0.82rem', fontWeight: 700 }}>Enable Automated Cluster Failover</div>
            <div style={{ fontSize: '0.72rem', color: 'var(--color-text-tertiary)' }}>
              Automatically reconnect to another healthy node in the same cluster if the active backend becomes unreachable.
            </div>
          </div>
        </label>
      </div>

      {/* Configured Connections List */}
      <div className="setting-item" style={{ gap: '0.85rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h3 style={{ margin: 0 }}>Registered Scraper Backends</h3>
            <span className="setting-description">
              Endpoints currently configured to service this WebUI instance.
            </span>
          </div>
          <button
            type="button"
            className="btn-save"
            onClick={() => setShowAddForm(!showAddForm)}
          >
            {showAddForm ? 'Cancel' : '+ Connect a backend'}
          </button>
        </div>

        {/* Connect a backend: inline form */}
        {showAddForm && (
          <form
            onSubmit={(e) => void handleAddSubmit(e)}
            style={{
              padding: '1rem',
              background: 'rgba(255,255,255,0.02)',
              border: '1px solid var(--ultimur-panel-border)',
              display: 'grid',
              gap: '0.75rem',
            }}
          >
            <h4 style={{ margin: 0, textTransform: 'uppercase', fontSize: '0.75rem', letterSpacing: '0.05em' }}>
              Add New Scraper Connection
            </h4>

            <div>
              <label htmlFor="conn-ticket" style={{ display: 'block', marginBottom: '0.2rem' }}>
                Import from Ticket
              </label>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <input
                  id="conn-ticket"
                  type="text"
                  value={ticketInput}
                  onChange={(e) => handleTicketInput(e.target.value)}
                  placeholder="Paste usr://ticket/... or usr://token@host:port"
                  style={{ flex: 1 }}
                />
                {ticketInput && (
                  <button
                    type="button"
                    className="btn-reset"
                    onClick={() => handleTicketInput('')}
                    style={{ padding: '0.3rem 0.6rem', fontSize: '0.75rem' }}
                  >
                    Clear
                  </button>
                )}
              </div>
              {ticketMessage ? (
                <small style={{ color: ticketMessage.startsWith('Imported') ? 'var(--color-success)' : 'var(--color-error)', fontSize: '0.75rem', display: 'block', marginTop: '0.25rem' }}>
                  {ticketMessage}
                </small>
              ) : (
                <small style={{ color: 'var(--color-text-tertiary)', fontSize: '0.75rem', display: 'block', marginTop: '0.25rem' }}>
                  Paste a ticket to automatically fill the fields below.
                </small>
              )}
            </div>

            <div>
              <label htmlFor="conn-name" style={{ display: 'block', marginBottom: '0.2rem' }}>
                Connection Name
              </label>
              <input
                id="conn-name"
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="e.g. Scraper Worker Alpha"
                required
              />
            </div>

            <div>
              <label htmlFor="conn-url" style={{ display: 'block', marginBottom: '0.2rem' }}>
                Backend Base URL
              </label>
              <input
                id="conn-url"
                type="text"
                value={form.base_url}
                onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                placeholder="http://192.168.1.50:8000"
                required
              />
            </div>

            <div>
              <label htmlFor="conn-token" style={{ display: 'block', marginBottom: '0.2rem' }}>
                Admin Token (Optional)
              </label>
              <input
                id="conn-token"
                type="password"
                value={form.token}
                onChange={(e) => setForm({ ...form, token: e.target.value })}
                placeholder="Leave blank if no admin token required"
              />
            </div>

            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={form.tls_verify}
                onChange={(e) => setForm({ ...form, tls_verify: e.target.checked })}
              />
              <span style={{ fontSize: '0.78rem' }}>Verify TLS / SSL certificates</span>
            </label>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '0.5rem' }}>
              <button
                type="button"
                className="btn-reset"
                onClick={() => setShowAddForm(false)}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="btn-save"
                disabled={isSaving}
              >
                {isSaving ? 'Connecting…' : 'Connect'}
              </button>
            </div>
          </form>
        )}

        {/* Backends Cards / Table */}
        {connections === null ? (
          <div style={{ padding: '1rem', color: 'var(--color-text-tertiary)' }}>Loading connections…</div>
        ) : connections.length === 0 ? (
          <div style={{ padding: '1rem', color: 'var(--color-text-tertiary)' }}>No backend connections configured.</div>
        ) : (
          <div style={{ display: 'grid', gap: '0.65rem' }}>
            {connections.map((conn) => {
              const isActive = conn.id === activeId;
              const test = tests[conn.id];
              const isTesting = test === 'testing';
              const testResult = typeof test === 'object' ? test : null;
              const member = clusters?.members.find((m) => m.connection_id === conn.id);
              const clusterId = member?.identity?.cluster_id;
              const memberVersion = member?.identity?.version;

              return (
                <div
                  key={conn.id}
                  style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '0.85rem 1rem',
                    background: isActive ? 'rgb(var(--color-success-rgb) / 0.05)' : 'rgba(255,255,255,0.02)',
                    border: `1px solid ${isActive ? 'rgb(var(--color-success-rgb) / 0.4)' : 'var(--ultimur-panel-border)'}`,
                    gap: '0.75rem',
                  }}
                >
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', minWidth: '200px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                      <strong style={{ fontSize: '0.88rem', color: 'var(--color-text-primary)' }}>
                        {conn.name}
                      </strong>
                      {isActive && (
                        <span
                          style={{
                            padding: '0.15rem 0.45rem',
                            background: 'rgb(var(--color-success-rgb) / 0.15)',
                            color: 'var(--color-success)',
                            fontSize: '0.65rem',
                            fontWeight: 700,
                            letterSpacing: '0.05em',
                            textTransform: 'uppercase',
                          }}
                        >
                          Active
                        </span>
                      )}
                      {clusterId && (
                        <span
                          style={{
                            padding: '0.15rem 0.45rem',
                            background: 'rgba(36, 170, 195, 0.15)',
                            color: '#24aac3',
                            fontSize: '0.65rem',
                            fontFamily: 'var(--font-mono)',
                            textTransform: 'uppercase',
                          }}
                        >
                          Cluster: {clusterId.slice(0, 8)}
                        </span>
                      )}
                      {memberVersion && (
                        <span
                          style={{
                            padding: '0.15rem 0.45rem',
                            background: 'rgba(255,255,255,0.06)',
                            fontSize: '0.65rem',
                            color: 'var(--color-text-tertiary)',
                          }}
                        >
                          v{memberVersion}
                        </span>
                      )}
                      {conn.managed && (
                        <span
                          style={{
                            padding: '0.15rem 0.45rem',
                            background: 'rgba(255,255,255,0.06)',
                            fontSize: '0.65rem',
                            color: 'var(--color-text-tertiary)',
                            textTransform: 'uppercase',
                          }}
                        >
                          Deployment
                        </span>
                      )}
                    </div>
                    <code style={{ fontSize: '0.75rem', color: 'var(--color-text-secondary)' }}>
                      {conn.base_url}
                    </code>
                    {testResult && (
                      <div
                        style={{
                          fontSize: '0.72rem',
                          color: testResult.reachable ? 'var(--color-success)' : 'var(--color-error)',
                        }}
                      >
                        {testResult.reachable ? '✓ Reachable' : '✗ Unreachable'}
                        {testResult.latency_ms !== null && ` (${testResult.latency_ms} ms)`}
                        {' · '}
                        {testResult.message}
                      </div>
                    )}
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                    <button
                      type="button"
                      className="btn-reset"
                      onClick={() => void runTest(conn.id)}
                      disabled={isTesting}
                      style={{ padding: '0.4rem 0.75rem', fontSize: '0.72rem' }}
                    >
                      {isTesting ? 'Testing…' : 'Test'}
                    </button>

                    <button
                      type="button"
                      className="btn-reset"
                      title="Copy connection ticket to clipboard"
                      onClick={() => void copyTicket(conn.id)}
                      style={{ padding: '0.4rem 0.75rem', fontSize: '0.72rem' }}
                    >
                      {copiedId === conn.id ? 'Copied!' : 'Copy Ticket'}
                    </button>

                    {!isActive ? (
                      <a
                        href={connectionHome(conn.id)}
                        className="btn-save"
                        style={{ padding: '0.4rem 0.75rem', fontSize: '0.72rem', textDecoration: 'none' }}
                      >
                        Switch
                      </a>
                    ) : (
                      <span style={{ fontSize: '0.72rem', color: 'var(--color-success)', fontWeight: 700 }}>
                        ● Connected
                      </span>
                    )}

                    <label
                      title="Allow backend native plugins to execute code in WebUI"
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.35rem',
                        fontSize: '0.72rem',
                        color: 'var(--color-text-tertiary)',
                        cursor: 'pointer',
                        marginLeft: '0.25rem',
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={conn.trust_plugins}
                        onChange={(e) => void handleTrustChange(conn, e.target.checked)}
                      />
                      Trust Plugins
                    </label>

                    {!conn.managed && !isActive && (
                      <button
                        type="button"
                        className="btn-delete"
                        onClick={() => void handleRemove(conn)}
                        style={{ padding: '0.4rem 0.75rem', fontSize: '0.72rem' }}
                      >
                        Remove
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
