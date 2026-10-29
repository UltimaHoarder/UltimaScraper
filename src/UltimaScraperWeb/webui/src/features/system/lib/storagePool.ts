import type { RegisterMount } from '../systemFleetRegisterData';

export interface StoragePoolSummary {
  totalBytes: number;
  usedBytes: number;
  freeBytes: number;
  /** Mounts reported, before any is folded into another. */
  mountCount: number;
  /** Separate pieces of storage left once each is counted once. */
  storageCount: number;
}

/** "server:/export" (NFS, SSHFS) names the same storage on every host that mounts it. */
function networkSource(device: string): { server: string; key: string } | null {
  const match = /^(?:[^@\s/]+@)?([^:\s/]+):(\/.*)$/.exec(device);
  return match ? { server: match[1], key: `${match[1]}:${match[2]}` } : null;
}

const GIB = 1024 ** 3;

/** Free space read at slightly different moments still matches within this. */
function sameFree(a: number, b: number): boolean {
  return Math.abs(a - b) <= Math.max(GIB, Math.max(a, b) * 0.005);
}

/**
 * Capacity with each device counted once. One disk mounted at several paths,
 * or one export mounted twice or on two hosts, is a single entry. Exports from
 * one server that report the same free space, give or take drift between reads,
 * are datasets of one pool (ZFS):
 * each reports the pool's free space as its own, so the pool is their used
 * space plus that free space once.
 */
export function summarizeStoragePool(mounts: RegisterMount[]): StoragePoolSummary {
  const seen = new Set<string>();
  const pools = new Map<string, RegisterMount[]>();

  for (const mount of mounts) {
    const network = networkSource(mount.device);
    // Identical figures from one server: the same filesystem under another export path.
    const identity = network
      ? [`${network.server}:${mount.totalBytes}:${mount.usedBytes}:${mount.freeBytes}`, network.key]
      : [`${mount.backendId}:${mount.device.replace(/^\/dev\//, '')}`];
    if (identity.some((key) => seen.has(key))) continue;
    identity.forEach((key) => seen.add(key));

    const poolKey = network
      ? ([...pools.keys()].find(
          (key) => key.startsWith(`${network.server}|`) && sameFree(pools.get(key)![0].freeBytes, mount.freeBytes),
        ) ?? `${network.server}|${mount.path}`)
      : identity[0];
    pools.set(poolKey, [...(pools.get(poolKey) ?? []), mount]);
  }

  let totalBytes = 0;
  let usedBytes = 0;
  let freeBytes = 0;
  for (const members of pools.values()) {
    const used = members.reduce((sum, mount) => sum + mount.usedBytes, 0);
    const free = members[0].freeBytes;
    usedBytes += used;
    freeBytes += free;
    // A single filesystem knows its own size (reserved blocks included).
    totalBytes += members.length === 1 ? members[0].totalBytes : used + free;
  }

  return { totalBytes, usedBytes, freeBytes, mountCount: mounts.length, storageCount: pools.size };
}
