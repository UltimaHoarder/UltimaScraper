import { useState } from 'react';
import type { AuthCredential } from '../../../../api/types/auths';
import type { AuthsMockModel } from '../authsMockModel';

interface MockVerificationModalProps {
  auth: AuthCredential;
  kind: 'age' | 'identity';
  model: AuthsMockModel;
  onClose: () => void;
}

export function MockVerificationModal({
  auth,
  kind,
  model,
  onClose,
}: MockVerificationModalProps) {
  const [copied, setCopied] = useState(false);

  const verificationUrl =
    kind === 'age'
      ? `https://onlyfans.com/api2/v2/users/me/verify/age?session_ref=${auth.id}&auth_token=8f921a`
      : `https://onlyfans.com/api2/v2/users/me/verify/identity?vendor=yoti&auth_id=${auth.user_id}`;

  const handleCopy = () => {
    navigator.clipboard.writeText(verificationUrl);
    setCopied(true);
    model.showNotification('Verification URL copied to clipboard!', 'success');
    setTimeout(() => setCopied(false), 2500);
  };

  const handleComplete = () => {
    model.updateAuth(auth.id, {
      ...auth,
      username: auth.username || undefined,
    });
    // Mark as verified
    model.showNotification(
      `✓ Verification challenge marked completed for @${auth.username || auth.id}! Credential is now valid.`,
      'success'
    );
    onClose();
  };

  return (
    <div className="arm-modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="arm-modal-card arm-verify-modal" onClick={(e) => e.stopPropagation()}>
        <header className="arm-modal-head">
          <div>
            <span className="arm-eyebrow">
              {kind === 'age' ? '🔞 COMPLIANCE // AGE VERIFICATION' : '🪪 COMPLIANCE // IDENTITY BIOMETRICS'}
            </span>
            <h3>{kind === 'age' ? 'Age Verification Required' : 'Identity Verification Required'}</h3>
          </div>
          <button type="button" className="arm-modal-close" onClick={onClose} aria-label="Close dialog">
            ✕
          </button>
        </header>

        <div className="arm-modal-body">
          <p className="arm-verify-intro">
            Upstream platform <strong>{auth.site}</strong> has issued a mandatory verification gate for{' '}
            <strong>@{auth.username || `User #${auth.user_id}`}</strong>. Scraping tasks are paused until
            this account completes the OAuth compliance challenge.
          </p>

          {/* QR Code Card */}
          <div className="arm-qr-card">
            <div className="arm-qr-frame">
              {/* Scalable SVG QR Code Representation */}
              <svg viewBox="0 0 160 160" width="140" height="140" className="arm-qr-svg">
                <rect width="160" height="160" fill="#141819" rx="8" />
                {/* QR Target 1 */}
                <rect x="15" y="15" width="40" height="40" fill="none" stroke="#24aac3" strokeWidth="6" />
                <rect x="25" y="25" width="20" height="20" fill="#24aac3" />
                {/* QR Target 2 */}
                <rect x="105" y="15" width="40" height="40" fill="none" stroke="#24aac3" strokeWidth="6" />
                <rect x="115" y="25" width="20" height="20" fill="#24aac3" />
                {/* QR Target 3 */}
                <rect x="15" y="105" width="40" height="40" fill="none" stroke="#24aac3" strokeWidth="6" />
                <rect x="25" y="115" width="20" height="20" fill="#24aac3" />
                {/* Dense Matrix Dots */}
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
                <rect x="130" y="105" width="15" height="40" fill="#24aac3" />
                <rect x="105" y="130" width="16" height="15" fill="#55d688" />
              </svg>
            </div>

            <div className="arm-qr-instructions">
              <h4>Mobile Handoff Recommended</h4>
              <p>
                Open your smartphone's camera app and scan this QR code to quickly upload ID documents or complete
                facial biometrics in the mobile browser.
              </p>
              <div className="arm-qr-badges">
                <span className="arm-mono-tag">TLS Encrypted</span>
                <span className="arm-mono-tag">Direct Vendor Gate</span>
              </div>
            </div>
          </div>

          {/* Direct Link & Copy */}
          <div className="arm-field" style={{ marginTop: '1rem' }}>
            <label>Direct Browser Verification URL</label>
            <div className="arm-copy-input-group">
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
                ↗ Open Link
              </a>
            </div>
          </div>
        </div>

        <footer className="arm-modal-footer">
          <button type="button" className="arm-btn arm-btn--quiet" onClick={onClose}>
            Close
          </button>
          <button
            type="button"
            className="arm-btn arm-btn--primary"
            onClick={handleComplete}
          >
            ✓ Mark Verification Completed
          </button>
        </footer>
      </div>
    </div>
  );
}
