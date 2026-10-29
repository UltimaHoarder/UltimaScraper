import {
  ContentLibraryAdvancedFiltersModal,
} from '../../../../features/content-library/components/ContentLibraryAdvancedFiltersModal';
import { ContentLibraryLoadoutModal } from '../../../../features/content-library/components/ContentLibraryLoadoutModal';
import { ContentLibraryResults } from '../../../../features/content-library/components/ContentLibraryResults';
import { ContentLibraryToolbar } from '../../../../features/content-library/components/ContentLibraryToolbar';
import { useContentLibraryController } from '../../../../features/content-library/hooks/useContentLibraryController';
import { buildAutoLoadoutName } from '../../../../features/content-library/lib/contentLibraryUtils';
import {
  OperationsNotice,
} from '../../patterns/OperationsChrome';
import { WorkspacePageHeader } from '../../../../shared/ui/WorkspacePageHeader';
import './ContentLibraryPage.css';

export function ContentLibraryPage() {
  const {
    activeAdvancedFilterCount,
    advancedModalOpen,
    applyAdvancedFilters,
    applyContentLoadout,
    clearDefaultLoadout,
    clearDraftAdvancedFilters,
    clearHiddenUsers,
    contentType,
    deleteSelectedLoadout,
    draftAdvancedFilters,
    error,
    excludedUserIds,
    excludedUsernames,
    handleSearchInput,
    hasMore,
    hideUser,
    items,
    loading,
    loadoutModalOpen,
    loadoutNameInput,
    loadouts,
    openAdvancedFilters,
    openLoadoutModal,
    order,
    retryInitialPage,
    saveCurrentLoadout,
    search,
    searchInput,
    selectedLoadoutIsDefault,
    selectedLoadoutName,
    sentinelRef,
    setAdvancedModalOpen,
    setContentType,
    setDraftFilterState,
    setLoadoutModalOpen,
    setLoadoutNameInput,
    setSelectedAsDefaultLoadout,
    setSelectedLoadoutName,
    setSite,
    setSortBy,
    site,
    sortBy,
    toggleOrder,
    total,
    totalIsExact,
    unhideUser,
  } = useContentLibraryController();

  const autoLoadoutName = buildAutoLoadoutName({
    site,
    search,
    searchInput,
  });

  return (
    <div className="content-library">
      <WorkspacePageHeader
        eyebrow="Content"
        title="Content Library"
        subtitle="Browse indexed media, apply saved loadouts, and narrow the library with site, search, and advanced filters."
        badges={[
          { label: 'Total', value: `${total.toLocaleString()}${totalIsExact ? '' : '+'}`, tone: 'accent' },
          { label: 'Site', value: site || 'All', tone: 'neutral' },
          { label: 'Type', value: contentType, tone: 'neutral' },
          {
            label: 'Filters',
            value: String(activeAdvancedFilterCount),
            tone: activeAdvancedFilterCount > 0 ? 'warning' : 'neutral',
          },
          ...(excludedUserIds.length > 0
            ? [
                {
                  label: 'Hidden Users',
                  value: String(excludedUserIds.length),
                  tone: 'warning' as const,
                },
              ]
            : []),
        ]}
        icon="▣"
      />

      {selectedLoadoutName || activeAdvancedFilterCount > 0 || excludedUserIds.length > 0 ? (
        <OperationsNotice tone="info" title="Curated content view">
          {selectedLoadoutName
            ? `Loadout: ${selectedLoadoutName}. `
            : ''}
          {activeAdvancedFilterCount > 0
            ? `${activeAdvancedFilterCount} advanced filter${activeAdvancedFilterCount === 1 ? '' : 's'} active. `
            : ''}
          {excludedUserIds.length > 0
            ? `${excludedUserIds.length} user${excludedUserIds.length === 1 ? '' : 's'} hidden from results.`
            : 'Use loadouts and advanced filters to pin down high-value slices quickly.'}
        </OperationsNotice>
      ) : null}

      <ContentLibraryToolbar
        activeAdvancedFilterCount={activeAdvancedFilterCount}
        contentType={contentType}
        onContentTypeChange={setContentType}
        onOpenAdvancedFilters={openAdvancedFilters}
        onOpenLoadoutModal={() => openLoadoutModal(autoLoadoutName)}
        onSearchChange={handleSearchInput}
        onSiteChange={setSite}
        onSortByChange={setSortBy}
        onToggleOrder={toggleOrder}
        order={order}
        searchInput={searchInput}
        site={site}
        sortBy={sortBy}
        excludedUserIds={excludedUserIds}
        excludedUsernames={excludedUsernames}
        onUnhideUser={unhideUser}
        onClearHiddenUsers={clearHiddenUsers}
      />

      <ContentLibraryResults
        error={error}
        hasMore={hasMore}
        items={items}
        loading={loading}
        onRetry={retryInitialPage}
        searchText={search}
        sentinelRef={sentinelRef}
        total={total}
        totalIsExact={totalIsExact}
        onHideUser={hideUser}
      />

      {loadoutModalOpen && (
        <ContentLibraryLoadoutModal
          loadoutNameInput={loadoutNameInput}
          loadouts={loadouts}
          onAutofill={() => setLoadoutNameInput(autoLoadoutName)}
          onClose={() => setLoadoutModalOpen(false)}
          onDelete={() => {
            void deleteSelectedLoadout();
          }}
          onInputChange={setLoadoutNameInput}
          onLoadoutSelect={(value) => {
            setSelectedLoadoutName(value);
            setLoadoutNameInput(value);
            const loadout = loadouts.find((entry) => entry.name === value);
            if (loadout) {
              applyContentLoadout(loadout);
            }
          }}
          onSaveCurrent={() => {
            const name = loadoutNameInput.trim() || autoLoadoutName;
            if (!name) {
              return;
            }
            void saveCurrentLoadout(name);
          }}
          onToggleDefault={() => {
            if (selectedLoadoutIsDefault) {
              void clearDefaultLoadout();
              return;
            }
            void setSelectedAsDefaultLoadout();
          }}
          selectedLoadoutIsDefault={selectedLoadoutIsDefault}
          selectedLoadoutName={selectedLoadoutName}
          suggestedName={autoLoadoutName}
        />
      )}

      {advancedModalOpen && (
        <ContentLibraryAdvancedFiltersModal
          draftAdvancedFilters={draftAdvancedFilters}
          onApply={applyAdvancedFilters}
          onClear={clearDraftAdvancedFilters}
          onClose={() => setAdvancedModalOpen(false)}
          onFilterStateChange={setDraftFilterState}
        />
      )}
    </div>
  );
}
