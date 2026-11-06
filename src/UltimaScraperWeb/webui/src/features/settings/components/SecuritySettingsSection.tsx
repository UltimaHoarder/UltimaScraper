import { useState, type FormEvent } from 'react';
import { changeWebUIPassword, MIN_WEBUI_PASSWORD_LENGTH, revokeAllWebUISessions, signOutOfWebUI, WEBUI_ACCOUNT_NAME } from '../../../api/webui';

export function SecuritySettingsSection() {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isRevoking, setIsRevoking] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setSuccessMessage(null);
    setErrorMessage(null);

    if (newPassword.length < MIN_WEBUI_PASSWORD_LENGTH) {
      setErrorMessage(`Use a new password of at least ${MIN_WEBUI_PASSWORD_LENGTH} characters.`);
      return;
    }

    if (newPassword !== confirmPassword) {
      setErrorMessage('New passwords do not match.');
      return;
    }

    setIsSubmitting(true);
    try {
      await changeWebUIPassword(currentPassword, newPassword);
      setSuccessMessage('WebUI password updated. Every other browser has been signed out.');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to update WebUI password.');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRevokeOtherSessions = async () => {
    if (!window.confirm('Revoke all other active WebUI browser sessions? You will stay logged in on this browser.')) {
      return;
    }

    setIsRevoking(true);
    setSuccessMessage(null);
    setErrorMessage(null);

    try {
      await revokeAllWebUISessions();
      setSuccessMessage('All other WebUI sessions have been revoked.');
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Failed to revoke other sessions.');
    } finally {
      setIsRevoking(false);
    }
  };

  const handleSignOut = async () => {
    try {
      await signOutOfWebUI();
    } catch {
      // Continue to reload anyway
    }
    window.location.reload();
  };

  return (
    <div className="settings-section" data-testid="security-settings-section">
      <h2>Security & Access</h2>
      <p className="section-description">
        Manage WebUI authentication credentials, session tokens, and security policies for this dashboard.
      </p>

      {successMessage && (
        <div className="test-result success" role="status" style={{ marginBottom: '1rem' }}>
          ✓ {successMessage}
        </div>
      )}

      {errorMessage && (
        <div className="error-message" role="alert" style={{ marginBottom: '1rem' }}>
          {errorMessage}
        </div>
      )}

      {/* Change Password Form */}
      <form onSubmit={(e) => void handleSubmit(e)} className="setting-item" style={{ gap: '0.85rem' }}>
        <h3 style={{ margin: 0 }}>Change WebUI Password</h3>
        <span className="setting-description">
          The WebUI password restricts access to this web application and all connected scraper backends.
        </span>

        <input type="text" name="username" autoComplete="username" value={WEBUI_ACCOUNT_NAME} readOnly hidden />

        <div>
          <label htmlFor="current-password" style={{ display: 'block', marginBottom: '0.25rem' }}>
            Current Password
          </label>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <input
              id="current-password"
              name="current-password"
              type={showCurrent ? 'text' : 'password'}
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              placeholder="Enter current password"
              autoComplete="current-password"
            />
            <button
              type="button"
              className="btn-reset"
              onClick={() => setShowCurrent(!showCurrent)}
              style={{ whiteSpace: 'nowrap' }}
            >
              {showCurrent ? 'Hide' : 'Show'}
            </button>
          </div>
        </div>

        <div>
          <label htmlFor="new-password" style={{ display: 'block', marginBottom: '0.25rem' }}>
            New Password
          </label>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <input
              id="new-password"
              name="new-password"
              type={showNew ? 'text' : 'password'}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder={`At least ${MIN_WEBUI_PASSWORD_LENGTH} characters`}
              autoComplete="new-password"
            />
            <button
              type="button"
              className="btn-reset"
              onClick={() => setShowNew(!showNew)}
              style={{ whiteSpace: 'nowrap' }}
            >
              {showNew ? 'Hide' : 'Show'}
            </button>
          </div>
        </div>

        <div>
          <label htmlFor="confirm-password" style={{ display: 'block', marginBottom: '0.25rem' }}>
            Confirm New Password
          </label>
          <input
            id="confirm-password"
            name="confirm-password"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder="Re-enter new password"
            autoComplete="new-password"
          />
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
          <button
            type="submit"
            className="btn-save"
            disabled={isSubmitting || !newPassword || !confirmPassword}
          >
            {isSubmitting ? 'Updating Password…' : 'Update Password'}
          </button>
        </div>
      </form>

      {/* Session Management */}
      <div className="setting-item" style={{ gap: '0.85rem' }}>
        <h3 style={{ margin: 0 }}>Active Session & Controls</h3>
        <span className="setting-description">
          Review your current authentication state or invalidate remote active sessions across other devices.
        </span>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.75rem' }}>
          <div style={{ padding: '0.75rem', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--ultimur-panel-border)' }}>
            <div style={{ fontSize: '0.65rem', textTransform: 'uppercase', color: 'var(--color-text-tertiary)', letterSpacing: '0.05em' }}>
              Session Status
            </div>
            <div style={{ fontSize: '0.88rem', fontWeight: 700, color: 'var(--color-success)', marginTop: '0.25rem' }}>
              Authenticated
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--color-text-secondary)', marginTop: '0.2rem' }}>
              30-day rolling session token
            </div>
          </div>

          <div style={{ padding: '0.75rem', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--ultimur-panel-border)' }}>
            <div style={{ fontSize: '0.65rem', textTransform: 'uppercase', color: 'var(--color-text-tertiary)', letterSpacing: '0.05em' }}>
              Cookie Security
            </div>
            <div style={{ fontSize: '0.88rem', fontWeight: 700, color: 'var(--color-text-primary)', marginTop: '0.25rem' }}>
              SameSite=Strict
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--color-text-secondary)', marginTop: '0.2rem' }}>
              HttpOnly · Cross-origin protected
            </div>
          </div>

          <div style={{ padding: '0.75rem', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--ultimur-panel-border)' }}>
            <div style={{ fontSize: '0.65rem', textTransform: 'uppercase', color: 'var(--color-text-tertiary)', letterSpacing: '0.05em' }}>
              Brute-Force Guard
            </div>
            <div style={{ fontSize: '0.88rem', fontWeight: 700, color: 'var(--color-text-primary)', marginTop: '0.25rem' }}>
              Rate Limiter Active
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--color-text-secondary)', marginTop: '0.2rem' }}>
              5 failed attempts / 60s window
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem', marginTop: '0.5rem' }}>
          <button
            type="button"
            className="btn-reset"
            onClick={() => void handleRevokeOtherSessions()}
            disabled={isRevoking}
          >
            {isRevoking ? 'Revoking Sessions…' : 'Revoke Other Sessions'}
          </button>
          <button
            type="button"
            className="btn-delete"
            onClick={() => void handleSignOut()}
          >
            Sign Out of WebUI
          </button>
        </div>
      </div>
    </div>
  );
}
