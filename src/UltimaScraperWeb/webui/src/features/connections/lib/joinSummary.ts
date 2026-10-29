import type { ClusterJoinResult } from '../../../api/webui';

/** One line on what joining a cluster added, and why any backend was left out. */
export function joinSummary(result: ClusterJoinResult): string {
  const notes = (result.members ?? []).filter((member) => member.note && member.connection_id === null);
  return (
    `Joined ${result.name}: ${result.created.length} backend${result.created.length === 1 ? '' : 's'} added` +
    // A one-time invite says why each member was not added; otherwise it was already here.
    (result.skipped.length && !result.members ? `, ${result.skipped.length} already here.` : '.') +
    notes.map((member) => ` ${member.name}: ${member.note}`).join('')
  );
}
