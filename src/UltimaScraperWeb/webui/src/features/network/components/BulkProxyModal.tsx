import { useEffect, useMemo, useState } from 'react';
import type { BulkProxyItem, BulkTestItem, BulkTestItemResult, NetworkProxy } from '../../../api/types/network';
import { formatProxyForText, parseBulkProxyText, type ParsedProxyLine } from '../lib/proxyParser';

interface BulkProxyModalProps {
  isOpen: boolean;
  existingGroups: string[];
  currentProxies?: NetworkProxy[];
  selectedGroupFilter?: string | null;
  isImporting: boolean;
  initialMode?: 'import' | 'edit';
  onClose: () => void;
  onImport: (proxies: BulkProxyItem[]) => void;
  onBulkSync?: (proxies: BulkProxyItem[], rawText?: string, targetGroup?: string | null) => void;
  onBulkTest: (items: BulkTestItem[]) => Promise<BulkTestItemResult[]>;
}

const EMPTY_PROXIES: NetworkProxy[] = [];

function getScopedProxies(proxies: NetworkProxy[], groupScope: string | null): NetworkProxy[] {
  if (!groupScope || groupScope === '__all__') {
    return proxies;
  }
  if (groupScope === '__ungrouped__') {
    return proxies.filter((p) => !p.group?.trim());
  }
  const normalized = groupScope.trim().toLowerCase();
  return proxies.filter((p) => (p.group || '').trim().toLowerCase() === normalized);
}

