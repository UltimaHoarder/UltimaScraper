import { useState } from 'react';
import type { AuthsMockModel } from './authsMockModel';

interface VerificationRunwayConceptProps {
  model: AuthsMockModel;
}

export function VerificationRunwayConcept({ model }: VerificationRunwayConceptProps) {
  const { sortedAuths, updateAuth, showNotification, setTestingAuth } = model;
  const [selectedAuthId, setSelectedAuthId] = useState<number>(104); // Default to sky_crawler_uk which needs age verification
  const [copied, setCopied] = useState(false);

  const selectedAuth = sortedAuths.find((a) => a.id === selectedAuthId) ?? sortedAuths[0];

  const verificationUrl = `https://${selectedAuth?.site || 'onlyfans'}.com/api2/v2/users/me/verify?session=${selectedAuth?.id}&token=8f921a`;

  const handleCopy = () => {
    navigator.clipboard.writeText(verificationUrl);
    setCopied(true);
    showNotification('Verification challenge link copied to clipboard!', 'success');
    setTimeout(() => setCopied(false), 2500);
  };

  const handlePassVerification = () => {
    if (!selectedAuth) return;
    updateAuth(selectedAuth.id, {
      ...selectedAuth,
      username: selectedAuth.username || undefined,
    });
    showNotification(`✓ Compliance challenge cleared for @${selectedAuth.username}! Credential is now valid.`, 'success');
  };

  return (
    <section className="arm-concept arm-runway" aria-label="Identity and Verification Runway">
      {/* 4-Stage Compliance Workflow Runway */}
      <div className="arm-stepper-bar">
        <div className="arm-step-node is-done">
          <span className="arm-node-num">01</span>
          <div>
            <strong>Session Ingestion</strong>
            <small>cURL / JSON Tokens</small>
          </div>
        </div>
        <span className="arm-step-arrow">➔</span>

        <div className="arm-step-node is-done">
          <span className="arm-node-num">02</span>
          <div>
            <strong>Proxy Gateway Binding</strong>
            <small>Dedicated IP Tunnel</small>
          </div>
        </div>
        <span className="arm-step-arrow">➔</span>

        <div className="arm-step-node is-active">
          <span className="arm-node-num">03</span>
          <div>
            <strong>Compliance Clearance</strong>
            <small>Age &amp; Identity Biometrics</small>
          </div>
        </div>
        <span className="arm-step-arrow">➔</span>

        <div className="arm-step-node">
          <span className="arm-node-num">04</span>
          <div>
            <strong>Fleet Dispatch</strong>
            <small>Worker Shards Active</small>
          </div>
        </div>
      </div>

      {/* Main 2-Column Runway Layout */}
      <div className="arm-runway-grid">
        {/* Left Column: Accounts Clearance Queue */}
        <div className="arm-runway-queue">
          <header className="arm-pane-head">
            <div>
              <span className="arm-eyebrow">COMPLIANCE // ACCOUNTS QUEUE</span>
              <h4>Verification Pipeline ({sortedAuths.length})</h4>
            </div>
            <button
              type="button"
              className="arm-mini-btn arm-btn--primary"
              onClick={() => model.setShowAddModal(true)}
            >
              + Onboard
            </button>
          </header>

          <div className="arm-queue-cards">
            {sortedAuths.map((auth) => {
              const isSelected = auth.id === selectedAuthId;
              const hasChallenge = auth.age_verification_required || auth.status === 'challenge_required';
              return (
                <div
                  key={auth.id}
                  className={`arm-queue-card ${isSelected ? 'is-selected' : ''} ${hasChallenge ? 'is-flagged' : ''}`}
                  onClick={() => setSelectedAuthId(auth.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') setSelectedAuthId(auth.id);
                  }}
                >
                  <div className="arm-queue-card-top">
                    <span className={`arm-platform-badge is-${auth.site.toLowerCase()}`}>
                      {auth.site}
                    </span>
                    <strong>@{auth.username || `User #${auth.user_id}`}</strong>
                    <span className={`arm-status-pill is-${auth.status}`}>
                      {auth.status.toUpperCase()}
                    </span>
                  </div>

                  <div className="arm-queue-card-meta">
                    {hasChallenge ? (
                      <span className="arm-warn-tag">🔞 Age Verification Required</span>
                    ) : (
                      <span className="arm-green-tag">✓ Fully Cleared &amp; Verified</span>
                    )}
                    <span>UID: {auth.user_id}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Column: Interactive Mobile Handoff & Compliance Hub */}
        {selectedAuth && (
          <div className="arm-runway-hub arm-card">
            <header className="arm-dossier-head">
              <div>
                <span className="arm-eyebrow">MOBILE HANDOFF HUB // COMPLIANCE STATION</span>
                <h3>Clearance Station: @{selectedAuth.username}</h3>
                <p>
                  Platform: <strong>{selectedAuth.site}</strong> · Auth ID: <strong>#{selectedAuth.id}</strong>
                </p>
              </div>

              <div className="arm-dossier-head-actions">
                <button
                  type="button"
                  className="arm-btn arm-btn--secondary"
                  onClick={() => setTestingAuth(selectedAuth)}
                >
                  🧪 Test Health
                </button>
                <button
                  type="button"
                  className="arm-btn arm-btn--primary"
                  onClick={handlePassVerification}
                >
                  ✓ Mark Cleared
                </button>
              </div>
            </header>

            {/* Embedded QR Code Mobile Handoff Section */}
            <div className="arm-hub-qr-section">
              <div className="arm-qr-frame">
                <svg viewBox="0 0 160 160" width="150" height="150" className="arm-qr-svg">
                  <rect width="160" height="160" fill="#141819" rx="8" />
                  <rect x="15" y="15" width="40" height="40" fill="none" stroke="#24aac3" strokeWidth="6" />
                  <rect x="25" y="25" width="20" height="20" fill="#24aac3" />
                  <rect x="105" y="15" width="40" height="40" fill="none" stroke="#24aac3" strokeWidth="6" />
                  <rect x="115" y="25" width="20" height="20" fill="#24aac3" />
                  <rect x="15" y="105" width="40" height="40" fill="none" stroke="#24aac3" strokeWidth="6" />
                  <rect x="25" y="115" width="20" height="20" fill="#24aac3" />
                  <rect x="68" y="20" width="8" height="8" fill="#55d688" />
                  <rect x="84" y="20" width="8" height="8" fill="#24aac3" />
                  <rect x="68" y="36" width="8" height="8" fill="#bec8c9" />
                  <rect x="84" y="36" width="8" height="8" fill="#55d688" />
                  <rect x="68" y="52" width="24" height="8" fill="#24aac3" />
                  <rect x="20" y="68" width="120" height="8" fill="#bec8c9" />
                  <rect x="20" y="84" width="20" height="8" fill="#24aac3" />
                  <rect x="50" y="84" width="40" height="8" fill="#55d688" />
                  <rect x="100" y="84" width="40" height="8" fill="#24aac3" />
                  <rect x="68" y="105" width="24" height="24" fill="#55d688" />
                  <rect x="105" y="105" width="16" height="16" fill="#bec8c9" />
                </svg>
              </div>

              <div className="arm-hub-qr-details">
                <h4>Scan to Complete Verification on Mobile</h4>
                <p>
                  Point your phone's camera at this QR code to complete age verification or biometric facial selfie
                  scans directly in your phone's browser.
                </p>
                <div className="arm-qr-badges">
                  <span className="arm-mono-tag">TLS Session Pinning</span>
                  <span className="arm-mono-tag">Instant Callback Detection</span>
                </div>
                <div className="arm-copy-input-group" style={{ marginTop: '0.75rem' }}>
                  <input type="text" readOnly value={verificationUrl} />
                  <button type="button" className="arm-btn arm-btn--secondary" onClick={handleCopy}>
                    {copied ? '✓ Copied' : '📋 Copy URL'}
                  </button>
                  <a
                    href={verificationUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="arm-btn arm-btn--primary"
                    style={{ textDecoration: 'none' }}
                  >
                    ↗ Open
                  </a>
                </div>
              </div>
            </div>

            {/* Subscription & Fleet Dossier */}
            <div className="arm-hub-subscription-box">
              <div className="arm-hub-sub-head">
                <div>
                  <span className="arm-eyebrow">FLEET TELEMETRY // SUBSCRIPTION LEASE</span>
                  <h4>Linked Creator Subscriptions (34 Creators Synced)</h4>
                </div>
                <div style={{ display: 'flex', gap: '6px' }}>
                  <button
                    type="button"
                    className="arm-btn arm-btn--secondary arm-btn--sm"
                    onClick={() => model.handleUpdateSubscriptions(selectedAuth.id)}
                  >
                    🔄 Sync Subscriptions
                  </button>
                  <button
                    type="button"
                    className="arm-btn arm-btn--secondary arm-btn--sm"
                    onClick={() => model.handleScrapePaidContent(selectedAuth.id)}
                  >
                    💎 Scrape Paid PPV
                  </button>
                </div>
              </div>

              <div className="arm-sub-pills-wrap">
                <span className="arm-sub-pill">@luna_archive</span>
                <span className="arm-sub-pill">@sarah_sky</span>
                <span className="arm-sub-pill">@nova_star</span>
                <span className="arm-sub-pill">@aurora_sky</span>
                <span className="arm-sub-pill">@cyber_vixen</span>
                <span className="arm-sub-pill">+29 more</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
