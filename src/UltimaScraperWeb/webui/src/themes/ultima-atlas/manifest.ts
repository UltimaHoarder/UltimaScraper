import { lazy } from 'react';

import type { ThemeManifest } from '../../app/theme/types';
import { AppShell, Sidebar } from './layout/AppShell';
import { ConfirmDialog } from './patterns/ConfirmDialog';
import {
  OperationsHero,
  OperationsNotice,
  OperationsState,
} from './patterns/OperationsChrome';
import './tokens.css';
import './globals.css';
import './workspaces.css';
import './dialogs.css';
import './job-details.css';
import './loading.css';

const AuthsView = lazy(async () => ({ default: (await import('./views/auths/AuthsPage')).AuthsPage }));
const ChatsView = lazy(async () => ({ default: (await import('./views/chats/ChatsPage')).ChatsPage }));
const ContentView = lazy(async () => ({
  default: (await import('./views/content/ContentLibraryPage')).ContentLibraryPage,
}));
const Dashboard = lazy(async () => ({
  default: (await import('./views/dashboard/Dashboard')).Dashboard,
}));
const FavouritesView = lazy(async () => ({
  default: (await import('./views/favourites/FavouritesPage')).FavouritesPage,
}));
const JobsView = lazy(async () => ({ default: (await import('./views/jobs/JobsPage')).JobsPage }));
const LogsView = lazy(async () => ({ default: (await import('./views/logs/LogsPage')).LogsPage }));
const MediaView = lazy(async () => ({ default: (await import('./views/media/MediaPage')).MediaPage }));
const NetworkView = lazy(() => import('./views/network/NetworkPage'));
const OrdersView = lazy(async () => ({ default: (await import('./views/orders/OrdersPage')).OrdersPage }));
const SettingsView = lazy(() => import('./views/settings/SettingsPage'));
const SetupView = lazy(() => import('./views/setup/SetupPage'));
const StatisticsView = lazy(async () => ({
  default: (await import('./views/statistics/StatisticsPage')).StatisticsPage,
}));
const SubscriptionsView = lazy(async () => ({
  default: (await import('./views/subscriptions/SubscriptionsPage')).SubscriptionsPage,
}));
const SystemView = lazy(async () => ({ default: (await import('./views/system/SystemPage')).SystemPage }));
const ToolsView = lazy(async () => ({ default: (await import('./views/tools/ToolsPage')).ToolsPage }));
const UserProfileView = lazy(async () => ({
  default: (await import('./views/user-profile/UserProfilePage')).UserProfilePage,
}));
const UsersView = lazy(async () => ({ default: (await import('./views/users/UsersPage')).UsersPage }));
const WebhooksView = lazy(() => import('./views/webhooks/WebhooksPage'));
const PluginsView = lazy(async () => ({ default: (await import('./views/plugins/PluginsPage')).PluginsPage }));

export const ultimaAtlasTheme = {
  id: 'ultima-atlas',
  label: 'Ultima Atlas',
  description: 'Industrial data acquisition systems. Graphite surfaces, engineering grids, and operational telemetry.',
  shell: { AppShell, Sidebar },
  patterns: {
    OperationsHero,
    OperationsNotice,
    OperationsState,
    ConfirmDialog,
  },
  views: {
    auths: AuthsView,
    chats: ChatsView,
    content: ContentView,
    dashboard: Dashboard,
    favourites: FavouritesView,
    jobs: JobsView,
    logs: LogsView,
    media: MediaView,
    network: NetworkView,
    orders: OrdersView,
    settings: SettingsView,
    setup: SetupView,
    statistics: StatisticsView,
    subscriptions: SubscriptionsView,
    system: SystemView,
    tools: ToolsView,
    userProfile: UserProfileView,
    users: UsersView,
    webhooks: WebhooksView,
    plugins: PluginsView,
  },
} satisfies ThemeManifest;
