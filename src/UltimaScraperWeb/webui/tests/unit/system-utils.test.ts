import { describe, expect, it } from 'vitest';

import type { SettingsResponse } from '../../src/api/types/settings';
import type { DriveInfo } from '../../src/api/types/system';
import {
  getWorkerGridClassName,
  mergeConfiguredDrivesWithInventory,
} from '../../src/features/system/lib/systemUtils';

const settingsFixture: SettingsResponse = {
  hostname: 'cluster-node',
  job_execution: {
    window_max_tasks: null,
    refill_ready_threshold: null,
    event_retention_hours: 168,
    task_history_retention_days: 3,
    receipt_retention_minutes: 60,
    terminal_reconcile_interval_seconds: 60,
    terminal_reconcile_min_age_seconds: 300,
    terminal_reconcile_batch_size: 100,
    completed_job_retention_seconds: 86400,
    completed_job_retention_batch_size: 100,
  },
  worker_pool: {
    enabled: true,
    size: 10,
    sites: ['onlyfans'],
    max_claimed_jobs: 4,
  },
  backend: {
    backend_id: 'backend-1',
    execution_mode: 'distributed',
  },
  redis: {
    host: 'localhost',
    port: 6379,
    db: 0,
    password: null,
    enabled: true,
  },
  network: {
    guest_route_rate_limit: 0,
    guest_session_pool: false,
    max_connections: 32,
    proxies: [],
    proxy_fallback: false,
    downloads: {
      max_concurrency: 8,
      per_domain_concurrency: 4,
      head_concurrency: 2,
      buffer_size_bytes: 1024,
    },
  },
  download_setup: {
    drives: [
      {
        minimum_space: 0,
        store: true,
        scan_existing: true,
        overflow: true,
        directories: ['/mnt/live/downloads', '/mnt/offline/downloads'],
      },
    ],
    alt_directory_formats: [],
    staging_directories: [],
    directory_format: '{site_name}/{user_username}',
    filename_format: '{filename}',
    text_length: 255,
    date_format: '%Y-%m-%d',
    overwrite_files: true,
  },
  metadata_setup: {
    drives: [
      {
        minimum_space: 0,
        store: true,
        scan_existing: true,
        overflow: true,
        directories: ['/mnt/offline/metadata'],
      },
    ],
    directory_format: '{site_name}/{user_username}',
  },
  previews_directory: null,
  subtitles_directory: null,
  drm: {
    device_client_blob_filepath: null,
    device_private_key_filepath: null,
  },
  sites: {
    onlyfans: { blacklists: [] },
    fansly: { blacklists: [] },
  },
  config_path: '/tmp/config.json',
  is_configured: true,
};

describe('getWorkerGridClassName', () => {
  it('keeps the default grid for smaller worker pools', () => {
    expect(getWorkerGridClassName(0)).toBe('workers-grid');
    expect(getWorkerGridClassName(15)).toBe('workers-grid');
  });

  it('switches to the dense grid for mid-sized worker pools', () => {
    expect(getWorkerGridClassName(16)).toBe('workers-grid workers-grid-dense');
    expect(getWorkerGridClassName(31)).toBe('workers-grid workers-grid-dense');
  });

  it('switches to the compact grid for large worker pools', () => {
    expect(getWorkerGridClassName(32)).toBe('workers-grid workers-grid-compact');
    expect(getWorkerGridClassName(40)).toBe('workers-grid workers-grid-compact');
  });
});

describe('mergeConfiguredDrivesWithInventory', () => {
  it('retains live drives and appends configured offline mounts', () => {
    const liveDrive: DriveInfo = {
      path: '/mnt/live',
      device: '/dev/sdz1',
      total_bytes: 1024,
      used_bytes: 256,
      free_bytes: 768,
      percent_used: 25,
      is_configured: false,
      directory_count: 0,
      configured_directories: [],
    };

    const merged = mergeConfiguredDrivesWithInventory([liveDrive], settingsFixture);

    expect(merged).toHaveLength(2);
    expect(merged[0]).toMatchObject({
      path: '/mnt/live',
      is_available: true,
      is_configured: true,
      configured_directories: ['/mnt/live/downloads'],
    });
    expect(merged[1]).toMatchObject({
      path: '/mnt/offline',
      device: 'Mount unavailable',
      is_available: false,
      is_configured: true,
      configured_directories: ['/mnt/offline/downloads', '/mnt/offline/metadata'],
    });
  });

  it('avoids duplicating configured directories already reported by the backend', () => {
    const liveDrive: DriveInfo = {
      path: '/mnt/live',
      device: '/dev/sdz1',
      total_bytes: 1024,
      used_bytes: 256,
      free_bytes: 768,
      percent_used: 25,
      is_configured: true,
      directory_count: 1,
      configured_directories: ['/mnt/live/downloads'],
    };

    const merged = mergeConfiguredDrivesWithInventory([liveDrive], settingsFixture);

    expect(merged[0].configured_directories).toEqual(['/mnt/live/downloads']);
    expect(merged[0].directory_count).toBe(1);
  });

  it('treats directories on the root mount as available when root is reported live', () => {
    const rootSettings: SettingsResponse = {
      ...settingsFixture,
      download_setup: {
        ...settingsFixture.download_setup,
        drives: [
          {
            minimum_space: 0,
            store: true,
            scan_existing: true,
            overflow: true,
            directories: ['/var/data/storage'],
          },
        ],
      },
      metadata_setup: {
        ...settingsFixture.metadata_setup,
        drives: [],
      },
    };

    const liveDrive: DriveInfo = {
      path: '/',
      device: '/dev/sda2',
      total_bytes: 1024,
      used_bytes: 256,
      free_bytes: 768,
      percent_used: 25,
      is_configured: false,
      directory_count: 0,
      configured_directories: [],
    };

    const merged = mergeConfiguredDrivesWithInventory([liveDrive], rootSettings);

    expect(merged).toHaveLength(1);
    expect(merged[0]).toMatchObject({
      path: '/',
      is_available: true,
      is_configured: true,
      configured_directories: ['/var/data/storage'],
    });
  });
});
