/**
 * Authentication credentials management page
 */

import { useState } from 'react';

import { FilterBar, FilterSelect } from '../../../../components/shared/FilterBar';
import type { AuthCredential } from '../../../../api/types/auths';
import { AddCurlModal } from '../../../../features/auths/components/AddCurlModal';
import { AuthsMatrix } from '../../../../features/auths/components/AuthsMatrix';
import { AuthsStats } from '../../../../features/auths/components/AuthsStats';
import { AuthTestModal } from '../../../../features/auths/components/AuthTestModal';
import {
  AgeVerificationModal,
  IdentityVerificationModal,
} from '../../../../features/auths/components/AuthVerificationModal';
import { ManageAuthModal } from '../../../../features/auths/components/ManageAuthModal';
import { useAuthsPageController } from '../../../../features/auths/hooks/useAuthsPageController';
import { AUTH_SORT_OPTIONS, type AuthStateFilter } from '../../../../features/auths/lib/authsUtils';
import { ConfirmDialog } from '../../../../shared/ui/ConfirmDialog';
import { WorkspacePageHeader } from '../../../../shared/ui/WorkspacePageHeader';
import {
  OperationsNotice,
  OperationsState,
} from '../../patterns/OperationsChrome';
import './AuthsPage.css';

const accountKey = (auth: AuthCredential) => `${auth.site}-${auth.user_id}`;

