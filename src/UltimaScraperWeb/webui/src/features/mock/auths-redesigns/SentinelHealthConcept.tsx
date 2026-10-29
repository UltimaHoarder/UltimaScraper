import { useState } from 'react';
import type { AuthsMockModel } from './authsMockModel';

interface SentinelHealthConceptProps {
  model: AuthsMockModel;
}

type SentinelTab = 'all' | 'healthy' | 'challenges' | 'expired';

export function SentinelHealthConcept({ model }: SentinelHealthConceptProps) {
  const { sortedAuths, toggleActive, setEditingAuth, setTestingAuth, setVerifyingAuth } = model;
  const [activeTab, setActiveTab] = useState<SentinelTab>('all');
  const [selectedAuthId, setSelectedAuthId] = useState<number>(sortedAuths[0]?.id ?? 101);
  const [inlineCurl, setInlineCurl] = useState('');

  const healthyAuths = sortedAuths.filter((a) => a.status === 'valid' && a.active);
  const challengeAuths = sortedAuths.filter(
    (a) => a.status === 'challenge_required' || a.age_verification_required
  );
  const expiredAuths = sortedAuths.filter((a) => a.status === 'expired' || !a.active);

  const displayedAuths =
    activeTab === 'healthy'
      ? healthyAuths
      : activeTab === 'challenges'
      ? challengeAuths
      : activeTab === 'expired'
      ? expiredAuths
      : sortedAuths;

  const selectedAuth = sortedAuths.find((a) => a.id === selectedAuthId) ?? sortedAuths[0];
  const assignedProxy = model.proxies.find((p) => p.id === selectedAuth?.proxy_id);

  const handleApplyInlineCurl = () => {
    if (!selectedAuth || !inlineCurl.trim()) return;
    model.updateAuth(selectedAuth.id, {
      ...selectedAuth,
      username: selectedAuth.username ?? undefined,
      cookie: 'sess=refreshed_session_token_' + Math.floor(Math.random() * 9000),
    });
    setInlineCurl('');
    model.showNotification(`Fresh session applied to @${selectedAuth.username}!`, 'success');
  };

  return (
    <section className="arm-concept arm-sentinel" aria-label="Session Sentinel and Health Triage">
      {/* Top Incident Summary Strip */}
      <div className="arm-sentinel-banner">
        <div className="arm-sentinel-headline">
          <span className="arm-eyebrow">CONTINUOUS HEALTH PROBING // SENTINEL ENGINE</span>
          <h3>Fleet Authentication Triage &amp; Incident Runbook</h3>
        </div>

        <div className="arm-triage-funnel">
          <button
            type="button"
            className={`arm-funnel-tab ${activeTab === 'all' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('all')}
          >
            All Accounts <b>{sortedAuths.length}</b>
          </button>
          <button
            type="button"
            className={`arm-funnel-tab is-green ${activeTab === 'healthy' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('healthy')}
          >
            Operational <b>{healthyAuths.length}</b>
          </button>
          <button
            type="button"
            className={`arm-funnel-tab is-warn ${activeTab === 'challenges' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('challenges')}
          >
            Challenges <b>{challengeAuths.length}</b>
          </button>
          <button
            type="button"
            className={`arm-funnel-tab is-danger ${activeTab === 'expired' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('expired')}
          >
            Expired / Stale <b>{expiredAuths.length}</b>
          </button>
        </div>
      </div>

      {/* 2-Column Triage Deck */}
      <div className="arm-sentinel-deck">
        {/* Left Column: Triage List */}
        <div className="arm-sentinel-list">
          <div className="arm-list-header">
            <span className="arm-eyebrow">ACCOUNTS QUEUE ({displayedAuths.length})</span>
            <button
              type="button"
              className="arm-mini-btn arm-btn--secondary"
              onClick={() => model.batchTest(displayedAuths.map((a) => a.id))}
            >
              ⚡ Test All Visible
            </button>
          </div>

          <div className="arm-sentinel-cards">
            {displayedAuths.map((auth) => {
              const isSelected = auth.id === selectedAuthId;
              return (
                <div
                  key={auth.id}
                  className={`arm-triage-item ${isSelected ? 'is-selected' : ''} is-${auth.status}`}
                  onClick={() => setSelectedAuthId(auth.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') setSelectedAuthId(auth.id);
                  }}
                >
                  <div className="arm-triage-item-top">
                    <span className={`arm-platform-badge is-${auth.site.toLowerCase()}`}>
                      {auth.site}
                    </span>
                    <strong>@{auth.username || `User #${auth.user_id}`}</strong>
                    <span className={`arm-status-pill is-${auth.status}`}>
                      {auth.status.toUpperCase()}
                    </span>
                  </div>

                  <div className="arm-triage-item-meta">
                    <span>AUTH #{auth.id}</span>
                    <span>{auth.proxy_id ? `🌐 ${auth.proxy_id}` : 'Local Direct'}</span>
                    <span>{auth.active ? '🟢 Enabled' : '⚪ Disabled'}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Column: Triage Dossier & Automated Remediation */}
        {selectedAuth && (
          <div className="arm-sentinel-dossier arm-card">
            <header className="arm-dossier-head">
              <div>
                <span className="arm-eyebrow">DIAGNOSTIC DOSSIER // AUTH #{selectedAuth.id}</span>
                <h3>@{selectedAuth.username || `User #${selectedAuth.user_id}`}</h3>
                <p>
                  Platform: <strong>{selectedAuth.site}</strong> · User ID: <strong>{selectedAuth.user_id}</strong>
                </p>
              </div>

              <div className="arm-dossier-head-actions">
                <button
                  type="button"
                  className="arm-btn arm-btn--secondary"
                  onClick={() => setTestingAuth(selectedAuth)}
                >
                  🧪 Diagnostic Probe
                </button>
                <button
                  type="button"
                  className="arm-btn arm-btn--quiet"
                  onClick={() => toggleActive(selectedAuth.id)}
                >
                  {selectedAuth.active ? 'Disable' : 'Enable'}
                </button>
                <button
                  type="button"
                  className="arm-btn arm-btn--secondary"
                  onClick={() => setEditingAuth(selectedAuth)}
                >
                  ⚙️ Edit Full
                </button>
              </div>
            </header>

            {/* Diagnostic Signals Grid */}
            <div className="arm-signal-grid">
              <div className="arm-signal-card">
                <span className="arm-signal-title">NETWORK ROUTING</span>
                <strong className={selectedAuth.proxy_id ? 'is-green' : 'is-cyan'}>
                  {selectedAuth.proxy_id ? 'PROXIED' : 'DIRECT CONNECTION'}
                </strong>
                <small>{assignedProxy ? `${assignedProxy.ip} · ${assignedProxy.latencyMs}ms` : 'Local host gateway'}</small>
              </div>

              <div className="arm-signal-card">
                <span className="arm-signal-title">SESSION HEALTH</span>
                <strong className={`is-${selectedAuth.status}`}>
                  {selectedAuth.status.toUpperCase()}
                </strong>
                <small>Last probed: {selectedAuth.last_tested_at ? '18m ago' : 'Never'}</small>
              </div>

              <div className="arm-signal-card">
                <span className="arm-signal-title">WORKER ALLOCATION</span>
                <strong>
                  {selectedAuth.worker_shard !== null ? `SHARD 0${selectedAuth.worker_shard}` : 'UNASSIGNED'}
                </strong>
                <small>Dedicated rate-limit lease</small>
              </div>

              <div className="arm-signal-card">
                <span className="arm-signal-title">WALLET SAFEGUARD</span>
                <strong className={selectedAuth.spend ? 'is-warn' : 'is-green'}>
                  {selectedAuth.spend ? `SPENDER (${selectedAuth.spender_type?.toUpperCase()})` : 'LOCKED (NO SPEND)'}
                </strong>
                <small>{selectedAuth.spend ? 'Financial access permitted' : 'Protected from charges'}</small>
              </div>
            </div>

            {/* 1-Click Remediation Playbook */}
            <div className="arm-remediation-box">
              <div className="arm-remediation-header">
                <span className="arm-eyebrow">AUTOMATED REMEDIATION RUNBOOK</span>
                <h4>Recommended Recovery Action</h4>
              </div>

              {selectedAuth.age_verification_required || selectedAuth.status === 'challenge_required' ? (
                <div className="arm-remedy-content is-warn">
                  <div className="arm-remedy-text">
                    <strong>🔞 Upstream Age / Identity Verification Required</strong>
                    <p>
                      {selectedAuth.site} requires OAuth verification. Scraping tasks are paused for this
                      credential until passed.
                    </p>
                  </div>
                  <button
                    type="button"
                    className="arm-btn arm-btn--primary"
                    onClick={() => setVerifyingAuth({ auth: selectedAuth, kind: 'age' })}
                  >
                    Open Verification QR &amp; Link
                  </button>
                </div>
              ) : selectedAuth.status === 'expired' ? (
                <div className="arm-remedy-content is-danger">
                  <div className="arm-remedy-text">
                    <strong>⚠️ Stale Session Token Detected (HTTP 401 Unauthorized)</strong>
                    <p>
                      Paste a freshly captured cURL command from your browser DevTools below to instantly revive
                      this credential.
                    </p>
                    <div className="arm-inline-remedy-input">
                      <input
                        type="text"
                        value={inlineCurl}
                        onChange={(e) => setInlineCurl(e.target.value)}
                        placeholder="Paste cURL request (curl 'https://...')..."
                      />
                      <button
                        type="button"
                        className="arm-btn arm-btn--primary"
                        onClick={handleApplyInlineCurl}
                        disabled={!inlineCurl.trim()}
                      >
                        ⚡ Revive Token
                      </button>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="arm-remedy-content is-green">
                  <div className="arm-remedy-text">
                    <strong>✓ Session Healthy &amp; Ready for Scraping Fleet</strong>
                    <p>
                      Token passes all upstream cryptographic checks and rate-limit allocations.
                    </p>
                  </div>
                  <div className="arm-remedy-actions">
                    <button
                      type="button"
                      className="arm-btn arm-btn--secondary arm-btn--sm"
                      onClick={() => model.handleUpdateSubscriptions(selectedAuth.id)}
                    >
                      🔄 Refresh Subscriptions
                    </button>
                    <button
                      type="button"
                      className="arm-btn arm-btn--secondary arm-btn--sm"
                      onClick={() => model.handleScrapePaidContent(selectedAuth.id)}
                    >
                      💎 Scrape PPV Vault
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Token Secret Inspector */}
            <div className="arm-token-raw-box">
              <span className="arm-eyebrow">RAW PARAMETER PREVIEW:</span>
              <div className="arm-raw-lines">
                <div>
                  <span>Cookie:</span>
                  <code>{selectedAuth.cookie_preview}</code>
                </div>
                <div>
                  <span>User-Agent:</span>
                  <code>{selectedAuth.user_agent_preview}</code>
                </div>
                <div>
                  <span>Created:</span>
                  <code>{selectedAuth.created_at}</code>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
