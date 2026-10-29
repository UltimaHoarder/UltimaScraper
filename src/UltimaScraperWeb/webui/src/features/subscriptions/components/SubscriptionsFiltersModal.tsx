import { FilterToggle } from '../../../components/shared/FilterBar';

interface SubscriptionsFiltersModalProps {
  draftActiveOnly: boolean;
  draftMinPrice: string;
  draftMaxPrice: string;
  draftSexFilter: number[];
  onClose: () => void;
  onDraftActiveOnlyChange: (value: boolean) => void;
  onDraftMinPriceChange: (value: string) => void;
  onDraftMaxPriceChange: (value: string) => void;
  onDraftSexFilterChange: (value: number[]) => void;
  onClear: () => void;
  onApply: () => void;
}

const SEX_OPTIONS = [
  { value: 0, label: 'Female' },
  { value: 1, label: 'Male' },
  { value: 2, label: 'Other' },
];

export function SubscriptionsFiltersModal({
  draftActiveOnly,
  draftMinPrice,
  draftMaxPrice,
  draftSexFilter,
  onClose,
  onDraftActiveOnlyChange,
  onDraftMinPriceChange,
  onDraftMaxPriceChange,
  onDraftSexFilterChange,
  onClear,
  onApply,
}: SubscriptionsFiltersModalProps) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-content content-library-filter-modal"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="content-library-filter-modal-header">
          <h3>Advanced Filters</h3>
          <button
            type="button"
            className="content-library-filter-close"
            onClick={onClose}
            aria-label="Close filters"
          >
            ×
          </button>
        </div>
        <p className="content-library-filter-help">Adjust which subscriptions are shown.</p>

        <div className="content-library-filter-list">
          <div className="content-library-filter-row">
            <span className="content-library-filter-name">Active Status</span>
            <FilterToggle
              checked={draftActiveOnly}
              onChange={onDraftActiveOnlyChange}
              label="Active Only"
            />
          </div>

          <div className="content-library-filter-row">
            <span className="content-library-filter-name">Price Range</span>
            <div className="content-library-filter-value">
              <div className="price-range-inputs-inline">
                <input
                  type="number"
                  value={draftMinPrice}
                  onChange={(event) => onDraftMinPriceChange(event.target.value)}
                  placeholder="Min"
                  min="0"
                  step="0.01"
                  className="price-range-input"
                />
                <span className="price-range-separator">to</span>
                <input
                  type="number"
                  value={draftMaxPrice}
                  onChange={(event) => onDraftMaxPriceChange(event.target.value)}
                  placeholder="Max"
                  min="0"
                  step="0.01"
                  className="price-range-input"
                />
              </div>
            </div>
          </div>

          <div className="content-library-filter-row">
            <span className="content-library-filter-name">Sex</span>
            <div className="content-library-filter-value">
              <div className="sex-filter-options">
                {SEX_OPTIONS.map((option) => (
                  <label key={option.value} className="sex-filter-option">
                    <input
                      type="checkbox"
                      checked={draftSexFilter.includes(option.value)}
                      onChange={(event) => {
                        if (event.target.checked) {
                          onDraftSexFilterChange([...draftSexFilter, option.value].sort());
                        } else {
                          onDraftSexFilterChange(
                            draftSexFilter.filter((value) => value !== option.value)
                          );
                        }
                      }}
                    />
                    <span>{option.label}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="content-library-filter-footer">
          <button type="button" className="btn-secondary" onClick={onClear}>
            Clear
          </button>
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn-primary" onClick={onApply}>
            Apply
          </button>
        </div>
      </div>
    </div>
  );
}
