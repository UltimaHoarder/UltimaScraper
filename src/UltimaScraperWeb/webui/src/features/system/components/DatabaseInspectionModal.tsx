import { useEffect, useState } from 'react';
import type { DatabaseOverview, DatabaseTableOverview } from '../../../api/types/system';
import { formatBytes } from '../../../shared/lib/format';
import { formatRowCount, ROW_ESTIMATE_TITLE } from '../lib/rowCounts';

export interface PendingDatabaseOp {
  type: 'vacuum' | 'analyze' | 'reindex';
  site?: string;
  table?: string;
  currentTable?: string;
  tablesCompleted?: number;
  tablesTotal?: number;
  phase?: string;
  progressPercent?: number;
  message?: string;
}

export interface DatabaseStatusNotice {
  tone: 'info' | 'warning' | 'danger';
  title: string;
  message: string;
}

interface DatabaseInspectionModalProps {
  database: DatabaseOverview;
  serverVersion?: string | null;
  onClose: () => void;
  onVacuumTable: (site: string, tableName?: string) => void;
  onAnalyzeTable: (site: string, tableName: string) => void;
  onReindexTable?: (site: string, tableName: string) => void;
  pendingOp?: PendingDatabaseOp | null;
  statusNotice?: DatabaseStatusNotice | null;
}

function InspectionMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="fleet-register-inspection-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function formatAge(timestamp: string | null): string {
  if (!timestamp) return 'Never';
  const diffMs = Date.now() - new Date(timestamp).getTime();
  if (isNaN(diffMs) || diffMs < 0) return 'Just now';
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const days = Math.floor(hr / 24);
  return `${days}d ago`;
}

