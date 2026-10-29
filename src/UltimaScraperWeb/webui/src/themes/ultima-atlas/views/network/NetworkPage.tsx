import { useState } from 'react';

import { BulkProxyModal } from '../../../../features/network/components/BulkProxyModal';
import { BulkEditConnectionsModal } from '../../../../features/network/components/BulkEditConnectionsModal';
import { DirectConnectionCard } from '../../../../features/network/components/DirectConnectionCard';
import { ErrorDetailModal } from '../../../../features/network/components/ErrorDetailModal';
import { ProxyAnalyzerModal } from '../../../../features/network/components/ProxyAnalyzerModal';
import { ProxyFormModal } from '../../../../features/network/components/ProxyFormModal';
import { ProxyListSection } from '../../../../features/network/components/ProxyListSection';
import { useGroupLookupTimeouts } from '../../../../features/network/hooks/useGroupLookupTimeouts';
import { useNetworkPageController } from '../../../../features/network/hooks/useNetworkPageController';
import {
  DIRECT_CONNECTION_PROXY,
  type NetworkProxy,
} from '../../../../api/types/network';
import { ConfirmDialog } from '../../../../shared/ui/ConfirmDialog';
import { WorkspacePageHeader } from '../../../../shared/ui/WorkspacePageHeader';
import {
  OperationsNotice,
  OperationsState,
} from '../../patterns/OperationsChrome';
import '../../../../features/network/components/NetworkWorkspace.css';
import './NetworkPage.css';

