import { Suspense, lazy, useEffect } from 'react';
import { BrowserRouter, Route, Routes, useLocation } from 'react-router-dom';
import { SetupGuard } from '../components/SetupGuard';
import { MainLayout } from '../components/layout';
import { getDocumentTitle } from '../components/layout/navigation';
import type { ThemeRouteViews } from '../shared/lib/theme/route-views';
import { RouteFallback } from './RouteFallback';
import { useTheme } from './theme/useTheme';
import { UserCardsProvider } from '../features/users/UserCardsProvider';
import { FavouritesProvider } from '../features/favourites/FavouritesProvider';
import { DevModeGate } from '../features/settings/components/DevModeGate';

const MockPage = lazy(async () => ({ default: (await import('../pages/MockPage')).MockPage }));
const PluginPage = lazy(async () => ({ default: (await import('../features/plugins/components/PluginPage')).PluginPage }));
const VideoPage = lazy(async () => ({ default: (await import('../pages/VideoPage')).VideoPage }));

type PropFreeViewName = Exclude<keyof ThemeRouteViews, 'jobs' | 'users'>;

/** Renders the active theme's view for a route; theme manifests lazy-load their views. */
function ThemeView({ view }: { view: PropFreeViewName }) {
  const { theme } = useTheme();
  const View = theme.views[view];
  return <View />;
}

function UsersView() {
  const { theme } = useTheme();
  const View = theme.views.users;
  return <View />;
}

function JobsView({ showCreator = false }: { showCreator?: boolean }) {
  const { theme } = useTheme();
  const View = theme.views.jobs;
  return <View showCreator={showCreator} />;
}

function DocumentTitleSync() {
  const location = useLocation();

  useEffect(() => {
    document.title = getDocumentTitle(location.pathname);
  }, [location.pathname]);

  return null;
}

export function AppRouter({ basename }: { basename?: string } = {}) {
  return (
    <BrowserRouter basename={basename}>
      <FavouritesProvider>
      <UserCardsProvider>
      <DocumentTitleSync />
      <SetupGuard>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/setup" element={<ThemeView view="setup" />} />
            <Route element={<MainLayout />}>
              <Route path="/" element={<ThemeView view="dashboard" />} />
              <Route path="/statistics" element={<ThemeView view="statistics" />} />
              <Route path="/jobs" element={<JobsView />} />
              <Route path="/jobs/new" element={<JobsView showCreator />} />
              <Route path="/subscriptions" element={<ThemeView view="subscriptions" />} />
              <Route path="/chats" element={<ThemeView view="chats" />} />
              <Route path="/auths" element={<ThemeView view="auths" />} />
              <Route path="/network" element={<ThemeView view="network" />} />
              <Route path="/tools" element={<ThemeView view="tools" />} />
              <Route path="/mock" element={<DevModeGate><MockPage /></DevModeGate>} />
              <Route path="/plugins" element={<DevModeGate><ThemeView view="plugins" /></DevModeGate>} />
              <Route path="/plugins/:pluginId/:contributionId" element={<DevModeGate><PluginPage /></DevModeGate>} />
              <Route path="/users" element={<UsersView />} />
              <Route path="/favourites" element={<ThemeView view="favourites" />} />
              <Route path="/users/:userId" element={<ThemeView view="userProfile" />} />
              <Route path="/orders" element={<ThemeView view="orders" />} />
              <Route path="/system" element={<ThemeView view="system" />} />
              <Route path="/settings" element={<ThemeView view="settings" />} />
              <Route path="/webhooks" element={<ThemeView view="webhooks" />} />
              <Route path="/logs" element={<ThemeView view="logs" />} />
              <Route path="/content" element={<ThemeView view="content" />} />
              <Route path="/media/video/:site/:mediaId" element={<VideoPage />} />
              <Route path="/media" element={<ThemeView view="media" />} />
            </Route>
          </Routes>
        </Suspense>
      </SetupGuard>
      </UserCardsProvider>
      </FavouritesProvider>
    </BrowserRouter>
  );
}
