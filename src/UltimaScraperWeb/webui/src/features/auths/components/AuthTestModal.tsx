import { useEffect, useRef, useState } from 'react';

import { getAuthById, testAuth, testAuthProxy } from '../../../api/auths';
import type { AuthCredential } from '../../../api/types/auths';

type TestStepStatus = 'idle' | 'running' | 'success' | 'failed' | 'skipped';

interface AuthTestModalProps {
  auth: AuthCredential;
  onClose: () => void;
  onAuthTested: () => void;
}

export function AuthTestModal({
  auth,
  onClose,
  onAuthTested,
}: AuthTestModalProps) {
  const [proxyStatus, setProxyStatus] = useState<TestStepStatus>('idle');
  const [proxyMessage, setProxyMessage] = useState('');
  const [proxyLatency, setProxyLatency] = useState<number | null>(null);
  const [proxyReturnIp, setProxyReturnIp] = useState('');
  const [authStatus, setAuthStatus] = useState<TestStepStatus>('idle');
  const [authMessage, setAuthMessage] = useState('');
  const onAuthTestedRef = useRef(onAuthTested);

  useEffect(() => {
    onAuthTestedRef.current = onAuthTested;
  }, [onAuthTested]);

  useEffect(() => {
    let cancelled = false;

    const fetchLatestAuth = async (): Promise<AuthCredential | null> => {
      try {
        return await getAuthById(auth.id, auth.site);
      } catch {
        return null;
      }
    };

    const runTests = async () => {
      const latestAuth = await fetchLatestAuth();
      if (cancelled) {
        return;
      }
      const authToTest = latestAuth ?? auth;

      setProxyStatus('running');
      setProxyMessage('');
      setProxyLatency(null);
      setProxyReturnIp('');

      try {
        const proxyResult = await testAuthProxy(authToTest.id, authToTest.site);
        if (cancelled) {
          return;
        }
        setProxyReturnIp(proxyResult.return_ip ?? '');
        if (proxyResult.skipped) {
          setProxyStatus('skipped');
          setProxyMessage('Direct connection (no proxy assigned)');
        } else if (proxyResult.success) {
          setProxyStatus('success');
          setProxyMessage(proxyResult.message);
          setProxyLatency(proxyResult.latency_ms ?? null);
        } else {
          setProxyStatus('failed');
          setProxyMessage(proxyResult.message);
          setAuthStatus('skipped');
          setAuthMessage('Auth test skipped due to proxy failure');
          return;
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        setProxyStatus('failed');
        setProxyMessage(
          error instanceof Error ? error.message : 'Proxy test failed',
        );
        setAuthStatus('skipped');
        setAuthMessage('Auth test skipped due to proxy failure');
        return;
      }

      setAuthStatus('running');
      setAuthMessage('');

      try {
        const authResult = await testAuth(authToTest.id, authToTest.site);
        if (cancelled) {
          return;
        }
        setAuthStatus(authResult.success ? 'success' : 'failed');
        setAuthMessage(authResult.message);
        onAuthTestedRef.current();
      } catch (error) {
        if (cancelled) {
          return;
        }
        setAuthStatus('failed');
        setAuthMessage(
          error instanceof Error ? error.message : 'Auth test failed',
        );
      }
    };

    void runTests();
    return () => {
      cancelled = true;
    };
  }, [auth]);

  const renderStatus = (status: TestStepStatus) => {
    if (status === 'running') return '⏳ Running...';
    if (status === 'success') return '✅ Success';
    if (status === 'failed') return '❌ Failed';
    if (status === 'skipped') return '⏭️ Skipped';
    return '—';
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content auth-test-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>🧪 Test Auth</h2>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <div className="form-info">
            <span>
              <strong>Site:</strong> {auth.site}
            </span>
            <span>
              <strong>User ID:</strong> {auth.user_id}
            </span>
            <span>
              <strong>Username:</strong> {auth.username || 'N/A'}
            </span>
          </div>

          <div className="auth-test-steps">
            <div className={`auth-test-step ${proxyStatus}`}>
              <div className="auth-test-step-header">
                <span className="auth-test-step-title">Proxy check</span>
                <span className="auth-test-step-status">
                  {renderStatus(proxyStatus)}
                </span>
              </div>
              <div className="auth-test-step-body">
                <div className="auth-test-step-message">
                  {proxyMessage ||
                    (auth.proxy_id
                      ? 'Verifying assigned proxy...'
                      : 'No proxy assigned')}
                </div>
                {proxyReturnIp && (
                  <div className="auth-test-step-latency">
                    Return IP: {proxyReturnIp}
                  </div>
                )}
                {proxyLatency !== null && (
                  <div className="auth-test-step-latency">
                    Latency: {proxyLatency} ms
                  </div>
                )}
              </div>
            </div>

            <div className={`auth-test-step ${authStatus}`}>
              <div className="auth-test-step-header">
                <span className="auth-test-step-title">Auth check</span>
                <span className="auth-test-step-status">
                  {renderStatus(authStatus)}
                </span>
              </div>
              <div className="auth-test-step-body">
                <div className="auth-test-step-message">
                  {authMessage || 'Waiting on auth test...'}
                </div>
              </div>
            </div>
          </div>
        </div>
        <div className="modal-footer">
          <button type="button" className="btn-cancel" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
