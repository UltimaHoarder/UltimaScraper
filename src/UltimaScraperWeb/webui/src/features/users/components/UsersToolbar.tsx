import type { ReactNode } from 'react';
import './UsersToolbar.css';

export interface UsersToolbarProps {
  // Identifier search
  searchTerm: string;
  onSearchTermChange: (value: string) => void;
  onSearchTermClear: () => void;
  searchPlaceholder?: string;

  // Description search (optional)
  searchDescriptionTerm?: string;
  onSearchDescriptionChange?: (value: string) => void;
  onSearchDescriptionClear?: () => void;

  // Site filter
  selectedSite: string;
  onSelectedSiteChange: (site: string) => void;
  siteOptions?: Array<{ value: string; label: string }>;

  // Extra controls (e.g. Auth select)
  extraControls?: ReactNode;

  // Sort controls
  sortBy: string;
  onSortByChange: (sortBy: string) => void;
  sortOptions: Array<{ value: string; label: string }>;
  sortOrder: 'asc' | 'desc';
  onSortOrderToggle: () => void;

  // Merged Filters (includes loadouts & filters)
  onOpenFiltersModal?: () => void;
  activeFilterCount?: number;
  selectedLoadoutName?: string;

  // Result metrics
  loadedCount?: number;
  totalCount?: number | null;
  totalUsers?: number;
}

export function UsersToolbar({
  searchTerm,
  onSearchTermChange,
  onSearchTermClear,
  searchPlaceholder = 'Search by identifier…',
  searchDescriptionTerm,
  onSearchDescriptionChange,
  onSearchDescriptionClear,
  selectedSite,
  onSelectedSiteChange,
  siteOptions,
  extraControls,
  sortBy,
  onSortByChange,
  sortOptions,
  sortOrder,
  onSortOrderToggle,
  onOpenFiltersModal,
  activeFilterCount = 0,
  selectedLoadoutName,
  loadedCount,
  totalCount,
  totalUsers = 0,
}: UsersToolbarProps) {
  const isFilterActive = activeFilterCount > 0 || Boolean(selectedLoadoutName);

  return (
    <div className="users-toolbar" role="toolbar" aria-label="Roster query controls">
      {/* 1. Identifier Box */}
      <label className="users-toolbar__search" title="Search by username, display name, or numeric ID">
        <span className="users-toolbar__icon" aria-hidden="true">🔍</span>
        <input
          type="text"
          aria-label="Search by identifier"
          placeholder={searchPlaceholder}
          value={searchTerm}
          onChange={(e) => onSearchTermChange(e.target.value)}
        />
        {searchTerm ? (
          <button
            type="button"
            className="users-toolbar__clear"
            onClick={onSearchTermClear}
            aria-label="Clear identifier search"
          >
            ×
          </button>
        ) : null}
      </label>

      {/* 2. Description Box (optional) */}
      {searchDescriptionTerm !== undefined && onSearchDescriptionChange && (
        <label className="users-toolbar__search users-toolbar__search--desc" title="Search biography text and profile description">
          <span className="users-toolbar__icon" aria-hidden="true">📝</span>
          <input
            type="text"
            aria-label="Search by description"
            placeholder="Search by description…"
            value={searchDescriptionTerm}
            onChange={(e) => onSearchDescriptionChange(e.target.value)}
          />
          {searchDescriptionTerm && onSearchDescriptionClear ? (
            <button
              type="button"
              className="users-toolbar__clear"
              onClick={onSearchDescriptionClear}
              aria-label="Clear description search"
            >
              ×
            </button>
          ) : null}
        </label>
      )}

      {/* 3. Site selector */}
      <select
        aria-label="Filter by site"
        className="users-toolbar__select"
        value={selectedSite}
        onChange={(e) => onSelectedSiteChange(e.target.value)}
      >
        {siteOptions ? (
          siteOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))
        ) : (
          <>
            <option value="">All Sites</option>
            <option value="onlyfans">OnlyFans</option>
            <option value="fansly">Fansly</option>
          </>
        )}
      </select>

      {/* Extra selects/controls (e.g. Auth select) */}
      {extraControls}

      {/* 4. Sort dropdown & direction toggle */}
      <div className="users-toolbar__sort-group">
        <select
          aria-label="Sort roster"
          className="users-toolbar__select"
          value={sortBy}
          onChange={(e) => onSortByChange(e.target.value)}
        >
          {sortOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>
              Sort: {opt.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="users-toolbar__order-btn"
          onClick={onSortOrderToggle}
          title={
            sortOrder === 'desc'
              ? 'Descending — click to sort ascending'
              : 'Ascending — click to sort descending'
          }
          aria-label={`Sort order: ${sortOrder === 'desc' ? 'descending' : 'ascending'}`}
        >
          {sortOrder === 'desc' ? '↓' : '↑'}
        </button>
      </div>

      {/* 5. Merged Filters button (optional) */}
      {onOpenFiltersModal && (
        <button
          type="button"
          className={`users-toolbar__btn ${isFilterActive ? 'users-toolbar__btn--active' : ''}`}
          onClick={onOpenFiltersModal}
          aria-label={`Filters${(activeFilterCount ?? 0) > 0 ? ` (${activeFilterCount})` : ''}`}
        >
          <span>⚙️</span>
          <span>Filters</span>
          {(activeFilterCount ?? 0) > 0 ? (
            <span className="users-toolbar__badge">{activeFilterCount}</span>
          ) : null}
          {selectedLoadoutName ? (
            <span className="users-toolbar__pill" title={`Active loadout: ${selectedLoadoutName}`}>
              {selectedLoadoutName}
            </span>
          ) : null}
        </button>
      )}

      {/* 6. Result count */}
      <span className="users-toolbar__count">
        {totalCount != null && totalCount > 0
          ? `${(loadedCount ?? totalUsers).toLocaleString()} / ${totalCount.toLocaleString()} visible`
          : `${totalUsers.toLocaleString()} creators`}
      </span>
    </div>
  );
}
