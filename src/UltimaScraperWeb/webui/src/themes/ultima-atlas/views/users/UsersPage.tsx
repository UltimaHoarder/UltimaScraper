import { UsersHeader } from '../../../../features/users/components/UsersHeader';
import { UsersAuthPickerModal } from '../../../../features/users/components/UsersAuthPickerModal';
import { UsersBulkIdentityModal } from '../../../../features/users/components/UsersBulkIdentityModal';
import { UsersEditModal } from '../../../../features/users/components/UsersEditModal';
import { UsersFiltersModal } from '../../../../features/users/components/UsersFiltersModal';
import { UsersLoadoutModal } from '../../../../features/users/components/UsersLoadoutModal';
import { UsersResults } from '../../../../features/users/components/UsersResults';
import { UsersSelectionBar } from '../../../../features/users/components/UsersSelectionBar';
import { useUsersPageController } from '../../../../features/users/hooks/useUsersPageController';
import { type UsersPageProps } from '../../../../features/users/lib/usersUtils';
import { ImageLightbox } from '../../../../shared/ui/ImageLightbox';
import './UsersPage.css';

export function UsersPage({
  title = 'Users',
  subtitle,
  icon,
  favoriteOnly = false,
}: UsersPageProps = {}) {
  const controller = useUsersPageController({ favoriteOnly });

  return (
    <div className="users-page ultimur-users-v2">
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

      <UsersAuthPickerModal
        isOpen={controller.authPickerOpen}
        targetUser={controller.authPickerTarget}
        eligibleAuths={controller.eligibleAuths ?? []}
        isCreatingJob={controller.createJobMutation.isPending}
        onClose={() => controller.setAuthPickerOpen(false)}
        onSelectAuth={(authId) => {
          if (!controller.authPickerTarget) {
            return;
          }
          controller.dispatchScrapeUser(controller.authPickerTarget, authId);
          controller.setAuthPickerOpen(false);
        }}
      />

      <UsersEditModal
        isOpen={controller.editModalOpen}
        targetUser={controller.editTarget}
        editName={controller.editName}
        editAlias={controller.editAlias}
        editDescription={controller.editDescription}
        {...controller.userEditIdentityFields}
        isSaving={controller.updateUserMutation.isPending}
        onClose={() => controller.setEditModalOpen(false)}
        onEditNameChange={controller.setEditName}
        onEditAliasChange={controller.setEditAlias}
        onEditDescriptionChange={controller.setEditDescription}
        onSave={controller.handleSaveUserEdit}
      />

      <UsersBulkIdentityModal
        isOpen={controller.bulkIdentityModalOpen}
        selectedCount={controller.selectedUsers.size}
        {...controller.bulkIdentityFields}
        isSaving={controller.bulkIdentitySaving}
        onClose={() => controller.setBulkIdentityModalOpen(false)}
        onSave={() => {
          void controller.handleSaveBulkIdentity();
        }}
      />

      <UsersHeader
        title={title}
        subtitle={subtitle ?? (favoriteOnly ? 'Browse favourited creators from your database' : 'Roster management, creator archives & metadata intelligence')}
        icon={icon ?? (favoriteOnly ? '⭐' : '👥')}
        entityLabel={favoriteOnly ? 'Favourites' : 'Creators'}
        totalRosterCount={controller.totalRosterCount}
        activeRosterCount={controller.activeRosterCount}
        watchedCount={controller.watchedCount}
        unscrapedCount={controller.unscrapedCount}
        avgPrice={controller.avgPrice}
        totalsStatus={controller.totalsStatus}
        onRetryTotals={controller.retryTotals}
        viewMode={controller.viewMode}
        onViewModeChange={controller.setViewMode}
        searchTerm={controller.searchTerm}
        onSearchTermChange={(value) => {
          controller.setSearchTerm(value);
          if (!value) {
            controller.setSearchQuery('');
          }
        }}
        onSearchTermClear={() => {
          controller.setSearchTerm('');
          controller.setSearchQuery('');
        }}
        searchDescriptionTerm={controller.searchDescriptionTerm}
        onSearchDescriptionChange={(value) => {
          controller.setSearchDescriptionTerm(value);
          if (!value) {
            controller.setSearchDescriptionQuery('');
          }
        }}
        onSearchDescriptionClear={() => {
          controller.setSearchDescriptionTerm('');
          controller.setSearchDescriptionQuery('');
        }}
        selectedSite={controller.selectedSite}
        onSelectedSiteChange={controller.setSelectedSite}
        sortBy={controller.sortBy}
        onSortByChange={controller.setSortBy}
        sortOptions={controller.sortOptions}
        sortOrder={controller.sortOrder}
        onSortOrderToggle={() =>
          controller.setSortOrder((currentOrder) =>
            currentOrder === 'asc' ? 'desc' : 'asc')
        }
        onOpenFiltersModal={controller.openUserFilters}
        activeFilterCount={controller.activeUserFilterCount}
        selectedLoadoutName={controller.selectedLoadoutName}
        loadedCount={controller.loadedCount}
        totalCount={controller.totalCount}
        totalUsers={controller.loadedCount}
      >
        <UsersSelectionBar
          selectedCount={controller.selectedUsers.size}
          totalUsers={controller.allUsers.length}
          isCreatingJob={controller.createJobMutation.isPending}
          isAuthPickerLoading={controller.authPickerLoading}
          isWatching={controller.watchMutation.isPending}
          isIgnoring={controller.ignoreMutation.isPending}
          isSettingIdentity={controller.bulkIdentitySaving}
          onSelectAll={controller.handleSelectAll}
          onClearSelection={() => controller.setSelectedUsers(new Set())}
          onScrapeSelected={controller.handleScrapeSelected}
          onWatchSelected={() => {
            void controller.handleWatchSelected();
          }}
          onIgnoreSelected={() => {
            void controller.handleIgnoreSelected();
          }}
          onSetIdentitySelected={controller.openBulkIdentityModal}
        />

        <UsersResults
          favoriteOnly={favoriteOnly}
          error={controller.usersError}
          allUsers={controller.visibleUsers}
          loadedCount={controller.loadedCount}
          totalCount={controller.totalCount}
              searchQuery={controller.searchQuery}
              viewMode={controller.viewMode}
              selectedUsers={controller.selectedUsers}
              watchedKeys={controller.watchedKeys}
              ignoredKeys={controller.ignoredKeys}
              isCreatingJob={controller.createJobMutation.isPending}
              isAuthPickerLoading={controller.authPickerLoading}
              isSubscribePending={controller.subscribeMutation.isPending}
              isWatchPending={
                controller.watchMutation.isPending || controller.unwatchMutation.isPending
              }
              isIgnorePending={
                controller.ignoreMutation.isPending || controller.unignoreMutation.isPending
              }
              isUpdatePending={controller.updateUserMutation.isPending}
              isLoadingInitialPage={controller.isLoadingInitialPage}
              isLoadingNextPage={controller.isLoadingNextPage}
              hasMore={controller.hasMore}
              pageSize={controller.pageSize}
              loadMoreSentinelRef={controller.loadMoreSentinelRef}
              navigate={controller.navigate}
              onLoadMore={controller.handleLoadMore}
              onSelectUser={controller.handleSelectUser}
              onScrapeUser={controller.handleScrapeUser}
              onSubscribeUser={controller.handleSubscribeUser}
              onWatchToggle={controller.handleWatchToggle}
              onIgnoreToggle={controller.handleIgnoreToggle}
              onEditUser={controller.openEditModal}
              onOpenLightbox={controller.openLightbox}
            />
      </UsersHeader>

      <UsersLoadoutModal
        isOpen={controller.loadoutModalOpen}
        loadouts={controller.loadoutsData?.loadouts || []}
        selectedLoadoutName={controller.selectedLoadoutName}
        selectedLoadoutIsDefault={controller.selectedLoadoutIsDefault}
        loadoutNameInput={controller.loadoutNameInput}
        placeholderName={controller.buildAutoLoadoutName()}
        onClose={() => controller.setLoadoutModalOpen(false)}
        onSelectedLoadoutChange={(value) => {
          controller.setSelectedLoadoutName(value);
          controller.setLoadoutNameInput(value);
          const loadout = controller.loadoutsData?.loadouts.find(
            (entry) => entry.name === value
          );
          if (loadout) {
            controller.applyUsersLoadout(loadout);
          }
        }}
        onLoadoutNameInputChange={controller.setLoadoutNameInput}
        onAutofill={() => controller.setLoadoutNameInput(controller.buildAutoLoadoutName())}
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
        onSave={() => {
          void controller.saveCurrentLoadout();
        }}
      />

      <UsersFiltersModal
        isOpen={controller.filtersModalOpen}
        loadouts={controller.loadoutsData?.loadouts || []}
        selectedLoadoutName={controller.selectedLoadoutName}
        selectedLoadoutIsDefault={controller.selectedLoadoutIsDefault}
        loadoutNameInput={controller.loadoutNameInput}
        placeholderLoadoutName={controller.buildAutoLoadoutName()}
        onSelectedLoadoutChange={(value) => {
          controller.setSelectedLoadoutName(value);
          controller.setLoadoutNameInput(value);
          const loadout = controller.loadoutsData?.loadouts.find(
            (entry) => entry.name === value
          );
          if (loadout) {
            controller.applyUsersLoadout(loadout);
          }
        }}
        onLoadoutNameInputChange={controller.setLoadoutNameInput}
        onAutofillLoadoutName={() => controller.setLoadoutNameInput(controller.buildAutoLoadoutName())}
        onDeleteLoadout={() => {
          void controller.deleteSelectedLoadout();
        }}
        onToggleDefaultLoadout={() => {
          if (controller.selectedLoadoutIsDefault) {
            void controller.clearDefaultLoadout();
          } else {
            void controller.setSelectedAsDefaultLoadout();
          }
        }}
        onSaveLoadout={() => {
          void controller.saveCurrentLoadout();
        }}
        draftActiveOnly={controller.draftActiveOnly}
        draftSexFilter={controller.draftSexFilter}
        draftGenderFilter={controller.draftGenderFilter}
        draftProfileTypeFilter={controller.draftProfileTypeFilter}
        draftSexualContentFilter={controller.draftSexualContentFilter}
        draftUserFilters={controller.draftUserFilters}
        draftMinPrice={controller.draftMinPrice}
        draftMaxPrice={controller.draftMaxPrice}
        draftMinPostCount={controller.draftMinPostCount}
        draftMaxPostCount={controller.draftMaxPostCount}
        draftMinImageCount={controller.draftMinImageCount}
        draftMaxImageCount={controller.draftMaxImageCount}
        draftMinVideoCount={controller.draftMinVideoCount}
        draftMaxVideoCount={controller.draftMaxVideoCount}
        onClose={() => controller.setFiltersModalOpen(false)}
        onApply={controller.applyUserFilters}
        onDraftActiveOnlyChange={controller.setDraftActiveOnly}
        onDraftSexFilterChange={controller.setDraftSexFilter}
        onDraftGenderFilterChange={controller.setDraftGenderFilter}
        onDraftProfileTypeFilterChange={controller.setDraftProfileTypeFilter}
        onDraftSexualContentFilterChange={controller.setDraftSexualContentFilter}
        onDraftUserFiltersChange={controller.setDraftUserFilters}
        onDraftMinPriceChange={controller.setDraftMinPrice}
        onDraftMaxPriceChange={controller.setDraftMaxPrice}
        onDraftMinPostCountChange={controller.setDraftMinPostCount}
        onDraftMaxPostCountChange={controller.setDraftMaxPostCount}
        onDraftMinImageCountChange={controller.setDraftMinImageCount}
        onDraftMaxImageCountChange={controller.setDraftMaxImageCount}
        onDraftMinVideoCountChange={controller.setDraftMinVideoCount}
        onDraftMaxVideoCountChange={controller.setDraftMaxVideoCount}
      />

      <ImageLightbox
        imageUrl={controller.lightboxUrl}
        alt={controller.lightboxAlt}
        onClose={controller.closeLightbox}
      />
    </div>
  );
}