export function AuthsPage() {
  const [deleteTarget, setDeleteTarget] = useState<AuthCredential | null>(null);
  const {
    apiError,
    batchActiveMutation,
    batchTestMutation,
    deleteMutation,
    editingAuth,
    error,
    filteredAuths,
    handleBatchSetActive,
    handleBatchTest,
    handleDelete,
    handleScrapePaidContentForAuth,
    handleSaveEdit,
    handleToggle,
    handleUpdateSubscriptions,
    handleUpdateSubscriptionsForAuth,
    hasNextPage,
    identityVerifyingAuth,
    identifierSearch,
    invalidateAuths,
    isFetchingNextPage,
    isLoading,
    loadMoreSentinelRef,
    loadedDisabledCount,
    loadedEnabledCount,
    openAgeVerification,
    openIdentityVerification,
    refreshMessage,
    refreshSubscriptionsMutation,
    refreshingAuthRecordId,
    scrapingPaidContentAuthId,
    refetch,
    setEditingAuth,
    setIdentifierSearch,
    setIdentityVerifyingAuth,
    setShowAddCurlModal,
    setSiteFilter,
    setSortBy,
    setSortOrder,
    setStateFilter,
    setTestingAuth,
    setVerifyingAuth,
    showAddCurlModal,
    siteFilter,
    sortBy,
    sortOrder,
    sortedAuths,
    stateFilter,
    testingAuth,
    totalAuths,
    toggleMutation,
    updateMutation,
    verifyingAuth,
  } = useAuthsPageController();

  const statusTone = loadedDisabledCount > 0 ? 'warn' : 'ok';
  const statusLabel = `${loadedEnabledCount} active`;

  if (isLoading) {
    return (
      <div className="auths-page">
        <WorkspacePageHeader eyebrow="People" title="Auths" subtitle="Manage saved accounts, credentials, and verification." icon="◎" />
        <OperationsState
          variant="loading"
          title="Loading auths"
          description="Refreshing stored credentials, verification state, and subscription refresh status."
        />
      </div>
    );
  }

  if (error) {
    return (
      <div className="auths-page">
        <WorkspacePageHeader eyebrow="People" title="Auths" subtitle="Manage saved accounts, credentials, and verification." icon="◎" />
        <OperationsState
          variant="error"
          title="Failed to load auths"
          description={error instanceof Error ? error.message : 'Unknown error'}
          actions={
            <button type="button" className="ops-action ops-action-primary" onClick={() => refetch()}>
              Retry
            </button>
          }
        />
      </div>
    );
  }

  return (
    <div className="auths-page">
      <WorkspacePageHeader
        eyebrow="People"
        title="Auths"
        subtitle="Manage saved accounts, credentials, and verification."
        icon="◎"
        meta={(
          <div className="ultimur-topbar__actions">
            <span className={`ultimur-topbar__status ultimur-topbar__status--${statusTone}`}>
              <span className="ultimur-topbar__dot" />
              {statusLabel}
            </span>
            <button
              type="button"
              className="ultimur-topbar__btn"
              onClick={() => setShowAddCurlModal(true)}
            >
              Add Account
            </button>
          </div>
        )}
      />

      {refreshMessage ? (
        <OperationsNotice tone="success" title="Auth refresh update">
          {refreshMessage}
        </OperationsNotice>
      ) : null}
      {apiError ? (
        <OperationsNotice tone="danger" title="Credential action failed">
          {apiError}
        </OperationsNotice>
      ) : null}

      <FilterBar
        searchValue={identifierSearch}
        onSearchChange={setIdentifierSearch}
        searchPlaceholder="Search by identifier…"
        sortOptions={AUTH_SORT_OPTIONS}
        sortBy={sortBy}
        onSortByChange={setSortBy}
        sortOrder={sortOrder}
        onSortOrderToggle={() =>
          setSortOrder((currentOrder) => (currentOrder === 'asc' ? 'desc' : 'asc'))
        }
        primaryExtras={
          <>
            <FilterSelect label="Site" value={siteFilter} onChange={setSiteFilter}>
              <option value="">All Sites</option>
              <option value="onlyfans">OnlyFans</option>
              <option value="fansly">Fansly</option>
            </FilterSelect>
            <FilterSelect
              label="Active"
              value={stateFilter}
              onChange={(value) => setStateFilter(value as AuthStateFilter)}
            >
              <option value="">All Auths</option>
              <option value="enabled">Active</option>
              <option value="disabled">Disabled</option>
            </FilterSelect>
          </>
        }
        secondaryExtras={
          <div className="auths-toolbar-actions">
            {identifierSearch && (
              <button
                type="button"
                className="filter-bar__filters-btn"
                onClick={() => setIdentifierSearch('')}
              >
                Clear
              </button>
            )}
            <button
              type="button"
              className="filter-bar__filters-btn"
              onClick={() => refetch()}
            >
              Refresh
            </button>
            <button
              type="button"
              className="filter-bar__filters-btn"
              onClick={handleUpdateSubscriptions}
              disabled={refreshSubscriptionsMutation.isPending}
            >
              {refreshSubscriptionsMutation.isPending
                ? 'Updating…'
                : 'Update Subscriptions'}
            </button>
          </div>
        }
      />



      {filteredAuths.length === 0 ? (
        <OperationsState
          title="No authentication credentials in this view"
          description={
            identifierSearch || stateFilter || siteFilter
              ? 'Adjust the current filters or search terms to widen the result set.'
              : 'Credentials are imported from configuration files or added from captured browser cURL requests and raw auth payloads.'
          }
        />
      ) : (
        <>
          <AuthsMatrix
            auths={sortedAuths}
            togglePending={toggleMutation.isPending}
            deletePending={deleteMutation.isPending}
            batchPending={batchActiveMutation.isPending || batchTestMutation.isPending}
            onManage={setEditingAuth}
            onTest={setTestingAuth}
            onToggle={handleToggle}
            onDelete={(auth) => setDeleteTarget(auth)}
            onBatchTest={handleBatchTest}
            onBatchSetActive={handleBatchSetActive}
            summary={
              <AuthsStats
                showing={filteredAuths.length}
                total={totalAuths}
                loadedEnabledCount={loadedEnabledCount}
                loadedDisabledCount={loadedDisabledCount}
                accounts={new Set(filteredAuths.map(accountKey)).size}
                spenderCount={new Set(filteredAuths.filter((auth) => auth.spend).map(accountKey)).size}
              />
            }
          />
          {isFetchingNextPage && (
            <div className="auths-loading-more">Loading more auths...</div>
          )}
          {!hasNextPage && totalAuths > 0 && (
            <div className="auths-end">All auths loaded</div>
          )}
          <div ref={loadMoreSentinelRef} className="auths-scroll-sentinel" />
        </>
      )}

      <ConfirmDialog
        isOpen={deleteTarget !== null}
        title="Delete authentication credential?"
        description={
          deleteTarget
            ? `Remove the stored auth for ${deleteTarget.username || deleteTarget.user_id}. This keeps downloaded content intact but removes the credential from active use.`
            : ''
        }
        confirmLabel="Delete credential"
        isPending={deleteMutation.isPending}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (!deleteTarget) {
            return;
          }
          handleDelete(deleteTarget);
          setDeleteTarget(null);
        }}
      />

      {editingAuth && (
        <ManageAuthModal
          auth={editingAuth}
          onClose={() => setEditingAuth(null)}
          onSave={handleSaveEdit}
          isSaving={updateMutation.isPending}
          onTest={() => setTestingAuth(editingAuth)}
          onUpdateSubscriptions={() => handleUpdateSubscriptionsForAuth(editingAuth)}
          onScrapePaidContent={() => handleScrapePaidContentForAuth(editingAuth)}
          onVerifyAge={() => openAgeVerification(editingAuth)}
          onVerifyIdentity={() => openIdentityVerification(editingAuth)}
          isUpdatingSubscriptions={
            refreshSubscriptionsMutation.isPending &&
            refreshingAuthRecordId === editingAuth.id
          }
          isScrapingPaidContent={scrapingPaidContentAuthId === editingAuth.user_id}
        />
      )}

      {showAddCurlModal && (
        <AddCurlModal
          onClose={() => setShowAddCurlModal(false)}
          onSuccess={invalidateAuths}
        />
      )}

      {testingAuth && (
        <AuthTestModal
          auth={testingAuth}
          onClose={() => setTestingAuth(null)}
          onAuthTested={invalidateAuths}
        />
      )}

      {verifyingAuth && (
        <AgeVerificationModal
          auth={verifyingAuth.auth}
          requestKey={verifyingAuth.requestKey}
          onClose={() => setVerifyingAuth(null)}
        />
      )}
      {identityVerifyingAuth && (
        <IdentityVerificationModal
          auth={identityVerifyingAuth.auth}
          requestKey={identityVerifyingAuth.requestKey}
          onClose={() => setIdentityVerifyingAuth(null)}
        />
      )}
    </div>
  );
}
