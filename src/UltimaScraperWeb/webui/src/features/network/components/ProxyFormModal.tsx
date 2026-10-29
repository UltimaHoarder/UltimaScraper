import type { NetworkProxy, ProxyTestStatus } from '../../../api/types/network';
import { parseProxyLine } from '../lib/proxyParser';

interface ProxyFormModalProps {
  isOpen: boolean;
  editingProxy: NetworkProxy | null;
  proxyUrl: string;
  username: string;
  password: string;
  group: string;
  existingGroups?: string[];
  maxConnections: number;
  guestLookupTimeout?: number | null;
  formError: string | null;
  testStatus: ProxyTestStatus;
  testMessage: string | null;
  testLatencyMs: number | null;
  isTesting: boolean;
  isSaving: boolean;
  onClose: () => void;
  onProxyUrlChange: (value: string) => void;
  onUsernameChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onGroupChange: (value: string) => void;
  onMaxConnectionsChange: (value: number) => void;
  onGuestLookupTimeoutChange?: (value: number | null) => void;
  onTest: () => void;
  onSave: () => void;
}

export function ProxyFormModal({
  isOpen,
  editingProxy,
  proxyUrl,
  username,
  password,
  group,
  existingGroups = [],
  maxConnections,
  guestLookupTimeout,
  formError,
  testStatus,
  testMessage,
  testLatencyMs,
  isTesting,
  isSaving,
  onClose,
  onProxyUrlChange,
  onUsernameChange,
  onPasswordChange,
  onGroupChange,
  onMaxConnectionsChange,
  onGuestLookupTimeoutChange,
  onTest,
  onSave,
}: ProxyFormModalProps) {
  if (!isOpen) {
    return null;
  }

  const hasProxyUrl = Boolean(proxyUrl.trim());
  const saveLabel = isSaving
    ? 'Saving...'
    : editingProxy
      ? 'Save Changes'
      : 'Add Proxy';

  const handleUrlChange = (value: string) => {
    // If user pasted a full proxy URL with credentials or comment
    if (value.includes('@') || value.includes('#') || (value.includes(':') && value.split(':').length === 4)) {
      try {
        const parsed = parseProxyLine(value, group || undefined);
        onProxyUrlChange(parsed.url);
        if (parsed.username) onUsernameChange(parsed.username);
        if (parsed.password) onPasswordChange(parsed.password);
        if (parsed.group) onGroupChange(parsed.group);
        return;
      } catch {
        // Fall back to normal setting
      }
    }
    onProxyUrlChange(value);
  };

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div className="modal-content wy-dialog">
        <div className="modal-header">
          <div>
            <span className="network-kicker">GATEWAY CONFIGURATION // PROTOCOL USV-02</span>
            <h2>{editingProxy ? 'Edit Proxy' : 'Add Proxy'}</h2>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close modal">
            ×
          </button>
        </div>
        <div className="modal-body">
          <div className="form-group">
            <label>Proxy URL *</label>
            <input
              type="text"
              value={proxyUrl}
              onChange={(event) => handleUrlChange(event.target.value)}
              placeholder="http://host:port or socks5://host:port"
              disabled={Boolean(editingProxy)}
              className={editingProxy ? 'input-readonly' : ''}
            />
          </div>
          <div className="form-group">
            <label>Group Name</label>
            <input
              type="text"
              value={group}
              onChange={(event) => onGroupChange(event.target.value)}
              placeholder="e.g. Datacenter US, Residential"
              list="form-existing-groups"
            />
            <datalist id="form-existing-groups">
              {existingGroups.map((g) => (
                <option key={g} value={g} />
              ))}
            </datalist>
            <span className="form-hint">Assign proxy to a group for organization and batch tuning</span>
          </div>
          <div className="form-group">
            <label>Username</label>
            <input
              type="text"
              value={username}
              onChange={(event) => onUsernameChange(event.target.value)}
              placeholder="Optional"
            />
          </div>
          <div className="form-group">
            <label>Password</label>
            <input
              type="password"
              value={password}
              onChange={(event) => onPasswordChange(event.target.value)}
              placeholder="Optional"
            />
          </div>
          <div className="form-group">
            <label>Max Connections</label>
            <input
              type="number"
              value={maxConnections}
              onChange={(event) =>
                onMaxConnectionsChange(Number.parseInt(event.target.value, 10) || -1)
              }
              placeholder="-1 for unlimited"
            />
            <span className="form-hint">Use -1 for unlimited connections</span>
          </div>
          <div className="form-group">
            <label htmlFor="proxy-guest-lookup-timeout">Guest Lookup Timeout (seconds)</label>
            <input
              id="proxy-guest-lookup-timeout"
              type="number"
              step="0.1"
              min="0.5"
              value={guestLookupTimeout ?? ''}
              onChange={(event) => {
                const val = event.target.value.trim();
                onGuestLookupTimeoutChange?.(val === '' ? null : Number.parseFloat(val));
              }}
              placeholder="Leave empty to use global setting"
            />
            <span className="form-hint">
              Override guest profile lookup timeout for this proxy. Leave empty to use global network timeout.
            </span>
          </div>
          {formError && <div className="error">{formError}</div>}
          <div className="proxy-test">
            <button
              className="btn-test network-button"
              onClick={onTest}
              disabled={!hasProxyUrl || isTesting}
            >
              {isTesting ? 'Analyzing...' : 'Test Proxy'}
            </button>
            {testStatus !== 'idle' && testMessage && (
              <div
                className={`test-result ${testStatus === 'success' ? 'success' : 'failure'}`}
              >
                {testMessage}
                {testLatencyMs !== null && (
                  <span className="test-latency">({testLatencyMs} ms)</span>
                )}
              </div>
            )}
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn-cancel network-button" onClick={onClose}>
            Cancel
          </button>
          {testStatus === 'error' && (
            <button
              className="btn-save btn-save-anyway network-button network-button--warning"
              onClick={onSave}
              disabled={!hasProxyUrl || isSaving}
            >
              {isSaving ? 'Saving...' : 'Save Anyway'}
            </button>
          )}
          <button
            className="btn-save network-button network-button--primary"
            onClick={onSave}
            disabled={!hasProxyUrl || isSaving || (!editingProxy && testStatus !== 'success')}
          >
            {saveLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
