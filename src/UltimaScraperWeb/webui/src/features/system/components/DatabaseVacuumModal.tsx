import { useEffect, useState } from 'react';
import type { DatabaseVacuumRequest } from '../../../api/types/system';

interface DatabaseVacuumModalProps {
  site?: string;
  tableName?: string;
  isOpen: boolean;
  isPending: boolean;
  onClose: () => void;
  onConfirm: (request: DatabaseVacuumRequest) => void;
}

export function DatabaseVacuumModal({
  site,
  tableName,
  isOpen,
  isPending,
  onClose,
  onConfirm,
}: DatabaseVacuumModalProps) {
  const [mode, setMode] = useState<'standard' | 'full' | 'analyze'>('standard');
  const [freeze, setFreeze] = useState(false);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isPending) {
        onClose();
      }
    };
    if (isOpen) {
      window.addEventListener('keydown', handleKeyDown);
      return () => window.removeEventListener('keydown', handleKeyDown);
    }
  }, [isOpen, isPending, onClose]);

  if (!isOpen) return null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === 'analyze') {
      onConfirm({
        site: site || undefined,
        table_name: tableName,
        full: false,
        analyze: true,
        freeze: false,
      });
    } else {
      onConfirm({
        site: site || undefined,
        table_name: tableName,
        full: mode === 'full',
        analyze: true,
        freeze,
      });
    }
  };

  return (
    <div className="modal-overlay" onClick={() => !isPending && onClose()}>
      <section
        className="modal-content fleet-register-inspect-modal database-vacuum-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="vacuum-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <span className="fleet-register-kicker">Database Maintenance</span>
            <h3 id="vacuum-modal-title">
              Vacuum Database {tableName ? `· ${tableName}` : site ? `· ${site}` : '· All Databases'}
            </h3>
          </div>
          <button
            type="button"
            className="modal-close"
            aria-label="Close vacuum dialog"
            disabled={isPending}
            onClick={onClose}
          >
            ×
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-body fleet-register-inspection-body">
          <div className="database-vacuum-target-card">
            <span className="database-vacuum-target-label">Target:</span>
            <strong>{site || 'All Databases'}</strong>
            {tableName ? (
              <code>.{tableName}</code>
            ) : (
              <span className="database-vacuum-target-scope">
                {site ? '(All tables in schema)' : '(All configured site schemas)'}
              </span>
            )}
          </div>

          <fieldset className="database-vacuum-fieldset">
            <legend className="database-vacuum-legend">Operation Mode</legend>

            <label className="database-vacuum-option">
              <input
                type="radio"
                name="vacuum-mode"
                value="standard"
                checked={mode === 'standard'}
                disabled={isPending}
                onChange={() => setMode('standard')}
              />
              <div className="database-vacuum-option-text">
                <strong>Standard VACUUM & ANALYZE (Recommended)</strong>
                <p>
                  Reclaims dead tuple space for reuse within table pages and updates planner statistics.
                  Non-blocking; safe to run while tasks and scraping are active.
                </p>
              </div>
            </label>

            <label className="database-vacuum-option">
              <input
                type="radio"
                name="vacuum-mode"
                value="full"
                checked={mode === 'full'}
                disabled={isPending}
                onChange={() => setMode('full')}
              />
              <div className="database-vacuum-option-text">
                <strong>VACUUM FULL</strong>
                <p>
                  Rewrites table files to disk, returning space to the operating system.
                  <span className="database-vacuum-warning">
                    Warning: Requires an exclusive lock. Queries on this table will pause until complete.
                  </span>
                </p>
              </div>
            </label>

            <label className="database-vacuum-option">
              <input
                type="radio"
                name="vacuum-mode"
                value="analyze"
                checked={mode === 'analyze'}
                disabled={isPending}
                onChange={() => setMode('analyze')}
              />
              <div className="database-vacuum-option-text">
                <strong>ANALYZE only</strong>
                <p>
                  Gathers query planner statistics without sweeping dead tuples. Extremely fast.
                </p>
              </div>
            </label>
          </fieldset>

          {mode !== 'analyze' && (
            <label className="database-vacuum-freeze-option">
              <input
                type="checkbox"
                checked={freeze}
                disabled={isPending}
                onChange={(e) => setFreeze(e.target.checked)}
              />
              <span>Freeze transaction IDs (aggressive tuple freezing for long-term storage)</span>
            </label>
          )}

          <div className="database-vacuum-actions">
            <button
              type="button"
              className="fleet-register-button"
              disabled={isPending}
              onClick={onClose}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="fleet-register-button btn-confirm"
              disabled={isPending}
            >
              {isPending
                ? 'Running operation…'
                : mode === 'full'
                  ? 'Run VACUUM FULL'
                  : mode === 'analyze'
                    ? 'Run ANALYZE'
                    : 'Run VACUUM ANALYZE'}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
