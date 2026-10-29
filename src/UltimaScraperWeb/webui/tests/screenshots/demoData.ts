import type { Page, Route } from '@playwright/test';
import { makeSiteStatistics, makeStatisticsSnapshot } from '../fixtures/statistics';
import { advanceActivityBucket } from '../../src/themes/ultima-atlas/views/statistics/statisticsActivityModel';
import type { StatisticsActivityInterval } from '../../src/api/types/statistics';
import { backendPath } from '../smoke/helpers';

// Fictional data for the README and docs screenshots, layered over the smoke
// mocks. Every name is a made-up demo_* handle; nothing here comes from a real
// account, creator, host or path.

const BACKEND_ID = 'usr-docker';
const HOSTNAME = 'homelab';
const VERSION = '0.1.0';
const MINUTE = 60_000;

const CREATORS = [
  { id: 101, user_id: 4_100_001, username: 'demo_aurora', name: 'Aurora (demo)', site: 'onlyfans', posts: 1_284, images: 3_912, videos: 418, price: 9.99 },
  { id: 102, user_id: 4_100_002, username: 'demo_basil', name: 'Basil (demo)', site: 'onlyfans', posts: 642, images: 1_870, videos: 233, price: 0 },
  { id: 103, user_id: 4_100_003, username: 'demo_cedar', name: 'Cedar (demo)', site: 'fansly', posts: 2_051, images: 5_104, videos: 760, price: 12.5 },
  { id: 104, user_id: 4_100_004, username: 'demo_dahlia', name: 'Dahlia (demo)', site: 'onlyfans', posts: 318, images: 902, videos: 64, price: 4.99 },
  { id: 105, user_id: 4_100_005, username: 'demo_ember', name: 'Ember (demo)', site: 'fansly', posts: 977, images: 2_640, videos: 301, price: 7.99 },
  { id: 106, user_id: 4_100_006, username: 'demo_fern', name: 'Fern (demo)', site: 'onlyfans', posts: 1_536, images: 4_211, videos: 512, price: 14.99 },
];

type DemoJob = { id: string; name: string; status: string; tasks: number; done: number; failed: number; creator: string; ageMinutes: number };

const JOBS: DemoJob[] = [
  { id: 'job-7f3a91', name: 'Nightly archive sync', status: 'running', tasks: 48, done: 31, failed: 0, creator: 'demo_aurora', ageMinutes: 22 },
  { id: 'job-6c2e10', name: 'Messages and stories', status: 'running', tasks: 12, done: 5, failed: 0, creator: 'demo_cedar', ageMinutes: 9 },
  { id: 'job-5d8b44', name: 'New subscriptions', status: 'pending', tasks: 6, done: 0, failed: 0, creator: 'demo_ember', ageMinutes: 3 },
  { id: 'job-4a1f07', name: 'Weekly full refresh', status: 'completed', tasks: 120, done: 120, failed: 0, creator: 'demo_fern', ageMinutes: 180 },
  { id: 'job-3b9c62', name: 'Highlights backfill', status: 'completed', tasks: 36, done: 35, failed: 1, creator: 'demo_basil', ageMinutes: 340 },
  { id: 'job-2e7d58', name: 'Profile checks', status: 'completed', tasks: 240, done: 240, failed: 0, creator: 'demo_dahlia', ageMinutes: 720 },
  { id: 'job-1c4a93', name: 'Purchased media', status: 'cancelled', tasks: 18, done: 7, failed: 0, creator: 'demo_aurora', ageMinutes: 1_440 },
];

function iso(minutesAgo: number): string {
  return new Date(Date.now() - minutesAgo * MINUTE).toISOString();
}

function json(route: Route, body: unknown) {
  return route.fulfill({ json: body, headers: { 'access-control-allow-origin': '*' } });
}

function onPath(page: Page, matches: (path: string) => boolean, handler: (route: Route, path: string) => unknown) {
  return page.route(
    (url) => matches(backendPath(url)),
    async (route) => {
      if (route.request().method() === 'OPTIONS') return route.fallback();
      return handler(route, backendPath(route.request().url()));
    },
  );
}

function jobPayload(job: DemoJob, startedAt: number) {
  // Running jobs keep completing tasks, so the dashboard measures a live rate.
  const done = job.status === 'running'
    ? Math.min(job.tasks - 1, job.done + Math.floor((Date.now() - startedAt) / 4000))
    : job.done;
  const creator = CREATORS.find((candidate) => candidate.username === job.creator)!;
  return {
    job_id: job.id,
    job_name: job.name,
    status: job.status,
    task_count: job.tasks,
    completed_tasks: done,
    failed_tasks: job.failed,
    tasks: [{
      task_type: 'scrape_user', content_type: null, status: job.status, username: creator.username,
      site: creator.site, auth_id: 1, items_processed: done, items_total: job.tasks,
    }],
    created_at: iso(job.ageMinutes),
    updated_at: iso(Math.max(0, job.ageMinutes - 2)),
    created_by: 'webui',
    is_scheduled: job.name.startsWith('Nightly') || job.name.startsWith('Weekly'),
    scheduled_for: null,
    interval_seconds: null,
    cron: job.name.startsWith('Nightly') ? '0 3 * * *' : null,
    run_count: job.name.startsWith('Nightly') ? 41 : 1,
    last_ran_at: iso(job.ageMinutes),
  };
}

