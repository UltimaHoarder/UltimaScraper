export type NavIconName =
  | 'dashboard'
  | 'statistics'
  | 'logs'
  | 'jobs'
  | 'orders'
  | 'tools'
  | 'content'
  | 'media'
  | 'favourites'
  | 'users'
  | 'subscriptions'
  | 'chats'
  | 'auths'
  | 'system'
  | 'network'
  | 'webhooks'
  | 'settings'
  | 'search'
  | 'scraper'
  | 'database'
  | 'bolt';

type NavMatchMode = 'default' | 'root' | 'subscriptions' | 'users';

export interface NavItem {
  path: string;
  label: string;
  icon: NavIconName;
  exact?: boolean;
  matchMode?: NavMatchMode;
}

export interface NavSection {
  title: string;
  description: string;
  items: readonly NavItem[];
}

export interface PageMeta {
  title: string;
  section: string;
  description: string;
}

export const APP_TITLE = 'UltimaScraper';

const navigationSections: readonly NavSection[] = [
  {
    title: 'Monitor',
    description: 'Live queue, runtime health, and reporting',
    items: [
      { path: '/', label: 'Dashboard', icon: 'dashboard', exact: true, matchMode: 'root' },
      { path: '/statistics', label: 'Statistics', icon: 'statistics', exact: true },
      { path: '/logs', label: 'Logs', icon: 'logs', exact: true },
    ],
  },
  {
    title: 'Jobs',
    description: 'Create, queue, and fulfill operational work',
    items: [
      { path: '/jobs', label: 'Jobs', icon: 'jobs' },
      { path: '/orders', label: 'Orders', icon: 'orders', exact: true },
    ],
  },
  {
    title: 'Content',
    description: 'Library, media, and saved discovery views',
    items: [
      { path: '/content', label: 'Content', icon: 'content', exact: true },
      { path: '/favourites', label: 'Favourites', icon: 'favourites', exact: true },
    ],
  },
  {
    title: 'People',
    description: 'Operators, creators, conversations, and auths',
    items: [
      { path: '/users', label: 'Users', icon: 'users', matchMode: 'users' },
      {
        path: '/subscriptions',
        label: 'Subscriptions',
        icon: 'subscriptions',
        exact: true,
        matchMode: 'subscriptions',
      },
      { path: '/chats', label: 'Chats', icon: 'chats', exact: true },
      { path: '/auths', label: 'Auths', icon: 'auths', exact: true },
    ],
  },
  {
    title: 'Platform',
    description: 'Infrastructure, hooks, storage, and utilities',
    items: [
      { path: '/system', label: 'System', icon: 'system', exact: true },
      { path: '/network', label: 'Network', icon: 'network', exact: true },
      { path: '/webhooks', label: 'Webhooks', icon: 'webhooks', exact: true },
      { path: '/tools', label: 'Tools', icon: 'tools', exact: true },
      { path: '/plugins', label: 'Plugins', icon: 'bolt', exact: true },
      { path: '/mock', label: 'Mock', icon: 'scraper', exact: true },
    ],
  },
  {
    title: 'Settings',
    description: 'Application policy, paths, and service config',
    items: [{ path: '/settings', label: 'Settings', icon: 'settings', exact: true }],
  },
] as const;

