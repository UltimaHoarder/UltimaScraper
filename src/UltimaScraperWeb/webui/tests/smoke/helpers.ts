import type { Page, Route } from '@playwright/test';
import { makeStatisticsActivity } from '../fixtures/statistics';
import type { StatisticsActivityInterval, StatisticsActivityMetric, StatisticsActivityRange } from '../../src/api/types/statistics';

const UI_ORIGIN = 'http://127.0.0.1:4173';
const SMOKE_STARTUP_ID = 'startup-smoke';
const JSON_HEADERS = {
  'access-control-allow-origin': UI_ORIGIN,
  'access-control-allow-credentials': 'true',
  'access-control-allow-methods': 'GET,POST,PUT,PATCH,DELETE,OPTIONS',
  'access-control-allow-headers': '*',
  'content-type': 'application/json',
};

type JobStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

interface SmokeJob {
  job_id: string;
  job_name: string;
  status: JobStatus;
  task_count: number;
  completed_tasks: number;
  failed_tasks: number;
  tasks: Array<{
    task_type: string;
    content_type: string | null;
    status: string;
    username: string | null;
    site: string | null;
    auth_id: number | null;
    items_processed: number;
    items_total: number | null;
  }>;
  created_at: string;
  updated_at: string | null;
  created_by: string;
  is_scheduled: boolean;
  scheduled_for: string | null;
  interval_seconds: number | null;
  cron: string | null;
  run_count: number;
  last_ran_at: string | null;
}

interface SmokeOptions {
  configured?: boolean;
  theme?: 'ultima-atlas';
}

interface SmokeChatMessage {
  id: number;
  text: string;
  from_user_id: number;
  from_username: string;
  is_from_me: boolean;
  created_at: string;
  is_tip: boolean;
  is_free: boolean | null;
  price: number | null;
  media_count: number;
  media: Array<{
    id: number;
    media_type: 'image' | 'video' | 'audio' | 'gif' | 'photo';
    url: string | null;
    thumb_url: string | null;
    preview_url: string | null;
    local_url: string | null;
    width: number | null;
    height: number | null;
    duration: number | null;
    can_view: boolean;
    has_drm: boolean;
    is_ready: boolean;
    already_owned: boolean;
  }>;
  is_opened: boolean | null;
  is_liked: boolean;
  has_rebundled_media: boolean;
}

interface SmokeOrderSummary {
  id: number;
  status: string;
  total_price: number | null;
  created_at: string;
  updated_at: string | null;
  item_count: number;
}

interface SmokeOrderItem {
  id: number;
  user_id: number;
  username: string | null;
  price: number | null;
  status: string;
  spender_user_id: number | null;
  spender_username: string | null;
  error_message: string | null;
}

interface SmokeSpender {
  auth_id: number;
  username: string | null;
  spender_type: string;
  balance: number;
  assigned_count: number;
  assigned_cost: number;
}

function createJob(
  jobId: string,
  jobName: string,
  status: JobStatus,
  username: string,
  authId: number,
): SmokeJob {
  return {
    job_id: jobId,
    job_name: jobName,
    status,
    task_count: 1,
    completed_tasks: status === 'completed' ? 1 : 0,
    failed_tasks: status === 'failed' ? 1 : 0,
    tasks: [
      {
        task_type: 'scrape_user',
        content_type: null,
        status,
        username,
        site: 'onlyfans',
        auth_id: authId,
        items_processed: status === 'completed' ? 12 : 0,
        items_total: 12,
      },
    ],
    created_at: '2026-03-08T00:00:00Z',
    updated_at: null,
    created_by: 'webui',
    is_scheduled: false,
    scheduled_for: null,
    interval_seconds: null,
    cron: null,
    run_count: 0,
    last_ran_at: null,
  };
}

function createSmokeMessage(
  id: number,
  text: string,
  overrides: Partial<SmokeChatMessage> = {},
): SmokeChatMessage {
  return {
    id,
    text,
    from_user_id: 123,
    from_username: 'alice',
    is_from_me: false,
    created_at: '2026-03-08T00:00:00Z',
    is_tip: false,
    is_free: null,
    price: null,
    media_count: 0,
    media: [],
    is_opened: true,
    is_liked: false,
    has_rebundled_media: false,
    ...overrides,
  };
}

function createSmokeOrderSummary(
  id: number,
  status: string,
  totalPrice: number,
  itemCount: number,
): SmokeOrderSummary {
  return {
    id,
    status,
    total_price: totalPrice,
    created_at: '2026-03-08T00:00:00Z',
    updated_at: null,
    item_count: itemCount,
  };
}

function createSmokeOrderItem(
  id: number,
  userId: number,
  username: string,
  price: number,
): SmokeOrderItem {
  return {
    id,
    user_id: userId,
    username,
    price,
    status: 'pending',
    spender_user_id: null,
    spender_username: null,
    error_message: null,
  };
}

function corsJson(body: unknown) {
  return {
    status: 200,
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  };
}

async function fulfillOptions(route: Route) {
  await route.fulfill({
    status: 204,
    headers: JSON_HEADERS,
    body: '',
  });
}

/** The page's backend, as the WebUI server lists it. */
export const SMOKE_CONNECTION = {
  id: 'default',
  // Not "backend": the header shows this name, and tests look for a Back button.
  name: 'Smoke server',
  base_url: 'http://backend:21121',
  tls_verify: true,
  managed: true,
  has_token: true,
  trust_plugins: true,
};
// The default connection's keys are unscoped (see connectionScopedKey).
const MIGRATION_KEY = SMOKE_CONNECTION.id === 'default'
  ? 'usr_migration_done_startup_id'
  : `usr_migration_done_startup_id@${SMOKE_CONNECTION.id}`;

/** A request path without the WebUI server's /b/{connection} prefix. */
export function backendPath(url: string | URL): string {
  return new URL(url).pathname.replace(/^\/b\/[^/]+(?=\/(api|ws)\/)/, '');
}

/** The WebUI server's own API: signed in, with one backend. */
async function installWebUIServerMocks(page: Page) {
  await page.route('**/webui/api/v1/session', (route) => route.fulfill({ json: {
    authenticated: true, password_set: true, can_claim: false, default_connection: SMOKE_CONNECTION.id,
  } }));
  await page.route('**/webui/api/v1/connections', (route) => route.fulfill({ json: [SMOKE_CONNECTION] }));
  await page.route('**/webui/api/v1/clusters', (route) => route.fulfill({ json: { members: [], clusters: [] } }));
  await page.route('**/webui/api/v1/deployments', (route) => route.fulfill({ json: [] }));
}

