import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { addAuthFromCurl, parseAuthJson, parseCurl } from '../../../api/auths';
import { listProxies } from '../../../api/network';
import type { ParsedCurlData } from '../../../api/types/auths';
import type { NetworkProxy } from '../../../api/types/network';
import {
  canNormalizeToAuthJson,
  detectAuthImportType,
  isSupportedAuthImportInput,
  normalizeToAuthJson,
  parseEmailNotificationPreference,
  type AuthImportTab,
  type EmailNotificationPreference,
} from '../lib/authsUtils';

interface AddCurlModalProps {
  onClose: () => void;
  onSuccess: () => void;
}

export function AddCurlModal({ onClose, onSuccess }: AddCurlModalProps) {
  const [activeTab, setActiveTab] = useState<AuthImportTab>('curl');
  const [curlCommand, setCurlCommand] = useState('');
  const [site, setSite] = useState('onlyfans');
  const [proxyId, setProxyId] = useState('');
  const [emailNotificationPreference, setEmailNotificationPreference] =
    useState<EmailNotificationPreference>('');
  const [parsedData, setParsedData] = useState<ParsedCurlData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [isAdding, setIsAdding] = useState(false);
  const lastParsedKeyRef = useRef('');
  const inFlightParseKeyRef = useRef<string | null>(null);
  const parseRequestIdRef = useRef(0);

  const { data: proxiesData } = useQuery<NetworkProxy[]>({
    queryKey: ['proxies'],
    queryFn: listProxies,
  });

  const parseCurlCommand = useCallback(
    async (
      command: string,
      selectedSite: string,
      importTab: AuthImportTab,
      options: { force?: boolean } = {},
    ) => {
      const trimmedCommand = command.trim();
      const parseKey = `${selectedSite}::${importTab}::${trimmedCommand}`;

      if (!options.force) {
        if (!isSupportedAuthImportInput(trimmedCommand, importTab)) {
          return;
        }

        if (
          lastParsedKeyRef.current === parseKey ||
          inFlightParseKeyRef.current === parseKey
        ) {
          return;
        }
      }

      const requestId = ++parseRequestIdRef.current;
      inFlightParseKeyRef.current = parseKey;
      setError(null);
      setSuccessMessage(null);
      setParsedData(null);

      try {
        const payloadToParse =
          importTab === 'json' ? normalizeToAuthJson(command) : command;
        const result =
          importTab === 'json'
            ? await parseAuthJson(payloadToParse, selectedSite)
            : await parseCurl(command, selectedSite);
        if (requestId !== parseRequestIdRef.current) {
          return;
        }
        setParsedData(result);
        lastParsedKeyRef.current = parseKey;
        if (!result.success) {
          setError(result.error || 'Failed to parse auth import');
        }
      } catch (err) {
        if (requestId !== parseRequestIdRef.current) {
          return;
        }
        setError(err instanceof Error ? err.message : 'Failed to parse auth import');
      } finally {
        if (inFlightParseKeyRef.current === parseKey) {
          inFlightParseKeyRef.current = null;
        }
      }
    },
    [],
  );

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const pastedText = e.clipboardData.getData('text');
    if (!pastedText) return;

    const trimmed = pastedText.trim();
    if (canNormalizeToAuthJson(trimmed)) {
      e.preventDefault();
      const normalized = normalizeToAuthJson(trimmed);
      setActiveTab('json');
      setCurlCommand(normalized);
      void parseCurlCommand(normalized, site, 'json', { force: true });
    } else if (trimmed.toLowerCase().startsWith('curl')) {
      if (activeTab !== 'curl') {
        setActiveTab('curl');
      }
    }
  };

  const handleCommandChange = (value: string) => {
    const trimmed = value.trim();

    if (
      canNormalizeToAuthJson(trimmed) &&
      (trimmed.startsWith("{'") ||
        trimmed.includes("': ") ||
        trimmed.includes('None') ||
        trimmed.includes('True') ||
        trimmed.includes('False'))
    ) {
      const normalized = normalizeToAuthJson(trimmed);
      setActiveTab('json');
      setCurlCommand(normalized);
      return;
    }

    const detected = detectAuthImportType(trimmed);
    if (detected === 'json' && activeTab === 'curl') {
      setActiveTab('json');
    } else if (detected === 'curl' && activeTab === 'json') {
      setActiveTab('curl');
    }

    setCurlCommand(value);
  };

  useEffect(() => {
    const trimmedCommand = curlCommand.trim();

    if (!isSupportedAuthImportInput(trimmedCommand, activeTab)) {
      parseRequestIdRef.current += 1;
      inFlightParseKeyRef.current = null;
      setParsedData(null);
      setError(null);
      lastParsedKeyRef.current = '';
      return;
    }

    const parseKey = `${site}::${activeTab}::${trimmedCommand}`;
    if (
      lastParsedKeyRef.current === parseKey ||
      inFlightParseKeyRef.current === parseKey
    ) {
      return;
    }

    const timeout = window.setTimeout(() => {
      void parseCurlCommand(curlCommand, site, activeTab);
    }, 450);

    return () => {
      window.clearTimeout(timeout);
    };
  }, [activeTab, curlCommand, site, parseCurlCommand]);

  const handleAdd = async () => {
    setIsAdding(true);
    setError(null);
    setSuccessMessage(null);
    try {
      const payloadToAdd =
        activeTab === 'json' ? normalizeToAuthJson(curlCommand) : curlCommand;
      const result = await addAuthFromCurl(
        payloadToAdd,
        site,
        activeTab,
        proxyId || null,
        parseEmailNotificationPreference(emailNotificationPreference),
      );
      if (result.success) {
        onSuccess();
        setSuccessMessage('Auth successful. Account saved.');
      } else {
        setError(result.error || 'Failed to add auth');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add auth');
    } finally {
      setIsAdding(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content curl-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>➕ Add Account</h2>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="modal-body">
          <p className="curl-instructions">
            Paste either a browser cURL command from DevTools or a raw auth JSON
            payload with values such as <code>sess</code>, <code>auth_id</code>,
            <code>user_agent</code>, and <code>x_bc</code>. The importer will
            extract and validate the account before saving it.
          </p>

          <div className="form-group">
            <label htmlFor="curl-site">Site:</label>
            <select
              id="curl-site"
              value={site}
              onChange={(e) => setSite(e.target.value)}
            >
              <option value="onlyfans">OnlyFans</option>
              <option value="fansly">Fansly</option>
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="curl-proxy">Proxy (optional):</label>
            <select
              id="curl-proxy"
              value={proxyId}
              onChange={(e) => setProxyId(e.target.value)}
            >
              <option value="">🌐 Direct connection (no proxy)</option>
              {proxiesData?.map((proxy) => (
                <option key={proxy.id} value={proxy.url} disabled={proxy.enabled === false}>
                  {proxy.url} {proxy.username ? `(${proxy.username})` : ''}
                  {proxy.enabled === false ? ' — disabled' : ''}
                </option>
              ))}
            </select>
          </div>

          {site.toLowerCase() === 'onlyfans' && (
            <div className="form-group">
              <label htmlFor="add-email-notifications">Email Notifications</label>
              <select
                id="add-email-notifications"
                value={emailNotificationPreference}
                onChange={(e) =>
                  setEmailNotificationPreference(
                    e.target.value as EmailNotificationPreference,
                  )
                }
              >
                <option value="">No change</option>
                <option value="enabled">Enabled</option>
                <option value="disabled">Disabled</option>
              </select>
            </div>
          )}

          <div className="form-group">
            <div className="manage-tabs" role="tablist" aria-label="Add account methods">
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 'curl'}
                className={`manage-tab ${activeTab === 'curl' ? 'active' : ''}`}
                onClick={() => setActiveTab('curl')}
              >
                cURL
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 'json'}
                className={`manage-tab ${activeTab === 'json' ? 'active' : ''}`}
                onClick={() => setActiveTab('json')}
              >
                Auth JSON
              </button>
            </div>
            <label htmlFor="curl-command">
              {activeTab === 'json' ? 'Auth JSON:' : 'cURL:'}
            </label>
            <textarea
              id="curl-command"
              value={curlCommand}
              onChange={(e) => handleCommandChange(e.target.value)}
              onPaste={handlePaste}
              placeholder={
                activeTab === 'json'
                  ? `{\n  "sess": "...",\n  "auth_id": "123456",\n  "auth_uid_": "123456",\n  "user_agent": "Mozilla/5.0 ...",\n  "x_bc": "...",\n  "app-token": "..."\n}`
                  : "curl 'https://onlyfans.com/api2/v2/...' -H 'cookie: ...' ..."
              }
              rows={8}
              className="curl-textarea"
            />
          </div>

          {error && <div className="curl-error">{error}</div>}
          {successMessage && <div className="curl-success">{successMessage}</div>}

          {parsedData && parsedData.success && (
            <div className="parsed-data">
              <h4>✅ Parsed Data:</h4>
              <div className="parsed-item">
                <span className="parsed-label">Site:</span>
                <span className="parsed-value">{parsedData.site}</span>
              </div>
              {parsedData.auth_id && (
                <div className="parsed-item">
                  <span className="parsed-label">Auth ID:</span>
                  <span className="parsed-value">{parsedData.auth_id}</span>
                </div>
              )}
              {parsedData.sess && (
                <div className="parsed-item">
                  <span className="parsed-label">Session:</span>
                  <span className="parsed-value mono">✅ Found</span>
                </div>
              )}
              {parsedData.user_id && (
                <div className="parsed-item">
                  <span className="parsed-label">User ID:</span>
                  <span className="parsed-value">{parsedData.user_id}</span>
                </div>
              )}
              <div className="parsed-item">
                <span className="parsed-label">App Token:</span>
                <span className="parsed-value mono">
                  {parsedData.app_token ? '✅ Found' : '❌ Not found'}
                </span>
              </div>
              <div className="parsed-item">
                <span className="parsed-label">Cookie:</span>
                <span className="parsed-value mono">
                  {parsedData.cookie ? '✅ Found' : '❌ Not found'}
                </span>
              </div>
              <div className="parsed-item">
                <span className="parsed-label">X-BC:</span>
                <span className="parsed-value mono">
                  {parsedData.x_bc ? '✅ Found' : '❌ Not found'}
                </span>
              </div>
              <div className="parsed-item">
                <span className="parsed-label">Authorization:</span>
                <span className="parsed-value mono">
                  {parsedData.authorization ? '✅ Found' : '❌ Not found'}
                </span>
              </div>
              <div className="parsed-item">
                <span className="parsed-label">User Agent:</span>
                <span className="parsed-value mono">
                  {parsedData.user_agent ? '✅ Found' : '❌ Not found'}
                </span>
              </div>
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button type="button" className="btn-cancel" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn-save"
            onClick={handleAdd}
            disabled={!parsedData?.success || isAdding}
          >
            {isAdding ? 'Adding...' : 'Add Account'}
          </button>
        </div>
      </div>
    </div>
  );
}
