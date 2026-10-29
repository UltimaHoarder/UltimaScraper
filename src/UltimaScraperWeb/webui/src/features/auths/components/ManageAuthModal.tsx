import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { parseAuthJson, parseCurl } from '../../../api/auths';
import { listProxies } from '../../../api/network';
import type {
  AuthCredential,
  AuthEditRequest,
  ParsedCurlData,
} from '../../../api/types/auths';
import type { NetworkProxy } from '../../../api/types/network';
import {
  canNormalizeToAuthJson,
  detectAuthImportType,
  isOnlyFansAuth,
  isSupportedAuthImportInput,
  needsAgeVerification,
  normalizeToAuthJson,
  parseEmailNotificationPreference,
  type AuthImportTab,
  type EmailNotificationPreference,
} from '../lib/authsUtils';

type ManageAuthTab = 'refresh' | 'credentials' | 'account';

interface ManageAuthModalProps {
  auth: AuthCredential;
  onClose: () => void;
  onSave: (data: AuthEditRequest) => void;
  isSaving: boolean;
  onTest: () => void;
  onUpdateSubscriptions: () => void;
  onScrapePaidContent: () => void;
  onVerifyAge: () => void;
  onVerifyIdentity: () => void;
  isUpdatingSubscriptions: boolean;
  isScrapingPaidContent: boolean;
}

