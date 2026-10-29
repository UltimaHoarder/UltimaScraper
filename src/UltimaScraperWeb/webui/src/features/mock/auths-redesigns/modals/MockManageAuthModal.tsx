import { useState, useId } from 'react';
import type { AuthCredential, AuthEditRequest } from '../../../../api/types/auths';
import type { AuthsMockModel } from '../authsMockModel';

interface MockManageAuthModalProps {
  auth: AuthCredential;
  model: AuthsMockModel;
  onClose: () => void;
}

type ManageTab = 'refresh' | 'credentials' | 'account';

export function MockManageAuthModal({ auth, model, onClose }: MockManageAuthModalProps) {
  const [activeTab, setActiveTab] = useState<ManageTab>('credentials');
  const [refreshInputType, setRefreshInputType] = useState<'curl' | 'json'>('curl');
  const [pastedCommand, setPastedCommand] = useState('');
  const [parsedPreview, setParsedPreview] = useState<{
    cookie?: string;
    auth_id?: string;
    x_bc?: string;
    authorization?: string;
    user_agent?: string;
  } | null>(null);

  const [formData, setFormData] = useState<AuthEditRequest>({
    username: auth.username || '',
    cookie: auth.cookie_preview || '',
    x_bc: '20491823f990',
    authorization: auth.has_authorization ? 'Bearer eyJhbGciOiJIUzI1Ni...' : '',
    user_agent: auth.user_agent_preview || '',
    active: auth.active,
    proxy_id: auth.proxy_id,
    spend: auth.spend,
    spender_type: auth.spender_type || 'all',
  });

  const usernameId = useId();
  const cookieId = useId();
  const xBcId = useId();
  const authHeaderId = useId();
  const userAgentId = useId();
  const proxySelectId = useId();
  const spenderTypeId = useId();
  const refreshTextareaId = useId();

  const handleSimulateParse = (text: string) => {
    setPastedCommand(text);
    if (!text.trim()) {
      setParsedPreview(null);
      return;
    }
    // Simulate smart parser
    setParsedPreview({
      cookie: 'sess=9f82a104e; auth_id=' + auth.user_id + '; csrf=fresh_token_882',
      auth_id: String(auth.user_id),
      x_bc: ' fresh_xbc_' + Math.floor(Math.random() * 90000 + 10000),
      authorization: 'Bearer fresh_jwt_token_' + Math.floor(Math.random() * 90000),
      user_agent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0',
    });
  };

  const handleApplyParsed = () => {
    if (!parsedPreview) return;
    setFormData((prev) => ({
      ...prev,
      cookie: parsedPreview.cookie,
      x_bc: parsedPreview.x_bc,
      authorization: parsedPreview.authorization,
      user_agent: parsedPreview.user_agent,
    }));
    model.showNotification('Parsed cURL values applied to credentials form!', 'success');
    setActiveTab('credentials');
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    model.updateAuth(auth.id, formData);
    onClose();
  };

  return (
    <div className="arm-modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="arm-modal-card" onClick={(e) => e.stopPropagation()}>
        <header className="arm-modal-head">
          <div>
            <span className="arm-eyebrow">CREDENTIAL MANAGEMENT // #{auth.id}</span>
            <h3>Manage Auth: @{auth.username || `User #${auth.user_id}`}</h3>
          </div>
          <button type="button" className="arm-modal-close" onClick={onClose} aria-label="Close dialog">
            ✕
          </button>
        </header>

        {/* Top Status & Fast Action Bar */}
        <div className="arm-modal-status-bar">
          <div className="arm-modal-meta-chips">
            <span className={`arm-platform-badge is-${auth.site.toLowerCase()}`}>{auth.site}</span>
            <span className={`arm-status-pill is-${auth.status}`}>{auth.status.toUpperCase()}</span>
            <span className="arm-mono-tag">UID: {auth.user_id}</span>
            {auth.proxy_id && <span className="arm-mono-tag is-proxy">PROXY: {auth.proxy_id}</span>}
            {auth.worker_shard !== null && (
              <span className="arm-mono-tag is-shard">SHARD {auth.worker_shard}</span>
            )}
          </div>

          <div className="arm-modal-actions-rack">
            <button
              type="button"
              className="arm-mini-btn arm-btn--test"
              onClick={() => {
                onClose();
                model.setTestingAuth(auth);
              }}
            >
              🧪 Diagnostic Probe
            </button>
            <button
              type="button"
              className="arm-mini-btn"
              onClick={() => model.handleUpdateSubscriptions(auth.id)}
            >
              🔄 Sync Subs
            </button>
            <button
              type="button"
              className="arm-mini-btn"
              onClick={() => model.handleScrapePaidContent(auth.id)}
            >
              💎 Scrape PPV
            </button>
            {auth.age_verification_required && (
              <button
                type="button"
                className="arm-mini-btn arm-btn--warn"
                onClick={() => {
                  onClose();
                  model.setVerifyingAuth({ auth, kind: 'age' });
                }}
              >
                🔞 Verify Age
              </button>
            )}
          </div>
        </div>

        {/* Tab switcher */}
        <div className="arm-modal-tabs">
          <button
            type="button"
            className={`arm-modal-tab ${activeTab === 'credentials' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('credentials')}
          >
            01. Active Credentials
          </button>
          <button
            type="button"
            className={`arm-modal-tab ${activeTab === 'account' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('account')}
          >
            02. Routing &amp; Spender
          </button>
          <button
            type="button"
            className={`arm-modal-tab ${activeTab === 'refresh' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('refresh')}
          >
            03. Rapid Token Refresh
          </button>
        </div>

        <form onSubmit={handleSubmit} className="arm-modal-body">
          {/* TAB 1: CREDENTIALS */}
          {activeTab === 'credentials' && (
            <div className="arm-form-stack">
              <div className="arm-field-grid">
                <div className="arm-field">
                  <label htmlFor={usernameId}>Username / Creator Handle</label>
                  <input
                    id={usernameId}
                    type="text"
                    value={formData.username || ''}
                    onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                    placeholder="e.g. operator_main"
                  />
                </div>
                <div className="arm-field">
                  <label htmlFor={xBcId}>OnlyFans x-bc Token</label>
                  <input
                    id={xBcId}
                    type="text"
                    value={formData.x_bc || ''}
                    onChange={(e) => setFormData({ ...formData, x_bc: e.target.value })}
                    placeholder="x-bc hex token..."
                  />
                </div>
              </div>

              <div className="arm-field">
                <div className="arm-label-row">
                  <label htmlFor={cookieId}>Browser Session Cookie (Raw / Masked)</label>
                  <span className="arm-badge-hint">Required for authenticated scraper leases</span>
                </div>
                <textarea
                  id={cookieId}
                  rows={3}
                  value={formData.cookie || ''}
                  onChange={(e) => setFormData({ ...formData, cookie: e.target.value })}
                  placeholder="sess=...; auth_id=...; fp_id=..."
                />
              </div>

              <div className="arm-field">
                <label htmlFor={authHeaderId}>Authorization Bearer Header (Optional)</label>
                <input
                  id={authHeaderId}
                  type="text"
                  value={formData.authorization || ''}
                  onChange={(e) => setFormData({ ...formData, authorization: e.target.value })}
                  placeholder="Bearer eyJhbGciOi..."
                />
              </div>

              <div className="arm-field">
                <label htmlFor={userAgentId}>Browser User-Agent Header</label>
                <input
                  id={userAgentId}
                  type="text"
                  value={formData.user_agent || ''}
                  onChange={(e) => setFormData({ ...formData, user_agent: e.target.value })}
                  placeholder="Mozilla/5.0..."
                />
              </div>
            </div>
          )}

          {/* TAB 2: ROUTING & SPENDER */}
          {activeTab === 'account' && (
            <div className="arm-form-stack">
              <div className="arm-panel-box">
                <h4>Fleet Network Routing</h4>
                <p>Assign dedicated residential proxies to prevent account bans and rate throttling.</p>
                <div className="arm-field" style={{ marginTop: '0.75rem' }}>
                  <label htmlFor={proxySelectId}>Assigned Proxy Node</label>
                  <select
                    id={proxySelectId}
                    value={formData.proxy_id || ''}
                    onChange={(e) =>
                      setFormData({ ...formData, proxy_id: e.target.value ? e.target.value : null })
                    }
                  >
                    <option value="">Direct Connection (No Proxy)</option>
                    {model.proxies.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} · {p.region} ({p.latencyMs}ms)
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="arm-panel-box">
                <h4>Spender Policy &amp; Wallet Safeguard</h4>
                <p>Configure automated unlocking of paywalled posts, PPV mass messages, and tips.</p>

                <label className="arm-checkbox-row" style={{ marginTop: '0.75rem' }}>
                  <input
                    type="checkbox"
                    checked={formData.spend || false}
                    onChange={(e) => setFormData({ ...formData, spend: e.target.checked })}
                  />
                  <span>
                    <strong>Allow Automated Financial Spending</strong>
                    <small>Enable UltimaScraper to deduct platform wallet balance for paid media.</small>
                  </span>
                </label>

                {formData.spend && (
                  <div className="arm-field" style={{ marginTop: '0.75rem' }}>
                    <label htmlFor={spenderTypeId}>Spender Privilege Tier</label>
                    <select
                      id={spenderTypeId}
                      value={formData.spender_type || 'all'}
                      onChange={(e) => setFormData({ ...formData, spender_type: e.target.value })}
                    >
                      <option value="all">Unrestricted (Paid Media + PPV + Tipping)</option>
                      <option value="paid">PPV / Paid Posts Only (No Tipping)</option>
                      <option value="free">Free / Discounted Promotions Only</option>
                    </select>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* TAB 3: REFRESH IMPORT */}
          {activeTab === 'refresh' && (
            <div className="arm-form-stack">
              <div className="arm-refresh-header">
                <div>
                  <h4>Paste Fresh Request Payload</h4>
                  <p>Copy any authenticated request from Chrome DevTools (Copy as cURL) or token JSON.</p>
                </div>
                <div className="arm-mini-toggle">
                  <button
                    type="button"
                    className={`arm-subtab ${refreshInputType === 'curl' ? 'is-active' : ''}`}
                    onClick={() => setRefreshInputType('curl')}
                  >
                    cURL Command
                  </button>
                  <button
                    type="button"
                    className={`arm-subtab ${refreshInputType === 'json' ? 'is-active' : ''}`}
                    onClick={() => setRefreshInputType('json')}
                  >
                    Raw JSON
                  </button>
                </div>
              </div>

              <div className="arm-field">
                <label htmlFor={refreshTextareaId}>
                  Paste {refreshInputType === 'curl' ? 'cURL (bash)' : 'JSON Auth Object'}
                </label>
                <textarea
                  id={refreshTextareaId}
                  rows={4}
                  value={pastedCommand}
                  onChange={(e) => handleSimulateParse(e.target.value)}
                  placeholder={
                    refreshInputType === 'curl'
                      ? "curl 'https://onlyfans.com/api2/v2/users/me' -H 'cookie: sess=...' -H 'x-bc: ...'"
                      : '{"sess": "...", "auth_id": "...", "user_agent": "..."}'
                  }
                />
              </div>

              {parsedPreview && (
                <div className="arm-parsed-dock">
                  <div className="arm-parsed-top">
                    <span className="arm-eyebrow is-green">✓ PARSED REFRESH TOKEN DETECTED</span>
                    <button
                      type="button"
                      className="arm-btn arm-btn--primary arm-btn--sm"
                      onClick={handleApplyParsed}
                    >
                      Apply Parsed Values
                    </button>
                  </div>
                  <div className="arm-parsed-chips">
                    <span><b>UID:</b> {parsedPreview.auth_id}</span>
                    <span><b>Cookie:</b> {parsedPreview.cookie?.slice(0, 24)}...</span>
                    <span><b>x-bc:</b> {parsedPreview.x_bc}</span>
                  </div>
                </div>
              )}
            </div>
          )}

          <footer className="arm-modal-footer">
            <button type="button" className="arm-btn arm-btn--quiet" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="arm-btn arm-btn--primary">
              💾 Save Changes
            </button>
          </footer>
        </form>
      </div>
    </div>
  );
}
