import { useState } from 'react';
import type { AuthAccount, NetworkProxy } from '../../../api/types/network';

interface ProxyCardProps {
  proxy: NetworkProxy;
  isExpanded: boolean;
  isSelected?: boolean;
  onToggleSelect?: (proxy: NetworkProxy) => void;
  authList?: AuthAccount[];
  isAuthsLoading: boolean;
  analyzerError?: string | null;
  stateError?: string | null;
  isAnalyzing: boolean;
  isStateChanging: boolean;
  onEdit: (proxy: NetworkProxy) => void;
  onToggleExpanded: () => void;
  onOpenAnalyzer: (proxy: NetworkProxy) => void;
  onDelete: (proxy: NetworkProxy) => void;
  onRemoveAuth: (authId: number) => void;
  onToggleEnabled: (proxy: NetworkProxy) => void;
  onTestReachability?: (proxy: NetworkProxy) => Promise<{ success: boolean; latency_ms?: number | null; message: string }>;
  quickTestResult?: { testing?: boolean; success?: boolean; latency_ms?: number | null; message?: string } | null;
}

function getLocation(proxy: NetworkProxy) {
  const geo = proxy.geolocation;
  if (!geo || geo.success === false) return 'Location pending';
  return [geo.city, geo.region, geo.country].filter(Boolean).join(', ') || 'Location unavailable';
}