export function ManageAuthModal({
  auth,
  onClose,
  onSave,
  isSaving,
  onTest,
  onUpdateSubscriptions,
  onScrapePaidContent,
  onVerifyAge,
  onVerifyIdentity,
  isUpdatingSubscriptions,
  isScrapingPaidContent,
}: ManageAuthModalProps) {
  const [activeTab, setActiveTab] = useState<ManageAuthTab>('credentials');
  const [refreshImportTab, setRefreshImportTab] = useState<AuthImportTab>('curl');
  const [formData, setFormData] = useState<AuthEditRequest>({
    username: auth.username || '',
    cookie: '',
    x_bc: '',
    authorization: '',
    user_agent: '',
    active: auth.active,
    proxy_id: auth.proxy_id,
    spend: auth.spend,
    spender_type: auth.spender_type || 'all',
  });
  const [emailNotificationPreference, setEmailNotificationPreference] =
    useState<EmailNotificationPreference>('');
  const [curlCommand, setCurlCommand] = useState('');
  const [parsedData, setParsedData] = useState<ParsedCurlData | null>(null);
  const [curlError, setCurlError] = useState<string | null>(null);
  const [curlAppliedMessage, setCurlAppliedMessage] = useState<string | null>(null);
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
      importTab: AuthImportTab,
      options: { force?: boolean } = {},
    ) => {
      const selectedSite = auth.site.toLowerCase();
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
      setCurlError(null);
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
          setCurlError(result.error || 'Failed to parse auth import');
        }
      } catch (err) {
        if (requestId !== parseRequestIdRef.current) {
          return;
        }
        setCurlError(err instanceof Error ? err.message : 'Failed to parse auth import');
      } finally {
        if (inFlightParseKeyRef.current === parseKey) {
          inFlightParseKeyRef.current = null;
        }
      }
    },
    [auth.site],
  );

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const pastedText = e.clipboardData.getData('text');
    if (!pastedText) return;

    const trimmed = pastedText.trim();
    if (canNormalizeToAuthJson(trimmed)) {
      e.preventDefault();
      const normalized = normalizeToAuthJson(trimmed);
      setRefreshImportTab('json');
      setCurlCommand(normalized);
      void parseCurlCommand(normalized, 'json', { force: true });
    } else if (trimmed.toLowerCase().startsWith('curl')) {
      if (refreshImportTab !== 'curl') {
        setRefreshImportTab('curl');
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
      setRefreshImportTab('json');
      setCurlCommand(normalized);
      return;
    }

    const detected = detectAuthImportType(trimmed);
    if (detected === 'json' && refreshImportTab === 'curl') {
      setRefreshImportTab('json');
    } else if (detected === 'curl' && refreshImportTab === 'json') {
      setRefreshImportTab('curl');
    }

    setCurlCommand(value);
  };

  useEffect(() => {
    const trimmedCommand = curlCommand.trim();

    if (!isSupportedAuthImportInput(trimmedCommand, refreshImportTab)) {
      parseRequestIdRef.current += 1;
      inFlightParseKeyRef.current = null;
      setParsedData(null);
      setCurlError(null);
      setCurlAppliedMessage(null);
      lastParsedKeyRef.current = '';
      return;
    }

    const parseKey = `${auth.site.toLowerCase()}::${refreshImportTab}::${trimmedCommand}`;
    if (
      lastParsedKeyRef.current === parseKey ||
      inFlightParseKeyRef.current === parseKey
    ) {
      return;
    }

    const timeout = window.setTimeout(() => {
      void parseCurlCommand(curlCommand, refreshImportTab);
    }, 450);

    return () => {
      window.clearTimeout(timeout);
    };
  }, [auth.site, curlCommand, parseCurlCommand, refreshImportTab]);

  const handleApplyParsedCurl = () => {
    if (!parsedData?.success) {
      return;
    }
    setFormData((prev) => ({
      ...prev,
      ...(parsedData.cookie ? { cookie: parsedData.cookie } : {}),
      ...(parsedData.x_bc ? { x_bc: parsedData.x_bc } : {}),
      ...(parsedData.authorization
        ? { authorization: parsedData.authorization }
        : {}),
      ...(parsedData.user_agent ? { user_agent: parsedData.user_agent } : {}),
    }));
    setCurlAppliedMessage('Parsed values applied. Review and click Save Changes.');
    setCurlError(null);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const updates: AuthEditRequest = {};
    if (formData.username !== (auth.username || '')) {
      updates.username = formData.username;
    }
    if (formData.cookie) {
      updates.cookie = formData.cookie;
    }
    if (formData.x_bc) {
      updates.x_bc = formData.x_bc;
    }
    if (formData.authorization) {
      updates.authorization = formData.authorization;
    }
    if (formData.user_agent) {
      updates.user_agent = formData.user_agent;
    }
    if (formData.proxy_id !== auth.proxy_id) {
      updates.proxy_id = formData.proxy_id;
    }
    if (formData.spend !== auth.spend) {
      updates.spend = formData.spend;
    }
    if (formData.spender_type !== auth.spender_type) {
      updates.spender_type = formData.spender_type;
    }

    const emailNotificationsEnabled = parseEmailNotificationPreference(
      emailNotificationPreference,
    );
    if (emailNotificationsEnabled !== null) {
      updates.email_notifications_enabled = emailNotificationsEnabled;
    }

    onSave(updates);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content manage-auth-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>Manage Auth</h2>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div className="form-info">
              <span>
                <strong>Site:</strong> {auth.site}
              </span>
              <span>
                <strong>User ID:</strong> {auth.user_id}
              </span>
              <span>
                <strong>Status:</strong> {auth.status}
              </span>
            </div>

            <div className="manage-section manage-panel">
              <h3>Account Actions</h3>
              <div className="manage-actions-grid">
                <button
                  type="button"
                  className="action-btn test-btn"
                  onClick={onTest}
                >
                  🧪 Test Auth
                </button>
                <button
                  type="button"
                  className="action-btn subscriptions-btn"
                  onClick={onUpdateSubscriptions}
                  disabled={isUpdatingSubscriptions}
                >
                  {isUpdatingSubscriptions ? '⏳ Updating...' : '🔄 Update Subs'}
                </button>
                <button
                  type="button"
                  className="action-btn subscriptions-btn"
                  onClick={onScrapePaidContent}
                  disabled={isScrapingPaidContent}
                >
                  {isScrapingPaidContent ? '⏳ Queueing...' : '💎 Scrape Paid Content'}
                </button>
                {needsAgeVerification(auth) && (
                  <button
                    type="button"
                    className="action-btn verify-btn"
                    onClick={onVerifyAge}
                  >
                    🔞 Verify Age
                  </button>
                )}
                {isOnlyFansAuth(auth) && (
                  <button
                    type="button"
                    className="action-btn verify-btn"
                    onClick={onVerifyIdentity}
                  >
                    🪪 Verify ID
                  </button>
                )}
              </div>
            </div>

            <div className="manage-tabs" role="tablist" aria-label="Manage auth sections">
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 'refresh'}
                className={`manage-tab ${activeTab === 'refresh' ? 'active' : ''}`}
                onClick={() => setActiveTab('refresh')}
              >
                Refresh
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 'credentials'}
                className={`manage-tab ${activeTab === 'credentials' ? 'active' : ''}`}
                onClick={() => setActiveTab('credentials')}
              >
                Credentials
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={activeTab === 'account'}
                className={`manage-tab ${activeTab === 'account' ? 'active' : ''}`}
                onClick={() => setActiveTab('account')}
              >
                Account
              </button>
            </div>

            {activeTab === 'refresh' && (
              <div className="manage-section manage-panel">
                <h3>Credential Refresh</h3>
                <div className="form-group">
                  <div className="manage-tabs" role="tablist" aria-label="Refresh auth input type">
                    <button
                      type="button"
                      role="tab"
                      aria-selected={refreshImportTab === 'curl'}
                      className={`manage-tab ${refreshImportTab === 'curl' ? 'active' : ''}`}
                      onClick={() => setRefreshImportTab('curl')}
                    >
                      cURL
                    </button>
                    <button
                      type="button"
                      role="tab"
                      aria-selected={refreshImportTab === 'json'}
                      className={`manage-tab ${refreshImportTab === 'json' ? 'active' : ''}`}
                      onClick={() => setRefreshImportTab('json')}
                    >
                      Auth JSON
                    </button>
                  </div>
                  <label htmlFor="edit-curl-command">
                    {refreshImportTab === 'json' ? 'Paste auth JSON' : 'Paste cURL'}
                  </label>
                  <p className="curl-instructions">
                    Paste a copied browser cURL command or a raw auth JSON
                    payload to extract fresh auth fields for this account.
                  </p>
                  <textarea
                    id="edit-curl-command"
                    value={curlCommand}
                    onChange={(e) => handleCommandChange(e.target.value)}
                    onPaste={handlePaste}
                    placeholder={
                      refreshImportTab === 'json'
                        ? `{\n  "sess": "...",\n  "auth_id": "123456",\n  "user_agent": "Mozilla/5.0 ...",\n  "x_bc": "..."\n}`
                        : "curl 'https://onlyfans.com/api2/v2/...' -H 'cookie: ...' ..."
                    }
                    rows={5}
                    className="curl-textarea"
                  />
                  {curlError && <div className="curl-error">{curlError}</div>}
                  {curlAppliedMessage && (
                    <div className="curl-success">{curlAppliedMessage}</div>
                  )}
                  {parsedData?.success && (
                    <button
                      type="button"
                      className="btn-parse"
                      onClick={handleApplyParsedCurl}
                    >
                      Apply Parsed Values
                    </button>
                  )}
                </div>
              </div>
            )}

            {activeTab === 'credentials' && (
              <div className="manage-section manage-panel">
                <h3>Credential Settings</h3>
                <div className="form-group">
                  <label htmlFor="edit-username">Username</label>
                  <input
                    id="edit-username"
                    type="text"
                    value={formData.username}
                    onChange={(e) =>
                      setFormData({ ...formData, username: e.target.value })
                    }
                    placeholder="Username"
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="edit-cookie">Cookie (leave empty to keep current)</label>
                  <textarea
                    id="edit-cookie"
                    value={formData.cookie}
                    onChange={(e) =>
                      setFormData({ ...formData, cookie: e.target.value })
                    }
                    placeholder="Paste new cookie value..."
                    rows={3}
                  />
                  <span className="form-hint">
                    Current: {auth.cookie_preview || 'Not set'}
                  </span>
                </div>

                {auth.site.toLowerCase() === 'onlyfans' && (
                  <div className="form-group">
                    <label htmlFor="edit-x-bc">X-BC Header (leave empty to keep current)</label>
                    <input
                      id="edit-x-bc"
                      type="text"
                      value={formData.x_bc}
                      onChange={(e) =>
                        setFormData({ ...formData, x_bc: e.target.value })
                      }
                      placeholder="Paste new x-bc value..."
                    />
                  </div>
                )}

                {auth.site.toLowerCase() === 'fansly' && (
                  <div className="form-group">
                    <label htmlFor="edit-auth">Authorization Token (leave empty to keep current)</label>
                    <input
                      id="edit-auth"
                      type="text"
                      value={formData.authorization}
                      onChange={(e) =>
                        setFormData({ ...formData, authorization: e.target.value })
                      }
                      placeholder="Paste new authorization token..."
                    />
                    <span className="form-hint">
                      Current: {auth.has_authorization ? '✅ Set' : 'Not set'}
                    </span>
                  </div>
                )}

                <div className="form-group">
                  <label htmlFor="edit-ua">User Agent (leave empty to keep current)</label>
                  <input
                    id="edit-ua"
                    type="text"
                    value={formData.user_agent}
                    onChange={(e) =>
                      setFormData({ ...formData, user_agent: e.target.value })
                    }
                    placeholder="Paste new user agent..."
                  />
                  <span className="form-hint">
                    Current: {auth.user_agent_preview || 'Not set'}
                  </span>
                </div>

                <div className="form-group">
                  <label htmlFor="edit-proxy">Proxy (optional)</label>
                  <select
                    id="edit-proxy"
                    value={formData.proxy_id || ''}
                    onChange={(e) =>
                      setFormData({ ...formData, proxy_id: e.target.value || null })
                    }
                  >
                    <option value="">🌐 Direct connection (no proxy)</option>
                    {proxiesData?.map((proxy) => (
                      <option key={proxy.id} value={proxy.url} disabled={proxy.enabled === false}>
                        {proxy.url} {proxy.username ? `(${proxy.username})` : ''}
                        {proxy.enabled === false ? ' — disabled' : ''}
                      </option>
                    ))}
                  </select>
                  {formData.proxy_id && (
                    <span className="form-hint">⚠️ All requests will use this proxy</span>
                  )}
                </div>
              </div>
            )}

            {activeTab === 'account' && (
              <div className="manage-section manage-panel">
                <h3>Account Settings</h3>
                {auth.site.toLowerCase() === 'onlyfans' && (
                  <div className="form-group">
                    <label htmlFor="edit-email-notifications">Email Notifications</label>
                    <select
                      id="edit-email-notifications"
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

                <div className="form-group checkbox-group">
                  <label>
                    <input
                      type="checkbox"
                      checked={formData.spend || false}
                      onChange={(e) =>
                        setFormData({ ...formData, spend: e.target.checked })
                      }
                    />
                    Spender (can purchase subscriptions)
                  </label>
                </div>

                {formData.spend && (
                  <div className="form-group">
                    <label htmlFor="edit-spender-type">Spender Type</label>
                    <select
                      id="edit-spender-type"
                      value={formData.spender_type || 'all'}
                      onChange={(e) =>
                        setFormData({ ...formData, spender_type: e.target.value })
                      }
                    >
                      <option value="all">All (any subscription price)</option>
                      <option value="free">Free only ($0.00)</option>
                      <option value="paid">Paid only (&gt; $0.00)</option>
                    </select>
                    <span className="form-hint">
                      {formData.spender_type === 'free' &&
                        '💰 Will only activate free subscriptions'}
                      {formData.spender_type === 'paid' &&
                        '💳 Will only activate paid subscriptions'}
                      {formData.spender_type === 'all' &&
                        '🎯 Can activate any subscription'}
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="modal-footer">
            <button type="button" className="btn-cancel" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-save" disabled={isSaving}>
              {isSaving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
