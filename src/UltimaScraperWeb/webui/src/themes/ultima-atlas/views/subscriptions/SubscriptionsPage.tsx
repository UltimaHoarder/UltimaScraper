import { UsersHeader } from '../../../../features/users/components/UsersHeader';
import { SubscriptionsAuthPickerModal } from '../../../../features/subscriptions/components/SubscriptionsAuthPickerModal';
import { SubscriptionsBulkActionModal } from '../../../../features/subscriptions/components/SubscriptionsBulkActionModal';
import { SubscriptionsEditModal } from '../../../../features/subscriptions/components/SubscriptionsEditModal';
import { SubscriptionsFiltersModal } from '../../../../features/subscriptions/components/SubscriptionsFiltersModal';
import { SubscriptionsLoadoutModal } from '../../../../features/subscriptions/components/SubscriptionsLoadoutModal';
import { SubscriptionsResults } from '../../../../features/subscriptions/components/SubscriptionsResults';
import { SubscriptionsSelectionBar } from '../../../../features/subscriptions/components/SubscriptionsSelectionBar';
import { useSubscriptionsPageController } from '../../../../features/subscriptions/hooks/useSubscriptionsPageController';
import { SUBSCRIPTION_SORT_OPTIONS } from '../../../../features/subscriptions/lib/subscriptionsUtils';
import { ImageLightbox } from '../../../../shared/ui/ImageLightbox';
import '../users/UsersPage.css';
import './SubscriptionsPage.css';