/** One hour of dashboard history, as the dashboard stores it between visits. */
function pulseHistory() {
  const bucket = 15_000;
  const end = Math.floor(Date.now() / bucket) * bucket;
  return Array.from({ length: 240 }, (_, index) => {
    const wave = Math.sin(index / 14) * 0.35 + Math.sin(index / 5) * 0.15;
    return {
      timestamp: end - (240 - index) * bucket,
      activeJobs: 2,
      queuedJobs: index > 200 ? 1 : 0,
      itemRate: Math.max(0, Math.round((34 + wave * 30) * 10) / 10),
      successRate: index % 53 === 17 ? 96.5 : 100,
      workerLoad: 75,
      writeRate: Math.round((18 + wave * 14) * 1_048_576),
    };
  });
}

export async function seedDemoBrowser(page: Page) {
  await page.addInitScript((samples) => {
    localStorage.setItem('usr_system_pulse_samples', JSON.stringify(samples));
  }, pulseHistory());
}

export async function installDemoMocks(page: Page) {
  const startedAt = Date.now();
  await seedDemoBrowser(page);
  await page.routeWebSocket(/\/ws\//, () => {});

  await page.route('**/webui/api/v1/connections', (route) => json(route, [{
    id: 'default', name: 'Home server', base_url: 'http://backend:21121', tls_verify: true, managed: true, has_token: true, trust_plugins: true,
  }]));
  await page.route('**/webui/api/v1/installs/cluster-stores*', (route) => json(route, { available: false }));

  await onPath(page, (path) => path === '/api/v1/system/bootstrap', (route) => json(route, {
    backend_id: BACKEND_ID, hostname: HOSTNAME, version: VERSION, supported_sites: ['onlyfans', 'fansly'],
    setup: { is_configured: true, has_config: true, has_database: true, data_directory: '/data', startup_id: 'startup-smoke' },
    features: { webhook_stream: true, startup_migrations: true, distributed_mode: true, remote_backends: false, system_bootstrap: true },
    support_matrix: { ui_mode: 'webui', tui_supported: false, runtime_database: 'postgresql', postgres_required: true, sqlite_runtime_supported: false, sqlite_import_supported: true },
  }));
  await onPath(page, (path) => path === '/api/v1/admin/health', (route) => json(route, {
    status: 'healthy', instance_id: BACKEND_ID, distributed_mode: true, transitioning: false, queue_type: 'redis', queue_size: 1, redis_connected: true,
  }));
  await onPath(page, (path) => path === '/api/v1/admin/queue-stats', (route) => json(route, {
    instance_id: BACKEND_ID, distributed_mode: true, transitioning: false, local_queue_size: 0, redis_queue_size: 1,
    active_queue_type: 'redis', recovery_interval: 60, next_recovery_seconds: 42, last_recovery_at: iso(1),
  }));
  await onPath(page, (path) => path === '/api/v1/system/backend', (route) => json(route, {
    backend_id: BACKEND_ID, distributed_mode: true, redis_connected: true, worker_count: 4, active_workers: 3, pending_jobs: 1,
    workers: [
      { worker_id: 'worker-1', status: 'busy', current_job: JOBS[0].id, jobs_completed: 412 },
      { worker_id: 'worker-2', status: 'busy', current_job: JOBS[0].id, jobs_completed: 398 },
      { worker_id: 'worker-3', status: 'busy', current_job: JOBS[1].id, jobs_completed: 377 },
      { worker_id: 'worker-4', status: 'idle', current_job: null, jobs_completed: 365 },
    ],
    system_stats: {
      timestamp: new Date().toISOString(), cpu_percent: 38.4, cpu_count: 16,
      memory_total: 34_359_738_368, memory_used: 13_743_895_347, memory_free: 20_615_843_021, memory_percent: 40,
      disks: [{
        device: 'sda1', mount_point: '/data', total_bytes: 8_001_563_222_016, used_bytes: 5_120_000_000_000,
        free_bytes: 2_881_563_222_016, percent_used: 64, read_bytes_per_sec: 4_194_304, write_bytes_per_sec: 23_068_672,
      }],
    },
  }));
  await onPath(page, (path) => path === '/api/v1/system/backends', (route) => json(route, {
    success: true, local_backend_id: BACKEND_ID, local_hostname: HOSTNAME, backends: [], total_backends: 0,
  }));
  await onPath(page, (path) => path === '/api/v1/system/drives', (route) => json(route, {
    backend_id: BACKEND_ID,
    drives: [{
      path: '/data', device: '/dev/sda1', total_bytes: 8_001_563_222_016, used_bytes: 5_120_000_000_000, free_bytes: 2_881_563_222_016,
      percent_used: 64, is_configured: true, directory_count: 2, configured_directories: ['/data/downloads', '/data/metadata'],
    }],
  }));

  await onPath(page, (path) => path === '/api/v1/jobs', (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    const jobs = JOBS.map((job) => jobPayload(job, startedAt));
    return json(route, { jobs, total: jobs.length, page: 1, page_size: 50 });
  });
  await onPath(page, (path) => path === '/api/v1/jobs/active-tasks', (route) => {
    const tasks = JOBS.filter((job) => job.status === 'running').map((job, index) => {
      const processed = 186 + Math.floor(((Date.now() - startedAt) / 1000) * (index === 0 ? 21 : 13));
      const creator = CREATORS.find((candidate) => candidate.username === job.creator)!;
      return {
        job_id: job.id, job_name: job.name, job_status: 'running', job_total_tasks: job.tasks,
        task_id: `${job.id}-task-${index + 1}`, task_type: 'scrape_user', status: 'running', site: creator.site,
        username: creator.username, content_type: index === 0 ? 'Posts' : 'Messages', started_at: iso(4), completed_at: null,
        // Grows between polls, so the dashboard's items/sec reads as live.
        progress: 0.62, items_processed: processed, items_total: 900, items_scraped: processed, items_saved: processed - 15,
        bytes_written: 1_288_490_188, total_bytes: 2_147_483_648, speed_bps: 18_874_368, avg_speed_bps: 16_777_216, error: null,
      };
    });
    return json(route, { tasks, total: tasks.length });
  });

  await onPath(page, (path) => path === '/api/v1/users' || path === '/api/v1/users/', (route) => {
    const users = CREATORS.map((creator, index) => ({
      id: creator.id, user_id: creator.user_id, username: creator.username, name: creator.name, site: creator.site,
      avatar_url: null, header_url: null, description: 'Demo profile for the documentation.',
      is_active: index !== 3, performer: true, favorite: index === 0 || index === 2, price: creator.price,
      post_count: creator.posts, media_count: creator.images + creator.videos, image_count: creator.images, video_count: creator.videos,
      sex: 0, is_subscribed: index !== 1, is_pending_order: false, downloaded_at: iso(60 * (index + 1)), last_checked_at: iso(30 * (index + 1)),
    }));
    const paid = users.filter((user) => user.price > 0);
    return json(route, {
      success: true, users, total: users.length, active: users.filter((user) => user.is_active).length,
      inactive: users.filter((user) => !user.is_active).length,
      avg_price: Math.round((paid.reduce((sum, user) => sum + user.price, 0) / paid.length) * 100) / 100,
      free: users.length - paid.length, paid: paid.length,
    });
  });

  await installDemoStatistics(page);
}

async function installDemoStatistics(page: Page) {
  const onlyfans = makeStatisticsSnapshot({
    total_media_count: 1_240_000, downloaded_media_count: 1_050_000,
    image_media_count: 840_000, video_media_count: 360_000, audio_media_count: 30_000, other_media_count: 10_000,
    sized_media_count: 1_100_000, image_sized_count: 750_000, video_sized_count: 320_000, audio_sized_count: 25_000, other_sized_count: 5_000,
    user_record_count: 92_400, performer_profile_count: 8_200, active_user_count: 74_800, archived_content_count: 640_000,
    post_count: 390_000, message_count: 165_000, story_count: 52_000, mass_message_count: 33_000,
    total_known_bytes: 48_000_000_000_000, avg_image_size_bytes: 3_000_000, avg_video_size_bytes: 140_000_000, avg_audio_size_bytes: 24_000_000,
    size_coverage_ratio: 1_100_000 / 1_240_000,
  });
  const fansly = makeStatisticsSnapshot({
    site: 'fansly', total_media_count: 240_000, downloaded_media_count: 168_000,
    image_media_count: 180_000, video_media_count: 50_000, audio_media_count: 8_000, other_media_count: 2_000,
    sized_media_count: 180_000, image_sized_count: 140_000, video_sized_count: 34_000, audio_sized_count: 5_000, other_sized_count: 1_000,
    user_record_count: 18_400, performer_profile_count: 2_100, active_user_count: 14_200, archived_content_count: 140_000,
    post_count: 88_000, message_count: 34_000, story_count: 11_000, mass_message_count: 7_000,
    total_known_bytes: 6_000_000_000_000, avg_image_size_bytes: 2_000_000, avg_video_size_bytes: 160_000_000, avg_audio_size_bytes: 24_000_000,
    size_coverage_ratio: 0.75,
  });
  const sitesFor = (params: URLSearchParams) => ['onlyfans', 'fansly'].filter((site) => !params.get('site') || params.get('site') === site);

  await page.route('**/api/v1/statistics?*', (route) => json(route, [makeSiteStatistics(onlyfans), makeSiteStatistics(fansly)]));
  await page.route('**/api/v1/statistics/activity?*', (route) => {
    const params = new URL(route.request().url()).searchParams;
    const interval = (params.get('interval') ?? 'day') as StatisticsActivityInterval;
    const length = { minute: 60, hour: 48, day: 90, month: 24, year: 9 }[interval];
    const step = { minute: MINUTE, hour: 60 * MINUTE, day: 1440 * MINUTE, month: 43_800 * MINUTE, year: 525_600 * MINUTE }[interval];
    const start = Date.now() - length * step;
    const dates: number[] = [];
    for (let bucket = start; dates.length < length; bucket = advanceActivityBucket(bucket, interval)) dates.push(bucket);
    const metric = params.get('metric');
    return json(route, {
      metric, interval, range: params.get('range'), date_field: metric === 'accounts' ? params.get('account_date') : 'created_at',
      start_at: new Date(start).toISOString(), end_at: new Date().toISOString(), calculated_at: new Date().toISOString(),
      sites: sitesFor(params).map((site, siteIndex) => ({
        site, available: true, availability_error: null, undated_count: 0,
        points: dates.map((bucket, index) => ({
          bucket_started_at: new Date(bucket).toISOString(),
          count: Math.round((metric === 'accounts' ? 90 : 2400) * (1 + index / length) * (1 + Math.sin(index * 0.45) * 0.35) / (siteIndex + 1.6)),
        })),
      })),
    });
  });
  await page.route('**/api/v1/statistics/seasonality?*', (route) => {
    const params = new URL(route.request().url()).searchParams;
    const cycle = (params.get('cycle') ?? 'weekday') as 'hour' | 'weekday' | 'monthday' | 'month';
    const bins = { hour: 24, weekday: 7, monthday: 31, month: 12 }[cycle];
    return json(route, {
      metric: params.get('metric'), cycle, date_field: 'created_at', start_date: '2025-10-30', end_date: '2026-10-29', calculated_at: new Date().toISOString(),
      exposures: Array(bins).fill(cycle === 'hour' ? 365 : cycle === 'weekday' ? 52 : cycle === 'monthday' ? 12 : 1),
      sites: sitesFor(params).map((site, siteIndex) => ({
        site, available: true, availability_error: null,
        counts: Array.from({ length: bins }, (_, index) => Math.round((10_000 + Math.sin(index * 0.6) * 6_000) / (siteIndex + 1))),
      })),
    });
  });
  await page.route('**/api/v1/statistics/history?*', (route) => json(route, {
    range: '30d', start_date: '2026-09-30', end_date: '2026-10-29',
    sites: [onlyfans, fansly].map((snapshot) => ({
      site: snapshot.site, available: true, availability_error: null,
      points: Array.from({ length: 30 }, (_, index) => ({
        ...snapshot,
        bucket_date: new Date(Date.UTC(2026, 8, 30 + index)).toISOString().slice(0, 10),
        total_media_count: snapshot.total_media_count - (29 - index) * 1_700,
        downloaded_media_count: (snapshot.downloaded_media_count ?? 0) - (29 - index) * 1_200,
      })),
    })),
  }));
}

/** The setup wizard's first steps on a fresh Ubuntu host. */
export async function installDemoSetupMocks(page: Page) {
  await page.route('**/webui/api/v1/installs/cluster-stores*', (route) => json(route, { available: false }));
  await page.route('**/webui/api/v1/installs/environment', (route) => json(route, {
    version: VERSION, in_container: true, local_available: true, copy_available: false, releases: [],
  }));
  await page.route('**/webui/api/v1/installs/detect', (route) => json(route, {
    facts: {
      architecture: 'amd64', os_name: 'Ubuntu 24.04', user: 'ultimascraper', home: '/home/ultimascraper', hostname: HOSTNAME,
      docker_version: '27.3.1', compose_version: '2.29.7', docker_needs_sudo: false, sudo_mode: 'none',
      memory_mb: 32_768, home_free_mb: 2_400_000, listening_ports: [21120], existing_projects: [], existing_install: null,
      services: {}, local_images: [], warnings: [],
    },
    recommended_components: { backend: 'install', worker: 'install', postgres: 'install', redis: 'install', webui: 'reuse' },
    needs_sudo_for: [], recommended_image_source: 'registry', recommended_version: VERSION,
  }));
}
