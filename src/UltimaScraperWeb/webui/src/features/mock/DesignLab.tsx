import { useSearchParams } from 'react-router-dom';
import { MpsRedesignsMock } from './mps-redesigns/MpsRedesignsMock';
import { WebhooksRedesignsMock } from './webhooks-redesigns/WebhooksRedesignsMock';
import { PluginsRedesignsMock } from './plugins-redesigns/PluginsRedesignsMock';
import { UsersRedesignsMock } from './users-redesigns/UsersRedesignsMock';
import { ChartsShowcaseMock } from './charts-showcase/ChartsShowcaseMock';
import { DrivesRedesignsMock } from './drives-redesigns/DrivesRedesignsMock';
import { ToolsRedesignsMock } from './tools-redesigns/ToolsRedesignsMock';
import { DashboardRedesignsMock } from './dashboard-redesigns/DashboardRedesignsMock';
import { JobCreatorRedesignsMock } from './job-creator-redesigns/JobCreatorRedesignsMock';
import { AuthsRedesignsMock } from './auths-redesigns/AuthsRedesignsMock';
import { WorkspacePageHeader } from '../../shared/ui/WorkspacePageHeader';
import './DesignLab.css';

/** Design lab: interactive redesign concepts rendered with sample data. */
export function DesignLab() {
  const [params, setParams] = useSearchParams();
  const requestedCategory = params.get('category');
  const category =
    requestedCategory === 'auths' ||
    requestedCategory === 'create-job' ||
    requestedCategory === 'dashboard' ||
    requestedCategory === 'drives' ||
    requestedCategory === 'tools' ||
    requestedCategory === 'mps' ||
    requestedCategory === 'plugins' ||
    requestedCategory === 'webhooks' ||
    requestedCategory === 'users'
      ? requestedCategory
      : 'charts';
  const categories = [
    { id: 'auths', label: 'Auths & Accounts', href: '/auths', current: 'Auths' },
    { id: 'create-job', label: 'Create Job', href: '/jobs?creator=1', current: 'Create Job' },
    { id: 'dashboard', label: 'Dashboard', href: '/', current: 'Dashboard' },
    { id: 'charts', label: 'ECharts Showcase', href: '/statistics', current: 'Charts' },
    { id: 'drives', label: 'Drive Configure Modal', href: '/system', current: 'Fleet & Drives' },
    { id: 'tools', label: 'Tools Workspace', href: '/tools', current: 'Tools' },
    { id: 'users', label: 'Users & Creators', href: '/users', current: 'Users' },
    { id: 'webhooks', label: 'Webhooks', href: '/webhooks', current: 'Webhooks' },
    { id: 'mps', label: 'Mass Profile Scraper', href: '/tools', current: 'MPS' },
    { id: 'plugins', label: 'Plugins', href: '/plugins', current: 'Plugins' },
  ] as const;
  const activeCategory = categories.find((item) => item.id === category) ?? categories[0];
  return (
    <div className="tools-page mock-page">
      <WorkspacePageHeader
        eyebrow="Platform / Mocks"
        title="Design lab"
        subtitle="Interactive previews · sample data"
        icon="◇"
      />
      <nav className="mock-categories" aria-label="Mock categories">
        {categories.map((item) => (
          <button key={item.id} type="button" aria-pressed={category === item.id} onClick={() => setParams({ category: item.id })}>
            {item.label}<span>5 concepts</span>
          </button>
        ))}
        <a href={activeCategory.href}>Open current {activeCategory.current} ↗</a>
      </nav>
      {category === 'auths' ? (
        <AuthsRedesignsMock />
      ) : category === 'create-job' ? (
        <JobCreatorRedesignsMock />
      ) : category === 'dashboard' ? (
        <DashboardRedesignsMock />
      ) : category === 'charts' ? (
        <ChartsShowcaseMock />
      ) : category === 'drives' ? (
        <DrivesRedesignsMock />
      ) : category === 'tools' ? (
        <ToolsRedesignsMock />
      ) : category === 'users' ? (
        <UsersRedesignsMock />
      ) : category === 'webhooks' ? (
        <WebhooksRedesignsMock />
      ) : category === 'plugins' ? (
        <PluginsRedesignsMock />
      ) : (
        <MpsRedesignsMock />
      )}
    </div>
  );
}
