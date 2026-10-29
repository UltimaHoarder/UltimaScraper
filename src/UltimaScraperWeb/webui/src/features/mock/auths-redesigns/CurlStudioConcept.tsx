import { useState } from 'react';
import type { AuthCredential } from '../../../api/types/auths';
import type { AuthsMockModel } from './authsMockModel';

interface CurlStudioConceptProps {
  model: AuthsMockModel;
}

export function CurlStudioConcept({ model }: CurlStudioConceptProps) {
  const { sortedAuths, proxies, addAuth, updateAuth, showNotification, setTestingAuth } = model;

  const [inputMode, setInputMode] = useState<'curl' | 'json'>('curl');
  const [editorText, setEditorText] = useState(
    "curl 'https://onlyfans.com/api2/v2/users/me' \\\n  -H 'cookie: sess=9f82a104e883; auth_id=104218; csrf=882e912a' \\\n  -H 'x-bc: 20491823f990' \\\n  -H 'user-agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0.0.0'"
  );
  const [selectedProxyId, setSelectedProxyId] = useState('');
  const [revealTokens, setRevealTokens] = useState(false);
  const [inspectAuthId, setInspectAuthId] = useState<number>(sortedAuths[0]?.id ?? 101);

  const inspectedAuth = sortedAuths.find((a) => a.id === inspectAuthId) ?? sortedAuths[0];

  // Simulated parsed token data
  const parsedData = {
    site: editorText.includes('fansly') ? 'fansly' : 'onlyfans',
    authId: '104218',
    sess: '9f82a104e883',
    csrf: '882e912a',
    xBc: '20491823f990',
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0.0.0',
    jwtValidDays: 28,
  };

  const handleDeployNew = () => {
    const randomUid = Math.floor(Math.random() * 800000 + 100000);
    addAuth({
      site: parsedData.site,
      username: `studio_ingest_${randomUid.toString().slice(-4)}`,
      user_id: randomUid,
      status: 'valid',
      active: true,
      last_tested_at: new Date().toISOString(),
      created_at: new Date().toISOString(),
      cookie_preview: `sess=${parsedData.sess}...; auth_id=${randomUid}`,
      has_authorization: true,
      user_agent_preview: parsedData.userAgent,
      proxy_id: selectedProxyId || null,
      worker_shard: 1,
      is_age_verified: true,
      age_verification_required: false,
      spend: false,
      spender_type: null,
    });
  };

  const handlePatchInspected = () => {
    if (!inspectedAuth) return;
    updateAuth(inspectedAuth.id, {
      ...inspectedAuth,
      username: inspectedAuth.username ?? undefined,
      cookie: `sess=${parsedData.sess}; auth_id=${inspectedAuth.user_id}`,
      user_agent: parsedData.userAgent,
    });
    showNotification(`Patched @${inspectedAuth.username} with fresh session from editor!`, 'success');
  };

  const handleCopyAsCurl = (auth: AuthCredential) => {
    const curl = `curl 'https://${auth.site}.com/api2/v2/users/me' \\\n  -H 'cookie: ${auth.cookie_preview}' \\\n  -H 'user-agent: ${auth.user_agent_preview}'`;
    navigator.clipboard.writeText(curl);
    showNotification(`Copied session cURL command for @${auth.username} to clipboard!`, 'info');
  };

  return (
    <section className="arm-concept arm-studio" aria-label="Rapid cURL Ingestion Studio">
      {/* Top Banner Toolbar */}
      <div className="arm-studio-banner">
        <div>
          <span className="arm-eyebrow">DEVELOPER COCKPIT // PROTOCOL INGESTION</span>
          <h3>Rapid Ingestion Studio &amp; Token Inspector</h3>
        </div>
        <div className="arm-studio-banner-actions">
          <button
            type="button"
            className="arm-btn arm-btn--secondary"
            onClick={() =>
              setEditorText(
                "curl 'https://onlyfans.com/api2/v2/users/me' \\\n  -H 'cookie: sess=fresh_" +
                  Math.floor(Math.random() * 90000) +
                  "; auth_id=772190' \\\n  -H 'user-agent: Mozilla/5.0 Chrome/130.0'"
              )
            }
          >
            📋 Load Sample cURL
          </button>
          <button
            type="button"
            className="arm-btn arm-btn--primary"
            onClick={handleDeployNew}
          >
            ⚡ Ingest to Fleet
          </button>
        </div>
      </div>

      {/* 2-Pane Split Workspace */}
      <div className="arm-studio-grid">
        {/* Left Pane: Ingestion Studio */}
        <div className="arm-studio-pane arm-card">
          <header className="arm-pane-head">
            <div>
              <span className="arm-eyebrow">INPUT PROTOCOL // PARSER</span>
              <h4>Live Request Terminal</h4>
            </div>
            <div className="arm-mini-toggle">
              <button
                type="button"
                className={`arm-subtab ${inputMode === 'curl' ? 'is-active' : ''}`}
                onClick={() => setInputMode('curl')}
              >
                cURL (bash)
              </button>
              <button
                type="button"
                className={`arm-subtab ${inputMode === 'json' ? 'is-active' : ''}`}
                onClick={() => setInputMode('json')}
              >
                Raw JSON
              </button>
            </div>
          </header>

          <div className="arm-terminal-box">
            <textarea
              className="arm-terminal-input"
              rows={6}
              value={editorText}
              onChange={(e) => setEditorText(e.target.value)}
              placeholder="Paste raw cURL or JSON session payload here..."
              spellCheck={false}
            />
          </div>

          {/* Real-time Token Decoding Grid */}
          <div className="arm-decoder-card">
            <div className="arm-decoder-head">
              <span className="arm-eyebrow is-green">✓ LIVE TOKEN PARAMETER DECODER</span>
              <span className={`arm-platform-badge is-${parsedData.site}`}>
                DETECTED: {parsedData.site.toUpperCase()}
              </span>
            </div>

            <div className="arm-decoder-grid">
              <div className="arm-decoder-cell">
                <small>Session Token (sess)</small>
                <code>{parsedData.sess}</code>
              </div>
              <div className="arm-decoder-cell">
                <small>Numeric User ID</small>
                <code>{parsedData.authId}</code>
              </div>
              <div className="arm-decoder-cell">
                <small>x-bc Security Token</small>
                <code>{parsedData.xBc}</code>
              </div>
              <div className="arm-decoder-cell">
                <small>JWT Lifecycle</small>
                <span className="is-green">Valid (~{parsedData.jwtValidDays} days remaining)</span>
              </div>
            </div>

            {/* Ingestion Proxy Binding */}
            <div className="arm-field" style={{ marginTop: '0.75rem' }}>
              <label>Attach Network Gateway Proxy</label>
              <select
                value={selectedProxyId}
                onChange={(e) => setSelectedProxyId(e.target.value)}
                className="arm-select"
              >
                <option value="">Direct Connection (No Proxy)</option>
                {proxies.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} · {p.region} ({p.latencyMs}ms)
                  </option>
                ))}
              </select>
            </div>

            <div className="arm-decoder-actions">
              <button
                type="button"
                className="arm-btn arm-btn--primary"
                onClick={handleDeployNew}
              >
                + Register as New Account
              </button>
              {inspectedAuth && (
                <button
                  type="button"
                  className="arm-btn arm-btn--secondary"
                  onClick={handlePatchInspected}
                  title="Overwrite the selected account's credentials with these fresh tokens"
                >
                  🔄 Patch @{inspectedAuth.username}
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Right Pane: Active Token Registry & Inspector */}
        <div className="arm-studio-pane arm-card">
          <header className="arm-pane-head">
            <div>
              <span className="arm-eyebrow">REGISTRY // STORED CREDENTIALS</span>
              <h4>Fleet Token Inspector</h4>
            </div>
            <button
              type="button"
              className="arm-mini-btn arm-btn--quiet"
              onClick={() => setRevealTokens(!revealTokens)}
            >
              {revealTokens ? '🔒 Mask Secrets' : '👁️ Reveal Raw'}
            </button>
          </header>

          {/* Quick Account Pill Selector */}
          <div className="arm-account-chips-bar">
            {sortedAuths.map((auth) => (
              <button
                type="button"
                key={auth.id}
                className={`arm-account-chip ${auth.id === inspectAuthId ? 'is-active' : ''}`}
                onClick={() => setInspectAuthId(auth.id)}
              >
                <span className={`arm-dot is-${auth.status}`} />
                @{auth.username || auth.id}
              </button>
            ))}
          </div>

          {/* Detailed Inspector Card */}
          {inspectedAuth && (
            <div className="arm-inspector-card">
              <div className="arm-inspector-head">
                <div>
                  <span className={`arm-platform-badge is-${inspectedAuth.site.toLowerCase()}`}>
                    {inspectedAuth.site}
                  </span>
                  <h4>@{inspectedAuth.username}</h4>
                </div>
                <div className="arm-inspector-tags">
                  <span className={`arm-status-pill is-${inspectedAuth.status}`}>
                    {inspectedAuth.status.toUpperCase()}
                  </span>
                  <span className="arm-mono-tag">AUTH #{inspectedAuth.id}</span>
                </div>
              </div>

              {/* Secret Fields Table */}
              <div className="arm-inspector-table">
                <div className="arm-insp-row">
                  <span className="arm-insp-label">SESSION COOKIE</span>
                  <div className="arm-insp-val">
                    <code>
                      {revealTokens
                        ? `sess=9f82a104e88371829; auth_id=${inspectedAuth.user_id}; fp=browser_fp_hash_7719; csrf=882e912a`
                        : inspectedAuth.cookie_preview}
                    </code>
                  </div>
                </div>

                <div className="arm-insp-row">
                  <span className="arm-insp-label">USER-AGENT</span>
                  <div className="arm-insp-val">
                    <code>{inspectedAuth.user_agent_preview}</code>
                  </div>
                </div>

                <div className="arm-insp-row">
                  <span className="arm-insp-label">GATEWAY PROXY</span>
                  <div className="arm-insp-val">
                    <span>{inspectedAuth.proxy_id ? `🌐 ${inspectedAuth.proxy_id}` : 'Local Direct Gateway'}</span>
                  </div>
                </div>

                <div className="arm-insp-row">
                  <span className="arm-insp-label">FINGERPRINT CHECK</span>
                  <div className="arm-insp-val">
                    <span className="is-green">✓ User-Agent &amp; TLS Client Hello Match</span>
                  </div>
                </div>
              </div>

              {/* Inspector Operations Bar */}
              <div className="arm-inspector-actions">
                <button
                  type="button"
                  className="arm-btn arm-btn--secondary arm-btn--sm"
                  onClick={() => setTestingAuth(inspectedAuth)}
                >
                  🧪 Test Health
                </button>
                <button
                  type="button"
                  className="arm-btn arm-btn--secondary arm-btn--sm"
                  onClick={() => handleCopyAsCurl(inspectedAuth)}
                >
                  📋 Export cURL
                </button>
                <button
                  type="button"
                  className="arm-btn arm-btn--secondary arm-btn--sm"
                  onClick={() => model.handleUpdateSubscriptions(inspectedAuth.id)}
                >
                  🔄 Sync Subs
                </button>
                <button
                  type="button"
                  className="arm-btn arm-btn--primary arm-btn--sm"
                  onClick={() => model.setEditingAuth(inspectedAuth)}
                >
                  ⚙️ Edit Full
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