export async function seedConfiguredApp(
  page: Page,
  options: { theme?: 'ultima-atlas'; devMode?: boolean } = {},
) {
  await installWebUIServerMocks(page);
  await page.addInitScript(({ migrationKey, startupId, theme, devMode }) => {
    localStorage.setItem(migrationKey, startupId);
    if (theme) {
      localStorage.setItem('usr_theme', theme);
    }
    // Plugins and mocks only run with Developer mode on.
    if (devMode) {
      localStorage.setItem('usr_webui_preferences', JSON.stringify({ devMode: true }));
    }
  }, { migrationKey: MIGRATION_KEY, startupId: SMOKE_STARTUP_ID, theme: options.theme ?? 'ultima-atlas', devMode: options.devMode ?? false });
}

export async function seedSetupApp(page: Page) {
  await installWebUIServerMocks(page);
  await page.addInitScript((migrationKey) => {
    localStorage.removeItem(migrationKey);
  }, MIGRATION_KEY);
}

/** A ready MPS analysis and proxy preview, as the tools workspace requests on load. */
export async function installMpsMocks(page: Page) {
  await page.route('**/api/v1/mps/analyze', (route) => route.fulfill({ json: {
    site: 'OnlyFans', start_id: 1, end_id: 10_000, range_size: 10_000,
    database_min_id: 1, database_max_id: 10_000, existing_user_count: 100,
    invalid_user_count: 0, invalid_table_ready: true, invalid_eligible_count: 0,
    existing_eligible_count: 0, missing_count: 2_000, candidate_count: 2_000,
    missing_range_count: 2, candidate_range_count: 2, missing_ranges_truncated: false, missing_ranges: [],
    missing_ids_preview: [], candidate_ranges_preview: [{ start_id: 1001, end_id: 2000, count: 1000 }, { start_id: 7001, end_id: 8000, count: 1000 }], candidate_ids_preview: [],
    candidate_preview_truncated: false, candidate_offset: 0, planned_batch_size: 200,
    planned_candidate_count: 200, remaining_candidate_count: 2_000,
    next_candidate_offset: 200, has_next_batch: true, recommended_batch_size: 200,
    batch_recommendations: [], warnings: [], requires_confirmation: false,
  } }));
  await page.route('**/api/v1/mps/proxy-preview', (route) => route.fulfill({ json: {
    site: 'OnlyFans', use_proxies: true, proxy_mode: 'unassigned_only',
    proxies_configured: 2, proxies_used: 2, direct_connection_included: false,
    proxy_urls: ['http://proxy1.example:8080', 'http://proxy2.example:8080'],
  } }));
}

/** Shaped statistics activity and seasonality responses for pages that load them. */
export async function installStatisticsActivityMocks(page: Page) {
  await page.route('**/api/v1/statistics/activity?*', (route) => {
    const params = new URL(route.request().url()).searchParams;
    return route.fulfill({ json: makeStatisticsActivity({
      metric: params.get('metric') as StatisticsActivityMetric,
      interval: params.get('interval') as StatisticsActivityInterval,
      range: params.get('range') as StatisticsActivityRange,
    }) });
  });
  await page.route('**/api/v1/statistics/seasonality?*', (route) => {
    const params = new URL(route.request().url()).searchParams;
    const cycle = params.get('cycle') ?? 'weekday';
    const bins = { hour: 24, weekday: 7, monthday: 31, month: 12 }[cycle as 'hour' | 'weekday' | 'monthday' | 'month'];
    return route.fulfill({ json: {
      metric: params.get('metric'), cycle, date_field: 'created_at', start_date: '2025-10-01', end_date: '2026-09-30',
      calculated_at: '2026-09-30T00:00:00Z', exposures: Array(bins).fill(52),
      sites: [{ site: 'onlyfans', available: true, availability_error: null, counts: Array(bins).fill(0) }],
    } });
  });
}

/** Webhook settings with no destinations, and an empty, running watch list. */
export async function installWebhookMocks(page: Page) {
  const unset = { active: false, url: null, hide_info: [] };
  await page.route(/\/api\/v1\/webhooks\/(?:\?.*)?$/, (route) => route.fulfill({ json: {
    sites: { onlyfans: { auth: unset, download: unset }, fansly: { auth: unset, download: unset } },
  } }));
  await page.route('**/api/v1/webhooks/watch/stats', (route) => route.fulfill({ json: {
    total_watched: 0, by_site: {}, paused: false,
  } }));
}

/** An enabled favourites store with nothing favourited yet. */
export async function installFavouritesMocks(page: Page) {
  await page.route(/\/api\/v1\/favourites(?:\?.*)?$/, (route) => route.fulfill({ json: {
    items: [], has_more: false, next_cursor: null,
  } }));
  await page.route(/\/api\/v1\/favourites\/counts(?:\?.*)?$/, (route) => route.fulfill({ json: {
    total: 0, by_type: { user: 0, post: 0, story: 0, message: 0 },
  } }));
  await page.route('**/api/v1/favourites/status', (route) => route.fulfill({ json: { enabled: true } }));
  await page.route('**/api/v1/favourites/states', (route) => route.fulfill({ json: { states: [] } }));
}