const NetworkPage = () => {
  const [deleteTarget, setDeleteTarget] = useState<NetworkProxy | null>(null);
  const {
    activeAnalyzerData,
    activeAnalyzerError,
    activeAnalyzerId,
    activeAnalyzerProxy,
    addProxyMutation,
    analyzeGroupRepresentative,
    analyzerErrors,
    analyzerLoading,
    analyzerModalTab,
    analyzerProgress,
    analyzerRequestCount,
    applyOptimalSettings,
    applySettingsNotice,
    applySettingsPending,
    assignProxyMutation,
    bulkAddProxiesMutation,
    bulkAssignGroupMutation,
    bulkEditMutation,
    bulkModalMode,
    bulkSyncProxiesMutation,
    closeBulkModal,
    closeProxyFormModal,
    deleteProxyMutation,
    disabledCount,
    editProxyMutation,
    editingProxy,
    enabledCount,
    error,
    errorDetailModal,
    existingGroups,
    expandedProxy,
    fetchGeolocation,
    filteredProxies,
    formError,
    handleBulkDeleteSelected,
    handleBulkDisableSelected,
    handleBulkEditSelected,
    handleBulkEnableSelected,
    handleBulkTest,
    handleBulkTestSelected,
    handleClearSelectedProxies,
    handleDeleteProxy,
    handleSaveProxy,
    handleSelectAllProxies,
    handleToggleProxyEnabled,
    handleToggleSelectGroup,
    handleToggleSelectProxy,
    isBulkTesting,
    isError,
    isLoading,
    isProxyAuthsLoading,
    proxyQuickTestResults,
    newProxyGroup,
    newProxyMaxConnections,
    newProxyGuestLookupTimeout,
    newProxyPassword,
    newProxyUrl,
    newProxyUsername,
    openAddModal,
    openAnalyzerModal,
    openBulkEditProxiesModal,
    openBulkModal,
    openEditModal,
    proxies,
    proxyAuths,
    proxyStateErrors,
    proxyStatePending,
    searchQuery,
    selectedGroupFilter,
    selectedProxyIds,
    setAnalyzerModalTab,
    setApplySettingsNotice,
    setAnalyzerRequestCount,
    setErrorDetailModal,
    setExpandedProxy,
    setNewProxyGroup,
    setNewProxyMaxConnections,
    setNewProxyGuestLookupTimeout,
    setNewProxyPassword,
    setNewProxyUrl,
    setNewProxyUsername,
    setSearchQuery,
    setSelectedGroupFilter,
    setShowAnalyzerModal,
    setShowBulkEditModal,
    setUseLiveCdn,
    showAddModal,
    showAnalyzerModal,
    showBulkModal,
    showBulkEditModal,
    startAnalysis,
    stopAnalysis,
    testLatencyMs,
    testMessage,
    testProxyMutation,
    testSingleReachability,
    testStatus,
    totalAssigned,
    unassignedCount,
    useLiveCdn,
    geoError,
    geoLoading,
  } = useNetworkPageController();
  const groupTimeouts = useGroupLookupTimeouts(existingGroups);

  const analyzerErrorCount = Object.values(analyzerErrors).filter(Boolean).length;
  if (isLoading) {
    return (
      <div className="proxies-page">
        <WorkspacePageHeader eyebrow="Platform" title="Network" subtitle="Proxy routing, health checks, and connection configuration." icon="⌘" />
        <OperationsState
          variant="loading"
          title="Loading network surface"
          description="Refreshing direct connection status, proxy inventory, and assignment health."
        />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="proxies-page">
        <WorkspacePageHeader eyebrow="Platform" title="Network" subtitle="Proxy routing, health checks, and connection configuration." icon="⌘" />
        <OperationsState
          variant="error"
          title="Failed to load network state"
          description={error instanceof Error ? error.message : 'Unknown error'}
        />
      </div>
    );
  }

  return (
    <div className="proxies-page">
      <WorkspacePageHeader
        eyebrow="Platform"
        title="Network"
        subtitle="Proxy routing, health checks, and connection configuration."
        icon="⌘"
        meta={(
          <div className="ultimur-topbar__actions">
            <span className={`ultimur-topbar__status ultimur-topbar__status--${unassignedCount > 0 ? 'warn' : 'ok'}`}>
              <span className="ultimur-topbar__dot" />
              {enabledCount}/{proxies.length} proxies enabled
            </span>
            <button type="button" className="ultimur-topbar__btn ultimur-topbar__btn--secondary" onClick={openBulkEditProxiesModal}>
              Bulk Edit
            </button>
            <button type="button" className="ultimur-topbar__btn ultimur-topbar__btn--secondary" onClick={openBulkModal}>
              Bulk Import
            </button>
            <button type="button" className="ultimur-topbar__btn" onClick={openAddModal}>
              Add Proxy
            </button>
          </div>
        )}
      />

      {searchQuery ? (
        <OperationsNotice tone="info" title="Filtered proxy view">
          Search is limited to proxies matching "{searchQuery}".
        </OperationsNotice>
      ) : null}

      {analyzerErrorCount > 0 ? (
        <OperationsNotice tone="danger" title={`${analyzerErrorCount} analyzer runs need review`}>
          Open the affected proxy cards to inspect the latest analyzer errors and rerun tests.
        </OperationsNotice>
      ) : null}

      {applySettingsNotice ? (
        <OperationsNotice
          tone={applySettingsNotice.tone}
          title={applySettingsNotice.title}
          actions={
            <button
              type="button"
              className="ops-action ops-action-secondary"
              onClick={() => setApplySettingsNotice(null)}
            >
              Dismiss
            </button>
          }
        >
          {applySettingsNotice.detail}
        </OperationsNotice>
      ) : null}

      <section className="network-command" aria-labelledby="route-strategy-title">
        <div className="network-section-head">
          <div>
            <span className="network-kicker">Traffic strategy</span>
            <h2 id="route-strategy-title">Route control</h2>
            <p>Benchmark the server exit, then compare it with regional proxy capacity.</p>
          </div>
        </div>
        <div className="network-command__grid">
          <DirectConnectionCard
            proxy={DIRECT_CONNECTION_PROXY}
            isAnalyzing={Boolean(analyzerLoading[DIRECT_CONNECTION_PROXY.id])}
            onOpenAnalyzer={openAnalyzerModal}
          />
          <article className="network-pool-card">
            <div><span className="network-kicker">Fallback capacity</span><h3>Proxy pool</h3></div>
            <div className="network-pool-card__metrics">
              <div><strong>{enabledCount}</strong><span>Enabled</span></div>
              <div className={disabledCount > 0 ? 'is-warning' : ''}><strong>{disabledCount}</strong><span>Disabled</span></div>
              <div className={unassignedCount > 0 ? 'is-warning' : ''}><strong>{unassignedCount}</strong><span>Idle</span></div>
            </div>
            <p>Guest resolution can rotate through up to three configured proxy exits after the direct route.</p>
          </article>
        </div>
      </section>

      <div className="network-section network-section--inventory">
        <ProxyListSection
          searchQuery={searchQuery}
          onSearchQueryChange={setSearchQuery}
          proxies={proxies}
          filteredProxies={filteredProxies}
          totalAssigned={totalAssigned}
          enabledCount={enabledCount}
          disabledCount={disabledCount}
          unassignedCount={unassignedCount}
          expandedProxyId={expandedProxy}
          proxyAuths={proxyAuths}
          isProxyAuthsLoading={isProxyAuthsLoading}
          analyzerLoading={analyzerLoading}
          analyzerErrors={analyzerErrors}
          proxyStatePending={proxyStatePending}
          proxyStateErrors={proxyStateErrors}
          onEditProxy={openEditModal}
          onToggleExpandedProxy={(proxyId) =>
            setExpandedProxy((currentProxyId) =>
              currentProxyId === proxyId ? null : proxyId
            )
          }
          onOpenAnalyzer={openAnalyzerModal}
          onDeleteProxy={(proxy) => setDeleteTarget(proxy)}
          onRemoveAuth={(authId) => assignProxyMutation.mutate({ auth_id: authId, proxy_url: null })}
          onToggleProxyEnabled={handleToggleProxyEnabled}
          existingGroups={existingGroups}
          selectedGroupFilter={selectedGroupFilter}
          onSelectGroupFilter={setSelectedGroupFilter}
          selectedProxyIds={selectedProxyIds}
          onToggleSelectProxy={handleToggleSelectProxy}
          onSelectAllProxies={handleSelectAllProxies}
          onClearSelectedProxies={handleClearSelectedProxies}
          onAssignGroupSelected={(group) =>
            bulkAssignGroupMutation.mutate({ proxyUrls: Array.from(selectedProxyIds), group })
          }
          onAnalyzeGroupRepresentative={analyzeGroupRepresentative}
          onTestReachability={testSingleReachability}
          onToggleSelectGroup={handleToggleSelectGroup}
          onBulkEnableSelected={handleBulkEnableSelected}
          onBulkDisableSelected={handleBulkDisableSelected}
          onBulkEditSelected={() => setShowBulkEditModal(true)}
          onBulkDeleteSelected={handleBulkDeleteSelected}
          onBulkTestSelected={handleBulkTestSelected}
          isBulkTesting={isBulkTesting}
          proxyQuickTestResults={proxyQuickTestResults}
          groupLookupTimeouts={groupTimeouts.timeouts}
          onSaveGroupLookupTimeout={groupTimeouts.saveTimeout}
          savingGroupLookupTimeout={groupTimeouts.savingGroup}
        />
      </div>

      <ConfirmDialog
        isOpen={deleteTarget !== null}
        title="Delete proxy?"
        description={
          deleteTarget
            ? `Remove ${deleteTarget.url} from the proxy pool. Assigned auth accounts will immediately fall back to other routing rules.`
            : ''
        }
        confirmLabel="Delete proxy"
        isPending={deleteProxyMutation.isPending}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (!deleteTarget) {
            return;
          }
          handleDeleteProxy(deleteTarget);
          setDeleteTarget(null);
        }}
      />

      <ProxyFormModal
        isOpen={showAddModal}
        editingProxy={editingProxy}
        proxyUrl={newProxyUrl}
        username={newProxyUsername}
        password={newProxyPassword}
        group={newProxyGroup}
        existingGroups={existingGroups}
        maxConnections={newProxyMaxConnections}
        guestLookupTimeout={newProxyGuestLookupTimeout}
        formError={formError}
        testStatus={testStatus}
        testMessage={testMessage}
        testLatencyMs={testLatencyMs}
        isTesting={testStatus === 'testing'}
        isSaving={addProxyMutation.isPending || editProxyMutation.isPending}
        onClose={closeProxyFormModal}
        onProxyUrlChange={setNewProxyUrl}
        onUsernameChange={setNewProxyUsername}
        onPasswordChange={setNewProxyPassword}
        onGroupChange={setNewProxyGroup}
        onMaxConnectionsChange={setNewProxyMaxConnections}
        onGuestLookupTimeoutChange={setNewProxyGuestLookupTimeout}
        onTest={() => testProxyMutation.mutate()}
        onSave={handleSaveProxy}
      />

      <BulkProxyModal
        isOpen={showBulkModal}
        existingGroups={existingGroups}
        currentProxies={proxies}
        selectedGroupFilter={selectedGroupFilter}
        initialMode={bulkModalMode}
        isImporting={bulkAddProxiesMutation.isPending || bulkSyncProxiesMutation.isPending}
        onClose={closeBulkModal}
        onImport={(items) => bulkAddProxiesMutation.mutate(items)}
        onBulkSync={(items, rawText, targetGroup) =>
          bulkSyncProxiesMutation.mutate({
            proxies: items,
            raw_text: rawText,
            target_group: targetGroup,
            default_group: targetGroup,
          })
        }
        onBulkTest={handleBulkTest}
      />

      <BulkEditConnectionsModal
        isOpen={showBulkEditModal}
        selectedProxyUrls={Array.from(selectedProxyIds)}
        proxies={proxies}
        isSaving={bulkEditMutation.isPending}
        onClose={() => setShowBulkEditModal(false)}
        onSave={handleBulkEditSelected}
      />

      <ProxyAnalyzerModal
        isOpen={showAnalyzerModal}
        proxy={activeAnalyzerProxy}
        tab={analyzerModalTab}
        analyzerData={activeAnalyzerData}
        analyzerError={activeAnalyzerError}
        isAnalyzing={Boolean(activeAnalyzerId && analyzerLoading[activeAnalyzerId])}
        progress={analyzerProgress}
        requestCount={analyzerRequestCount}
        useLiveCdn={useLiveCdn}
        geoLoading={geoLoading}
        geoError={geoError}
        onClose={() => setShowAnalyzerModal(false)}
        onTabChange={setAnalyzerModalTab}
        onRequestCountChange={setAnalyzerRequestCount}
        onUseLiveCdnChange={setUseLiveCdn}
        onFetchGeolocation={fetchGeolocation}
        onStopAnalysis={stopAnalysis}
        onStartAnalysis={startAnalysis}
        onApplyOptimalSettings={applyOptimalSettings}
        applySettingsPending={applySettingsPending}
        onShowErrorDetail={setErrorDetailModal}
      />

      <ErrorDetailModal detail={errorDetailModal} onClose={() => setErrorDetailModal(null)} />
    </div>
  );
};

export default NetworkPage;