export function SubscriptionsPage() {
  const controller = useSubscriptionsPageController();
  const stats = controller.stats ?? [];
  const totalSubscriptions = stats.reduce((sum, stat) => sum + stat.total, 0);
  const totalActiveSubscriptions = stats.reduce((sum, stat) => sum + stat.active, 0);
  const totalExpiredSubscriptions = Math.max(totalSubscriptions - totalActiveSubscriptions, 0);
  const visible = controller.visibleSubscriptions;
  const avgPrice = visible.length
    ? (visible.reduce((sum, s) => sum + (s.price ?? 0), 0) / visible.length).toFixed(2)
    : '0.00';

  return (
    <div className="subscriptions-page ultimur-subscriptions-v2">
      {controller.toast && (
        <div className={`toast toast-${controller.toast.type}`}>
          <span className="toast-icon">
            {controller.toast.type === 'success' ? '✓' : '✗'}
          </span>
          <span className="toast-message">{controller.toast.message}</span>
          <button className="toast-close" onClick={() => controller.setToast(null)}>
            ×
          </button>
        </div>
      )}

      {controller.isScrapeMultipleDialogOpen && (
        <SubscriptionsBulkActionModal
          title="🚀 Scrape Selected Subscriptions"
          description={`This will create a job to scrape and download content from ${controller.selectedScrapableSubscriptions.length} subscription${controller.selectedScrapableSubscriptions.length !== 1 ? 's' : ''}.${controller.selectedSubscriptions.size - controller.selectedScrapableSubscriptions.length > 0 ? ` (${controller.selectedSubscriptions.size - controller.selectedScrapableSubscriptions.length} ignored user${controller.selectedSubscriptions.size - controller.selectedScrapableSubscriptions.length !== 1 ? 's' : ''} will be skipped)` : ''}`}
          previewSubscriptions={controller.selectedScrapableSubscriptions.slice(0, 5)}
          overflowCount={Math.max(controller.selectedScrapableSubscriptions.length - 5, 0)}
          confirmLabel={
            controller.createJobMutation.isPending
              ? 'Creating...'
              : `Scrape ${controller.selectedScrapableSubscriptions.length} Selected`
          }
          confirmDisabled={
            controller.createJobMutation.isPending ||
            controller.selectedScrapableSubscriptions.length === 0
          }
          onClose={() => controller.setIsScrapeMultipleDialogOpen(false)}
          onConfirm={controller.confirmScrapeMultiple}
        />
      )}

      {controller.isIgnoreMultipleDialogOpen && (
        <SubscriptionsBulkActionModal
          title="🚫 Ignore Selected Users"
          description={`Ignore ${controller.selectedIgnorableSubscriptions.length} user${controller.selectedIgnorableSubscriptions.length !== 1 ? 's' : ''}. They will be skipped when scraping.`}
          previewSubscriptions={controller.selectedSubscriptionObjects.slice(0, 5)}
          overflowCount={Math.max(controller.selectedSubscriptions.size - 5, 0)}
          confirmLabel={`🚫 Ignore ${controller.selectedIgnorableSubscriptions.length} Selected`}
          confirmButtonClassName="btn-confirm btn-confirm-ignore"
          onClose={() => controller.setIsIgnoreMultipleDialogOpen(false)}
          onConfirm={() => {
            void controller.confirmIgnoreMultiple();
          }}
        />
      )}

      {controller.isWatchMultipleDialogOpen && (
        <SubscriptionsBulkActionModal
          title="👁 Add to Watch List"
          description={`Add ${controller.selectedWatchableSubscriptions.length} user${controller.selectedWatchableSubscriptions.length !== 1 ? 's' : ''} to the watch list.`}
          previewSubscriptions={controller.selectedSubscriptionObjects.slice(0, 5)}
          overflowCount={Math.max(controller.selectedSubscriptions.size - 5, 0)}
          confirmLabel={`👁 Watch ${controller.selectedWatchableSubscriptions.length} Selected`}
          confirmButtonClassName="btn-confirm btn-confirm-watch"
          onClose={() => controller.setIsWatchMultipleDialogOpen(false)}
          onConfirm={() => {
            void controller.confirmWatchMultiple();
          }}
        />
      )}

      {controller.authPickerOpen && controller.authPickerTarget && (
        <SubscriptionsAuthPickerModal
          target={controller.authPickerTarget}
          eligibleAuths={controller.eligibleAuths}
          isPending={controller.createJobMutation.isPending}
          onClose={() => controller.setAuthPickerOpen(false)}
          onSelectAuth={(authId) => {
            if (!controller.authPickerTarget) {
              return;
            }
            controller.dispatchScrapeUser(controller.authPickerTarget, authId);
            controller.setAuthPickerOpen(false);
          }}
        />
      )}

      {controller.editModalOpen && controller.editTarget && (
        <SubscriptionsEditModal
          target={controller.editTarget}
          editName={controller.editName}
          editDescription={controller.editDescription}
          editSex={controller.editSex}
          isPending={controller.updateUserMutation.isPending}
          onClose={() => controller.setEditModalOpen(false)}
          onNameChange={controller.setEditName}
          onDescriptionChange={controller.setEditDescription}
          onSexChange={controller.setEditSex}
          onSave={controller.handleSaveUserEdit}
        />
      )}

      <UsersHeader
        title="Subscriptions"
        subtitle="Active memberships, renewal telemetry & creator dossiers"
        icon="💳"
        entityLabel="Subscriptions"
        totalRosterCount={totalSubscriptions}
        activeRosterCount={totalActiveSubscriptions}
        metricTiles={[
          {
            label: 'Total Subscriptions',
            value: totalSubscriptions == null ? '—' : String(totalSubscriptions).padStart(2, '0'),
            detail: 'Across all platforms',
          },
          {
            label: 'Active Subscriptions',
            value: String(totalActiveSubscriptions).padStart(2, '0'),
            detail: 'Live billing',
            accent: true,
          },
          {
            label: 'Expired / Inactive',
            value: String(totalExpiredSubscriptions).padStart(2, '0'),
            detail: 'Past memberships',
            warn: totalExpiredSubscriptions > 0,
          },
          {
            label: 'Average Rate',
            value: `$${avgPrice}`,
            detail: 'Monthly renewal',
          },
        ]}
        searchTerm={controller.searchTerm}
        onSearchTermChange={(value) => {
          controller.setSearchTerm(value);
          if (!value) controller.setSearchQuery('');
        }}
        onSearchTermClear={() => {
          controller.setSearchTerm('');
          controller.setSearchQuery('');
        }}
        selectedSite={controller.selectedSite}
        onSelectedSiteChange={controller.setSelectedSite}
        extraControls={
          <select
            aria-label="Filter by auth"
            className="users-toolbar__select"
            value={String(controller.selectedAuthId)}
            onChange={(e) =>
              controller.setSelectedAuthId(e.target.value === '' ? '' : Number(e.target.value))
            }
          >
            <option value="">All Auths</option>
            {controller.auths?.auths?.map((auth) => (
              <option key={`${auth.site}-${auth.id}`} value={auth.id}>
                {auth.username || `Auth ${auth.id}`} ({auth.site})
                {auth.active ? '' : ' • Inactive'}
              </option>
            ))}
          </select>
        }
        sortBy={controller.orderBy}
        onSortByChange={controller.setOrderBy}
        sortOptions={SUBSCRIPTION_SORT_OPTIONS}
        sortOrder={controller.orderDir}
        onSortOrderToggle={() =>
          controller.setOrderDir((prev) => (prev === 'asc' ? 'desc' : 'asc'))
        }
        onOpenFiltersModal={controller.openFiltersModal}
        activeFilterCount={controller.activeFilterCount}
        selectedLoadoutName={controller.selectedLoadoutName}
        loadedCount={controller.visibleSubscriptions.length}
        totalCount={controller.subscriptionsTotal}
        totalUsers={controller.visibleSubscriptions.length}
      >
        <SubscriptionsSelectionBar
          selectedCount={controller.selectedSubscriptions.size}
          visibleCount={controller.visibleSubscriptions.length}
          createJobPending={controller.createJobMutation.isPending}
          onSelectAll={controller.selectAll}
          onClear={controller.clearSelections}
          onScrape={controller.handleScrapeMultiple}
          onWatch={controller.handleWatchMultiple}
          onIgnore={controller.handleIgnoreMultiple}
        />

        <SubscriptionsResults
          visibleSubscriptions={controller.visibleSubscriptions}
          subscriptionsTotal={controller.subscriptionsTotal}
          priceRangeActive={Boolean(controller.minPrice.trim() || controller.maxPrice.trim())}
          isLoading={controller.isLoading}
          error={controller.error}
          hasNextPage={controller.hasNextPage}
          isFetchingNextPage={controller.isFetchingNextPage}
          isActionPending={controller.createJobMutation.isPending || controller.authPickerLoading}
          selectedSubscriptions={controller.selectedSubscriptions}
          watchedKeys={controller.watchedKeys}
          ignoredKeys={controller.ignoredKeys}
          isWatchPending={
            controller.watchMutation.isPending || controller.unwatchMutation.isPending
          }
          isIgnorePending={
            controller.ignoreMutation.isPending || controller.unignoreMutation.isPending
          }
          isUpdatePending={controller.updateUserMutation.isPending}
          loadMoreSentinelRef={controller.loadMoreSentinelRef}
          onFetchNextPage={() => {
            void controller.fetchNextPage();
          }}
          onScrape={controller.handleScrapeUser}
          onView={controller.handleViewUser}
          onSelect={controller.toggleSubscriptionSelection}
          onWatchToggle={controller.handleWatchToggle}
          onIgnoreToggle={controller.handleIgnoreToggle}
          onEdit={controller.openEditModal}
          onOpenLightbox={controller.openLightbox}
        />
      </UsersHeader>

      {controller.loadoutModalOpen && (
        <SubscriptionsLoadoutModal
          loadoutsData={controller.loadoutsData}
          selectedLoadoutName={controller.selectedLoadoutName}
          loadoutNameInput={controller.loadoutNameInput}
          selectedLoadoutIsDefault={controller.selectedLoadoutIsDefault}
          autoNamePlaceholder={controller.buildAutoLoadoutName()}
          onClose={() => controller.setLoadoutModalOpen(false)}
          onLoadoutSelect={(value) => controller.handleSelectLoadout(value, controller.loadoutsData)}
          onInputChange={controller.setLoadoutNameInput}
          onAutofill={controller.autofillLoadoutName}
          onDelete={() => {
            void controller.deleteSelectedLoadout();
          }}
          onToggleDefault={() => {
            if (controller.selectedLoadoutIsDefault) {
              void controller.clearDefaultLoadout();
            } else {
              void controller.setSelectedAsDefaultLoadout();
            }
          }}
          onSaveCurrent={() => {
            void controller.saveCurrentLoadout();
          }}
        />
      )}

      {controller.filtersModalOpen && (
        <SubscriptionsFiltersModal
          draftActiveOnly={controller.draftActiveOnly}
          draftMinPrice={controller.draftMinPrice}
          draftMaxPrice={controller.draftMaxPrice}
          draftSexFilter={controller.draftSexFilter}
          onClose={() => controller.setFiltersModalOpen(false)}
          onDraftActiveOnlyChange={controller.setDraftActiveOnly}
          onDraftMinPriceChange={controller.setDraftMinPrice}
          onDraftMaxPriceChange={controller.setDraftMaxPrice}
          onDraftSexFilterChange={controller.setDraftSexFilter}
          onClear={controller.clearFilters}
          onApply={controller.applyFilters}
        />
      )}

      <ImageLightbox
        imageUrl={controller.lightboxUrl}
        alt={controller.lightboxAlt}
        onClose={controller.closeLightbox}
      />
    </div>
  );
}
