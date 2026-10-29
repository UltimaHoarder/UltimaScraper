import type { StagingDirectory } from '../../../api/types/setup';
import type { RegisterBackend, RegisterMount } from '../systemFleetRegisterData';
import type { FlowTarget } from './downloadFlows';

export type StorageKind = 'ram-staging' | 'staging' | 'drive' | 'mount';

/** One piece of storage on a host, once however many paths mount it. */
export interface StorageRow {
  key: string;
  path: string;
  /** Other paths the same device is mounted at. */
  alsoAt: string[];
  device: string;
  totalBytes: number | null;
  percentUsed: number | null;
  kind: StorageKind;
  /** What it is used for, e.g. the staging directory on it. */
  note: string | null;
  /** The staging directory on it, when it holds one. */
  stagingPath: string | null;
  flowTarget: FlowTarget | null;
}

export interface StorageGroup {
  backendId: string;
  host: string;
  clusterId: string | null;
  rows: StorageRow[];
}

const KIND_ORDER: Record<StorageKind, number> = { 'ram-staging': 0, staging: 1, drive: 2, mount: 3 };

// RAM disks the backend leaves out of its mounts; anything under them is not on "/".
const RAM_DISKS = ['/dev/shm', '/run/shm'];

function deviceKey(mount: RegisterMount): string {
  return mount.device.replace(/^\/dev\//, '');
}

/** The mount holding a path: the longest mount point it sits under. */
function mountFor(path: string, rows: StorageRow[]): StorageRow | null {
  let best: StorageRow | null = null;
  let bestLength = -1;
  for (const row of rows) {
    for (const point of [row.path, ...row.alsoAt]) {
      const inside = path === point || path.startsWith(point.endsWith('/') ? point : `${point}/`);
      if (inside && point.length > bestLength) {
        best = row;
        bestLength = point.length;
      }
    }
  }
  return best;
}

/**
 * Each host's storage for the architecture: its mounts with duplicates folded,
 * the staging directories (on the backend whose settings these are) and the
 * download drives, marked with where a download passes through.
 */
export function buildStorageGroups(
  backends: RegisterBackend[],
  staging: StagingDirectory[] | undefined,
): StorageGroup[] {
  return backends.map((backend) => {
    const rows: StorageRow[] = [];
    for (const mount of backend.mounts) {
      const same = rows.find((row) => row.device === deviceKey(mount));
      if (same) {
        same.alsoAt.push(mount.path);
        if (mount.isConfigured && same.kind === 'mount') {
          same.kind = 'drive';
          same.note = 'download drive';
        }
        continue;
      }
      rows.push({
        key: `${backend.backendId}:${mount.path}`,
        path: mount.path,
        alsoAt: [],
        device: deviceKey(mount),
        totalBytes: mount.totalBytes,
        percentUsed: mount.percentUsed,
        kind: mount.isConfigured ? 'drive' : 'mount',
        note: mount.isConfigured ? 'download drive' : null,
        stagingPath: null,
        flowTarget: null,
      });
    }

    // Staging settings belong to the backend this WebUI talks to.
    if (backend.isLocal) {
      let ramMarked = false;
      let diskMarked = false;
      for (const directory of staging ?? []) {
        const preferred = directory.policy.includes('prefer');
        const target: FlowTarget | null =
          preferred && !ramMarked ? 'ram' : !preferred && !diskMarked ? 'disk' : null;
        if (target === 'ram') ramMarked = true;
        if (target === 'disk') diskMarked = true;
        const note = `staging ${directory.path}${preferred ? ' (preferred)' : ''}`;
        const inRam = RAM_DISKS.some((disk) => directory.path === disk || directory.path.startsWith(`${disk}/`));
        const holder = inRam ? null : mountFor(directory.path, rows);
        if (holder) {
          holder.kind = 'staging';
          holder.note = note;
          holder.stagingPath ??= directory.path;
          holder.flowTarget ??= target;
        } else {
          // On a RAM disk, or a mount the backend did not report.
          rows.push({
            key: `${backend.backendId}:staging:${directory.path}`,
            path: directory.path,
            alsoAt: [],
            device: 'tmpfs (RAM)',
            totalBytes: null,
            percentUsed: null,
            kind: 'ram-staging',
            note,
            stagingPath: directory.path,
            flowTarget: target,
          });
        }
      }
      // With no existing performer folder, drive selection takes the configured drive with the most room.
      const drives = rows.filter((row) => row.kind === 'drive');
      const roomiest = backend.mounts
        .filter((mount) => mount.isConfigured)
        .sort((a, b) => b.freeBytes - a.freeBytes)[0];
      const chosen = drives.find((row) => roomiest && (row.path === roomiest.path || row.alsoAt.includes(roomiest.path)));
      if (chosen) chosen.flowTarget = 'drive';
    }

    rows.sort((a, b) => KIND_ORDER[a.kind] - KIND_ORDER[b.kind] || a.path.localeCompare(b.path));
    return { backendId: backend.backendId, host: backend.label, clusterId: backend.clusterId ?? null, rows };
  });
}

/** A mount downloads actually use, with the backend it belongs to. */
export interface ActiveMount extends StorageRow {
  backendId: string;
  host: string;
  clusterId: string | null;
}

/** Only the staging directories and download drives, each on its own, across backends. */
export function buildActiveMounts(
  backends: RegisterBackend[],
  staging: StagingDirectory[] | undefined,
): ActiveMount[] {
  return buildStorageGroups(backends, staging).flatMap((group) =>
    group.rows
      .filter((row) => row.kind !== 'mount')
      .map((row) => ({ ...row, backendId: group.backendId, host: group.host, clusterId: group.clusterId })),
  );
}
