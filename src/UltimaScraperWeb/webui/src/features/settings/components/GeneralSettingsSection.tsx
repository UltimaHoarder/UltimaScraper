import type { TopLevelSettingsKey } from '../lib/settingsUtils';

interface GeneralSettingsSectionProps {
  getCurrentValue: (key: TopLevelSettingsKey) => unknown;
  onChange: (key: TopLevelSettingsKey, value: unknown) => void;
}

export function GeneralSettingsSection({
  getCurrentValue,
  onChange,
}: GeneralSettingsSectionProps) {
  return (
    <div className="settings-section">
      <h2>General Settings</h2>

      <div className="setting-item">
        <label htmlFor="hostname">Hostname</label>
        <input
          id="hostname"
          disabled
          type="text"
          value={(getCurrentValue('hostname') as string) || ''}
          onChange={(event) => onChange('hostname', event.target.value)}
        />
        <span className="setting-description">Deployment setting; changes require a restart</span>
      </div>

      <div className="setting-item checkbox">
        <label>
          <input
            type="checkbox"
            checked={(getCurrentValue('infinite_loop') as boolean) || false}
            onChange={(event) => onChange('infinite_loop', event.target.checked)}
          />
          Infinite Loop
        </label>
        <span className="setting-description">Continue scraping in a loop</span>
      </div>

      <div className="setting-item checkbox">
        <label>
          <input
            type="checkbox"
            checked={(getCurrentValue('exit_on_completion') as boolean) || false}
            onChange={(event) => onChange('exit_on_completion', event.target.checked)}
          />
          Exit on Completion
        </label>
        <span className="setting-description">
          Exit the application when all jobs complete
        </span>
      </div>
    </div>
  );
}
