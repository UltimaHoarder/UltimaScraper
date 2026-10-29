import { useMemo, useState } from 'react';
import { ProxyCard } from './ProxyCard';
import { OperationsState } from '../../../shared/ui/operations/OperationsChrome';
import type { AuthAccount, NetworkProxy } from '../../../api/types/network';

interface ProxyListSectionProps {
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  proxies: NetworkProxy[];
  filteredProxies: NetworkProxy[];
  totalAssigned: number;
  enabledCount: number;
  disabledCount: number;
  unassignedCount: number;
  expandedProxyId: string | null;
  proxyAuths?: AuthAccount[];
  isProxyAuthsLoading: boolean;
  analyzerLoading: Record<string, boolean>;
  analyzerErrors: Record<string, string | null>;
  proxyStatePending: Record<string, boolean>;
  proxyStateErrors: Record<string, string | null>;
  onEditProxy: (proxy: NetworkProxy) => void;
  onToggleExpandedProxy: (proxyId: string) => void;
  onOpenAnalyzer: (proxy: NetworkProxy) => void;
  onDeleteProxy: (proxy: NetworkProxy) => void;
  onRemoveAuth: (authId: number) => void;
  onToggleProxyEnabled: (proxy: NetworkProxy) => void;
  existingGroups?: string[];
  selectedGroupFilter?: string | null;
  onSelectGroupFilter?: (group: string | null) => void;
  selectedProxyIds?: Set<string>;
  onToggleSelectProxy?: (proxy: NetworkProxy) => void;
  onSelectAllProxies?: () => void;
  onClearSelectedProxies?: () => void;
  onAssignGroupSelected?: (group: string | null) => void;
  onAnalyzeGroupRepresentative?: (group: string) => void;
  onTestReachability?: (proxy: NetworkProxy) => Promise<{ success: boolean; latency_ms?: number | null; message: string }>;
  onToggleSelectGroup?: (groupProxies: NetworkProxy[]) => void;
  onBulkEnableSelected?: (urls: string[]) => void;
  onBulkDisableSelected?: (urls: string[]) => void;
  onBulkEditSelected?: (urls: string[]) => void;
  onBulkDeleteSelected?: (urls: string[]) => void;
  onBulkTestSelected?: (urls: string[]) => void;
  isBulkTesting?: boolean;
  proxyQuickTestResults?: Record<string, { testing?: boolean; success?: boolean; latency_ms?: number | null; message: string }>;
  /** Each group's own guest lookup timeout (seconds); null uses the network default. */
  groupLookupTimeouts?: Record<string, number | null>;
  onSaveGroupLookupTimeout?: (group: string, timeout: number | null) => Promise<unknown>;
  savingGroupLookupTimeout?: string | null;
}

