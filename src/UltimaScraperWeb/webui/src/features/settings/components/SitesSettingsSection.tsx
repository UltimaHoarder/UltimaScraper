import type { SettingsResponse } from '../../../api/types/settings';

interface SitesSettingsSectionProps {
  settings: SettingsResponse;
  getDeepNestedValue: (section: string, subsection: string, key: string) => unknown;
  onNestedChange: (section: string, key: string, value: unknown) => void;
}

export function SitesSettingsSection({
  settings,
  getDeepNestedValue,
  onNestedChange,
}: SitesSettingsSectionProps) {
  return (
    <div className="settings-section">
      <h2>OnlyFans Settings</h2>

      <div className="setting-item">
        <label>Blacklist</label>
        <textarea
          value={
            ((getDeepNestedValue('sites', 'onlyfans', 'blacklists') as string[])
              ?? settings.sites?.onlyfans?.blacklists
              ?? []).join('\n')
          }
          onChange={(event) =>
            onNestedChange('sites', 'onlyfans', {
              ...(settings.sites?.onlyfans || {}),
              blacklists: event.target.value.split('\n').filter((value) => value.trim()),
            })}
          placeholder="One username per line"
          rows={5}
        />
        <span className="setting-description">Users to skip during scraping</span>
      </div>

      <h2>Fansly Settings</h2>

      <div className="setting-item">
        <label>Blacklist</label>
        <textarea
          value={
            ((getDeepNestedValue('sites', 'fansly', 'blacklists') as string[])
              ?? settings.sites?.fansly?.blacklists
              ?? []).join('\n')
          }
          onChange={(event) =>
            onNestedChange('sites', 'fansly', {
              ...(settings.sites?.fansly || {}),
              blacklists: event.target.value.split('\n').filter((value) => value.trim()),
            })}
          placeholder="One username per line"
          rows={5}
        />
        <span className="setting-description">Users to skip during scraping</span>
      </div>
    </div>
  );
}
