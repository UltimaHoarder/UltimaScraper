import { CONTENT_TYPES, SORT_OPTIONS } from '../lib/contentLibraryUtils';

interface ContentLibraryToolbarProps {
  activeAdvancedFilterCount: number;
  contentType: string;
  onContentTypeChange: (value: string) => void;
  onOpenAdvancedFilters: () => void;
  onOpenLoadoutModal: () => void;
  onSearchChange: (value: string) => void;
  onSiteChange: (value: string) => void;
  onSortByChange: (value: string) => void;
  onToggleOrder: () => void;
  order: 'asc' | 'desc';
  searchInput: string;
  site: string;
  sortBy: string;
  excludedUserIds?: number[];
  excludedUsernames?: Record<number, string>;
  onUnhideUser?: (userId: number) => void;
  onClearHiddenUsers?: () => void;
}

export function ContentLibraryToolbar({
  activeAdvancedFilterCount,
  contentType,
  onContentTypeChange,
  onOpenAdvancedFilters,
  onOpenLoadoutModal,
  onSearchChange,
  onSiteChange,
  onSortByChange,
  onToggleOrder,
  order,
  searchInput,
  site,
  sortBy,
  excludedUserIds,
  excludedUsernames,
  onUnhideUser,
  onClearHiddenUsers,
}: ContentLibraryToolbarProps) {
  return (
    <div className="content-library-toolbar">
      <div className="content-library-filters">
        <div className="content-library-tabs">
          {CONTENT_TYPES.map((contentOption) => (
            <button
              key={contentOption.value}
              className={`content-library-tab ${contentType === contentOption.value ? 'active' : ''}`}
              onClick={() => onContentTypeChange(contentOption.value)}
            >
              {contentOption.label}
            </button>
          ))}
        </div>

        <select
          className="content-library-select"
          value={site}
          onChange={(event) => onSiteChange(event.target.value)}
        >
          <option value="">All Sites</option>
          <option value="onlyfans">OnlyFans</option>
          <option value="fansly">Fansly</option>
        </select>
      </div>

      <div className="content-library-controls">
        <div className="content-library-search">
          <span className="content-library-search-icon">🔍</span>
          <input
            type="text"
            className="content-library-search-input"
            placeholder="Search content..."
            value={searchInput}
            onChange={(event) => onSearchChange(event.target.value)}
          />
        </div>

        <div className="content-library-sort">
          <label className="content-library-sort-label">Sort by:</label>
          <select
            className="content-library-select"
            value={sortBy}
            onChange={(event) => onSortByChange(event.target.value)}
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button
            className="content-library-order-btn"
            onClick={onToggleOrder}
            title={order === 'desc' ? 'Newest first' : 'Oldest first'}
          >
            {order === 'desc' ? '↓' : '↑'}
          </button>
          <button className="content-library-filter-btn" onClick={onOpenAdvancedFilters}>
            Filters{activeAdvancedFilterCount > 0 ? ` (${activeAdvancedFilterCount})` : ''}
          </button>
          <button className="content-library-filter-btn" onClick={onOpenLoadoutModal}>
            Loadouts
          </button>
        </div>
      </div>

      {excludedUserIds && excludedUserIds.length > 0 && (
        <div className="content-library-hidden-users">
          <span className="content-library-hidden-users-label">
            🚫 Hidden from results ({excludedUserIds.length}):
          </span>
          <div className="content-library-hidden-users-chips">
            {excludedUserIds.map((userId) => (
              <span key={userId} className="content-library-hidden-chip">
                {excludedUsernames?.[userId] ? `@${excludedUsernames[userId]}` : `User ${userId}`}
                {onUnhideUser && (
                  <button
                    type="button"
                    className="content-library-hidden-chip-remove"
                    onClick={() => onUnhideUser(userId)}
                    title="Unhide user"
                  >
                    ×
                  </button>
                )}
              </span>
            ))}
          </div>
          {onClearHiddenUsers && (
            <button
              type="button"
              className="content-library-hidden-users-clear"
              onClick={onClearHiddenUsers}
            >
              Clear hidden
            </button>
          )}
        </div>
      )}
    </div>
  );
}