export function ProxyListSection({
  searchQuery,
  onSearchQueryChange,
  proxies,
  filteredProxies,
  totalAssigned,
  enabledCount,
  disabledCount,
  unassignedCount,
  expandedProxyId,
  proxyAuths,
  isProxyAuthsLoading,
  analyzerLoading,
  analyzerErrors,
  proxyStatePending,
  proxyStateErrors,
  onEditProxy,
  onToggleExpandedProxy,
  onOpenAnalyzer,
  onDeleteProxy,
  onRemoveAuth,
  onToggleProxyEnabled,
  existingGroups = [],
  selectedGroupFilter = null,
  onSelectGroupFilter,
  selectedProxyIds = new Set(),
  onToggleSelectProxy,
  onSelectAllProxies,
  onClearSelectedProxies,
  onAssignGroupSelected,
  onAnalyzeGroupRepresentative,
  onTestReachability,
  onToggleSelectGroup,
  onBulkEnableSelected,
  onBulkDisableSelected,
  onBulkEditSelected,
  onBulkDeleteSelected,
  onBulkTestSelected,
  isBulkTesting = false,
  proxyQuickTestResults,
  groupLookupTimeouts = {},
  onSaveGroupLookupTimeout,
  savingGroupLookupTimeout = null,
}: ProxyListSectionProps) {
  const [bulkGroupInput, setBulkGroupInput] = useState('');
  const [timeoutEditor, setTimeoutEditor] = useState<{
    group: string;
    value: string;
    error?: string;
  } | null>(null);

  const saveGroupTimeout = async (group: string, raw: string | null) => {
    if (!onSaveGroupLookupTimeout) return;
    const trimmed = raw?.trim() ?? '';
    const timeout = trimmed === '' ? null : Number.parseFloat(trimmed);
    if (timeout !== null && (!Number.isFinite(timeout) || timeout < 0.5)) {
      setTimeoutEditor({ group, value: raw ?? '', error: 'Enter at least 0.5 seconds, or clear it.' });
      return;
    }
    try {
      await onSaveGroupLookupTimeout(group, timeout);
      setTimeoutEditor(null);
    } catch (error) {
      setTimeoutEditor({
        group,
        value: raw ?? '',
        error: error instanceof Error ? error.message : 'Could not save the group timeout.',
      });
    }
  };
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set());

  const toggleGroupCollapse = (groupKey: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupKey)) {
        next.delete(groupKey);
      } else {
        next.add(groupKey);
      }
      return next;
    });
  };

  const hasGroups = existingGroups.length > 0;
  const ungroupedCount = proxies.filter((p) => !p.group?.trim()).length;
  const hasSelection = selectedProxyIds.size > 0;
  const allFilteredSelected = filteredProxies.length > 0 && filteredProxies.every((p) => selectedProxyIds.has(p.url));
  const groupedProxySections = useMemo(() => {
    const sections = new Map<string, NetworkProxy[]>();

    for (const proxy of filteredProxies) {
      const groupKey = proxy.group?.trim() || '__ungrouped__';
      const groupProxies = sections.get(groupKey) || [];
      groupProxies.push(proxy);
      sections.set(groupKey, groupProxies);
    }

    return Array.from(sections, ([groupKey, groupProxies]) => ({
      group: groupKey === '__ungrouped__' ? null : groupKey,
      proxies: groupProxies,
    }));
  }, [filteredProxies]);

  const handleApplyGroup = () => {
    const group = bulkGroupInput.trim();
    if (!onAssignGroupSelected || !hasSelection || !group) return;
    onAssignGroupSelected(group);
    setBulkGroupInput('');
  };

  return (
    <section className="network-inventory" aria-labelledby="proxy-inventory-title">
      <div className="network-section-head">
        <div>
          <span className="network-kicker">ROUTING VECTOR POOL // USV-02</span>
          <h2 id="proxy-inventory-title">Proxy Gateway Inventory</h2>
          <p>{totalAssigned} account assignments across {proxies.length} configured egress routes.</p>
        </div>
        <label className="network-search" htmlFor="proxy-search">
          <span aria-hidden="true">⌕</span>
          <input
            id="proxy-search"
            value={searchQuery}
            onChange={(event) => onSearchQueryChange(event.target.value)}
            placeholder="SEARCH ROUTE / REGION / IP / PROVIDER…"
          />
          {searchQuery ? (
            <button type="button" onClick={() => onSearchQueryChange('')} aria-label="Clear search">×</button>
          ) : null}
        </label>
      </div>

      <div className="network-telemetry-array" aria-label="Proxy telemetry metrics">
        <div className="network-telemetry-cell">
          <span className="network-telemetry-cell__value">{proxies.length}</span>
          <span className="network-telemetry-cell__label">CONFIGURED</span>
          <span className="network-telemetry-cell__kicker">{filteredProxies.length} SHOWN</span>
        </div>
        <div className="network-telemetry-cell">
          <span className="network-telemetry-cell__value network-telemetry-cell__value--cyan">{enabledCount}</span>
          <span className="network-telemetry-cell__label">ACTIVE RELAYS</span>
          <span className="network-telemetry-cell__kicker">NOMINAL</span>
        </div>
        <div className="network-telemetry-cell">
          <span className="network-telemetry-cell__value network-telemetry-cell__value--yellow">{enabledCount - unassignedCount}</span>
          <span className="network-telemetry-cell__label">COMMITTED</span>
          <span className="network-telemetry-cell__kicker">{totalAssigned} ASSIGNED</span>
        </div>
        <div className={`network-telemetry-cell ${unassignedCount > 0 ? 'is-warning' : ''}`}>
          <span className="network-telemetry-cell__value">{unassignedCount}</span>
          <span className="network-telemetry-cell__label">IDLE POOL</span>
          <span className="network-telemetry-cell__kicker">{unassignedCount > 0 ? 'CAPACITY UNUSED' : 'BALANCED'}</span>
        </div>
        <div className={`network-telemetry-cell ${disabledCount > 0 ? 'is-alert' : ''}`}>
          <span className="network-telemetry-cell__value">{disabledCount}</span>
          <span className="network-telemetry-cell__label">SUSPENDED</span>
          <span className="network-telemetry-cell__kicker">{disabledCount > 0 ? 'OFFLINE' : 'NONE'}</span>
        </div>
      </div>

      {hasGroups ? (
        <div className="network-inventory__toolbar">
          <div className="network-inventory__group-tabs">
            <button
              type="button"
              className={`network-filter-tab ${selectedGroupFilter === null ? 'is-active' : ''}`}
              onClick={() => onSelectGroupFilter?.(null)}
            >
              ALL <span className="network-filter-tab__count">{proxies.length}</span>
            </button>
            {existingGroups.map((groupName) => {
              const count = proxies.filter((p) => p.group?.trim() === groupName).length;
              return (
                <button
                  key={groupName}
                  type="button"
                  className={`network-filter-tab ${selectedGroupFilter === groupName ? 'is-active' : ''}`}
                  onClick={() => onSelectGroupFilter?.(groupName)}
                >
                  {groupName.toUpperCase()} <span className="network-filter-tab__count">{count}</span>
                </button>
              );
            })}
            {ungroupedCount > 0 ? (
              <button
                type="button"
                className={`network-filter-tab ${selectedGroupFilter === '__ungrouped__' ? 'is-active' : ''}`}
                onClick={() => onSelectGroupFilter?.('__ungrouped__')}
              >
                UNGROUPED <span className="network-filter-tab__count">{ungroupedCount}</span>
              </button>
            ) : null}
          </div>

          {selectedGroupFilter && selectedGroupFilter !== '__ungrouped__' && onAnalyzeGroupRepresentative ? (
            <button
              type="button"
              className="network-button network-button--secondary network-group-analyze-btn"
              onClick={() => onAnalyzeGroupRepresentative(selectedGroupFilter)}
              title={`Analyze representative proxy from ${selectedGroupFilter}`}
            >
              ⚡ PROFILE GROUP ({selectedGroupFilter.toUpperCase()})
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="network-selection-bar" role="region" aria-label="Proxy bulk actions">
        <div className="network-selection-bar__left">
          <input
            type="checkbox"
            ref={(el) => {
              if (el) {
                el.indeterminate = hasSelection && !allFilteredSelected;
              }
            }}
            checked={allFilteredSelected}
            onChange={() => onSelectAllProxies?.()}
            aria-label="Select all filtered proxies"
          />
          <span className="network-selection-bar__count">
            {hasSelection ? (
              <><strong>{selectedProxyIds.size}</strong> ROUTE{selectedProxyIds.size === 1 ? '' : 'S'} STAGED</>
            ) : (
              'SELECT ROUTES FOR BULK ACTIONS'
            )}
          </span>
        </div>
        <div className="network-selection-bar__actions">
          {hasSelection ? (
            <div className="network-selection-bar__buttons">
              {onBulkTestSelected ? (
                <button
                  type="button"
                  className="network-button network-button--secondary"
                  onClick={() => onBulkTestSelected(Array.from(selectedProxyIds))}
                  disabled={isBulkTesting}
                  title="Test active reachability of selected proxies"
                >
                  {isBulkTesting ? 'TESTING…' : `⚡ TEST (${selectedProxyIds.size})`}
                </button>
              ) : null}
              {onBulkEnableSelected ? (
                <button
                  type="button"
                  className="network-button network-button--ghost"
                  onClick={() => onBulkEnableSelected(Array.from(selectedProxyIds))}
                  title="Enable selected proxies"
                >
                  ENABLE ({selectedProxyIds.size})
                </button>
              ) : null}
              {onBulkDisableSelected ? (
                <button
                  type="button"
                  className="network-button network-button--ghost"
                  onClick={() => onBulkDisableSelected(Array.from(selectedProxyIds))}
                  title="Disable selected proxies"
                >
                  DISABLE ({selectedProxyIds.size})
                </button>
              ) : null}
              {onBulkEditSelected ? (
                <button
                  type="button"
                  className="network-button network-button--secondary"
                  onClick={() => onBulkEditSelected(Array.from(selectedProxyIds))}
                  title="Edit connection settings for selected proxies"
                >
                  EDIT CONNECTIONS ({selectedProxyIds.size})
                </button>
              ) : null}
              {onBulkDeleteSelected ? (
                <button
                  type="button"
                  className="network-button network-button--ghost network-button--danger"
                  onClick={() => onBulkDeleteSelected(Array.from(selectedProxyIds))}
                  title="Revoke selected proxies"
                >
                  REVOKE ({selectedProxyIds.size})
                </button>
              ) : null}
            </div>
          ) : null}
          <div className="network-selection-bar__group-form">
            <input
              type="text"
              list="existing-groups-datalist"
              placeholder="ASSIGN GROUP NAME…"
              value={bulkGroupInput}
              onChange={(e) => setBulkGroupInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleApplyGroup();
                }
              }}
              className="network-selection-bar__input"
            />
            <datalist id="existing-groups-datalist">
              {existingGroups.map((g) => (
                <option key={g} value={g} />
              ))}
            </datalist>
            <button
              type="button"
              className="network-button network-button--primary"
              onClick={handleApplyGroup}
              disabled={!hasSelection || !bulkGroupInput.trim()}
            >
              ASSIGN GROUP
            </button>
            {hasSelection && bulkGroupInput.trim() === '' ? (
              <button
                type="button"
                className="network-button network-button--ghost"
                onClick={() => onAssignGroupSelected?.(null)}
                title="Remove group from selected proxies"
              >
                CLEAR GROUP
              </button>
            ) : null}
          </div>
          {hasSelection ? (
            <button
              type="button"
              className="network-button network-button--ghost"
              onClick={() => onClearSelectedProxies?.()}
            >
              DESELECT ALL
            </button>
          ) : null}
        </div>
      </div>

      {hasSelection ? (
        <div
          className="selection-bar-floating"
          role="toolbar"
          aria-label="Floating selection actions"
        >
          <div className="selection-info">
            <span className="network-selection-bar__count selection-count">
              <strong>{selectedProxyIds.size}</strong> ROUTE{selectedProxyIds.size === 1 ? '' : 'S'} STAGED
            </span>
            {!allFilteredSelected && onSelectAllProxies ? (
              <button
                type="button"
                className="network-button network-button--ghost"
                onClick={() => onSelectAllProxies()}
              >
                SELECT ALL ({filteredProxies.length})
              </button>
            ) : null}
            {onClearSelectedProxies ? (
              <button
                type="button"
                className="network-button network-button--ghost"
                onClick={() => onClearSelectedProxies()}
              >
                DESELECT ALL
              </button>
            ) : null}
          </div>
          <div className="selection-bar-floating__divider" />
          <div className="selection-bar-actions">
            {onBulkTestSelected ? (
              <button
                type="button"
                className="network-button network-button--secondary"
                onClick={() => onBulkTestSelected(Array.from(selectedProxyIds))}
                disabled={isBulkTesting}
                title="Test active reachability of selected proxies"
              >
                {isBulkTesting ? 'TESTING…' : `⚡ TEST (${selectedProxyIds.size})`}
              </button>
            ) : null}
            {onBulkEnableSelected ? (
              <button
                type="button"
                className="network-button network-button--ghost"
                onClick={() => onBulkEnableSelected(Array.from(selectedProxyIds))}
                title="Enable selected proxies"
              >
                ENABLE ({selectedProxyIds.size})
              </button>
            ) : null}
            {onBulkDisableSelected ? (
              <button
                type="button"
                className="network-button network-button--ghost"
                onClick={() => onBulkDisableSelected(Array.from(selectedProxyIds))}
                title="Disable selected proxies"
              >
                DISABLE ({selectedProxyIds.size})
              </button>
            ) : null}
            {onBulkEditSelected ? (
              <button
                type="button"
                className="network-button network-button--secondary"
                onClick={() => onBulkEditSelected(Array.from(selectedProxyIds))}
                title="Edit connection settings for selected proxies"
              >
                EDIT CONNECTIONS ({selectedProxyIds.size})
              </button>
            ) : null}
            {onBulkDeleteSelected ? (
              <button
                type="button"
                className="network-button network-button--ghost network-button--danger"
                onClick={() => onBulkDeleteSelected(Array.from(selectedProxyIds))}
                title="Revoke selected proxies"
              >
                REVOKE ({selectedProxyIds.size})
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="network-inventory__meta" aria-label="Proxy pool summary">
        <span><strong>{filteredProxies.length}</strong> shown</span>
        <span><strong>{enabledCount}</strong> enabled</span>
        <span><strong>{enabledCount - unassignedCount}</strong> in use</span>
        <span className={unassignedCount > 0 ? 'is-warning' : ''}>
          <strong>{unassignedCount}</strong> idle
        </span>
        <span className={disabledCount > 0 ? 'is-warning' : ''}>
          <strong>{disabledCount}</strong> disabled
        </span>
      </div>

      {filteredProxies.length === 0 ? (
        <OperationsState
          title={proxies.length === 0 ? 'No proxies configured' : 'No routes match this search'}
          description={
            proxies.length === 0
              ? 'Add your first proxy to create a regional fallback route.'
              : 'Try a URL, city, country, or network provider.'
          }
        />
      ) : (
        <div className="network-proxy-list">
          {groupedProxySections.map(({ group, proxies: groupProxies }, groupIndex) => {
            const groupKey = group || '__ungrouped__';
            const isCollapsed = collapsedGroups.has(groupKey);
            const allGroupSelected = groupProxies.length > 0 && groupProxies.every((p) => selectedProxyIds.has(p.url));
            const someGroupSelected = groupProxies.some((p) => selectedProxyIds.has(p.url));
            const isGroupIndeterminate = someGroupSelected && !allGroupSelected;

            return (
              <section
                key={groupKey}
                className={`network-proxy-group ${isCollapsed ? 'is-collapsed' : ''}`}
                aria-labelledby={hasGroups ? `proxy-group-${groupIndex}` : undefined}
              >
                {hasGroups ? (
                  <div
                    className="network-proxy-group__header"
                    role="button"
                    tabIndex={0}
                    aria-expanded={!isCollapsed}
                    aria-label={`Toggle routing group ${group || 'Ungrouped routes'}`}
                    onClick={() => toggleGroupCollapse(groupKey)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        toggleGroupCollapse(groupKey);
                      }
                    }}
                  >
                    <div className="network-proxy-group__header-left">
                      {onToggleSelectGroup ? (
                        <input
                          type="checkbox"
                          className="network-proxy-group__checkbox"
                          ref={(el) => {
                            if (el) {
                              el.indeterminate = isGroupIndeterminate;
                            }
                          }}
                          checked={allGroupSelected}
                          onChange={() => onToggleSelectGroup(groupProxies)}
                          onClick={(e) => e.stopPropagation()}
                          aria-label={`Select all proxies in ${group || 'Ungrouped routes'}`}
                        />
                      ) : null}
                      <div>
                        <span className="network-kicker">ROUTING GROUP</span>
                        <strong id={`proxy-group-${groupIndex}`}>
                          {group || 'Ungrouped routes'}
                        </strong>
                      </div>
                    </div>
                    <div className="network-proxy-group__header-meta">
                      {group && onSaveGroupLookupTimeout ? (
                        <span
                          className="network-proxy-group__timeout"
                          onClick={(e) => e.stopPropagation()}
                          onKeyDown={(e) => e.stopPropagation()}
                        >
                          {timeoutEditor?.group === group ? (
                            <>
                              <input
                                type="number"
                                min={0.5}
                                step={0.5}
                                className="network-proxy-group__timeout-input"
                                value={timeoutEditor.value}
                                placeholder="default"
                                aria-label={`Guest lookup timeout for ${group} in seconds`}
                                autoFocus
                                onChange={(e) => setTimeoutEditor({ group, value: e.target.value })}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') void saveGroupTimeout(group, timeoutEditor.value);
                                  if (e.key === 'Escape') setTimeoutEditor(null);
                                }}
                              />
                              <button
                                type="button"
                                className="network-button network-button--secondary"
                                disabled={savingGroupLookupTimeout === group}
                                onClick={() => void saveGroupTimeout(group, timeoutEditor.value)}
                              >
                                Save
                              </button>
                              <button
                                type="button"
                                className="network-button network-button--secondary"
                                disabled={savingGroupLookupTimeout === group}
                                onClick={() => void saveGroupTimeout(group, null)}
                              >
                                Clear
                              </button>
                              <button
                                type="button"
                                className="network-button network-button--secondary"
                                onClick={() => setTimeoutEditor(null)}
                              >
                                Cancel
                              </button>
                              {timeoutEditor.error ? (
                                <span role="alert" className="network-proxy-group__timeout-error">
                                  {timeoutEditor.error}
                                </span>
                              ) : null}
                            </>
                          ) : (
                            <button
                              type="button"
                              className="network-proxy-group__timeout-chip"
                              title="Guest lookup timeout for every proxy in this group. A proxy's own timeout wins."
                              onClick={() =>
                                setTimeoutEditor({
                                  group,
                                  value: groupLookupTimeouts[group]?.toString() ?? '',
                                })
                              }
                            >
                              TIMEOUT{' '}
                              {groupLookupTimeouts[group] != null
                                ? `${groupLookupTimeouts[group]}s`
                                : 'DEFAULT'}
                            </button>
                          )}
                        </span>
                      ) : null}
                      <span>
                        {groupProxies.length} route{groupProxies.length === 1 ? '' : 's'} ·{' '}
                        {groupProxies.reduce((sum, proxy) => sum + proxy.assigned_auths.length, 0)} assigned
                      </span>
                      <span className="network-proxy-group__chevron" aria-hidden="true">
                        {isCollapsed ? '▶' : '▼'}
                      </span>
                    </div>
                  </div>
                ) : null}
                {!isCollapsed && (
                  <div className="network-proxy-group__rows">
                    {groupProxies.map((proxy) => {
                      const isExpanded = expandedProxyId === proxy.id;
                      return (
                        <ProxyCard
                          key={proxy.id}
                          proxy={proxy}
                          isExpanded={isExpanded}
                          isSelected={selectedProxyIds.has(proxy.url)}
                          onToggleSelect={onToggleSelectProxy}
                          authList={isExpanded ? proxyAuths : undefined}
                          isAuthsLoading={isExpanded && isProxyAuthsLoading}
                          analyzerError={analyzerErrors[proxy.id]}
                          stateError={proxyStateErrors[proxy.id]}
                          isAnalyzing={Boolean(analyzerLoading[proxy.id])}
                          isStateChanging={Boolean(proxyStatePending[proxy.url])}
                          onEdit={onEditProxy}
                          onToggleExpanded={() => onToggleExpandedProxy(proxy.id)}
                          onOpenAnalyzer={onOpenAnalyzer}
                          onDelete={onDeleteProxy}
                          onRemoveAuth={onRemoveAuth}
                          onToggleEnabled={onToggleProxyEnabled}
                          onTestReachability={onTestReachability}
                          quickTestResult={proxyQuickTestResults?.[proxy.url]}
                        />
                      );
                    })}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}
    </section>
  );
}
