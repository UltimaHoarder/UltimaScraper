import { TAB_META, type SettingsTab, type WebUISettingsTab } from '../lib/settingsUtils';

interface SettingsTabsProps {
  activeTab: SettingsTab;
  onTabChange: (tab: SettingsTab) => void;
  tabs?: SettingsTab[];
}

const DEFAULT_WEBUI_TABS: WebUISettingsTab[] = ['security', 'connections', 'appearance', 'developer', 'about'];

export function SettingsTabs({ activeTab, onTabChange, tabs = DEFAULT_WEBUI_TABS }: SettingsTabsProps) {
  return (
    <nav className="settings-tabs" aria-label="Settings categories">
      {tabs.map((tabKey) => {
        const meta = TAB_META[tabKey] ?? { label: tabKey, description: '' };
        return (
          <button
            key={tabKey}
            className={`tab ${activeTab === tabKey ? 'active' : ''}`}
            onClick={() => onTabChange(tabKey)}
            type="button"
          >
            <span className="tab-title">{meta.label}</span>
            <span className="tab-description">{meta.description}</span>
          </button>
        );
      })}
    </nav>
  );
}
