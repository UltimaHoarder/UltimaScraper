import type { ConsolidationPreview } from '../../../api/consolidation';

/** A target drive's usable free space and the reserve it keeps for downloads. */
export interface DriveSpace {
  free: number;
  reserve: number;
}

/** `ok` fits, `reserve` fits only by using some of the reserve, `no_space` does not fit. */
export type SpaceFit = 'ok' | 'reserve' | 'no_space';

export interface PerformerFit {
  fit: SpaceFit;
  root: string;
  /** Bytes this performer adds to the drive. */
  needed: number;
  /** Bytes the other ticked performers already add to the same drive. */
  committed: number;
  space: DriveSpace | null;
}

export interface DriveUsage extends DriveSpace {
  root: string;
  used: number;
  performers: number;
}

/**
 * Free space per drive, from every preview that reported it. Previews are taken
 * at different times, so the smallest figure wins.
 */
export function driveSpaces(previews: Iterable<ConsolidationPreview>): Record<string, DriveSpace> {
  const spaces: Record<string, DriveSpace> = {};
  for (const preview of previews) {
    for (const folder of preview.folders) {
      if (folder.free_bytes == null) continue;
      const known = spaces[folder.root];
      spaces[folder.root] = {
        free: known ? Math.min(known.free, folder.free_bytes) : folder.free_bytes,
        reserve: folder.reserve_bytes ?? 0,
      };
    }
  }
  return spaces;
}

function classify(total: number, space: DriveSpace | null): SpaceFit {
  if (!space || total <= 0) return 'ok';
  if (total > space.free) return 'no_space';
  return total > space.free - space.reserve ? 'reserve' : 'ok';
}

/**
 * Whether a previewed performer still fits on its target once the other ticked
 * performers moving to the same drive are counted; null without a target.
 */
export function performerFit(
  path: string,
  previews: Record<string, ConsolidationPreview>,
  selected: readonly string[],
  spaces: Record<string, DriveSpace>,
): PerformerFit | null {
  const preview = previews[path];
  const root = preview?.target_root;
  if (!preview || !root) return null;
  const committed = selected
    .filter((other) => other !== path && previews[other]?.target_root === root)
    .reduce((sum, other) => sum + (previews[other]?.needed_bytes ?? 0), 0);
  const space = spaces[root] ?? null;
  const needed = preview.needed_bytes;
  // Nothing to move never needs room, even on a full drive.
  const fit = needed <= 0 ? 'ok' : classify(committed + needed, space);
  return { fit, root, needed, committed, space };
}

/** What the ticked performers add to each target drive. */
export function driveUsage(
  previews: Record<string, ConsolidationPreview>,
  selected: readonly string[],
  spaces: Record<string, DriveSpace>,
): DriveUsage[] {
  const usage = new Map<string, DriveUsage>();
  for (const path of selected) {
    const preview = previews[path];
    const root = preview?.target_root;
    if (!preview || !root) continue;
    const space = spaces[root] ?? { free: 0, reserve: 0 };
    const entry = usage.get(root) ?? { root, used: 0, performers: 0, ...space };
    entry.used += preview.needed_bytes;
    entry.performers += 1;
    usage.set(root, entry);
  }
  return [...usage.values()].sort((a, b) => a.root.localeCompare(b.root));
}

/** Ticks `paths` in order, skipping any that would no longer fit. */
export function tickWhereTheyFit(
  paths: readonly string[],
  previews: Record<string, ConsolidationPreview>,
  selected: readonly string[],
  spaces: Record<string, DriveSpace>,
): string[] {
  let next = [...selected];
  for (const path of paths) {
    if (next.includes(path)) continue;
    const fit = performerFit(path, previews, next, spaces);
    if (fit && fit.fit !== 'no_space') next = [...next, path];
  }
  return next;
}

/**
 * Bytes a performer would add to `root`. The backend's figure leaves out files
 * already there; without it, everything held elsewhere is counted.
 */
export function bytesFor(preview: ConsolidationPreview, root: string): number | null {
  const reported = preview.folders.find((folder) => folder.root === root)?.needed_bytes;
  if (reported != null) return reported;
  const sizes = preview.folders.map((folder) => folder.bytes);
  if (sizes.some((size) => size == null)) return null;
  const here = preview.folders.find((folder) => folder.root === root)?.bytes ?? 0;
  return (sizes as number[]).reduce((sum, size) => sum + size, 0) - here;
}
