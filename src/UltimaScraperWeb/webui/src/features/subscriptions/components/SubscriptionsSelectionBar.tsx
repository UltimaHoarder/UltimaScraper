interface SubscriptionsSelectionBarProps {
  selectedCount: number;
  visibleCount: number;
  createJobPending: boolean;
  onSelectAll: () => void;
  onClear: () => void;
  onScrape: () => void;
  onWatch: () => void;
  onIgnore: () => void;
}

export function SubscriptionsSelectionBar({
  selectedCount,
  visibleCount,
  createJobPending,
  onSelectAll,
  onClear,
  onScrape,
  onWatch,
  onIgnore,
}: SubscriptionsSelectionBarProps) {
  return (
    <>
      <div className="selection-bar">
        <div className="selection-info">
          <span className="selection-count">
            {selectedCount > 0 ? `${selectedCount} selected` : 'Click cards to select'}
          </span>
          {visibleCount > 0 && (
            <span className="selection-shortcuts">Ctrl/Cmd+A selects visible · Esc clears</span>
          )}
          {selectedCount < visibleCount && (
            <button type="button" className="btn-select-all" onClick={onSelectAll}>
              Select All ({visibleCount})
            </button>
          )}
          {selectedCount > 0 && (
            <button type="button" className="btn-clear-selection" onClick={onClear}>
              Clear Selection
            </button>
          )}
        </div>
        <div className="selection-bar-actions">
          <button
            type="button"
            className="btn-scrape-multiple"
            onClick={onScrape}
            disabled={selectedCount === 0 || createJobPending}
          >
            Scrape ({selectedCount})
          </button>
          <button
            type="button"
            className="btn-watch-multiple"
            onClick={onWatch}
            disabled={selectedCount === 0}
          >
            Watch ({selectedCount})
          </button>
          <button
            type="button"
            className="btn-ignore-multiple"
            onClick={onIgnore}
            disabled={selectedCount === 0}
          >
            Ignore ({selectedCount})
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
            {selectedCount < visibleCount && (
              <button
                type="button"
                className="btn-select-all"
                onClick={onSelectAll}
              >
                Select All ({visibleCount})
              </button>
            )}
            <button
              type="button"
              className="btn-clear-selection"
              onClick={onClear}
            >
              Clear
            </button>
          </div>
          <div className="selection-bar-floating__divider" />
          <div className="selection-bar-actions">
            <button
              type="button"
              className="btn-scrape-multiple"
              onClick={onScrape}
              disabled={createJobPending}
            >
              Scrape ({selectedCount})
            </button>
            <button
              type="button"
              className="btn-watch-multiple"
              onClick={onWatch}
            >
              Watch ({selectedCount})
            </button>
            <button
              type="button"
              className="btn-ignore-multiple"
              onClick={onIgnore}
            >
              Ignore ({selectedCount})
            </button>
          </div>
        </div>
      )}
    </>
  );
}
