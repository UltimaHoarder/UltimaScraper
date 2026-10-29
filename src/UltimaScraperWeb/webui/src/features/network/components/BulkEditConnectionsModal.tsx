import { useState } from 'react';
import type { NetworkProxy } from '../../../api/types/network';

interface BulkEditConnectionsModalProps {
  isOpen: boolean;
  selectedProxyUrls: string[];
  proxies: NetworkProxy[];
  isSaving: boolean;
  onClose: () => void;
  onSave: (settings: {
    max_connections?: number | null;
    max_concurrency?: number | null;
    guest_lookup_timeout?: number | null;
  }) => void;
}

export function BulkEditConnectionsModal({
  isOpen,
  selectedProxyUrls,
  proxies,
  isSaving,
  onClose,
  onSave,
}: BulkEditConnectionsModalProps) {
  const [maxConnections, setMaxConnections] = useState('');
  const [maxConcurrency, setMaxConcurrency] = useState('');
  const [guestLookupTimeout, setGuestLookupTimeout] = useState('');
  const [editConnections, setEditConnections] = useState(true);
  const [editConcurrency, setEditConcurrency] = useState(false);
  const [editGuestLookupTimeout, setEditGuestLookupTimeout] = useState(false);

  if (!isOpen) {
    return null;
  }

  const selectedProxies = proxies.filter((p) => selectedProxyUrls.includes(p.url));
  const previewCount = 5;
  const shownProxies = selectedProxies.slice(0, previewCount);
  const remainingCount = selectedProxies.length - previewCount;

  const hasChanges =
    (editConnections && maxConnections.trim() !== '') ||
    (editConcurrency && maxConcurrency.trim() !== '') ||
    editGuestLookupTimeout;

  const handleSave = () => {
    const settings: {
      max_connections?: number | null;
      max_concurrency?: number | null;
      guest_lookup_timeout?: number | null;
    } = {};
    if (editConnections && maxConnections.trim() !== '') {
      settings.max_connections = Number.parseInt(maxConnections, 10);
    }
    if (editConcurrency && maxConcurrency.trim() !== '') {
      settings.max_concurrency = Number.parseInt(maxConcurrency, 10);
    }
    if (editGuestLookupTimeout) {
      const trimmed = guestLookupTimeout.trim();
      settings.guest_lookup_timeout = trimmed === '' ? null : Number.parseFloat(trimmed);
    }
    onSave(settings);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && hasChanges && !isSaving) {
      e.preventDefault();
      handleSave();
    }
  };

  // Determine current values for placeholder hints
  const connectionValues = new Set(selectedProxies.map((p) => p.max_connections));
  const connectionsPlaceholder =
    connectionValues.size === 1
      ? `Current: ${[...connectionValues][0] === -1 ? 'Unlimited (-1)' : [...connectionValues][0]}`
      : `Mixed values (${connectionValues.size} different)`;

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div className="modal-content wy-dialog">
        <div className="modal-header">
          <div>
            <span className="network-kicker">BULK CAPACITY EDIT // USV-02</span>
            <h2>Edit Connections — {selectedProxies.length} Prox{selectedProxies.length === 1 ? 'y' : 'ies'}</h2>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close modal">
            ×
          </button>
        </div>
        <div className="modal-body">
          <div className="bulk-edit-preview">
            <span className="network-kicker">TARGETED ROUTES</span>
            <div className="bulk-edit-preview-list">
              {shownProxies.map((proxy) => (
                <div key={proxy.url} className="bulk-edit-preview-item">
                  <span className={`network-status-dot ${proxy.enabled !== false ? ((proxy.active_assigned_count ?? 0) > 0 ? 'network-status-dot--ready' : 'network-status-dot--idle') : 'network-status-dot--disabled'}`} />
                  <code>{proxy.url}</code>
                  <span className="bulk-edit-preview-conn">
                    {proxy.max_connections === -1 ? '∞' : proxy.max_connections} conn
                  </span>
                </div>
              ))}
              {remainingCount > 0 && (
                <div className="bulk-edit-preview-more">
                  + {remainingCount} more route{remainingCount === 1 ? '' : 's'}
                </div>
              )}
            </div>
          </div>

          <div className="form-group">
            <label>
              <input
                type="checkbox"
                checked={editConnections}
                onChange={(e) => setEditConnections(e.target.checked)}
              />{' '}
              Max Connections
            </label>
            {editConnections && (
              <>
                <input
                  type="number"
                  value={maxConnections}
                  onChange={(e) => setMaxConnections(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={connectionsPlaceholder}
                  min={-1}
                />
                <span className="form-hint">Use -1 for unlimited connections. Applied to all selected proxies.</span>
              </>
            )}
          </div>

          <div className="form-group">
            <label>
              <input
                type="checkbox"
                checked={editConcurrency}
                onChange={(e) => setEditConcurrency(e.target.checked)}
              />{' '}
              Max Concurrency
            </label>
            {editConcurrency && (
              <>
                <input
                  type="number"
                  value={maxConcurrency}
                  onChange={(e) => setMaxConcurrency(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="e.g. 32"
                  min={1}
                />
                <span className="form-hint">Max simultaneous download tasks per proxy. Applied to all selected proxies.</span>
              </>
            )}
          </div>

          <div className="form-group">
            <label>
              <input
                type="checkbox"
                checked={editGuestLookupTimeout}
                onChange={(e) => setEditGuestLookupTimeout(e.target.checked)}
              />{' '}
              Guest Lookup Timeout (seconds)
            </label>
            {editGuestLookupTimeout && (
              <>
                <input
                  type="number"
                  step="0.1"
                  min="0.5"
                  value={guestLookupTimeout}
                  onChange={(e) => setGuestLookupTimeout(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="e.g. 6.0 (leave blank to clear override)"
                />
                <span className="form-hint">
                  Override guest lookup timeout for selected proxies. Leave blank to clear override and inherit global setting.
                </span>
              </>
            )}
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn-cancel network-button" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-save network-button network-button--primary"
            onClick={handleSave}
            disabled={!hasChanges || isSaving}
          >
            {isSaving ? 'Saving…' : `Apply to ${selectedProxies.length} Prox${selectedProxies.length === 1 ? 'y' : 'ies'}`}
          </button>
        </div>
      </div>
    </div>
  );
}
