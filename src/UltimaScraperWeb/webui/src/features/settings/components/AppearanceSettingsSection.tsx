import { useTheme } from '../../../app/theme/useTheme';
import { useWebUIPreferences } from '../hooks/useWebUIPreferences';

export function AppearanceSettingsSection() {
  const { theme, themes, setTheme } = useTheme();
  const { preferences, updatePreferences } = useWebUIPreferences();
  const canSwitchThemes = themes.length > 1;

  return (
    <div className="settings-section" data-testid="appearance-settings-section">
      <h2>Appearance & UI Display</h2>
      <p className="section-description">
        Customize the visual presentation, interface density, telemetry refresh intervals, and alerts for this WebUI client.
      </p>

      {/* Theme Selection */}
      <div className="setting-item">
        <label htmlFor="theme-select">Active Theme</label>
        {canSwitchThemes ? (
          <select
            id="theme-select"
            value={theme.id}
            onChange={(event) => setTheme(event.target.value as typeof theme.id)}
          >
            {themes.map((availableTheme) => (
              <option key={availableTheme.id} value={availableTheme.id}>
                {availableTheme.label}
              </option>
            ))}
          </select>
        ) : (
          <div className="theme-static-value" style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--color-success)' }}>
            {theme.label}
          </div>
        )}
        <span className="setting-description">
          {canSwitchThemes
            ? 'Switch the active WebUI theme at runtime. The selection is stored in this browser.'
            : 'The current theme is registered and active. Additional themes will appear here automatically once they are added to the registry.'}
        </span>
        {theme.description ? (
          <span className="setting-description" style={{ fontStyle: 'italic', marginTop: '0.2rem' }}>
            {theme.description}
          </span>
        ) : null}
      </div>

      {/* Interface Density */}
      <div className="setting-item" style={{ gap: '0.75rem' }}>
        <h3 style={{ margin: 0 }}>Interface Density & Scale</h3>
        <span className="setting-description">
          Adjust component sizing and vertical spacing for compact monitors or dense telemetry workspaces.
        </span>

        <label style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', cursor: 'pointer', marginTop: '0.25rem' }}>
          <input
            type="checkbox"
            checked={preferences.compactMode}
            onChange={(e) => updatePreferences({ compactMode: e.target.checked })}
          />
          <div>
            <div style={{ fontSize: '0.82rem', fontWeight: 700 }}>Enable High-Density Compact Mode</div>
            <div style={{ fontSize: '0.72rem', color: 'var(--color-text-tertiary)' }}>
              Condenses tables, toolbars, and list item padding for dense data acquisition displays.
            </div>
          </div>
        </label>
      </div>

      {/* Telemetry Polling Frequency */}
      <div className="setting-item" style={{ gap: '0.75rem' }}>
        <h3 style={{ margin: 0 }}>Telemetry Polling Rate</h3>
        <span className="setting-description">
          Select how frequently live queue rates, worker metrics, and telemetry charts refresh from the active backend.
        </span>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '0.65rem', marginTop: '0.25rem' }}>
          {[
            { rate: 1000, label: 'Real-Time (1s)', desc: 'Immediate updates; highest network activity' },
            { rate: 3000, label: 'Balanced (3s)', desc: 'Recommended default; smooth monitoring' },
            { rate: 10000, label: 'Relaxed (10s)', desc: 'Lowest overhead; ideal for background tabs' },
          ].map(({ rate, label, desc }) => {
            const isSelected = preferences.telemetryPollRate === rate;
            return (
              <button
                key={rate}
                type="button"
                onClick={() => updatePreferences({ telemetryPollRate: rate })}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'flex-start',
                  padding: '0.75rem',
                  border: `1px solid ${isSelected ? 'rgb(var(--color-success-rgb) / 0.4)' : 'var(--ultimur-panel-border)'}`,
                  background: isSelected ? 'rgb(var(--color-success-rgb) / 0.08)' : 'rgba(255,255,255,0.02)',
                  color: isSelected ? 'var(--color-success)' : 'var(--color-text-primary)',
                  textAlign: 'left',
                  cursor: 'pointer',
                  borderRadius: 0,
                  transition: 'var(--transition-fast)',
                }}
              >
                <div style={{ fontSize: '0.82rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                  {label}
                </div>
                <div style={{ fontSize: '0.7rem', color: 'var(--color-text-tertiary)', marginTop: '0.25rem' }}>
                  {desc}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Toast Notification Preferences */}
      <div className="setting-item" style={{ gap: '0.75rem' }}>
        <h3 style={{ margin: 0 }}>Notifications & Alerts</h3>
        <span className="setting-description">
          Control toast notification durations and audible signals.
        </span>

        <div>
          <label htmlFor="toast-duration-select" style={{ display: 'block', marginBottom: '0.25rem' }}>
            Toast Notification Duration
          </label>
          <select
            id="toast-duration-select"
            value={preferences.toastDuration}
            onChange={(e) => updatePreferences({ toastDuration: Number(e.target.value) })}
          >
            <option value={2000}>Brief (2 seconds)</option>
            <option value={4000}>Standard (4 seconds)</option>
            <option value={8000}>Extended (8 seconds)</option>
            <option value={15000}>Persistent (15 seconds)</option>
          </select>
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', cursor: 'pointer', marginTop: '0.25rem' }}>
          <input
            type="checkbox"
            checked={preferences.enableSoundCues}
            onChange={(e) => updatePreferences({ enableSoundCues: e.target.checked })}
          />
          <div>
            <div style={{ fontSize: '0.82rem', fontWeight: 700 }}>Operational Audio Cues</div>
            <div style={{ fontSize: '0.72rem', color: 'var(--color-text-tertiary)' }}>
              Play subtle audio tones on completed job downloads or critical system warnings.
            </div>
          </div>
        </label>
      </div>
    </div>
  );
}
