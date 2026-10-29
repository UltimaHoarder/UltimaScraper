import { useTheme } from '../../../app/theme/useTheme';

export function ThemeSettingsSection() {
  const { theme, themes, setTheme } = useTheme();
  const canSwitchThemes = themes.length > 1;

  return (
    <div className="settings-section">
      <h2>Appearance</h2>

      <div className="setting-item">
        <label htmlFor="theme-select">Active theme</label>
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
          <div className="theme-static-value">{theme.label}</div>
        )}
        <span className="setting-description">
          {canSwitchThemes
            ? 'Switch the active WebUI theme at runtime. The selection is stored in this browser.'
            : 'The current theme is registered and active. Additional themes will appear here automatically once they are added to the registry.'}
        </span>
        {theme.description ? (
          <span className="setting-description">
            {theme.description}
          </span>
        ) : null}
      </div>
    </div>
  );
}