export function ProxyCard({
  proxy,
  isExpanded,
  isSelected,
  onToggleSelect,
  authList,
  isAuthsLoading,
  analyzerError,
  stateError,
  isAnalyzing,
  isStateChanging,
  onEdit,
  onToggleExpanded,
  onOpenAnalyzer,
  onDelete,
  onRemoveAuth,
  onToggleEnabled,
  onTestReachability,
  quickTestResult,
}: ProxyCardProps) {
  const [localQuickTest, setLocalQuickTest] = useState<{
    testing?: boolean;
    success?: boolean;
    latency_ms?: number | null;
    message?: string;
  } | null>(null);

  const quickTest = quickTestResult ?? localQuickTest;
  // Only active accounts make a proxy "in use"; disabled auths are ignored here.
  const assignedCount = proxy.active_assigned_count ?? 0;
  const geo = proxy.geolocation;
  const isEnabled = proxy.enabled !== false;

  const handleQuickTest = async () => {
    if (!onTestReachability || quickTest?.testing) return;
    setLocalQuickTest({ testing: true });
    try {
      const res = await onTestReachability(proxy);
      setLocalQuickTest({ testing: false, success: res.success, latency_ms: res.latency_ms, message: res.message });
    } catch (err) {
      setLocalQuickTest({ testing: false, success: false, message: err instanceof Error ? err.message : 'Test failed' });
    }
  };

  return (
    <article className={`network-proxy ${isExpanded ? 'is-expanded' : ''} ${isEnabled ? '' : 'is-disabled'} ${isSelected ? 'is-selected' : ''}`}>
      <div className="network-proxy__main">
        {onToggleSelect ? (
          <div className="network-proxy__select">
            <input
              type="checkbox"
              checked={Boolean(isSelected)}
              onChange={() => onToggleSelect(proxy)}
              aria-label={`Select proxy ${proxy.url}`}
            />
          </div>
        ) : null}

        <div className="network-proxy__identity">
          <span className="network-proxy__flag" aria-hidden="true" title={geo?.country || 'Gateway Exit'}>
            {geo?.country_code ? geo.country_code.toUpperCase() : geo?.flag?.emoji || 'GW'}
          </span>
          <div className="network-proxy__identity-body">
            <div className="network-proxy__url">
              <code>{proxy.url}</code>
            </div>
            <div className="network-proxy__subline">
              <span>{!isEnabled ? 'SUSPENDED · ' : ''}{proxy.username ? `AUTH: ${proxy.username}` : 'NO CREDENTIALS STORED'}</span>
              {proxy.group ? (
                <span className="network-proxy__group-badge" title={`Routing Group: ${proxy.group}`}>
                  <span className="network-proxy__group-prefix">GRP // </span>
                  {proxy.group}
                </span>
              ) : null}
              {proxy.guest_lookup_timeout != null && proxy.guest_lookup_timeout > 0 ? (
                <span
                  className="network-proxy__group-badge"
                  title={`Custom Guest Lookup Timeout: ${proxy.guest_lookup_timeout}s`}
                >
                  <span className="network-proxy__group-prefix">TIMEOUT // </span>
                  {proxy.guest_lookup_timeout}s
                </span>
              ) : null}
            </div>
          </div>
        </div>

        <div className="network-proxy__metric network-proxy__metric--region">
          <span className="network-proxy__metric-kicker">Region // Exit</span>
          <strong>{getLocation(proxy)}</strong>
          {geo?.connection?.isp ? <small>{geo.connection.isp}</small> : null}
        </div>

        <div className="network-proxy__metric network-proxy__metric--capacity">
          <span className="network-proxy__metric-kicker">Throughput // Capacity</span>
          <strong>{proxy.max_connections === -1 ? 'Uncapped Pool' : `${proxy.max_connections} connections`}</strong>
          <small>{assignedCount} assigned account{assignedCount === 1 ? '' : 's'}</small>
        </div>

        <div className="network-proxy__state">
          <span className={`network-status-dot ${!isEnabled ? 'network-status-dot--disabled' : assignedCount > 0 ? 'network-status-dot--ready' : 'network-status-dot--idle'}`} />
          {!isEnabled ? 'Disabled' : assignedCount > 0 ? 'In use' : 'Idle'}
          {quickTest ? (
            <span
              className={`network-proxy__quick-test-tag ${quickTest.testing ? 'is-testing' : quickTest.success ? 'is-success' : 'is-failure'}`}
              title={quickTest.message}
            >
              {quickTest.testing ? 'PROBING…' : quickTest.success ? `✓ ${quickTest.latency_ms ?? 0}ms` : '✗ OFFLINE'}
            </span>
          ) : null}
        </div>

        <div className="network-proxy__actions">
          {onTestReachability ? (
            <button
              type="button"
              className="network-button network-button--ghost"
              onClick={handleQuickTest}
              disabled={Boolean(quickTest?.testing)}
              title="Test proxy active status"
            >
              {quickTest?.testing ? 'Testing…' : 'Test'}
            </button>
          ) : null}
          <button
            type="button"
            className="network-button network-button--primary"
            onClick={() => onOpenAnalyzer(proxy)}
          >
            {isAnalyzing ? 'Live run' : 'Analyze'}
          </button>
          <button
            type="button"
            className={`network-button ${isEnabled ? 'network-button--warning' : 'network-button--primary'}`}
            onClick={() => onToggleEnabled(proxy)}
            disabled={isStateChanging}
            aria-label={`${isEnabled ? 'Disable' : 'Enable'} proxy ${proxy.url}`}
          >
            {isStateChanging ? 'Saving…' : isEnabled ? 'Disable' : 'Enable'}
          </button>
          <button type="button" className="network-icon-button" onClick={onToggleExpanded} aria-label={`${isExpanded ? 'Hide' : 'Show'} proxy details`}>
            {isExpanded ? '▲' : '▼'}
          </button>
        </div>
      </div>

      {analyzerError ? <div className="network-proxy__error">ANALYZER EXCEPTION: {analyzerError}</div> : null}
      {stateError ? <div className="network-proxy__error">GATEWAY EXCEPTION: {stateError}</div> : null}

      {isExpanded ? (
        <div className="network-proxy__drawer">
          <div className="network-proxy__drawer-head">
            <div>
              <span className="network-kicker">ROUTED CLEARANCES</span>
              <h4>Credentials Assigned to this Gateway</h4>
            </div>
            <div className="network-proxy__drawer-actions">
              <button type="button" className="network-button" onClick={() => onEdit(proxy)}>Edit route</button>
              <button type="button" className="network-button network-button--danger" onClick={() => onDelete(proxy)}>Revoke route</button>
            </div>
          </div>
          {isAuthsLoading ? (
            <p className="network-muted">Polling assigned accounts…</p>
          ) : !authList?.length ? (
            <p className="network-muted">No accounts are pinned to this route.</p>
          ) : (
            <div className="network-assignment-list">
              {authList.map((auth) => (
                <div key={auth.id} className="network-assignment">
                  <span className={`network-status-dot ${auth.active && auth.status === 'active' ? 'network-status-dot--ready' : 'network-status-dot--idle'}`} />
                  <div>
                    <strong>{auth.username || `AUTH #${auth.id}`}</strong>
                    <small>{auth.site} · {auth.status}</small>
                  </div>
                  <button type="button" onClick={() => onRemoveAuth(auth.id)}>DISCONNECT</button>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null}
    </article>
  );
}