export function DatabaseInspectionModal({
  database,
  serverVersion,
  onClose,
  onVacuumTable,
  onAnalyzeTable,
  onReindexTable,
  pendingOp,
  statusNotice,
}: DatabaseInspectionModalProps) {
  const [filterQuery, setFilterQuery] = useState('');

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const filteredTables = database.tables.filter((table) =>
    table.table_name.toLowerCase().includes(filterQuery.trim().toLowerCase()),
  );

  const isOpPending = Boolean(pendingOp);
  const isAllVacuuming =
    pendingOp?.type === 'vacuum' &&
    (!pendingOp.site || pendingOp.site === database.site) &&
    !pendingOp.table;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <section
        className="modal-content fleet-register-inspect-modal database-inspection-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="database-inspection-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <span className="fleet-register-kicker">Database Inspection</span>
            <h3 id="database-inspection-title">{database.site} Database</h3>
          </div>
          <button
            type="button"
            className="modal-close"
            aria-label="Close database inspection"
            onClick={onClose}
          >
            ×
          </button>
        </div>

        <div className="modal-body fleet-register-inspection-body">
          {pendingOp && (
            <div className="database-modal-notice database-modal-notice--info" role="status">
              <span className="database-op-spinner" aria-hidden="true" />
              <strong>
                {pendingOp.type.charAt(0).toUpperCase() + pendingOp.type.slice(1)} in progress:
              </strong>{' '}
              {pendingOp.message ||
                (pendingOp.table
                  ? `Running ${pendingOp.type} on table "${pendingOp.table}"… Large tables can take several minutes.`
                  : `Running ${pendingOp.type} on database "${pendingOp.site || database.site}"… This can take several minutes.`)}
              {typeof pendingOp.progressPercent === 'number' && pendingOp.progressPercent > 0 && (
                <span className="database-progress-pct" style={{ marginLeft: 8 }}>
                  {pendingOp.progressPercent.toFixed(1)}%
                </span>
              )}
            </div>
          )}

          {!pendingOp && statusNotice && (
            <div
              className={`database-modal-notice database-modal-notice--${statusNotice.tone}`}
              role="alert"
            >
              <strong>{statusNotice.title}:</strong> {statusNotice.message}
            </div>
          )}

          <div className="fleet-register-inspection-status">
            <span className={`fleet-register-state fleet-register-state--${database.status}`}>
              <i aria-hidden="true" />
              {database.status === 'healthy'
                ? 'Healthy'
                : database.status === 'warning'
                  ? 'Needs vacuum'
                  : 'Offline'}
            </span>
            <code>{database.database_name}</code>
            <span className="fleet-register-panel-meta">
              {database.host}
              {database.port ? `:${database.port}` : ''} · Schema: {database.schema_name}
            </span>
          </div>

          <div className="fleet-register-inspection-metrics">
            <InspectionMetric label="Total Size" value={database.total_size_pretty} />
            <InspectionMetric label="Tables" value={database.table_count} />
            <InspectionMetric
              label={database.row_counts_estimated ? 'Rows (estimate)' : 'Live Tuples'}
              value={formatRowCount(database.total_live_tuples, database.row_counts_estimated)}
            />
            <InspectionMetric
              label="Dead Tuples"
              value={database.total_dead_tuples.toLocaleString()}
            />
            <InspectionMetric label="Estimated Bloat" value={`${database.bloat_percent}%`} />
            <InspectionMetric
              label="Last Vacuum"
              value={formatAge(database.last_vacuum)}
            />
            <InspectionMetric
              label="Last Analyze"
              value={formatAge(database.last_analyze)}
            />
            <InspectionMetric
              label="Server Version"
              value={serverVersion ? serverVersion.split(' ')[0] + ' ' + (serverVersion.split(' ')[1] || '') : 'PostgreSQL'}
            />
          </div>

          <section className="fleet-register-inspection-section">
            <div className="fleet-register-row">
              <h4>Tables ({database.tables.length})</h4>
              <button
                type="button"
                className="fleet-register-link"
                disabled={isOpPending}
                onClick={() => onVacuumTable(database.site)}
              >
                {isAllVacuuming && <span className="database-op-spinner" aria-hidden="true" />}
                {isAllVacuuming ? 'Vacuuming All Tables…' : 'Vacuum All Tables ↗'}
              </button>
            </div>

            <div className="database-tables-filter">
              <input
                aria-label="Filter tables"
                placeholder="Filter table name…"
                value={filterQuery}
                onChange={(e) => setFilterQuery(e.target.value)}
              />
              <span className="fleet-register-record-count">
                {filteredTables.length} {filteredTables.length === 1 ? 'table' : 'tables'}
              </span>
            </div>

            <div className="fleet-register-table-scroll">
              <table className="fleet-register-table database-tables-table">
                <thead>
                  <tr>
                    <th scope="col">Table Name</th>
                    <th
                      scope="col"
                      title={database.row_counts_estimated ? ROW_ESTIMATE_TITLE : undefined}
                    >
                      {database.row_counts_estimated ? 'Rows (estimate)' : 'Live Rows'}
                    </th>
                    <th scope="col">Dead Rows</th>
                    <th scope="col">Total Size</th>
                    <th scope="col">Table / Index</th>
                    <th scope="col">Last Vacuum</th>
                    <th scope="col">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredTables.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="fleet-register-empty">
                        No tables matching filter.
                      </td>
                    </tr>
                  ) : (
                    filteredTables.map((table: DatabaseTableOverview) => {
                      const totalTup = table.live_tuples + table.dead_tuples;
                      const bloat = totalTup > 0 ? (table.dead_tuples / totalTup) * 100 : 0;
                      const isMatchingTable = Boolean(
                        pendingOp &&
                          (pendingOp.table === table.table_name ||
                            pendingOp.currentTable === table.table_name),
                      );
                      const isThisTableVacuuming =
                        pendingOp?.type === 'vacuum' &&
                        (!pendingOp.site || pendingOp.site === database.site || pendingOp.site === 'all') &&
                        isMatchingTable;
                      const isThisTableAnalyzing =
                        pendingOp?.type === 'analyze' &&
                        (!pendingOp.site || pendingOp.site === database.site || pendingOp.site === 'all') &&
                        isMatchingTable;
                      const isThisTableReindexing =
                        pendingOp?.type === 'reindex' &&
                        (!pendingOp.site || pendingOp.site === database.site || pendingOp.site === 'all') &&
                        isMatchingTable;

                      return (
                        <tr key={table.table_name}>
                          <th scope="row">
                            <code>{table.table_name}</code>
                          </th>
                          <td>{formatRowCount(table.live_tuples, database.row_counts_estimated)}</td>
                          <td>
                            <span
                              className={
                                table.dead_tuples > 100 && bloat > 10
                                  ? 'database-dead-warning'
                                  : ''
                              }
                            >
                              {table.dead_tuples.toLocaleString()}
                              {bloat > 5 && ` (${bloat.toFixed(1)}%)`}
                            </span>
                          </td>
                          <td>{formatBytes(table.total_bytes)}</td>
                          <td>
                            <small>
                              {formatBytes(table.table_bytes)} / {formatBytes(table.index_bytes)}
                            </small>
                          </td>
                          <td>{formatAge(table.last_vacuum || table.last_autovacuum)}</td>
                          <td>
                            <div className="database-table-actions">
                              <button
                                type="button"
                                className="fleet-register-link"
                                disabled={isOpPending}
                                onClick={() => onVacuumTable(database.site, table.table_name)}
                              >
                                {isThisTableVacuuming && (
                                  <span className="database-op-spinner" aria-hidden="true" />
                                )}
                                {isThisTableVacuuming ? 'Vacuuming…' : 'Vacuum'}
                              </button>
                              <span className="database-action-separator">·</span>
                              <button
                                type="button"
                                className="fleet-register-link"
                                disabled={isOpPending}
                                onClick={() => onAnalyzeTable(database.site, table.table_name)}
                              >
                                {isThisTableAnalyzing && (
                                  <span className="database-op-spinner" aria-hidden="true" />
                                )}
                                {isThisTableAnalyzing ? 'Analyzing…' : 'Analyze'}
                              </button>
                              {onReindexTable && (
                                <>
                                  <span className="database-action-separator">·</span>
                                  <button
                                    type="button"
                                    className="fleet-register-link"
                                    disabled={isOpPending}
                                    onClick={() => onReindexTable(database.site, table.table_name)}
                                  >
                                    {isThisTableReindexing && (
                                      <span className="database-op-spinner" aria-hidden="true" />
                                    )}
                                    {isThisTableReindexing ? 'Reindexing…' : 'Reindex'}
                                  </button>
                                </>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </section>
    </div>
  );
}
