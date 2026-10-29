/** PostgreSQL row counts are planner estimates (reltuples), refreshed by VACUUM/ANALYZE. */
export const ROW_ESTIMATE_TITLE =
  'Estimated from PostgreSQL statistics (updated by VACUUM/ANALYZE), not an exact COUNT(*).';

export function formatRowCount(count: number, estimated?: boolean): string {
  return `${estimated ? '~' : ''}${count.toLocaleString()}`;
}
