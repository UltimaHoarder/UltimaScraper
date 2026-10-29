interface UsersSelectionBarProps {
  selectedCount: number;
  totalUsers: number;
  isCreatingJob: boolean;
  isAuthPickerLoading: boolean;
  isWatching: boolean;
  isIgnoring: boolean;
  isSettingIdentity: boolean;
  onSelectAll: () => void;
  onClearSelection: () => void;
  onScrapeSelected: () => void;
  onWatchSelected: () => void;
  onIgnoreSelected: () => void;
  onSetIdentitySelected: () => void;
}

export function UsersSelectionBar({
  selectedCount,
  totalUsers,
  isCreatingJob,
  isAuthPickerLoading,
  isWatching,
  isIgnoring,
  isSettingIdentity,
  onSelectAll,
  onClearSelection,
  onScrapeSelected,
  onWatchSelected,
  onIgnoreSelected,
  onSetIdentitySelected,
}: UsersSelectionBarProps) {
  return (
    <>
      <div className="selection-bar">
        <div className="selection-info">
          <span className="selection-count">
            {selectedCount > 0 ? `${selectedCount} selected` : 'Click cards to select'}
          </span>
          {totalUsers > 0 && (
            <span className="selection-shortcuts">Ctrl/Cmd+A selects visible · Esc clears</span>
          )}
          {selectedCount < totalUsers && totalUsers > 0 && (
            <button type="button" className="btn-select-all" onClick={onSelectAll}>
              Select All ({totalUsers})
            </button>
          )}
          {selectedCount > 0 && (
            <button type="button" className="btn-clear-selection" onClick={onClearSelection}>
              Clear Selection
            </button>
          )}
        </div>
        <div className="selection-bar-actions">
          <button
            type="button"
            className="btn-scrape-multiple"
            onClick={onScrapeSelected}
            disabled={selectedCount === 0 || isCreatingJob || isAuthPickerLoading}
          >
            Scrape ({selectedCount})
          </button>
          <button
            type="button"
            className="btn-watch-multiple"
            onClick={onWatchSelected}
            disabled={selectedCount === 0 || isWatching}
          >
            Watch ({selectedCount})
          </button>
          <button
            type="button"
            className="btn-ignore-multiple"
            onClick={onIgnoreSelected}
            disabled={selectedCount === 0 || isIgnoring}
          >
            Ignore ({selectedCount})
          </button>
          <button
            type="button"
            className="btn-identity-multiple"
            onClick={onSetIdentitySelected}
            disabled={selectedCount === 0 || isSettingIdentity}
          >
            Set Identity ({selectedCount})
          </button>
        </div>
      </div>

      {selectedCount > 0 && (
        <div
          className="selection-bar-floating"
          role="toolbar"
          aria-label="Floating selection actions"
        >
          <div className="selection-info">
            <span className="selection-count">{selectedCount} selected</span>
            {selectedCount < totalUsers && totalUsers > 0 && (
              <button
                type="button"
                className="btn-select-all"
                onClick={onSelectAll}
              >
                Select All ({totalUsers})
              </button>
            )}
            <button
              type="button"
              className="btn-clear-selection"
              onClick={onClearSelection}
            >
              Clear
            </button>
          </div>
          <div className="selection-bar-floating__divider" />
          <div className="selection-bar-actions">
            <button
              type="button"
              className="btn-scrape-multiple"
              onClick={onScrapeSelected}
              disabled={isCreatingJob || isAuthPickerLoading}
            >
              Scrape ({selectedCount})
            </button>
            <button
              type="button"
              className="btn-watch-multiple"
              onClick={onWatchSelected}
              disabled={isWatching}
            >
              Watch ({selectedCount})
            </button>
            <button
              type="button"
              className="btn-ignore-multiple"
              onClick={onIgnoreSelected}
              disabled={isIgnoring}
            >
              Ignore ({selectedCount})
            </button>
            <button
              type="button"
              className="btn-identity-multiple"
              onClick={onSetIdentitySelected}
              disabled={isSettingIdentity}
            >
              Set Identity ({selectedCount})
            </button>
          </div>
        </div>
      )}
    </>
  );
}
