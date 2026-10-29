import { describe, expect, it } from 'vitest';

import { summarizeStoragePool } from '../../src/features/system/lib/storagePool';
import type { RegisterMount } from '../../src/features/system/systemFleetRegisterData';

const GB = 1024 ** 3;

const mount = (backendId: string, path: string, device: string, totalGb: number, usedGb: number, freeGb: number): RegisterMount => ({
  id: `${backendId}:${path}`,
  backendId,
  path,
  device,
  totalBytes: totalGb * GB,
  usedBytes: usedGb * GB,
  freeBytes: freeGb * GB,
  percentUsed: (usedGb / totalGb) * 100,
  configuredDirectories: [],
  isAvailable: true,
  isConfigured: false,
});

describe('summarizeStoragePool', () => {
  it('counts one disk mounted at several paths once, per host', () => {
    const pool = summarizeStoragePool([
      mount('pi', '/app/__user_data__', 'mmcblk0p2', 28, 21, 6),
      mount('pi', '/app/logs', 'mmcblk0p2', 28, 21, 6),
      mount('desk', '/', '/dev/sda2', 1800, 1650, 55),
      mount('desk', '/home', 'sda2', 1800, 1650, 55),
      // Another host's mmcblk0p2 is a different card.
      mount('pi2', '/', 'mmcblk0p2', 28, 10, 18),
    ]);

    expect(pool.totalBytes).toBe((28 + 1800 + 28) * GB);
    expect(pool.storageCount).toBe(3);
    expect(pool.mountCount).toBe(5);
  });

  it('counts an export once however many paths or hosts mount it', () => {
    const pool = summarizeStoragePool([
      mount('desk', '/mnt/media2', '192.0.2.10:/mnt/fast/media', 3300, 3000, 240),
      mount('desk', '/mnt/fast/media2', '192.0.2.10:/mnt/fast/media', 3300, 3000, 240),
      mount('pi', '/data', 'root@192.0.2.10:/mnt/fast/media', 3300, 3000, 240),
    ]);

    expect(pool.totalBytes).toBe(3300 * GB);
    expect(pool.storageCount).toBe(1);
  });

  it("counts a NAS pool's shared free space once across its datasets", () => {
    const pool = summarizeStoragePool([
      mount('desk', '/mnt/media', '192.0.2.10:/mnt/tank/media', 50000, 49750, 250),
      mount('desk', '/mnt/archive', '192.0.2.10:/mnt/tank/backups', 307, 57, 250),
      mount('desk', '/mnt/databases', '192.0.2.10:/mnt/tank/databases', 250, 0, 250),
      // Another server's export with the same free space is its own storage.
      mount('desk', '/mnt/vault1', '192.0.2.20:/mnt/vault1', 13000, 12750, 250),
    ]);

    expect(pool.usedBytes).toBe((49750 + 57 + 0 + 12750) * GB);
    expect(pool.freeBytes).toBe((250 + 250) * GB);
    expect(pool.totalBytes).toBe((49750 + 57 + 250 + 13000) * GB);
    expect(pool.storageCount).toBe(2);
  });

  it('keeps datasets in one pool when their free space was read a moment apart', () => {
    const pool = summarizeStoragePool([
      mount('desk', '/mnt/work', '192.0.2.10:/mnt/fast/work', 240, 0.07, 239.999),
      mount('desk', '/mnt/media2', '192.0.2.10:/mnt/fast/media', 3227, 2987, 240),
      // A different pool on the same server is far apart in free space.
      mount('desk', '/mnt/logs', '192.0.2.10:/mnt/apps/logs', 434, 0, 434),
    ]);

    expect(pool.storageCount).toBe(2);
  });
});
