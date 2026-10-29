import { useEffect, useRef, useState } from 'react';
import type { AuthCredential } from '../../../../api/types/auths';
import type { AuthsMockModel } from '../authsMockModel';

interface MockAuthTestModalProps {
  auth: AuthCredential;
  model: AuthsMockModel;
  onClose: () => void;
}

export function MockAuthTestModal({ auth, model, onClose }: MockAuthTestModalProps) {
  const [isRunning, setIsRunning] = useState(true);
  const [proxyStatus, setProxyStatus] = useState<'running' | 'success' | 'skipped'>('running');
  const [authStatus, setAuthStatus] = useState<'pending' | 'running' | 'success'>('pending');
  const [latency, setLatency] = useState(48);

  const assignedProxy = model.proxies.find((p) => p.id === auth.proxy_id);

  // Each run is a number; the effect plays the probe out for the current one.
  const [run, setRun] = useState(0);
  const handleTestAuth = useRef(model.handleTestAuth);
  useEffect(() => {
    handleTestAuth.current = model.handleTestAuth;
  });

  const runDiagnostic = () => {
    setIsRunning(true);
    setProxyStatus('running');
    setAuthStatus('pending');
    setRun((current) => current + 1);
  };

  useEffect(() => {
    let finish: number | undefined;
    const probe = window.setTimeout(() => {
      setProxyStatus(auth.proxy_id ? 'success' : 'skipped');
      setAuthStatus('running');

      finish = window.setTimeout(() => {
        setAuthStatus('success');
        setIsRunning(false);
        setLatency(Math.floor(Math.random() * 30 + 35));
        handleTestAuth.current(auth.id);
      }, 700);
    }, 600);
    return () => {
      window.clearTimeout(probe);
      window.clearTimeout(finish);
    };
  }, [run, auth.id, auth.proxy_id]);

  return (
    <div className="arm-modal-overlay" onClick={onClose} role="dialog" aria-modal="true">
      <div className="arm-modal-card arm-test-modal" onClick={(e) => e.stopPropagation()}>
        <header className="arm-modal-head">
          <div>
            <span className="arm-eyebrow">DIAGNOSTIC PROBE // AUTH #{auth.id}</span>
            <h3>Dual-Stage Credential Health Probe</h3>
          </div>
          <button type="button" className="arm-modal-close" onClick={onClose} aria-label="Close dialog">
            ✕
          </button>
        </header>

        <div className="arm-modal-body">
          {/* Target Account Header */}
          <div className="arm-probe-target">
            <span className={`arm-platform-badge is-${auth.site.toLowerCase()}`}>{auth.site}</span>
            <strong>@{auth.username || `User #${auth.user_id}`}</strong>
            <span className="arm-mono-tag">UID: {auth.user_id}</span>
          </div>

          {/* 2-Step Test Pipeline */}
          <div className="arm-probe-steps">
            {/* Step 1: Network Proxy */}
            <div className={`arm-probe-step is-${proxyStatus}`}>
              <div className="arm-step-icon">
                {proxyStatus === 'running' ? '⏳' : proxyStatus === 'skipped' ? '⚡' : '✓'}
              </div>
              <div className="arm-step-info">
                <strong>Stage 01: Network Layer &amp; Proxy Exit</strong>
                <p>
                  {proxyStatus === 'running'
                    ? 'Probing outbound gateway...'
                    : proxyStatus === 'skipped'
                    ? 'Direct connection (no proxy assigned) — Local Gateway Active'
                    : `Routed via ${assignedProxy?.name || auth.proxy_id} (${assignedProxy?.ip || '142.250.190.46'})`}
                </p>
              </div>
              <div className="arm-step-badge">
                {proxyStatus === 'running' ? (
                  <span className="arm-pulse-dot" />
                ) : (
                  <span>{proxyStatus === 'skipped' ? 'DIRECT' : `${assignedProxy?.latencyMs || 42}ms`}</span>
                )}
              </div>
            </div>

            {/* Step 2: Upstream Platform Handshake */}
            <div className={`arm-probe-step is-${authStatus}`}>
              <div className="arm-step-icon">
                {authStatus === 'pending'
                  ? '⋯'
                  : authStatus === 'running'
                  ? '⏳'
                  : '✓'}
              </div>
              <div className="arm-step-info">
                <strong>Stage 02: Platform Authentication Handshake</strong>
                <p>
                  {authStatus === 'pending'
                    ? 'Waiting for network gate...'
                    : authStatus === 'running'
                    ? `Verifying session token against ${auth.site} API endpoints...`
                    : `HTTP 200 OK — Session valid for @${auth.username}. User profile authenticated.`}
                </p>
              </div>
              <div className="arm-step-badge">
                {authStatus === 'running' ? (
                  <span className="arm-pulse-dot" />
                ) : authStatus === 'success' ? (
                  <span className="is-green">VALID (200 OK)</span>
                ) : (
                  <span>STANDBY</span>
                )}
              </div>
            </div>
          </div>

          {/* Diagnostic Metrics Box */}
          <div className="arm-diagnostic-box">
            <div className="arm-diag-row">
              <span>Overall Status:</span>
              <strong className={isRunning ? 'is-warn' : 'is-green'}>
                {isRunning ? 'TESTING IN PROGRESS...' : 'OPERATIONAL / PASSED'}
              </strong>
            </div>
            <div className="arm-diag-row">
              <span>Round-Trip Latency:</span>
              <strong>{latency} ms</strong>
            </div>
            <div className="arm-diag-row">
              <span>Rate Limit Capacity:</span>
              <strong>120 req/min (Normal)</strong>
            </div>
            <div className="arm-diag-row">
              <span>Exit IP Address:</span>
              <code>{assignedProxy?.ip || '127.0.0.1 (Local)'}</code>
            </div>
          </div>
        </div>

        <footer className="arm-modal-footer">
          <button
            type="button"
            className="arm-btn arm-btn--secondary"
            onClick={runDiagnostic}
            disabled={isRunning}
          >
            {isRunning ? 'Probing...' : '⚡ Re-run Probe'}
          </button>
          <button type="button" className="arm-btn arm-btn--primary" onClick={onClose}>
            Done
          </button>
        </footer>
      </div>
    </div>
  );
}
