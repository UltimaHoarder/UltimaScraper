import { describe, expect, it } from 'vitest';

import type {
  BackendStatusResponse,
  DriveInfo,
  RemoteBackendInfo,
} from '../../src/api/types/system';
import { buildRegisterBackends } from '../../src/features/system/systemFleetRegisterData';

const now = Date.parse('2026-09-15T12:00:00.000Z');

const localStatus: BackendStatusResponse = {
  backend_id: 'control-01',
  distributed_mode: true,
  redis_connected: true,
  worker_count: 2,
  active_workers: 1,
  pending_jobs: 7,
  workers: [
    {
      worker_id: 'control-01-w01',
      status: 'busy',
      current_job: 'job-archive-1',
      jobs_completed: 12,
    },
    {
      worker_id: 'control-01-w02',
      status: 'idle',
      current_job: null,
      jobs_completed: 9,
    },
  ],
  system_stats: null,
};

const localDrive: DriveInfo = {
  path: '/mnt/archive',
  device: '/dev/md0',
  total_bytes: 1000,
  used_bytes: 500,
  free_bytes: 500,
  percent_used: 50,
  is_configured: true,
  directory_count: 1,
  configured_directories: ['/mnt/archive/OnlyFans'],
  is_available: true,
};

const remoteBackend: RemoteBackendInfo = {
  backend_id: 'archive-02',
  hostname: 'archive-secondary',
  status: 'online',
  last_seen: '2026-09-15T11:59:40.000Z',
  max_workers: 4,
  version: '1.0.0',
  drives: [
    {
      path: '/mnt/secondary',
      device: '/dev/md1',
      total_bytes: 2000,
      used_bytes: 1900,
      free_bytes: 100,
      percent_used: 95,
      configured_directories: [],
    },
  ],
  workers: [
    {
      worker_id: 'archive-02-w01',
      status: 'idle',
      current_job: null,
      jobs_completed: 4,
    },
  ],
  active_workers: 0,
  pending_jobs: 7,
};

describe('buildRegisterBackends', () => {
  it('synthesizes the local row and keeps local storage ownership distinct', () => {
    const result = buildRegisterBackends(
      localStatus,
      {
        local_backend_id: 'control-01',
        local_hostname: 'control-host',
        backends: [remoteBackend],
      },
      [localDrive],
      now,
    );

    expect(result.map((backend) => backend.backendId)).toEqual(['control-01', 'archive-02']);
    expect(result[0]).toMatchObject({
      isLocal: true,
      activeWorkers: 1,
      pendingJobs: 7,
      maxWorkers: 2,
    });
    expect(result[0].mounts.map((mount) => mount.path)).toEqual(['/mnt/archive']);
    expect(result[1].mounts[0]).toMatchObject({
      backendId: 'archive-02',
      path: '/mnt/secondary',
    });
  });

  it('marks stale remote heartbeats offline while retaining their records', () => {
    const result = buildRegisterBackends(
      undefined,
      {
        local_backend_id: 'control-01',
        local_hostname: 'control-host',
        backends: [{
          ...remoteBackend,
          last_seen: '2026-09-15T11:57:00.000Z',
          status: 'online',
        }],
      },
      [],
      now,
    );

    expect(result[0].backendId).toBe('control-01');
    expect(result[1]).toMatchObject({
      backendId: 'archive-02',
      health: 'offline',
      heartbeatAge: 180,
    });
  });
});
