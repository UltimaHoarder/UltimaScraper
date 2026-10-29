import { describe, expect, it } from 'vitest';

import { buildActiveMounts, buildStorageGroups } from '../../src/features/system/lib/architectureStorage';
import type { RegisterBackend, RegisterMount } from '../../src/features/system/systemFleetRegisterData';

const GB = 1000 ** 3;

const mount = (path: string, device: string, freeGb: number, isConfigured = false): RegisterMount => ({
  id: path,
  backendId: 'desk',
  path,
  device,
  totalBytes: 1000 * GB,
  usedBytes: (1000 - freeGb) * GB,
  freeBytes: freeGb * GB,
  percentUsed: 100 - freeGb / 10,
  configuredDirectories: [],
  isAvailable: true,
  isConfigured,
});

const backend = (overrides: Partial<RegisterBackend>): RegisterBackend => ({
  backendId: 'desk',
  label: 'desk',
  hostname: 'desk',
  status: 'online',
  version: '0.1.0',
  maxWorkers: 8,
  activeWorkers: 0,
  pendingJobs: 0,
  lastSeen: '',
  heartbeatAge: null,
  health: 'healthy',
  isLocal: true,
  clusterId: 'home',
  workers: [],
  mounts: [],
  ...overrides,
});

describe('buildStorageGroups', () => {
  it('folds paths of one device and marks staging, drives and the flow path', () => {
    const [group] = buildStorageGroups(
      [
        backend({
          mounts: [
            mount('/', '/dev/sda2', 60),
            mount('/mnt/work2', '192.0.2.10:/mnt/apps/work', 400),
            mount('/mnt/media', '192.0.2.10:/mnt/tank/media', 50, true),
            mount('/mnt/vault2', '192.0.2.20:/mnt/vault2', 90, true),
            mount('/mnt/media2', '192.0.2.10:/mnt/fast/media', 10),
            mount('/mnt/fast/media2', '192.0.2.10:/mnt/fast/media', 10),
          ],
        }),
      ],
      [
        { path: '/dev/shm/UltimaStaging', usage: ['downloads'], policy: ['prefer'] },
        { path: '/mnt/work2/decrypted-media', usage: ['downloads'], policy: [] },
      ],
    );

    expect(group.rows.map((row) => [row.path, row.kind, row.flowTarget])).toEqual([
      ['/dev/shm/UltimaStaging', 'ram-staging', 'ram'],
      ['/mnt/work2', 'staging', 'disk'],
      ['/mnt/media', 'drive', null],
      ['/mnt/vault2', 'drive', 'drive'],
      ['/', 'mount', null],
      ['/mnt/media2', 'mount', null],
    ]);
    expect(group.rows.find((row) => row.path === '/mnt/media2')?.alsoAt).toEqual(['/mnt/fast/media2']);
  });

  it('keeps only mounts in use, each tied to its backend', () => {
    const mounts = buildActiveMounts(
      [
        backend({
          mounts: [
            mount('/', '/dev/sda2', 60),
            mount('/mnt/work2', '192.0.2.10:/mnt/apps/work', 400),
            mount('/mnt/media', '192.0.2.10:/mnt/tank/media', 50, true),
          ],
        }),
        backend({ backendId: 'atlas', label: 'atlas', isLocal: false, mounts: [mount('/app/logs', 'mmcblk0p2', 6)] }),
      ],
      [{ path: '/mnt/work2/decrypted-media', usage: ['downloads'], policy: [] }],
    );

    expect(mounts.map((entry) => [entry.path, entry.kind, entry.backendId, entry.clusterId])).toEqual([
      ['/mnt/work2', 'staging', 'desk', 'home'],
      ['/mnt/media', 'drive', 'desk', 'home'],
    ]);
  });

  it('leaves staging off hosts whose settings are not loaded here', () => {
    const [group] = buildStorageGroups(
      [backend({ backendId: 'atlas', label: 'atlas', isLocal: false, mounts: [mount('/', 'mmcblk0p2', 6)] })],
      [{ path: '/dev/shm/UltimaStaging', usage: ['downloads'], policy: ['prefer'] }],
    );

    expect(group.rows.map((row) => row.kind)).toEqual(['mount']);
  });
});