const pageMetaMatchers: Array<{
  matches: (pathname: string) => boolean;
  meta: PageMeta;
}> = [
  {
    matches: (pathname) => pathname === '/',
    meta: {
      title: 'Dashboard',
      section: 'Monitor',
      description: 'Track queue health, worker activity, and recovery signals.',
    },
  },
  {
    matches: (pathname) => pathname === '/statistics',
    meta: {
      title: 'Statistics',
      section: 'Monitor',
      description: 'Review throughput, site activity, and pipeline totals.',
    },
  },
  {
    matches: (pathname) => pathname === '/logs',
    meta: {
      title: 'Logs',
      section: 'Monitor',
      description: 'Inspect runtime events, diagnostics, and system output.',
    },
  },
  {
    matches: (pathname) => pathname.startsWith('/jobs'),
    meta: {
      title: 'Jobs',
      section: 'Jobs',
      description: 'Create new work, inspect execution, and recover failures.',
    },
  },
  {
    matches: (pathname) => pathname === '/orders',
    meta: {
      title: 'Orders',
      section: 'Jobs',
      description: 'Review order queues and expand task-level fulfillment details.',
    },
  },
  {
    matches: (pathname) => pathname === '/content',
    meta: {
      title: 'Content Library',
      section: 'Content',
      description: 'Browse indexed media, apply filters, and save loadouts.',
    },
  },
  {
    matches: (pathname) => pathname === '/media',
    meta: {
      title: 'Media',
      section: 'Content',
      description: 'Inspect stored assets and playback-ready content.',
    },
  },
  {
    matches: (pathname) => pathname === '/favourites',
    meta: {
      title: 'Favourites',
      section: 'Content',
      description: 'Keep high-value creators and sources close to hand.',
    },
  },
  {
    matches: (pathname) => pathname === '/users',
    meta: {
      title: 'Users',
      section: 'People',
      description: 'Review creators, segment lists, and trigger actions in bulk.',
    },
  },
  {
    matches: (pathname) => pathname.startsWith('/users/'),
    meta: {
      title: 'User Profile',
      section: 'People',
      description: 'Inspect identity, subscriptions, content, and operator actions.',
    },
  },
  {
    matches: (pathname) => pathname === '/subscriptions',
    meta: {
      title: 'Subscriptions',
      section: 'People',
      description: 'Audit active creators, loadouts, and subscription health.',
    },
  },
  {
    matches: (pathname) => pathname === '/chats',
    meta: {
      title: 'Chats',
      section: 'People',
      description: 'Track messages, outreach context, and conversation state.',
    },
  },
  {
    matches: (pathname) => pathname === '/auths',
    meta: {
      title: 'Auths',
      section: 'People',
      description: 'Manage credentials, session health, and verification flows.',
    },
  },
  {
    matches: (pathname) => pathname === '/system',
    meta: {
      title: 'System',
      section: 'Platform',
      description: 'Monitor runtime status, workers, storage, and remote backends.',
    },
  },
  {
    matches: (pathname) => pathname === '/network',
    meta: {
      title: 'Network',
      section: 'Platform',
      description: 'Operate proxies, connection health, and analyzer workflows.',
    },
  },
  {
    matches: (pathname) => pathname === '/webhooks',
    meta: {
      title: 'Webhooks',
      section: 'Platform',
      description: 'Manage outbound hooks, watch lists, and delivery telemetry.',
    },
  },
  {
    matches: (pathname) => pathname === '/tools',
    meta: {
      title: 'Tools',
      section: 'Platform',
      description: 'Run the Mass Profile Scraper and send raw API requests.',
    },
  },
  {
    matches: (pathname) => pathname === '/plugins',
    meta: {
      title: 'Plugins',
      section: 'Platform',
      description: 'Create, inspect, and manage plugin manifests and lifecycle.',
    },
  },
  {
    matches: (pathname) => pathname === '/mock',
    meta: {
      title: 'Design Lab',
      section: 'Platform',
      description: 'Compare interactive Webhooks and Mass Profile Scraper designs.',
    },
  },
  {
    matches: (pathname) => pathname === '/settings',
    meta: {
      title: 'Settings',
      section: 'Settings',
      description: 'Configure services, directories, site defaults, and policies.',
    },
  },
  {
    matches: (pathname) => pathname === '/setup',
    meta: {
      title: 'Setup',
      section: 'Settings',
      description: 'Initialize the runtime, database, and support requirements.',
    },
  },
] as const;

// Pages that only exist while Developer mode is on.
const DEV_MODE_PATHS = new Set(['/plugins', '/mock']);

export function getNavigationSections(devMode = false): readonly NavSection[] {
  if (devMode) return navigationSections;
  return navigationSections.map((section) => ({
    ...section,
    items: section.items.filter((item) => !DEV_MODE_PATHS.has(item.path)),
  }));
}

export function isNavItemActive(
  item: NavItem,
  pathname: string,
  search: string,
  routerActive: boolean
): boolean {
  const source = new URLSearchParams(search).get('source');
  const isSubscriptionsContext =
    pathname.startsWith('/users/') && source === 'subscriptions';

  switch (item.matchMode) {
    case 'root':
      return pathname === '/';
    case 'subscriptions':
      return routerActive || isSubscriptionsContext;
    case 'users':
      if (isSubscriptionsContext) return false;
      return routerActive;
    default:
      return routerActive;
  }
}

export function getPageMeta(pathname: string): PageMeta {
  const matched = pageMetaMatchers.find((entry) => entry.matches(pathname));
  if (matched) {
    return matched.meta;
  }

  return {
    title: APP_TITLE,
    section: 'Workspace',
    description: 'Operate jobs, people, and platform services from the WebUI shell.',
  };
}

export function formatDocumentTitle(title: string): string {
  return title === APP_TITLE ? APP_TITLE : `${title} | ${APP_TITLE}`;
}

export function getDocumentTitle(pathname: string): string {
  const { title } = getPageMeta(pathname);
  return formatDocumentTitle(title);
}

export function getUserProfileDocumentTitle(username: string | null | undefined): string {
  const normalizedUsername = username?.trim().replace(/^@+/, '') ?? '';
  return formatDocumentTitle(normalizedUsername || 'User Profile');
}
