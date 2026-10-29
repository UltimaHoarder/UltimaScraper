import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  executeApiMethod,
  getApiMethods,
  type ApiMethodSpec,
  type ApiRequestResponse,
} from '../../../api/apiRequests';
import { getAuthList } from '../../../api/auths';
import type { AuthCredential } from '../../../api/types/auths';
import JsonView from '@uiw/react-json-view';
import { githubDarkTheme } from '@uiw/react-json-view/githubDark';

const SITES = ['onlyfans', 'fansly'] as const;

function isJsonTreeValue(value: unknown): value is Record<string, unknown> | unknown[] {
  return Array.isArray(value) || (typeof value === 'object' && value !== null);
}

function formatResultValue(value: unknown): string {
  if (value === undefined) {
    return 'No data returned.';
  }
  if (value === null) {
    return 'null';
  }
  if (typeof value === 'string') {
    return value;
  }

  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function APIRequestsTool() {
  // --- catalogues ---
  const [methods, setMethods] = useState<Record<string, ApiMethodSpec>>({});
  const [auths, setAuths] = useState<AuthCredential[]>([]);

  // --- selections ---
  const [site, setSite] = useState<string>(SITES[0]);
  const [authId, setAuthId] = useState<number | null>(null);
  const [methodKey, setMethodKey] = useState<string>('');
  const [argValues, setArgValues] = useState<Record<string, string>>({});

  // --- execution state ---
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ApiRequestResponse | null>(null);

  // Fetch method catalogue once
  useEffect(() => {
    getApiMethods()
      .then((res) => {
        setMethods(res.methods);
        const first = Object.keys(res.methods)[0];
        if (first) setMethodKey(first);
      })
      .catch(console.error);
  }, []);

  // Fetch auths when site changes
  useEffect(() => {
    getAuthList(site, true)
      .then((res) => {
        setAuths(res.auths ?? []);
        setAuthId(null);
      })
      .catch(console.error);
  }, [site]);

  // Auto-select first auth
  useEffect(() => {
    if (authId === null && auths.length > 0) {
      setAuthId(auths[0].id);
    }
  }, [auths, authId]);

  // Reset arg values when method changes
  const selectedMethod = methods[methodKey] ?? null;
  useEffect(() => {
    if (!selectedMethod) return;
    const defaults: Record<string, string> = {};
    for (const [key, spec] of Object.entries(selectedMethod.args)) {
      defaults[key] = spec.default !== undefined ? String(spec.default) : '';
    }
    setArgValues(defaults);
  }, [selectedMethod]);

  const filteredAuths = useMemo(
    () => auths.filter((a) => a.site === site),
    [auths, site],
  );

  const setArg = useCallback((key: string, value: string) => {
    setArgValues((prev) => ({ ...prev, [key]: value }));
  }, []);

  const canExecute = site && authId !== null && methodKey;
  const resultCanUseJsonTree = isJsonTreeValue(result?.data);
  const resultTextValue = formatResultValue(result?.data);

  const handleExecute = async () => {
    if (!canExecute) return;
    setLoading(true);
    setResult(null);

    // Build args — skip blanks for optional params
    const args: Record<string, unknown> = {};
    if (selectedMethod) {
      for (const [key, spec] of Object.entries(selectedMethod.args)) {
        const raw = argValues[key] ?? '';
        if (raw === '' && !spec.required) continue;
        if (spec.type === 'integer') {
          args[key] = parseInt(raw, 10) || 0;
        } else if (spec.type === 'float') {
          args[key] = parseFloat(raw) || 0;
        } else {
          args[key] = raw;
        }
      }
    }

    try {
      const res = await executeApiMethod({
        site,
        auth_id: authId!,
        method: methodKey,
        args,
      });
      setResult(res);
    } catch (err: unknown) {
      setResult({
        success: false,
        method: methodKey,
        error: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="tools-panel">
      {/* Header */}
      <div className="tools-panel-head">
        <span className="tools-step">API</span>
        <div>
          <h2>API Requests</h2>
          <p>Execute API methods on an authenticated session and inspect the response.</p>
        </div>
      </div>

      {/* Form */}
      <div className="tools-form-grid">
        {/* Site */}
        <div className="tools-field">
          <span>Site</span>
          <select value={site} onChange={(e) => setSite(e.target.value)}>
            {SITES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        {/* Auth */}
        <div className="tools-field">
          <span>Auth</span>
          <select
            value={authId ?? ''}
            onChange={(e) => setAuthId(e.target.value ? Number(e.target.value) : null)}
          >
            {filteredAuths.length === 0 && <option value="">No auths available</option>}
            {filteredAuths.map((a) => (
              <option key={a.id} value={a.id}>
                {a.username ?? `User ${a.user_id}`} (ID {a.id})
              </option>
            ))}
          </select>
        </div>

        {/* Method */}
        <div className="tools-field tools-field-full">
          <span>Method</span>
          <select value={methodKey} onChange={(e) => setMethodKey(e.target.value)}>
            {Object.entries(methods).map(([key, spec]) => (
              <option key={key} value={key}>
                {key} — {spec.description}
              </option>
            ))}
          </select>
        </div>

        {/* Dynamic arguments */}
        {selectedMethod &&
          Object.entries(selectedMethod.args).map(([key, spec]) => (
            <div className="tools-field" key={key}>
              <span>
                {key}
                {spec.required && <span style={{ color: '#ef4444' }}> *</span>}
              </span>
              {spec.options ? (
                <select value={argValues[key] ?? ''} onChange={(e) => setArg(key, e.target.value)}>
                  {spec.options.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type={spec.type === 'integer' || spec.type === 'float' ? 'number' : 'text'}
                  placeholder={spec.description}
                  value={argValues[key] ?? ''}
                  onChange={(e) => setArg(key, e.target.value)}
                />
              )}
            </div>
          ))}
      </div>

      {/* Execute */}
      <div className="tools-actions">
        <button
          className="tools-btn tools-btn-primary"
          disabled={!canExecute || loading}
          onClick={handleExecute}
        >
          {loading ? 'Executing…' : 'Execute'}
        </button>
      </div>

      {/* Result */}
      {result && (
        <div style={{ marginTop: 16 }}>
          {result.success ? (
            <div className="tools-alert success" style={{ marginBottom: 8 }}>
              ✓ {result.method} completed successfully
            </div>
          ) : (
            <div className="tools-alert error" style={{ marginBottom: 8 }}>
              ✗ {result.method} failed: {result.error}
            </div>
          )}
          <div className="api-requests-result">
            {resultCanUseJsonTree ? (
              <JsonView
                value={result.data as Record<string, unknown> | unknown[]}
                style={githubDarkTheme}
                collapsed={2}
                displayDataTypes={false}
              />
            ) : (
              <pre
                style={{
                  margin: 0,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  fontFamily: 'var(--font-family-mono, monospace)',
                }}
              >
                {resultTextValue}
              </pre>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
