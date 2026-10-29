import {
  ADVANCED_FILTER_OPTIONS,
  type AdvancedFilterKey,
  type AdvancedFilterMap,
} from '../lib/contentLibraryUtils';

interface ContentLibraryAdvancedFiltersModalProps {
  draftAdvancedFilters: AdvancedFilterMap;
  onApply: () => void;
  onClear: () => void;
  onClose: () => void;
  onFilterStateChange: (key: AdvancedFilterKey, value: 'none' | 'include' | 'exclude') => void;
}

const MEDIA_TYPES = [
  { key: 'has_video' as const, label: 'Videos' },
  { key: 'has_photo' as const, label: 'Photos' },
  { key: 'has_audio' as const, label: 'Audio' },
] as const;

export function ContentLibraryAdvancedFiltersModal({
  draftAdvancedFilters,
  onApply,
  onClear,
  onClose,
  onFilterStateChange,
}: ContentLibraryAdvancedFiltersModalProps) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content content-library-filter-modal" onClick={(event) => event.stopPropagation()}>
        <div className="content-library-filter-modal-header">
          <h3>Advanced Filters</h3>
          <button className="content-library-filter-close" onClick={onClose}>
            ×
          </button>
        </div>
        <p className="content-library-filter-help">
          Use <strong>+</strong> to include and <strong>-</strong> to exclude matching content.
        </p>
        <div className="content-library-filter-list">
          <div className="content-library-filter-row media-types-multi-row">
            <span className="content-library-filter-name">Media Types</span>
            <div className="media-types-toggle-group">
              {MEDIA_TYPES.map((type) => {
                const isSelected = draftAdvancedFilters[type.key] === 'include';
                return (
                  <button
                    key={type.key}
                    type="button"
                    className={`media-type-toggle-btn ${isSelected ? 'active' : ''}`}
                    onClick={() =>
                      onFilterStateChange(type.key, isSelected ? 'none' : 'include')
                    }
                  >
                    {isSelected ? '✓ ' : ''}{type.label}
                  </button>
                );
              })}
            </div>
          </div>
          {ADVANCED_FILTER_OPTIONS.map((option) => {
            const state = draftAdvancedFilters[option.key];
            return (
              <div key={option.key} className="content-library-filter-row">
                <span className="content-library-filter-name">{option.label}</span>
                <div className="content-library-filter-actions">
                  <button
                    className={`content-library-filter-state-btn ${state === 'exclude' ? 'active' : ''}`}
                    onClick={() =>
                      onFilterStateChange(option.key, state === 'exclude' ? 'none' : 'exclude')
                    }
                    title="Exclude (-)"
                  >
                    -
                  </button>
                  <button
                    className={`content-library-filter-state-btn ${state === 'none' ? 'active' : ''}`}
                    onClick={() => onFilterStateChange(option.key, 'none')}
                    title="No filter"
                  >
                    ·
                  </button>
                  <button
                    className={`content-library-filter-state-btn ${state === 'include' ? 'active' : ''}`}
                    onClick={() =>
                      onFilterStateChange(option.key, state === 'include' ? 'none' : 'include')
                    }
                    title="Include (+)"
                  >
                    +
                  </button>
                </div>
              </div>
            );
          })}
        </div>
        <div className="content-library-filter-footer">
          <button className="btn-secondary" onClick={onClear}>
            Clear
          </button>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={onApply}>
            Apply
          </button>
        </div>
      </div>
    </div>
  );
}
