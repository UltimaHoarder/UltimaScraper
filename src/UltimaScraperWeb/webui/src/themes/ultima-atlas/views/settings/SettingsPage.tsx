import { useSearchParams, NavLink } from 'react-router-dom';
import { WorkspacePageHeader } from '../../../../shared/ui/WorkspacePageHeader';

import { SecuritySettingsSection } from '../../../../features/settings/components/SecuritySettingsSection';
import { ConnectionsSettingsSection } from '../../../../features/settings/components/ConnectionsSettingsSection';
import { AppearanceSettingsSection } from '../../../../features/settings/components/AppearanceSettingsSection';
import { DeveloperSettingsSection } from '../../../../features/settings/components/DeveloperSettingsSection';
import { AboutSettingsSection } from '../../../../features/settings/components/AboutSettingsSection';
import { SettingsTabs } from '../../../../features/settings/components/SettingsTabs';
import { useAppBootstrap } from '../../../../app/bootstrap/AppBootstrapProvider';
import type { SettingsTab, WebUISettingsTab } from '../../../../features/settings/lib/settingsUtils';
import './SettingsPage.css';

const VALID_TABS: WebUISettingsTab[] = ['security', 'connections', 'appearance', 'developer', 'about'];

export function SettingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { statusText } = useAppBootstrap();

  const tabParam = searchParams.get('tab') as WebUISettingsTab | null;
  const activeTab: WebUISettingsTab = tabParam && VALID_TABS.includes(tabParam) ? tabParam : 'security';

  const handleTabChange = (nextTab: SettingsTab) => {
    if (VALID_TABS.includes(nextTab as WebUISettingsTab)) {
      setSearchParams({ tab: nextTab });
    }
  };

  return (
    <div className="settings-page ultimur-settings" data-testid="webui-settings-page">
      <WorkspacePageHeader
        eyebrow="Configuration / Platform Deck"
        title="Settings"
        subtitle="Configure WebUI security credentials, backend fleet connections, appearance, and local diagnostics."
        icon="⚙"
        meta={(
          <div className="settings-topbar__actions">
            <span className="settings-topbar__status settings-topbar__status--ok">
              <span className="settings-topbar__dot" />
              WebUI Active
            </span>
            <span className="settings-topbar__pill" title={statusText}>
              {statusText}
            </span>
            <NavLink
              to="/system"
              className="btn-save"
              style={{
                textDecoration: 'none',
                padding: '0.35rem 0.75rem',
                fontSize: '0.7rem',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '0.35rem',
              }}
              title="Configure drives, worker pools, database mappings, and site parameters per backend node"
            >
              System Fleet (Scraper Config) →
            </NavLink>
          </div>
        )}
      />

      <div className="settings-shell">
        <SettingsTabs
          activeTab={activeTab}
          onTabChange={handleTabChange}
          tabs={VALID_TABS}
        />

        <div className="settings-content">
          {activeTab === 'security' && <SecuritySettingsSection />}
          {activeTab === 'connections' && <ConnectionsSettingsSection />}
          {activeTab === 'appearance' && <AppearanceSettingsSection />}
          {activeTab === 'developer' && <DeveloperSettingsSection />}
          {activeTab === 'about' && <AboutSettingsSection />}
        </div>
      </div>
    </div>
  );
}

export default SettingsPage;
