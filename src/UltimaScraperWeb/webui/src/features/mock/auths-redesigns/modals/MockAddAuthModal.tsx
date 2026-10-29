import { useState, useId } from 'react';
import type { AuthsMockModel } from '../authsMockModel';

interface MockAddAuthModalProps {
  model: AuthsMockModel;
  onClose: () => void;
}

export function MockAddAuthModal({ model, onClose }: MockAddAuthModalProps) {
  const [importTab, setImportTab] = useState<'curl' | 'json'>('curl');
  const [site, setSite] = useState<'onlyfans' | 'fansly'>('onlyfans');
  const [proxyId, setProxyId] = useState('');
  const [rawPayload, setRawPayload] = useState('');
  const [parsed, setParsed] = useState<{
    username: string;
    userId: number;
    cookie: string;
    xBc?: string;
    userAgent: string;
  } | null>(null);

  const siteSelectId = useId();
  const proxySelectId = useId();
  const rawTextareaId = useId();

  const handleTextChange = (text: string) => {
    setRawPayload(text);
    if (!text.trim()) {
      setParsed(null);
      return;
    }

    // Auto-detect json vs curl
    if (text.trim().startsWith('{')) {
      setImportTab('json');
    }

    const randomUid = Math.floor(Math.random() * 800000 + 100000);
    setParsed({
      username: `creator_${randomUid.toString().slice(0, 4)}`,
      userId: randomUid,
      cookie: 'sess=9f82a104e; auth_id=' + randomUid + '; fp=browser_fingerprint_v2',
      xBc: site === 'onlyfans' ? '20491823f990' : undefined,
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0',
    });
  };

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    const finalUsername = parsed?.username || `user_${Date.now().toString().slice(-4)}`;
    const finalUserId = parsed?.userId || Math.floor(Math.random() * 900000 + 100000);

    model.addAuth({
      site,
      username: finalUsername,
      user_id: finalUserId,
      status: 'valid',
      active: true,
      last_tested_at: new Date().toISOString(),
      created_at: new Date().toISOString(),
      cookie_preview: parsed?.cookie ? `${parsed.cookie.slice(0, 24)}...` : 'sess=fresh_auth_cookie...',
      has_authorization: true,
      user_agent_preview: parsed?.userAgent || 'Mozilla/5.0 Chrome/130.0',
      proxy_id: proxyId ? proxyId : null,
      worker_shard: (model.auths.length % 3) + 1,
      is_age_verified: true,
      age_verification_required: false,
      spend: false,
      spender_type: null,
    });
    onClose();
  };

  return (
    <div className="arm-modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="arm-modal-card arm-add-modal" onClick={(e) => e.stopPropagation()}>
        <header className="arm-modal-head">
          <div>
            <span className="arm-eyebrow">CREDENTIAL ONBOARDING // NEW SESSION</span>
            <h3>Add Authentication Account</h3>
          </div>
          <button type="button" className="arm-modal-close" onClick={onClose} aria-label="Close dialog">
            ✕
          </button>
        </header>

        <form onSubmit={handleAdd} className="arm-modal-body">
          {/* Target Platform & Proxy Selection */}
          <div className="arm-field-grid">
            <div className="arm-field">
              <label htmlFor={siteSelectId}>Target Platform Site *</label>
              <select
                id={siteSelectId}
                value={site}
                onChange={(e) => setSite(e.target.value as 'onlyfans' | 'fansly')}
              >
                <option value="onlyfans">OnlyFans (onlyfans.com)</option>
                <option value="fansly">Fansly (fansly.com)</option>
              </select>
            </div>

            <div className="arm-field">
              <label htmlFor={proxySelectId}>Assigned Proxy Node</label>
              <select
                id={proxySelectId}
                value={proxyId}
                onChange={(e) => setProxyId(e.target.value)}
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

          {/* Import tabs */}
          <div className="arm-mini-toggle" style={{ marginTop: '0.75rem', marginBottom: '0.5rem' }}>
            <button
              type="button"
              className={`arm-subtab ${importTab === 'curl' ? 'is-active' : ''}`}
              onClick={() => setImportTab('curl')}
            >
              cURL (bash) Import
            </button>
            <button
              type="button"
              className={`arm-subtab ${importTab === 'json' ? 'is-active' : ''}`}
              onClick={() => setImportTab('json')}
            >
              JSON Auth Object
            </button>
          </div>

          <div className="arm-field">
            <div className="arm-label-row">
              <label htmlFor={rawTextareaId}>
                Paste {importTab === 'curl' ? 'cURL Request' : 'JSON Configuration'} *
              </label>
              <span className="arm-badge-hint">
                DevTools Network ➔ Copy as cURL (bash)
              </span>
            </div>
            <textarea
              id={rawTextareaId}
              rows={4}
              required
              value={rawPayload}
              onChange={(e) => handleTextChange(e.target.value)}
              placeholder={
                importTab === 'curl'
                  ? "curl 'https://onlyfans.com/api2/v2/users/me' -H 'cookie: sess=...' -H 'user-agent: ...'"
                  : '{\n  "auth_id": "104218",\n  "sess": "9f82...",\n  "user_agent": "..."\n}'
              }
            />
          </div>

          {/* Live Extracted Values Preview */}
          {parsed && (
            <div className="arm-parsed-dock">
              <div className="arm-parsed-top">
                <span className="arm-eyebrow is-green">✓ CREDENTIAL EXTRACTED SUCCESSFULLY</span>
              </div>
              <div className="arm-parsed-grid">
                <div>
                  <small>Detected Handle</small>
                  <strong>@{parsed.username}</strong>
                </div>
                <div>
                  <small>Numeric User ID</small>
                  <strong>UID {parsed.userId}</strong>
                </div>
                <div>
                  <small>Session Cookie</small>
                  <code>{parsed.cookie.slice(0, 20)}...</code>
                </div>
                <div>
                  <small>Target Gateway</small>
                  <span>{proxyId ? proxyId : 'Direct (No Proxy)'}</span>
                </div>
              </div>
            </div>
          )}

          <footer className="arm-modal-footer">
            <button type="button" className="arm-btn arm-btn--quiet" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="arm-btn arm-btn--primary">
              ⚡ Onboard Credential to Fleet
            </button>
          </footer>
        </form>
      </div>
    </div>
  );
}
