import type { ComponentType, LazyExoticComponent } from 'react';

import type { UsersPageProps } from '../../../features/users/lib/usersUtils';

export interface JobsRouteProps {
  showCreator?: boolean;
}

export type ThemeViewComponent<Props = Record<string, never>> =
  | ComponentType<Props>
  | LazyExoticComponent<ComponentType<Props>>;

export interface ThemeRouteViews {
  auths: ThemeViewComponent;
  chats: ThemeViewComponent;
  content: ThemeViewComponent;
  dashboard: ThemeViewComponent;
  favourites: ThemeViewComponent;
  jobs: ThemeViewComponent<JobsRouteProps>;
  logs: ThemeViewComponent;
  media: ThemeViewComponent;
  network: ThemeViewComponent;
  orders: ThemeViewComponent;
  settings: ThemeViewComponent;
  setup: ThemeViewComponent;
  statistics: ThemeViewComponent;
  subscriptions: ThemeViewComponent;
  system: ThemeViewComponent;
  tools: ThemeViewComponent;
  userProfile: ThemeViewComponent;
  users: ThemeViewComponent<UsersPageProps>;
  webhooks: ThemeViewComponent;
  plugins: ThemeViewComponent;
}