export function BulkProxyModal({
  isOpen,
  existingGroups,
  currentProxies = EMPTY_PROXIES,
  selectedGroupFilter,
  isImporting,
  initialMode = 'import',
  onClose,
  onImport,
  onBulkSync,
  onBulkTest,
}: BulkProxyModalProps) {
  const [mode, setMode] = useState<'import' | 'edit'>(initialMode);
  const [rawText, setRawText] = useState('');
  const [defaultGroup, setDefaultGroup] = useState('');
  const [maxConnections, setMaxConnections] = useState<number>(-1);
  const [testResults, setTestResults] = useState<
    Record<string, { testing?: boolean; success?: boolean; message?: string; latency_ms?: number | null }>
  >({});
  const [isTestingAll, setIsTestingAll] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [filterTab, setFilterTab] = useState<'all' | 'active' | 'failed' | 'untested'>('all');

  const activeScopeGroup = useMemo(() => {
    const trimmed = defaultGroup.trim();
    if (trimmed) return trimmed;
    if (selectedGroupFilter === '__ungrouped__') return '__ungrouped__';
    return null;
  }, [defaultGroup, selectedGroupFilter]);

  const scopedCurrentProxies = useMemo(
    () => getScopedProxies(currentProxies, activeScopeGroup),
    [currentProxies, activeScopeGroup],
  );

  useEffect(() => {
    if (isOpen) {
      setMode(initialMode);
      const initialGroup =
        selectedGroupFilter && selectedGroupFilter !== '__ungrouped__'
          ? selectedGroupFilter
          : '';
      setDefaultGroup(initialGroup);

      const initialScope =
        initialGroup ||
        (selectedGroupFilter === '__ungrouped__' ? '__ungrouped__' : null);
      const initialScoped = getScopedProxies(currentProxies, initialScope);

      if (initialMode === 'edit' && initialScoped.length > 0) {
        setRawText(initialScoped.map(formatProxyForText).join('\n'));
      } else {
        setRawText('');
      }
      setSelectedIds(new Set());
      setTestResults({});
      setFilterTab('all');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, initialMode]);

  const handleLoadCurrentProxies = () => {
    if (scopedCurrentProxies.length === 0) return;
    setRawText(scopedCurrentProxies.map(formatProxyForText).join('\n'));
  };

  const parsedLines = useMemo(
    () => parseBulkProxyText(rawText, defaultGroup.trim() || null),
    [rawText, defaultGroup],
  );

  const validLines = useMemo(
    () => parsedLines.filter((line) => !line.error),
    [parsedLines],
  );

  const currentUrlMap = useMemo(() => {
    const map = new Map<string, NetworkProxy>();
    for (const p of currentProxies) {
      map.set(p.url, p);
    }
    return map;
  }, [currentProxies]);

  const scopedUrlMap = useMemo(() => {
    const map = new Map<string, NetworkProxy>();
    for (const p of scopedCurrentProxies) {
      map.set(p.url, p);
    }
    return map;
  }, [scopedCurrentProxies]);

  const parsedUrlSet = useMemo(
    () => new Set(validLines.map((l) => l.url)),
    [validLines],
  );

  const keptCount = useMemo(
    () => validLines.filter((l) => scopedUrlMap.has(l.url)).length,
    [validLines, scopedUrlMap],
  );

  const addedCount = useMemo(
    () => validLines.filter((l) => !currentUrlMap.has(l.url)).length,
    [validLines, currentUrlMap],
  );

  const omittedProxies = useMemo(
    () => scopedCurrentProxies.filter((p) => !parsedUrlSet.has(p.url)),
    [scopedCurrentProxies, parsedUrlSet],
  );

  const deletedCount = omittedProxies.length;

  const activeCount = useMemo(
    () => validLines.filter((l) => testResults[l.url]?.success === true).length,
    [validLines, testResults],
  );

  const failedCount = useMemo(
    () => validLines.filter((l) => testResults[l.url] && testResults[l.url].success === false).length,
    [validLines, testResults],
  );

  const untestedCount = validLines.length - activeCount - failedCount;

  const displayedLines = useMemo(() => {
    if (filterTab === 'all') return parsedLines;
    if (filterTab === 'active') return validLines.filter((l) => testResults[l.url]?.success === true);
    if (filterTab === 'failed') return validLines.filter((l) => testResults[l.url] && testResults[l.url].success === false);
    if (filterTab === 'untested') return validLines.filter((l) => !testResults[l.url]);
    return parsedLines;
  }, [filterTab, parsedLines, validLines, testResults]);

  if (!isOpen) return null;

  const handleToggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleSelectAllDisplayed = () => {
    const validDisplayed = displayedLines.filter((l) => !l.error);
    const allSelected = validDisplayed.every((l) => selectedIds.has(l.id));
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allSelected) {
        for (const l of validDisplayed) {
          next.delete(l.id);
        }
      } else {
        for (const l of validDisplayed) {
          next.add(l.id);
        }
      }
      return next;
    });
  };

  const handleTestAll = async () => {
    if (validLines.length === 0 || isTestingAll) return;

    setIsTestingAll(true);
    setTestResults((prev) => {
      const next = { ...prev };
      for (const line of validLines) {
        next[line.url] = { testing: true };
      }
      return next;
    });

    try {
      const testItems: BulkTestItem[] = validLines.map((line) => ({
        url: line.url,
        username: line.username,
        password: line.password,
      }));

      const results = await onBulkTest(testItems);
      setTestResults((prev) => {
        const next = { ...prev };
        for (const res of results) {
          next[res.url] = {
            testing: false,
            success: res.success,
            message: res.message,
            latency_ms: res.latency_ms,
          };
        }
        return next;
      });
    } catch {
      setTestResults((prev) => {
        const next = { ...prev };
        for (const line of validLines) {
          if (next[line.url]?.testing) {
            next[line.url] = { testing: false, success: false, message: 'Test failed' };
          }
        }
        return next;
      });
    } finally {
      setIsTestingAll(false);
    }
  };

  const handleImportSelected = () => {
    const toImport = validLines.filter((l) => selectedIds.has(l.id));
    if (toImport.length === 0) return;
    onImport(
      toImport.map((l) => ({
        url: l.url,
        username: l.username,
        password: l.password,
        group: l.group,
        max_connections: maxConnections,
        enabled: true,
      })),
    );
  };

  const handleImportActive = () => {
    const toImport = validLines.filter((l) => testResults[l.url]?.success === true);
    if (toImport.length === 0) return;
    onImport(
      toImport.map((l) => ({
        url: l.url,
        username: l.username,
        password: l.password,
        group: l.group,
        max_connections: maxConnections,
        enabled: true,
      })),
    );
  };

  const handleImportAll = () => {
    if (validLines.length === 0) return;
    onImport(
      validLines.map((l) => ({
        url: l.url,
        username: l.username,
        password: l.password,
        group: l.group,
        max_connections: maxConnections,
        enabled: true,
      })),
    );
  };

  const handleApplyBulkEdit = () => {
    if (onBulkSync) {
      const toSync: BulkProxyItem[] = validLines.map((l) => ({
        url: l.url,
        username: l.username,
        password: l.password,
        group: l.group,
        max_connections: maxConnections,
        enabled: true,
      }));
      onBulkSync(toSync, rawText, activeScopeGroup);
    } else {
      handleImportAll();
    }
  };

  return (
    <div className="modal-overlay bulk-proxy-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="bulk-proxy-modal-title">
      <div className="modal-content modal-content--wide wy-dialog wy-bulk-modal">
        <div className="modal-header">
          <div>
            <span className="network-kicker">
              {mode === 'edit'
                ? 'MANAGEMENT PROTOCOL // BULK GATEWAY SYNCHRONIZATION'
                : 'INGESTION PROTOCOL // BULK GATEWAY UPLINK'}
            </span>
            <h2 id="bulk-proxy-modal-title">
              {mode === 'edit' ? 'Bulk Edit Proxies' : 'Bulk Add Proxies'}
            </h2>
            <p className="network-muted" style={{ margin: '4px 0 0', fontSize: '0.8rem' }}>
              {mode === 'edit'
                ? 'Update your proxy pool: existing routes in the list are kept as-is, new routes are added, and omitted routes are deleted.'
                : 'Import multiple proxies, assign them to a group, and test connectivity.'}
            </p>
          </div>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close modal">
            ×
          </button>
        </div>

        <div className="bulk-proxy-modal__mode-toggle">
          <button
            type="button"
            className={`network-filter-tab ${mode === 'edit' ? 'is-active' : ''}`}
            onClick={() => {
              setMode('edit');
              if (!rawText && scopedCurrentProxies.length > 0) {
                setRawText(scopedCurrentProxies.map(formatProxyForText).join('\n'));
              }
            }}
          >
            BULK EDIT (SYNC LIST)
          </button>
          <button
            type="button"
            className={`network-filter-tab ${mode === 'import' ? 'is-active' : ''}`}
            onClick={() => setMode('import')}
          >
            BULK IMPORT (APPEND)
          </button>
        </div>

        <div className="modal-body bulk-proxy-modal__body">
          {mode === 'edit' && (
            <div className="bulk-proxy-diff-banner">
              <span className="bulk-proxy-diff-banner__title">
                SYNC PLAN {activeScopeGroup && activeScopeGroup !== '__all__' ? `[${activeScopeGroup === '__ungrouped__' ? 'UNGROUPED' : activeScopeGroup.toUpperCase()}] //` : '//'}
              </span>
              <span className="bulk-diff-badge bulk-diff-badge--keep">
                ✓ KEEP {keptCount} EXISTING
              </span>
              <span className="bulk-diff-badge bulk-diff-badge--add">
                + ADD {addedCount} NEW
              </span>
              <span className={`bulk-diff-badge ${deletedCount > 0 ? 'bulk-diff-badge--delete' : 'bulk-diff-badge--neutral'}`}>
                − DELETE {deletedCount} OMITTED
              </span>
            </div>
          )}

          <div className="bulk-proxy-modal__config-grid">
            <div className="form-group">
              <label htmlFor="bulk-group-name">Assign to Group Name</label>
              <input
                id="bulk-group-name"
                type="text"
                value={defaultGroup}
                onChange={(e) => setDefaultGroup(e.target.value)}
                placeholder="e.g. Datacenter US, Residential-UK"
                list="bulk-existing-groups"
              />
              <datalist id="bulk-existing-groups">
                {existingGroups.map((g) => (
                  <option key={g} value={g} />
                ))}
              </datalist>
              <span className="form-hint">
                {mode === 'edit'
                  ? 'Scopes sync and deletion to this group name (proxies in other groups are never deleted)'
                  : 'Applies to all proxies without an explicit group tag'}
              </span>
            </div>

            <div className="form-group">
              <label htmlFor="bulk-max-connections">Max Connections</label>
              <input
                id="bulk-max-connections"
                type="number"
                value={maxConnections}
                onChange={(e) => setMaxConnections(Number.parseInt(e.target.value, 10) || -1)}
                placeholder="-1 for unlimited"
              />
              <span className="form-hint">Use -1 for unlimited connection pool</span>
            </div>
          </div>

          <div className="form-group">
            <div className="bulk-proxy-modal__textarea-header">
              <label htmlFor="bulk-proxies-input">
                {mode === 'edit' ? 'Proxy Pool List (one per line)' : 'Paste Proxies (one per line)'}
              </label>
              {mode === 'edit' && scopedCurrentProxies.length > 0 && (
                <div className="bulk-proxy-modal__textarea-actions">
                  <button
                    type="button"
                    className="network-button network-button--ghost network-button--xs"
                    onClick={handleLoadCurrentProxies}
                  >
                    {activeScopeGroup && activeScopeGroup !== '__all__'
                      ? `Reload ${activeScopeGroup === '__ungrouped__' ? 'Ungrouped' : activeScopeGroup} (${scopedCurrentProxies.length})`
                      : `Reload Current (${currentProxies.length})`}
                  </button>
                  {rawText && (
                    <button
                      type="button"
                      className="network-button network-button--ghost network-button--xs"
                      onClick={() => setRawText('')}
                    >
                      Clear
                    </button>
                  )}
                </div>
              )}
            </div>
            <textarea
              id="bulk-proxies-input"
              rows={5}
              className="bulk-proxy-modal__textarea"
              value={rawText}
              onChange={(e) => setRawText(e.target.value)}
              placeholder={`http://anon:anon@203.0.113.10:6754\nhttp://anon:anon@203.0.113.20:6014\nhttp://anon:anon@203.0.113.30:6462\nsocks5://usr:pass@host:port # Optional Group Name\nhost:port:user:pass`}
            />
          </div>

          {mode === 'edit' && deletedCount > 0 && (
            <div className="bulk-proxy-deleted-preview">
              <div className="bulk-proxy-deleted-preview__header">
                <span className="network-status-dot network-status-dot--disabled" />
                <span>
                  <strong>{deletedCount} Omitted {deletedCount === 1 ? 'Route' : 'Routes'}</strong>
                  {activeScopeGroup && activeScopeGroup !== '__all__'
                    ? ` in ${activeScopeGroup === '__ungrouped__' ? 'ungrouped scope' : `group "${activeScopeGroup}"`}`
                    : ''}{' '}
                  will be deleted from proxy pool:
                </span>
              </div>
              <div className="bulk-proxy-deleted-preview__chips">
                {omittedProxies.map((p) => (
                  <code key={p.url} className="bulk-proxy-deleted-chip">
                    {p.url}
                  </code>
                ))}
              </div>
            </div>
          )}

          {parsedLines.length > 0 ? (
            <div className="bulk-proxy-modal__preview-section">
              <div className="bulk-proxy-modal__toolbar">
                <div className="bulk-proxy-modal__tabs">
                  <button
                    type="button"
                    className={`network-filter-tab ${filterTab === 'all' ? 'is-active' : ''}`}
                    onClick={() => setFilterTab('all')}
                  >
                    ALL <span className="network-filter-tab__count">{parsedLines.length}</span>
                  </button>
                  <button
                    type="button"
                    className={`network-filter-tab ${filterTab === 'active' ? 'is-active' : ''}`}
                    onClick={() => setFilterTab('active')}
                  >
                    ACTIVE <span className="network-filter-tab__count">{activeCount}</span>
                  </button>
                  <button
                    type="button"
                    className={`network-filter-tab ${filterTab === 'failed' ? 'is-active' : ''}`}
                    onClick={() => setFilterTab('failed')}
                  >
                    FAILED <span className="network-filter-tab__count">{failedCount}</span>
                  </button>
                  <button
                    type="button"
                    className={`network-filter-tab ${filterTab === 'untested' ? 'is-active' : ''}`}
                    onClick={() => setFilterTab('untested')}
                  >
                    UNTESTED <span className="network-filter-tab__count">{untestedCount}</span>
                  </button>
                </div>

                <div className="bulk-proxy-modal__actions">
                  <button
                    type="button"
                    className="network-button network-button--primary"
                    onClick={handleTestAll}
                    disabled={isTestingAll || validLines.length === 0}
                  >
                    {isTestingAll ? 'Testing active status…' : `Test All (${validLines.length})`}
                  </button>
                  <button
                    type="button"
                    className="network-button network-button--ghost"
                    onClick={handleSelectAllDisplayed}
                  >
                    Toggle select all
                  </button>
                </div>
              </div>

              <div className="bulk-proxy-modal__table-wrap">
                <table className="bulk-proxy-modal__table">
                  <thead>
                    <tr>
                      <th style={{ width: '36px' }}>
                        <span className="visually-hidden">Select</span>
                      </th>
                      {mode === 'edit' ? <th>ACTION // PLAN</th> : null}
                      <th>TARGET ENDPOINT</th>
                      <th>CREDENTIALS</th>
                      <th>ROUTING GROUP</th>
                      <th>STATUS // REACHABILITY</th>
                    </tr>
                  </thead>
                  <tbody>
                    {displayedLines.map((line: ParsedProxyLine) => {
                      const isSelected = selectedIds.has(line.id);
                      const testInfo = testResults[line.url];
                      const isExisting = currentUrlMap.has(line.url);

                      return (
                        <tr key={line.id} className={line.error ? 'is-error-row' : ''}>
                          <td>
                            {!line.error ? (
                              <input
                                type="checkbox"
                                checked={isSelected}
                                onChange={() => handleToggleSelect(line.id)}
                                aria-label={`Select ${line.url}`}
                              />
                            ) : null}
                          </td>
                          {mode === 'edit' ? (
                            <td>
                              {line.error ? (
                                <span className="bulk-diff-badge bulk-diff-badge--error">INVALID</span>
                              ) : isExisting ? (
                                <span className="bulk-diff-badge bulk-diff-badge--keep">KEEP AS-IS</span>
                              ) : (
                                <span className="bulk-diff-badge bulk-diff-badge--add">+ ADD NEW</span>
                              )}
                            </td>
                          ) : null}
                          <td className="bulk-proxy-modal__cell-url">
                            <code>{line.url}</code>
                            {line.error ? (
                              <div className="bulk-proxy-modal__error-hint">{line.error}</div>
                            ) : null}
                          </td>
                          <td>
                            {line.username ? (
                              <span className="bulk-proxy-modal__auth-badge">
                                {line.username}:{line.password ? '••••' : ''}
                              </span>
                            ) : (
                              <span className="network-muted">NONE</span>
                            )}
                          </td>
                          <td>
                            {line.group ? (
                              <span className="network-proxy__group-badge">
                                <span className="network-proxy__group-prefix">GRP // </span>
                                {line.group}
                              </span>
                            ) : (
                              <span className="network-muted">—</span>
                            )}
                          </td>
                          <td>
                            {testInfo?.testing ? (
                              <span className="bulk-status-badge bulk-status-badge--testing">Testing…</span>
                            ) : testInfo?.success === true ? (
                              <span className="bulk-status-badge bulk-status-badge--success">
                                ✓ Active {testInfo.latency_ms !== null ? `(${testInfo.latency_ms} ms)` : ''}
                              </span>
                            ) : testInfo?.success === false ? (
                              <span className="bulk-status-badge bulk-status-badge--failure" title={testInfo.message}>
                                ✗ Offline: {testInfo.message || 'Failed'}
                              </span>
                            ) : (
                              <span className="bulk-status-badge bulk-status-badge--idle">Untested</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
        </div>

        <div className="modal-footer bulk-proxy-modal__footer">
          <button type="button" className="btn-cancel network-button" onClick={onClose} disabled={isImporting}>
            Cancel
          </button>

          {mode === 'edit' ? (
            <button
              type="button"
              className="btn-save network-button network-button--primary"
              onClick={handleApplyBulkEdit}
              disabled={isImporting || (validLines.length === 0 && deletedCount === 0)}
            >
              {isImporting
                ? 'Applying…'
                : `Apply Changes (Add ${addedCount}, Keep ${keptCount}${deletedCount > 0 ? `, Delete ${deletedCount}` : ''})`}
            </button>
          ) : (
            <>
              {activeCount > 0 ? (
                <button
                  type="button"
                  className="network-button network-button--secondary"
                  onClick={handleImportActive}
                  disabled={isImporting}
                >
                  {isImporting ? 'Importing…' : `Import Active Only (${activeCount})`}
                </button>
              ) : null}

              {selectedIds.size > 0 ? (
                <button
                  type="button"
                  className="network-button"
                  onClick={handleImportSelected}
                  disabled={isImporting}
                >
                  {isImporting ? 'Importing…' : `Import Selected (${selectedIds.size})`}
                </button>
              ) : null}

              <button
                type="button"
                className="btn-save network-button network-button--primary"
                onClick={handleImportAll}
                disabled={validLines.length === 0 || isImporting}
              >
                {isImporting ? 'Importing…' : `Import All (${validLines.length})`}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
