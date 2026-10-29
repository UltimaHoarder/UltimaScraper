import { useState } from 'react';
import { useAppBootstrap } from '../../../app/bootstrap/AppBootstrapProvider';
import { useWebUIPreferences } from '../hooks/useWebUIPreferences';

export function AboutSettingsSection() {
  const { bootstrap, statusText } = useAppBootstrap();
  const { resetPreferences } = useWebUIPreferences();
  const [resetMessage, setResetMessage] = useState<string | null>(null);

  const handleResetPreferences = () => {
    if (!window.confirm('Reset all custom WebUI preferences (theme, density, polling rates) to factory defaults?')) {
      return;
    }
    resetPreferences();
    setResetMessage('Preferences have been restored to defaults.');
    setTimeout(() => setResetMessage(null), 3000);
  };

  const handleClearCache = () => {
    if (!window.confirm('Clear all local UI cache (saved filters, card layouts, column sizes)? Backend scraping data and credentials are not touched.')) {
      return;
    }
    try {
      const keysToKeep = new Set(['usr_webui_session', 'usr_webui_preferences']);
      const allKeys = Object.keys(localStorage);
      for (const key of allKeys) {
        if (!keysToKeep.has(key)) {
          localStorage.removeItem(key);
        }
      }
      setResetMessage('Local browser cache cleared. Refreshing view…');
      setTimeout(() => window.location.reload(), 1000);
    } catch {
      setResetMessage('Could not clear local cache.');
    }
  };

  return (
    <div className="settings-section" data-testid="about-settings-section">
      <h2>About & Diagnostics</h2>
      <p className="section-description">
        System versions, environment diagnostics, connected cluster topology, and local workspace storage.
      </p>

      {resetMessage && (
        <div className="test-result success" role="status">
          ✓ {resetMessage}
        </div>
      )}

      {/* System Telemetry & Identifiers */}
      <div className="setting-item" style={{ gap: '0.85rem' }}>
        <h3 style={{ margin: 0 }}>System Telemetry & Identity</h3>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '0.75rem' }}>
          <div style={{ padding: '0.75rem', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--ultimur-panel-border)' }}>
            <div style={{ fontSize: '0.65rem', textTransform: 'uppercase', color: 'var(--color-text-tertiary)', letterSpacing: '0.05em' }}>
              WebUI Client
            </div>
            <div style={{ fontSize: '0.88rem', fontWeight: 700, color: 'var(--color-text-primary)', marginTop: '0.25rem' }}>
              Ultima Atlas UI
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--color-text-secondary)', marginTop: '0.2rem' }}>
              React 19 · Vite SPA
            </div>
          </div>

          <div style={{ padding: '0.75rem', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--ultimur-panel-border)' }}>
            <div style={{ fontSize: '0.65rem', textTransform: 'uppercase', color: 'var(--color-text-tertiary)', letterSpacing: '0.05em' }}>
              Backend Node
            </div>
            <div style={{ fontSize: '0.88rem', fontWeight: 700, color: 'var(--color-success)', marginTop: '0.25rem' }}>
              {bootstrap?.backend_id ?? 'Unknown Node'}
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--color-text-secondary)', marginTop: '0.2rem' }}>
              v{bootstrap?.version ?? 'N/A'} · Host: {bootstrap?.hostname ?? 'local'}
            </div>
          </div>

          <div style={{ padding: '0.75rem', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--ultimur-panel-border)' }}>
            <div style={{ fontSize: '0.65rem', textTransform: 'uppercase', color: 'var(--color-text-tertiary)', letterSpacing: '0.05em' }}>
              Runtime Status
            </div>
            <div style={{ fontSize: '0.88rem', fontWeight: 700, color: 'var(--color-text-primary)', marginTop: '0.25rem' }}>
              {statusText}
            </div>
            <div style={{ fontSize: '0.72rem', color: 'var(--color-text-secondary)', marginTop: '0.2rem' }}>
              Deployment Health: Active
            </div>
          </div>
        </div>
      </div>

      {/* Local Storage & Browser Diagnostics */}
      <div className="setting-item" style={{ gap: '0.85rem' }}>
        <h3 style={{ margin: 0 }}>Local Storage & Client Cache</h3>
        <span className="setting-description">
          This browser stores cached UI filters, table column widths, and interface preferences locally.
        </span>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem', marginTop: '0.25rem' }}>
          <button
            type="button"
            className="btn-reset"
            onClick={handleResetPreferences}
          >
            Reset UI Preferences
          </button>
          <button
            type="button"
            className="btn-reset"
            onClick={handleClearCache}
          >
            Clear Browser UI Cache
          </button>
        </div>
      </div>
    </div>
  );
}