export async function installApiMocks(page: Page, options: SmokeOptions = {}) {
  const configured = options.configured ?? true;
  const jobs: SmokeJob[] = [
    createJob('job-running-1', 'Running Smoke Job', 'running', 'alice', 1),
    createJob('job-failed-1', 'Failed Smoke Job', 'failed', 'bravo', 2),
  ];
  const chats = [
    {
      id: 123,
      user: {
        id: 123,
        username: 'alice',
        name: 'Alice Example',
        avatar_url: null,
      },
      last_message_text: 'Locked drop incoming',
      last_message_at: '2026-03-08T00:05:00Z',
      unread_count: 1,
      has_purchased_feed: true,
      pinned_count: 0,
    },
  ];
  const chatMessagesByUser = new Map<number, SmokeChatMessage[]>([
    [
      123,
      [
        createSmokeMessage(9001, 'Hey there, this is a smoke-test thread.'),
        createSmokeMessage(9002, '', {
          created_at: '2026-03-08T00:02:00Z',
          price: 5,
          media_count: 1,
          media: [
            {
              id: 501,
              media_type: 'video',
              url: 'https://cdn.example.invalid/media/smoke.mp4',
              thumb_url: 'https://cdn.example.invalid/media/smoke-thumb.jpg',
              preview_url: 'https://cdn.example.invalid/media/smoke-thumb.jpg',
              local_url: null,
              width: 1280,
              height: 720,
              duration: 22,
              can_view: false,
              has_drm: false,
              is_ready: true,
              already_owned: false,
            },
          ],
          is_opened: false,
        }),
      ],
    ],
  ]);
  const subscriptions = [
    {
      id: 301,
      user_id: 123,
      username: 'alice',
      name: 'Alice Example',
      description: 'Top creator',
      sex: 0,
      avatar_url: null,
      header_url: null,
      price: 9.99,
      post_count: 12,
      media_count: 39,
      image_count: 34,
      video_count: 5,
      is_active: true,
      expires_at: '2026-03-31T00:00:00Z',
      watched: false,
      ignored: false,
      site: 'onlyfans',
    },
  ];
  const orders: SmokeOrderSummary[] = [createSmokeOrderSummary(222, 'pending', 10, 1)];
  const orderItemsByOrder = new Map<number, SmokeOrderItem[]>([
    [222, [createSmokeOrderItem(401, 123, 'alice', 10)]],
  ]);
  const orderSpenders: SmokeSpender[] = [
    {
      auth_id: 1,
      username: 'auth-main',
      spender_type: 'primary',
      balance: 250,
      assigned_count: 0,
      assigned_cost: 0,
    },
  ];
  const proxies = [
    {
      id: 'http://proxy1.example:8080',
      url: 'http://proxy1.example:8080',
      username: 'smoke',
      max_connections: 32,
      assigned_auths: [1],
      geolocation: {
        ip: '203.0.113.10',
        success: true,
        city: 'London',
        region: 'England',
        country: 'United Kingdom',
        flag: { emoji: '🇬🇧' },
        connection: { isp: 'SmokeNet' },
      },
    },
    {
      id: 'http://proxy2.example:8080',
      url: 'http://proxy2.example:8080',
      username: null,
      max_connections: 16,
      assigned_auths: [],
      geolocation: null,
    },
  ];
  const dbSettings = [
    {
      id: 1,
      backend: 'backend-smoke',
      key: 'network.max_connections',
      value: '64',
      is_secret: false,
      description: 'Global network limit',
      version: 1,
    },
  ];
  const backendInventory = [
    {
      id: 1,
      backend_name: 'backend-smoke',
      hostname: 'smoke-host',
      local_ip: '127.0.0.1',
      settings_id: 1,
      settings_scope: 'backend-smoke',
      settings_key: 'network.max_connections',
    },
  ];
  let nextDbSettingId = 2;
  let nextInventoryId = 2;
  let nextMessageId = 9100;
  let createdJobCounter = 1;

  const settingsPayload = {
    hostname: 'smoke-host',
    worker_pool: {
      enabled: true,
      size: 2,
      sites: ['onlyfans'],
      max_claimed_jobs: 4,
    },
    backend: {
      backend_id: 'backend-smoke',
      execution_mode: 'local',
    },
    redis: {
      host: 'localhost',
      port: 6379,
      db: 0,
      password: null,
      enabled: true,
      completed_job_retention_seconds: 3600,
    },
    network: {
      max_connections: 64,
      proxies: [],
      proxy_fallback: true,
      downloads: {
        max_concurrency: 8,
        per_domain_concurrency: 4,
        head_concurrency: 4,
        buffer_size_bytes: 65536,
      },
    },
    download_setup: {
      drives: [],
      alt_directory_formats: [],
      staging_directories: [],
      site_directory_aliases: { onlyfans: ['OnlyFansImages', 'OnlyFans (G)'] },
      find_only_site_directories: {},
      directory_format: '{site}/{username}',
      filename_format: '{id}_{filename}',
      text_length: 255,
      date_format: '%Y-%m-%d',
      overwrite_files: false,
    },
    metadata_setup: {
      drives: [],
      directory_format: '{site}/{username}',
    },
    previews_directory: '/tmp/usr/previews',
    subtitles_directory: '/tmp/usr/subtitles',
    drm: {
      device_client_blob_filepath: null,
      device_private_key_filepath: null,
    },
    sites: {
      onlyfans: { blacklists: [] },
      fansly: { blacklists: [] },
    },
    config_path: '/tmp/usr/config.json',
    is_configured: configured,
    config_scope: 'local',
    configuration_source: 'database',
    config_version: 1,
    config_updated_at: '2026-03-08T00:00:00Z',
  };

  const getOrderById = (orderId: number) => orders.find((order) => order.id === orderId) ?? null;
  const getOrderItems = (orderId: number) => orderItemsByOrder.get(orderId) ?? [];
  const syncOrderState = (orderId: number) => {
    const order = getOrderById(orderId);
    if (!order) {
      return;
    }
    const items = getOrderItems(orderId);
    order.item_count = items.length;
    order.total_price = items.reduce((sum, item) => sum + (item.price ?? 0), 0);
    if (items.length === 0) {
      order.status = 'pending';
    }
  };

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    // The WebUI server's own API has its own mocks (installWebUIServerMocks).
    if (url.pathname.startsWith('/webui/')) return route.fallback();
    const path = backendPath(url);
    const method = request.method().toUpperCase();

    if (method === 'OPTIONS') {
      await fulfillOptions(route);
      return;
    }

    if (path === '/api/v1/system/bootstrap') {
      await route.fulfill(
        corsJson({
          backend_id: 'backend-smoke',
          hostname: 'smoke-host',
          version: '9.9.9',
          supported_sites: ['onlyfans', 'fansly'],
          setup: {
            is_configured: configured,
            has_config: configured,
            has_database: configured,
            data_directory: '/tmp/usr',
            startup_id: SMOKE_STARTUP_ID,
          },
          features: {
            webhook_stream: true,
            startup_migrations: true,
            distributed_mode: false,
            remote_backends: false,
            system_bootstrap: true,
          },
          support_matrix: {
            ui_mode: 'webui',
            tui_supported: false,
            runtime_database: 'postgresql',
            postgres_required: true,
            sqlite_runtime_supported: false,
            sqlite_import_supported: true,
          },
        }),
      );
      return;
    }

    if (path === '/api/v1/setup/status') {
      await route.fulfill(
        corsJson({
          is_configured: configured,
          has_config: configured,
          has_database: configured,
          data_directory: '/tmp/usr',
          startup_id: SMOKE_STARTUP_ID,
        }),
      );
      return;
    }

    if (path === '/api/v1/admin/health') {
      await route.fulfill(
        corsJson({
          status: 'healthy',
          instance_id: 'backend-smoke',
          distributed_mode: false,
          transitioning: false,
          queue_type: 'local',
          queue_size: 2,
          redis_connected: false,
        }),
      );
      return;
    }

    if (path === '/api/v1/admin/queue-stats') {
      await route.fulfill(
        corsJson({
          instance_id: 'backend-smoke',
          distributed_mode: false,
          transitioning: false,
          local_queue_size: jobs.length,
          redis_queue_size: 0,
          active_queue_type: 'local',
          recovery_interval: 60,
          next_recovery_seconds: 42,
          last_recovery_at: '2026-03-08T00:00:00Z',
        }),
      );
      return;
    }

    if (path === '/api/v1/system/backend') {
      await route.fulfill(
        corsJson({
          backend_id: 'backend-smoke',
          distributed_mode: false,
          redis_connected: false,
          worker_count: 2,
          active_workers: 1,
          pending_jobs: jobs.filter((job) => job.status === 'pending').length,
          workers: [
            {
              worker_id: 'worker-1',
              status: 'busy',
              current_job: 'job-running-1',
              jobs_completed: 12,
            },
            {
              worker_id: 'worker-2',
              status: 'idle',
              current_job: null,
              jobs_completed: 7,
            },
          ],
          system_stats: {
            timestamp: '2026-03-08T00:00:00Z',
            cpu_percent: 42.5,
            cpu_count: 8,
            memory_total: 17179869184,
            memory_used: 8589934592,
            memory_free: 8589934592,
            memory_percent: 50,
            disks: [
              {
                device: 'nvme0n1',
                mount_point: '/data',
                total_bytes: 1099511627776,
                used_bytes: 439804651110,
                free_bytes: 659706976666,
                percent_used: 40,
                read_bytes_per_sec: 1048576,
                write_bytes_per_sec: 2097152,
              },
            ],
          },
        }),
      );
      return;
    }

    if (path === '/api/v1/system/backends') {
      await route.fulfill(
        corsJson({
          success: true,
          local_backend_id: 'backend-smoke',
          local_hostname: 'smoke-host',
          backends: [],
          total_backends: 0,
        }),
      );
      return;
    }

    if (path === '/api/v1/system/drives') {
      await route.fulfill(
        corsJson({
          backend_id: 'backend-smoke',
          drives: [
            {
              path: '/tmp/usr',
              device: '/dev/mock0',
              total_bytes: 1000000,
              used_bytes: 250000,
              free_bytes: 750000,
              percent_used: 25,
              is_configured: true,
              directory_count: 2,
              configured_directories: ['/tmp/usr/downloads', '/tmp/usr/metadata'],
            },
          ],
        }),
      );
      return;
    }

    if ((path === '/api/v1/settings/' || path === '/api/v1/settings') && method === 'GET') {
      await route.fulfill(corsJson(settingsPayload));
      return;
    }

    if ((path === '/api/v1/settings/' || path === '/api/v1/settings') && method === 'PUT') {
      const payload = (request.postDataJSON() ?? {}) as Record<string, unknown>;
      Object.assign(settingsPayload, payload);
      await route.fulfill(corsJson(settingsPayload));
      return;
    }

    if (path === '/api/v1/settings/runtime/redis' && method === 'PUT') {
      const payload = (request.postDataJSON() ?? {}) as Record<string, unknown>;
      settingsPayload.redis = { ...settingsPayload.redis, ...payload };
      await route.fulfill(corsJson(settingsPayload));
      return;
    }

    if (path === '/api/v1/settings/config-path') {
      await route.fulfill(corsJson({ config_path: settingsPayload.config_path }));
      return;
    }

    if (path === '/api/v1/settings/test-redis' && method === 'POST') {
      await route.fulfill(
        corsJson({
          success: true,
          message: 'Connected successfully',
          latency_ms: 4,
        }),
      );
      return;
    }

    if (path === '/api/v1/settings/db' && method === 'GET') {
      await route.fulfill(corsJson(dbSettings));
      return;
    }

    if (path === '/api/v1/settings/db' && method === 'PUT') {
      const payload = request.postDataJSON() as {
        backend: string;
        key: string;
        value: string;
        is_secret?: boolean;
        description?: string | null;
      };
      const nextRecord = {
        id: nextDbSettingId,
        backend: payload.backend,
        key: payload.key,
        value: payload.value,
        is_secret: Boolean(payload.is_secret),
        description: payload.description ?? null,
        version: 1,
      };
      nextDbSettingId += 1;
      dbSettings.unshift(nextRecord);
      await route.fulfill(corsJson(nextRecord));
      return;
    }

    const dbSettingMatch = path.match(/^\/api\/v1\/settings\/db\/(\d+)$/);
    if (dbSettingMatch && method === 'DELETE') {
      const targetId = Number(dbSettingMatch[1]);
      const index = dbSettings.findIndex((row) => row.id === targetId);
      if (index >= 0) {
        dbSettings.splice(index, 1);
      }
      await route.fulfill(corsJson({ success: true, id: targetId }));
      return;
    }

    if (path === '/api/v1/settings/db/backends' && method === 'GET') {
      await route.fulfill(corsJson(backendInventory));
      return;
    }

    if (path === '/api/v1/settings/db/backends' && method === 'PUT') {
      const payload = request.postDataJSON() as {
        backend_name: string;
        hostname: string;
        local_ip?: string | null;
        settings_id: number;
      };
      const nextRecord = {
        id: nextInventoryId,
        backend_name: payload.backend_name,
        hostname: payload.hostname,
        local_ip: payload.local_ip ?? null,
        settings_id: payload.settings_id,
        settings_scope: payload.backend_name,
        settings_key: null,
      };
      nextInventoryId += 1;
      backendInventory.unshift(nextRecord);
      await route.fulfill(corsJson(nextRecord));
      return;
    }

    const backendInventoryMatch = path.match(/^\/api\/v1\/settings\/db\/backends\/(\d+)$/);
    if (backendInventoryMatch && method === 'DELETE') {
      const targetId = Number(backendInventoryMatch[1]);
      const index = backendInventory.findIndex((row) => row.id === targetId);
      if (index >= 0) {
        backendInventory.splice(index, 1);
      }
      await route.fulfill(corsJson({ success: true, id: targetId }));
      return;
    }

    if (path === '/api/v1/search-loadouts/' && method === 'GET') {
      await route.fulfill(
        corsJson({
          loadouts: [],
        }),
      );
      return;
    }

    if (path === '/api/v1/tasks/types') {
      await route.fulfill(
        corsJson([
          {
            task_id: 'scrape_user',
            name: 'Scrape User',
            category: 'scrape',
            description: 'Scrape a single performer.',
            keywords: ['scrape'],
            parameters: [
              {
                name: 'username',
                label: 'Username',
                param_type: 'text',
                required: true,
                default: '',
                description: 'Target performer',
                options: [],
                placeholder: 'target-user',
                min_value: null,
                max_value: null,
              },
            ],
          },
        ]),
      );
      return;
    }

    if (path === '/api/v1/jobs/templates') {
      await route.fulfill(corsJson([]));
      return;
    }

    if (path === '/api/v1/subscriptions/stats' && method === 'GET') {
      await route.fulfill(
        corsJson([
          {
            site: 'onlyfans',
            total: subscriptions.length,
            active: subscriptions.filter((subscription) => subscription.is_active).length,
            expired: subscriptions.filter((subscription) => !subscription.is_active).length,
          },
        ]),
      );
      return;
    }

    if ((path === '/api/v1/subscriptions/' || path === '/api/v1/subscriptions') && method === 'GET') {
      const search = (url.searchParams.get('search') || '').toLowerCase();
      const filteredSubscriptions = subscriptions.filter((subscription) =>
        search
          ? `${subscription.username ?? ''} ${subscription.name ?? ''} ${subscription.user_id}`
              .toLowerCase()
              .includes(search)
          : true,
      );
      await route.fulfill(
        corsJson({
          success: true,
          subscriptions: filteredSubscriptions,
          total: filteredSubscriptions.length,
        }),
      );
      return;
    }

    if (path === '/api/v1/auths/' || path === '/api/v1/auths') {
      await route.fulfill(
        corsJson({
          success: true,
          total: 2,
          error: null,
          auths: [
            {
              id: 1,
              site: 'onlyfans',
              username: 'auth-main',
              user_id: 1001,
              status: 'ok',
              active: true,
              last_tested_at: null,
              created_at: null,
              cookie_preview: null,
              has_authorization: false,
              user_agent_preview: null,
              proxy_id: null,
              worker_shard: 0,
              is_age_verified: true,
              age_verification_required: false,
              spend: true,
              spender_type: 'primary',
            },
            {
              id: 2,
              site: 'onlyfans',
              username: 'auth-backup',
              user_id: 1002,
              status: 'ok',
              active: true,
              last_tested_at: null,
              created_at: null,
              cookie_preview: null,
              has_authorization: false,
              user_agent_preview: null,
              proxy_id: null,
              worker_shard: 1,
              is_age_verified: true,
              age_verification_required: false,
              spend: true,
              spender_type: 'backup',
            },
          ],
        }),
      );
      return;
    }

    const authBalanceMatch = path.match(/^\/api\/v1\/auths\/(\d+)\/balance$/);
    if (authBalanceMatch && method === 'GET') {
      await route.fulfill(
        corsJson({
          success: true,
          balance: authBalanceMatch[1] === '1' ? 42.5 : 18,
        }),
      );
      return;
    }

    if (path === '/api/v1/jobs' && method === 'GET') {
      await route.fulfill(
        corsJson({
          jobs,
          total: jobs.length,
          page: 1,
          page_size: 50,
        }),
      );
      return;
    }

    if (path === '/api/v1/jobs' && method === 'POST') {
      const payload = request.postDataJSON() as {
        job_name: string;
        tasks?: Array<{ task_type: string; params: Record<string, unknown> }>;
      };
      const username = String(payload.tasks?.[0]?.params?.username ?? 'unknown');
      const nextJob = createJob(
        `job-created-${createdJobCounter}`,
        payload.job_name,
        'pending',
        username,
        Number(payload.tasks?.[0]?.params?.auth_id ?? 1),
      );
      createdJobCounter += 1;
      jobs.unshift(nextJob);
      await route.fulfill(corsJson(nextJob));
      return;
    }

    if (path === '/api/v1/jobs/active-tasks') {
      await route.fulfill(
        corsJson({
          tasks: jobs
            .filter((job) => job.status === 'running')
            .map((job) => ({
              job_id: job.job_id,
              job_name: job.job_name,
              job_status: job.status,
              job_total_tasks: 1,
              task_id: `${job.job_id}-task-1`,
              task_type: 'scrape_user',
              status: 'running',
              site: 'onlyfans',
              username: job.tasks[0]?.username ?? 'alice',
              content_type: null,
              started_at: '2026-03-08T00:00:00Z',
              completed_at: null,
              progress: 0.5,
              items_processed: 6,
              items_total: 12,
              items_scraped: 6,
              items_saved: 4,
              bytes_written: null,
              total_bytes: null,
              speed_bps: null,
              avg_speed_bps: null,
              error: null,
            })),
          total: jobs.filter((job) => job.status === 'running').length,
        }),
      );
      return;
    }

    const retryMatch = path.match(/^\/api\/v1\/jobs\/([^/]+)\/retry$/);
    if (retryMatch && method === 'POST') {
      const sourceJob = jobs.find((job) => job.job_id === retryMatch[1]);
      const retriedJob = createJob(
        `job-retry-${createdJobCounter}`,
        `Retry: ${sourceJob?.job_name ?? 'Recovered Job'}`,
        'pending',
        sourceJob?.tasks[0]?.username ?? 'unknown',
        sourceJob?.tasks[0]?.auth_id ?? 1,
      );
      createdJobCounter += 1;
      jobs.unshift(retriedJob);
      await route.fulfill(corsJson(retriedJob));
      return;
    }

    const cancelMatch = path.match(/^\/api\/v1\/jobs\/([^/]+)\/cancel$/);
    if (cancelMatch && method === 'POST') {
      const target = jobs.find((job) => job.job_id === cancelMatch[1]);
      if (target) {
        target.status = 'cancelled';
        target.updated_at = '2026-03-08T01:00:00Z';
      }
      await route.fulfill(
        corsJson({
          success: true,
          job_id: cancelMatch[1],
          status: target?.status ?? 'cancelled',
        }),
      );
      return;
    }

    const prioritizeMatch = path.match(/^\/api\/v1\/jobs\/([^/]+)\/prioritize$/);
    if (prioritizeMatch && method === 'POST') {
      await route.fulfill(
        corsJson({
          job_id: prioritizeMatch[1],
          rescored: 1,
          priority: -1,
        }),
      );
      return;
    }

    const jobDetailMatch = path.match(/^\/api\/v1\/jobs\/([^/]+)$/);
    if (jobDetailMatch && method === 'GET') {
      const target = jobs.find((job) => job.job_id === jobDetailMatch[1]);
      await route.fulfill(
        corsJson({
          job_id: target?.job_id ?? jobDetailMatch[1],
          job_name: target?.job_name ?? 'Unknown Job',
          job_type: 'scrape',
          status: target?.status ?? 'pending',
          site: 'onlyfans',
          priority: 0,
          worker_id: null,
          retries: 0,
          max_retries: 3,
          created_at: target?.created_at ?? '2026-03-08T00:00:00Z',
          started_at: null,
          completed_at: null,
          result_success: null,
          result_message: null,
          result_error: null,
          args: {
            schedule: null,
          },
          tasks: [
            {
              task_id: `${jobDetailMatch[1]}-task-1`,
              task_type: 'scrape_user',
              status: target?.status ?? 'pending',
              site: 'onlyfans',
              username: target?.tasks[0]?.username ?? 'unknown',
              content_type: null,
              payload: {
                username: target?.tasks[0]?.username ?? 'unknown',
                auth_id: target?.tasks[0]?.auth_id ?? 1,
              },
              started_at: '2026-03-08T00:00:00Z',
              completed_at: null,
              progress: target?.status === 'running' ? 0.5 : 0,
              items_processed: 6,
              items_total: 12,
              error: target?.status === 'failed' ? 'Auth expired' : null,
              result: null,
            },
          ],
          run_count: 0,
          last_ran_at: null,
        }),
      );
      return;
    }

    const sseMatch = path.match(/^\/api\/v1\/jobs\/([^/]+)\/tasks\/stream$/);
    if (sseMatch && method === 'GET') {
      await route.fulfill({
        status: 200,
        headers: {
          ...JSON_HEADERS,
          'content-type': 'text/event-stream',
        },
        body: [
          `data: ${JSON.stringify({
            task_id: `${sseMatch[1]}-task-1`,
            task_type: 'scrape_user',
            status: 'running',
            site: 'onlyfans',
            username: 'alice',
            content_type: null,
            payload: { username: 'alice', auth_id: 1 },
            started_at: '2026-03-08T00:00:00Z',
            completed_at: null,
            progress: 0.5,
            items_processed: 6,
            items_total: 12,
            error: null,
            result: null,
          })}\n\n`,
          'data: [DONE]\n\n',
        ].join(''),
      });
      return;
    }

    const chatsMatch = path.match(/^\/api\/v1\/chats\/([^/]+)$/);
    if (chatsMatch && method === 'GET') {
      await route.fulfill(
        corsJson({
          success: true,
          chats,
          total: chats.length,
          source: 'db',
          syncing: false,
          error: null,
        }),
      );
      return;
    }

    const chatMessagesMatch = path.match(/^\/api\/v1\/chats\/([^/]+)\/(\d+)\/messages$/);
    if (chatMessagesMatch && method === 'GET') {
      const chatUserId = Number(chatMessagesMatch[2]);
      const messages = chatMessagesByUser.get(chatUserId) ?? [];
      await route.fulfill(
        corsJson({
          success: true,
          messages,
          has_more: false,
          source: 'db',
          syncing: false,
          error: null,
        }),
      );
      return;
    }

    if (chatMessagesMatch && method === 'POST') {
      const chatUserId = Number(chatMessagesMatch[2]);
      const payload = request.postDataJSON() as { text: string };
      const messages = chatMessagesByUser.get(chatUserId) ?? [];
      const nextMessage = createSmokeMessage(nextMessageId, payload.text, {
        from_user_id: 1001,
        from_username: 'auth-main',
        is_from_me: true,
        created_at: '2026-03-08T00:09:00Z',
      });
      nextMessageId += 1;
      messages.push(nextMessage);
      chatMessagesByUser.set(chatUserId, messages);
      await route.fulfill(
        corsJson({
          success: true,
          message: nextMessage,
          error: null,
        }),
      );
      return;
    }

    const buyMessageMatch = path.match(/^\/api\/v1\/chats\/([^/]+)\/(\d+)\/messages\/(\d+)\/buy$/);
    if (buyMessageMatch && method === 'POST') {
      const chatUserId = Number(buyMessageMatch[2]);
      const messageId = Number(buyMessageMatch[3]);
      const messages = chatMessagesByUser.get(chatUserId) ?? [];
      const targetMessage = messages.find((message) => message.id === messageId) ?? null;
      if (targetMessage) {
        targetMessage.is_opened = true;
        targetMessage.media = targetMessage.media.map((media) => ({
          ...media,
          can_view: true,
          already_owned: true,
          local_url: media.local_url || media.url,
        }));
      }
      await route.fulfill(
        corsJson({
          success: true,
          message: targetMessage,
          error: null,
        }),
      );
      return;
    }

    const likeMessageMatch = path.match(/^\/api\/v1\/chats\/([^/]+)\/(\d+)\/messages\/(\d+)\/like$/);
    if (likeMessageMatch && method === 'POST') {
      const chatUserId = Number(likeMessageMatch[2]);
      const messageId = Number(likeMessageMatch[3]);
      const messages = chatMessagesByUser.get(chatUserId) ?? [];
      const targetMessage = messages.find((message) => message.id === messageId) ?? null;
      if (targetMessage) {
        targetMessage.is_liked = !targetMessage.is_liked;
      }
      await route.fulfill(
        corsJson({
          success: true,
          is_liked: targetMessage?.is_liked ?? false,
          error: null,
        }),
      );
      return;
    }

    if (path === '/api/v1/users/resolve') {
      const identifier = (url.searchParams.get('identifier') || '').replace(/^@/, '').toLowerCase();
      const matchedBy = /^\d+$/.test(identifier) ? 'user_id' : 'username';
      await route.fulfill(
        corsJson({
          success: true,
          status: 'resolved',
          user_id: 123,
          username: 'alice',
          candidates: [
            {
              user_id: 123,
              username: 'alice',
              active: true,
              last_checked_at: '2026-03-08T00:00:00Z',
              matched_by: [matchedBy],
            },
          ],
          total: 1,
          page: 1,
          page_size: 20,
          error: null,
        }),
      );
      return;
    }

    if (path === '/api/v1/users/' || path === '/api/v1/users') {
      await route.fulfill(
        corsJson({
          success: true,
          users: [
            {
              id: 123,
              user_id: 98765,
              username: 'alice',
              name: 'Alice Example',
              site: 'onlyfans',
              avatar_url: null,
              header_url: null,
              description: 'Top creator',
              is_active: true,
              performer: true,
              favorite: false,
              price: 9.99,
              post_count: 12,
              media_count: 39,
              image_count: 34,
              video_count: 5,
              sex: 0,
              is_subscribed: true,
              is_pending_order: false,
              downloaded_at: null,
              last_checked_at: '2026-03-08T00:00:00Z',
            },
          ],
          total: 1,
          active: 1,
          inactive: 0,
          avg_price: 9.99,
          free: 0,
          paid: 1,
        }),
      );
      return;
    }

    if (path === '/api/v1/users/123') {
      await route.fulfill(
        corsJson({
          success: true,
          user: {
            id: 123,
            user_id: 98765,
            username: 'alice',
            name: 'Alice Example',
            site: 'onlyfans',
            avatar_url: null,
            header_url: null,
            description: 'Top creator',
            is_active: true,
            performer: true,
            favorite: false,
            price: 9.99,
            post_count: 12,
            media_count: 39,
            image_count: 34,
            video_count: 5,
            audio_count: 0,
            stream_count: 0,
            paid_content_count: 2,
            subscribers_count: 120,
            favourited_count: 20,
            favourites_count: 2,
            size: 4096,
            display_size: 4096,
            estimated_size: null,
            size_source: 'actual',
            statistics_bucket_date: null,
            location: null,
            website: null,
            sex: 0,
            gender: null,
            promotion: false,
            download_count: 3,
            archived_post_count: 0,
            balance: 0,
            spend: true,
            is_subscribed: true,
            subscription_expires_at: '2026-03-31T00:00:00Z',
            join_date: null,
            downloaded_at: null,
            first_downloaded_at: null,
            last_checked_at: '2026-03-08T00:00:00Z',
            created_at: '2026-03-01T00:00:00Z',
            profile_media_history: [],
            socials: [],
          },
        }),
      );
      return;
    }

    if (path === '/api/v1/files/users/search') {
      await route.fulfill(
        corsJson({
          success: true,
          username: 'alice',
          site: 'onlyfans',
          user_directory_format: '{site}/{username}',
          matches: [
            {
              root: '/tmp/usr/downloads',
              path: '/tmp/usr/downloads/alice',
            },
          ],
          checked_patterns: ['{site}/{username}'],
          usernames_searched: ['alice'],
          resolved_user_id: 98765,
        }),
      );
      return;
    }

    if (path === '/api/v1/database/users/123/history') {
      await route.fulfill(
        corsJson({
          success: true,
          snapshots: [],
          total: 0,
        }),
      );
      return;
    }

    if (path === '/api/v1/database/users/123/aliases') {
      await route.fulfill(
        corsJson({
          success: true,
          aliases: [],
          total: 0,
        }),
      );
      return;
    }

    if (path === '/api/v1/database/content') {
      await route.fulfill(
        corsJson({
          success: true,
          content: [],
          total: 0,
          page: 1,
          page_size: 20,
        }),
      );
      return;
    }

    if (path === '/api/v1/users/123/eligible-auths') {
      await route.fulfill(
        corsJson({
          auths: [
            {
              auth_id: 1,
              auth_username: 'auth-main',
              is_active: true,
            },
          ],
        }),
      );
      return;
    }

    if ((path === '/api/v1/orders/' || path === '/api/v1/orders') && method === 'GET') {
      await route.fulfill(
        corsJson({
          success: true,
          orders,
          total: orders.length,
          error: null,
        }),
      );
      return;
    }

    const orderDetailMatch = path.match(/^\/api\/v1\/orders\/(\d+)$/);
    if (orderDetailMatch && method === 'GET') {
      const orderId = Number(orderDetailMatch[1]);
      await route.fulfill(
        corsJson({
          success: true,
          order: getOrderById(orderId),
          items: getOrderItems(orderId),
          error: null,
        }),
      );
      return;
    }

    const calculateOrderMatch = path.match(/^\/api\/v1\/orders\/(\d+)\/calculate$/);
    if (calculateOrderMatch && method === 'POST') {
      const orderId = Number(calculateOrderMatch[1]);
      const items = getOrderItems(orderId);
      await route.fulfill(
        corsJson({
          success: true,
          order: getOrderById(orderId),
          items,
          spenders: orderSpenders,
          unassigned_count: 0,
          total_cost: items.reduce((sum, item) => sum + (item.price ?? 0), 0),
          error: null,
        }),
      );
      return;
    }

    const checkOrderMatch = path.match(/^\/api\/v1\/orders\/(\d+)\/check$/);
    if (checkOrderMatch && method === 'POST') {
      const orderId = Number(checkOrderMatch[1]);
      await route.fulfill(
        corsJson({
          success: true,
          order: getOrderById(orderId),
          items: getOrderItems(orderId),
          error: null,
        }),
      );
      return;
    }

    const deleteOrderMatch = path.match(/^\/api\/v1\/orders\/(\d+)\/delete$/);
    if (deleteOrderMatch && method === 'POST') {
      const orderId = Number(deleteOrderMatch[1]);
      const index = orders.findIndex((order) => order.id === orderId);
      if (index >= 0) {
        orders.splice(index, 1);
      }
      orderItemsByOrder.delete(orderId);
      await route.fulfill(
        corsJson({
          success: true,
          order: null,
          items: [],
          error: null,
        }),
      );
      return;
    }

    const clearPerformersMatch = path.match(/^\/api\/v1\/orders\/(\d+)\/performers\/clear$/);
    if (clearPerformersMatch && method === 'POST') {
      const orderId = Number(clearPerformersMatch[1]);
      orderItemsByOrder.set(orderId, []);
      syncOrderState(orderId);
      await route.fulfill(
        corsJson({
          success: true,
          order: getOrderById(orderId),
          items: [],
          error: null,
        }),
      );
      return;
    }

    const deleteOrderedPerformerMatch = path.match(/^\/api\/v1\/orders\/performers\/(\d+)$/);
    if (deleteOrderedPerformerMatch && method === 'DELETE') {
      const performerId = Number(deleteOrderedPerformerMatch[1]);
      for (const [orderId, items] of orderItemsByOrder.entries()) {
        const nextItems = items.filter((item) => item.id !== performerId);
        if (nextItems.length !== items.length) {
          orderItemsByOrder.set(orderId, nextItems);
          syncOrderState(orderId);
          await route.fulfill(
            corsJson({
              success: true,
              order: getOrderById(orderId),
              items: nextItems,
              error: null,
            }),
          );
          return;
        }
      }
      await route.fulfill(
        corsJson({
          success: false,
          order: null,
          items: [],
          error: 'Performer not found',
        }),
      );
      return;
    }

    if (path === '/api/v1/orders/performers' && method === 'POST') {
      const payload = request.postDataJSON() as {
        username?: string | null;
        user_id?: number | null;
        price?: number | null;
      };
      const nextItem = createSmokeOrderItem(
        500 + getOrderItems(222).length,
        Number(payload.user_id ?? 123),
        payload.username || 'alice',
        Number(payload.price ?? 10),
      );
      orderItemsByOrder.set(222, [...getOrderItems(222), nextItem]);
      syncOrderState(222);
      await route.fulfill(
        corsJson({
          success: true,
          performer_id: nextItem.id,
          order_id: 222,
          username: nextItem.username,
          user_id: nextItem.user_id,
          price: nextItem.price,
          message: 'Created',
        }),
      );
      return;
    }

    if (path === '/api/v1/proxies/' && method === 'GET') {
      await route.fulfill(corsJson(proxies));
      return;
    }

    if (path === '/api/v1/proxies/' && method === 'POST') {
      const payload = request.postDataJSON() as {
        url: string;
        username?: string;
        max_connections?: number;
      };
      const nextProxy = {
        id: payload.url,
        url: payload.url,
        username: payload.username ?? null,
        max_connections: payload.max_connections ?? 16,
        assigned_auths: [],
        geolocation: null,
      };
      proxies.unshift(nextProxy);
      await route.fulfill(corsJson(nextProxy));
      return;
    }

    const proxyAuthsMatch = path.match(/^\/api\/v1\/proxies\/([^/]+)\/auths$/);
    if (proxyAuthsMatch && method === 'GET') {
      await route.fulfill(
        corsJson([
          {
            id: 1,
            site: 'onlyfans',
            username: 'auth-main',
            status: 'active',
            active: true,
          },
        ]),
      );
      return;
    }

    const proxyGeolocationMatch = path.match(/^\/api\/v1\/proxies\/([^/]+)\/geolocation$/);
    if (proxyGeolocationMatch && method === 'POST') {
      await route.fulfill(
        corsJson({
          ip: '203.0.113.10',
          success: true,
          city: 'London',
          region: 'England',
          country: 'United Kingdom',
          latitude: 51.5072,
          longitude: -0.1276,
          flag: { emoji: '🇬🇧' },
          connection: { isp: 'SmokeNet', org: 'SmokeNet London' },
          timezone: { id: 'Europe/London', abbr: 'GMT', utc: '+00:00' },
        }),
      );
      return;
    }

    const proxyAnalyzeMatch = path.match(/^\/api\/v1\/proxies\/([^/]+)\/analyze-stream$/);
    if (proxyAnalyzeMatch && method === 'POST') {
      const payload = request.postDataJSON() as { concurrency_levels?: number[] };
      const level = payload.concurrency_levels?.[0] ?? 32;
      const efficiencyScore = level === 32 ? 1.15 : level === 16 ? 0.88 : 0.73;
      const throughput = level === 32 ? 42 : level === 16 ? 31 : 25;
      const result = {
        concurrency: level,
        max_connections: 32,
        requests: 32,
        successes: 32,
        errors: 0,
        avg_latency_ms: 180,
        p50_latency_ms: 170,
        p95_latency_ms: 230,
        p99_latency_ms: 260,
        max_latency_ms: 280,
        min_latency_ms: 140,
        jitter_ms: 22,
        avg_ttfb_ms: 90,
        throughput_mbps: throughput,
        efficiency_score: efficiencyScore,
        status_counts: { '200': 32 },
        head_status_counts: { '200': 32 },
        download_status_counts: { '200': 32 },
        proxy_ip: '203.0.113.10',
        ip_consistent: true,
        geolocation: {
          ip: '203.0.113.10',
          success: true,
          city: 'London',
          region: 'England',
          country: 'United Kingdom',
          flag: { emoji: '🇬🇧' },
          connection: { isp: 'SmokeNet' },
          timezone: { id: 'Europe/London', abbr: 'GMT', utc: '+00:00' },
        },
      };
      await route.fulfill({
        status: 200,
        headers: {
          ...JSON_HEADERS,
          'content-type': 'text/event-stream',
        },
        body: [
          `data: ${JSON.stringify({ type: 'warmup', ip: '203.0.113.10' })}\n\n`,
          `data: ${JSON.stringify({
            type: 'progress',
            concurrency: level,
            connections: 32,
            requests: 32,
          })}\n\n`,
          `data: ${JSON.stringify({ type: 'result', result })}\n\n`,
          `data: ${JSON.stringify({
            type: 'complete',
            recommended_concurrency: 32,
            recommended_connections: 32,
          })}\n\n`,
        ].join(''),
      });
      return;
    }

    if (path === '/api/v1/proxies/media-pool' && method === 'GET') {
      await route.fulfill(
        corsJson({
          success: true,
          urls: ['https://cdn.example.invalid/media/smoke.mp4'],
          message: null,
        }),
      );
      return;
    }

    if (path === '/api/v1/proxies/assign' && method === 'POST') {
      await route.fulfill(corsJson({ success: true }));
      return;
    }

    if (path === '/api/v1/proxies/test' && method === 'POST') {
      await route.fulfill(
        corsJson({
          success: true,
          message: 'Proxy reachable',
          latency_ms: 84,
        }),
      );
      return;
    }

    if (path === '/api/v1/proxies/bulk-test' && method === 'POST') {
      const payload = request.postDataJSON() as { proxies: Array<{ url: string }> };
      await route.fulfill(
        corsJson({
          results: payload.proxies.map((proxy) => ({
            url: proxy.url,
            success: true,
            message: 'Proxy reachable',
            latency_ms: 84,
          })),
        }),
      );
      return;
    }

    if (path === '/api/v1/proxies/bulk-edit' && method === 'PUT') {
      const payload = request.postDataJSON() as {
        proxy_urls: string[];
        max_connections?: number | null;
        max_concurrency?: number | null;
      };
      const targetUrls = new Set(payload.proxy_urls);
      let updatedCount = 0;
      for (const proxy of proxies) {
        if (!targetUrls.has(proxy.url)) continue;
        if (payload.max_connections != null) {
          proxy.max_connections = payload.max_connections;
        }
        updatedCount += 1;
      }
      await route.fulfill(
        corsJson({
          status: 'success',
          message: `Updated max_connections=${payload.max_connections} on ${updatedCount} proxies`,
          updated_count: updatedCount,
          max_connections: payload.max_connections ?? null,
          max_concurrency: payload.max_concurrency ?? null,
        }),
      );
      return;
    }

    if (path === '/api/v1/proxies/network' && method === 'PUT') {
      await route.fulfill(corsJson({ success: true }));
      return;
    }

    const proxyMutationMatch = path.match(/^\/api\/v1\/proxies\/([^/]+)$/);
    if (proxyMutationMatch && method === 'DELETE') {
      const proxyUrl = decodeURIComponent(proxyMutationMatch[1]);
      const index = proxies.findIndex((proxy) => proxy.url === proxyUrl);
      if (index >= 0) {
        proxies.splice(index, 1);
      }
      await route.fulfill(corsJson({ success: true }));
      return;
    }

    if (proxyMutationMatch && method === 'PUT') {
      const proxyUrl = decodeURIComponent(proxyMutationMatch[1]);
      const payload = request.postDataJSON() as {
        username?: string;
        max_connections?: number;
        max_concurrency?: number | null;
      };
      const proxy = proxies.find((item) => item.url === proxyUrl);
      if (proxy) {
        if (payload.username !== undefined) {
          proxy.username = payload.username || null;
        }
        if (payload.max_connections !== undefined) {
          proxy.max_connections = payload.max_connections;
        }
      }
      await route.fulfill(corsJson(proxy ?? { success: true }));
      return;
    }

    if (path === '/api/v1/plugins/active-webui') {
      await route.fulfill(corsJson([]));
      return;
    }

    await route.fulfill(corsJson({}));
  });

  // Registered after the catch-all so these structured responses take precedence;
  // spec-specific routes registered later still override them.
  await installMpsMocks(page);
  await installStatisticsActivityMocks(page);
  await installWebhookMocks(page);
  await installFavouritesMocks(page);
}
