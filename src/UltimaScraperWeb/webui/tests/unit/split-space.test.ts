import { describe, expect, it } from 'vitest';

import type { ConsolidationPreview } from '../../src/api/consolidation';
import {
  bytesFor,
  driveSpaces,
  driveUsage,
  performerFit,
  tickWhereTheyFit,
} from '../../src/features/tools/lib/splitSpace';

function preview(path: string, target: string | null, needed: number, free = 1000, reserve = 100): ConsolidationPreview {
  return {
    relative_path: path,
    folders: [
      { root: '/a', path: `/a/${path}`, priority: 0, files: 1, bytes: 500, free_bytes: free, reserve_bytes: reserve },
      { root: '/b', path: `/b/${path}`, priority: 0, files: 1, bytes: needed, free_bytes: 10_000, reserve_bytes: 0 },
    ],
    target_root: target,
    reason: '',
    needed_bytes: needed,
    into_reserve: false,
    no_space: false,
    move_files: needed > 0 ? 1 : 0,
    move_bytes: needed,
    duplicates: 0,
    conflicts: [],
    recent: 0,
    too_long: 0,
  };
}

describe('split performer space', () => {
  it('counts what the other ticked performers add to the same drive', () => {
    const previews = { p1: preview('p1', '/a', 600), p2: preview('p2', '/a', 350), p3: preview('p3', '/a', 200) };
    const spaces = driveSpaces(Object.values(previews));

    expect(performerFit('p2', previews, [], spaces)?.fit).toBe('ok');
    // 600 + 350 = 950 of 1000 free leaves less than the 100 reserve.
    expect(performerFit('p2', previews, ['p1'], spaces)).toMatchObject({ fit: 'reserve', committed: 600 });
    // 600 + 350 + 200 = 1150 is more than is free.
    expect(performerFit('p3', previews, ['p1', 'p2'], spaces)?.fit).toBe('no_space');
  });

  it('never needs room to move nothing', () => {
    const previews = { full: preview('full', '/a', 0, 0) };
    expect(performerFit('full', previews, [], driveSpaces(Object.values(previews)))?.fit).toBe('ok');
  });

  it('uses the smallest free space any preview saw', () => {
    const spaces = driveSpaces([preview('p1', '/a', 1, 900), preview('p2', '/a', 1, 700)]);
    expect(spaces['/a']).toEqual({ free: 700, reserve: 100 });
  });

  it('ticks in order and skips what no longer fits', () => {
    const previews = { p1: preview('p1', '/a', 600), p2: preview('p2', '/a', 500), p3: preview('p3', '/a', 300) };
    const spaces = driveSpaces(Object.values(previews));

    expect(tickWhereTheyFit(['p1', 'p2', 'p3'], previews, [], spaces)).toEqual(['p1', 'p3']);
  });

  it('adds up what each drive takes', () => {
    const previews = { p1: preview('p1', '/a', 600), p2: preview('p2', '/a', 300), p3: preview('p3', null, 50) };
    expect(driveUsage(previews, ['p1', 'p2', 'p3'], driveSpaces(Object.values(previews)))).toEqual([
      { root: '/a', used: 900, performers: 2, free: 1000, reserve: 100 },
    ]);
  });

  it('works out what a refused drive would have needed', () => {
    expect(bytesFor(preview('p1', null, 250), '/a')).toBe(250);
    expect(bytesFor(preview('p1', null, 250), '/b')).toBe(500);
  });

  it("uses the backend's figure, which leaves out duplicates", () => {
    const duplicated = preview('p1', null, 250);
    duplicated.folders = duplicated.folders.map((folder) => ({ ...folder, needed_bytes: 0 }));
    expect(bytesFor(duplicated, '/a')).toBe(0);
  });
});
