import { useWebUIPreferences } from '../hooks/useWebUIPreferences';

export function DeveloperSettingsSection() {
  const { preferences, updatePreferences } = useWebUIPreferences();

  return (
    <div className="settings-section" data-testid="developer-settings-section">
      <h2>Developer</h2>
      <p className="section-description">
        Tools for building and testing the WebUI. This choice is stored in this browser.
      </p>

      <div className="setting-item checkbox">
        <label>
          <input
            type="checkbox"
            checked={preferences.devMode}
            onChange={(event) => updatePreferences({ devMode: event.target.checked })}
          />
          Developer mode
        </label>
        <span className="setting-description">
          Runs installed plugins and shows the Plugins page and the design lab mocks. Off by default.
        </span>
      </div>
    </div>
  );
}
