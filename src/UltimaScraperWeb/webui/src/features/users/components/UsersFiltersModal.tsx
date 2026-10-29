import type { ReactNode } from 'react';
import type { SearchLoadoutItem } from '../../../api/types/loadouts';
import { FilterToggle } from '../../../components/shared/FilterBar';
import {
  DEFAULT_USER_FILTERS,
  GENDER_FILTER_OPTIONS,
  PROFILE_TYPE_FILTER_OPTIONS,
  SEX_FILTER_OPTIONS,
  SEXUAL_CONTENT_FILTER_OPTIONS,
  USER_FILTER_OPTIONS,
  type UserFilterKey,
  type UserFilterMap,
  type UserFilterState,
} from '../lib/usersUtils';

interface UsersFiltersModalProps {
  isOpen: boolean;
  title?: string;
  help?: ReactNode;
  extraFilters?: ReactNode;
  onClearExtraFilters?: () => void;
  clearActiveOnly?: boolean;
  clearUserFilters?: UserFilterMap;
  loadouts?: SearchLoadoutItem[];
  selectedLoadoutName?: string;
  selectedLoadoutIsDefault?: boolean;
  loadoutNameInput?: string;
  placeholderLoadoutName?: string;
  onSelectedLoadoutChange?: (value: string) => void;
  onLoadoutNameInputChange?: (value: string) => void;
  onAutofillLoadoutName?: () => void;
  onDeleteLoadout?: () => void;
  onToggleDefaultLoadout?: () => void;
  onSaveLoadout?: () => void;
  draftActiveOnly: boolean;
  draftSexFilter: number[];
  draftGenderFilter: number[];
  draftProfileTypeFilter: number[];
  draftSexualContentFilter: number[];
  draftUserFilters: UserFilterMap;
  draftMinPrice: string;
  draftMaxPrice: string;
  draftMinPostCount: string;
  draftMaxPostCount: string;
  draftMinImageCount: string;
  draftMaxImageCount: string;
  draftMinVideoCount: string;
  draftMaxVideoCount: string;
  onClose: () => void;
  onApply: () => void;
  onDraftActiveOnlyChange: (value: boolean) => void;
  onDraftSexFilterChange: (value: number[]) => void;
  onDraftGenderFilterChange: (value: number[]) => void;
  onDraftProfileTypeFilterChange: (value: number[]) => void;
  onDraftSexualContentFilterChange: (value: number[]) => void;
  onDraftUserFiltersChange: (value: UserFilterMap) => void;
  onDraftMinPriceChange: (value: string) => void;
  onDraftMaxPriceChange: (value: string) => void;
  onDraftMinPostCountChange: (value: string) => void;
  onDraftMaxPostCountChange: (value: string) => void;
  onDraftMinImageCountChange: (value: string) => void;
  onDraftMaxImageCountChange: (value: string) => void;
  onDraftMinVideoCountChange: (value: string) => void;
  onDraftMaxVideoCountChange: (value: string) => void;
}

function setDraftUserFilterState(
  currentFilters: UserFilterMap,
  key: UserFilterKey,
  state: UserFilterState
) {
  return {
    ...currentFilters,
    [key]: state,
  };
}

export function UsersFiltersModal({
  isOpen,
  title = 'Advanced Filters',
  help,
  extraFilters,
  onClearExtraFilters,
  clearActiveOnly = true,
  clearUserFilters = DEFAULT_USER_FILTERS,
  loadouts,
  selectedLoadoutName,
  selectedLoadoutIsDefault,
  loadoutNameInput,
  placeholderLoadoutName,
  onSelectedLoadoutChange,
  onLoadoutNameInputChange,
  onAutofillLoadoutName,
  onDeleteLoadout,
  onToggleDefaultLoadout,
  onSaveLoadout,
  draftActiveOnly,
  draftSexFilter,
  draftGenderFilter,
  draftProfileTypeFilter,
  draftSexualContentFilter,
  draftUserFilters,
  draftMinPrice,
  draftMaxPrice,
  draftMinPostCount,
  draftMaxPostCount,
  draftMinImageCount,
  draftMaxImageCount,
  draftMinVideoCount,
  draftMaxVideoCount,
  onClose,
  onApply,
  onDraftActiveOnlyChange,
  onDraftSexFilterChange,
  onDraftGenderFilterChange,
  onDraftProfileTypeFilterChange,
  onDraftSexualContentFilterChange,
  onDraftUserFiltersChange,
  onDraftMinPriceChange,
  onDraftMaxPriceChange,
  onDraftMinPostCountChange,
  onDraftMaxPostCountChange,
  onDraftMinImageCountChange,
  onDraftMaxImageCountChange,
  onDraftMinVideoCountChange,
  onDraftMaxVideoCountChange,
}: UsersFiltersModalProps) {
  if (!isOpen) {
    return null;
  }

  const handleClear = () => {
    onDraftUserFiltersChange(clearUserFilters);
    onDraftActiveOnlyChange(clearActiveOnly);
    onClearExtraFilters?.();
    onDraftSexFilterChange([]);
    onDraftGenderFilterChange([]);
    onDraftProfileTypeFilterChange([]);
    onDraftSexualContentFilterChange([]);
    onDraftMinPriceChange('');
    onDraftMaxPriceChange('');
    onDraftMinPostCountChange('');
    onDraftMaxPostCountChange('');
    onDraftMinImageCountChange('');
    onDraftMaxImageCountChange('');
    onDraftMinVideoCountChange('');
    onDraftMaxVideoCountChange('');
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-content content-library-filter-modal"
        role="dialog" aria-modal="true" aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="content-library-filter-modal-header">
          <h3>{title}</h3>
          <button className="content-library-filter-close" aria-label="Close filters" onClick={onClose}>
            ×
          </button>
        </div>
        <p className="content-library-filter-help">
          {help ?? <>Use <strong>+</strong> to include and <strong>-</strong> to exclude matching users.</>}
        </p>

        {extraFilters}

        {/* ── Saved Loadout Presets (Merged) ── */}
        {loadouts !== undefined && (
          <div className="content-library-filter-row users-filter-loadout-row">
            <span className="content-library-filter-name">Preset Loadout</span>
            <div className="content-library-filter-value users-filter-loadout-controls">
              <select
                aria-label="Preset Loadout"
                className="filter-bar__select users-filter-loadout-select"
                value={selectedLoadoutName || ''}
                onChange={(event) => onSelectedLoadoutChange?.(event.target.value)}
              >
                <option value="">{loadouts.length === 0 ? 'Custom / None (no saved presets)' : 'Custom / None'}</option>
                {loadouts.map((loadout) => (
                  <option key={loadout.name} value={loadout.name}>
                    {loadout.name}
                    {loadout.is_default ? ' (default)' : ''}
                  </option>
                ))}
              </select>
              {selectedLoadoutName ? (
                <div className="users-filter-loadout-actions">
                  <button
                    type="button"
                    className="btn-cancel btn-sm"
                    onClick={onToggleDefaultLoadout}
                    title={selectedLoadoutIsDefault ? 'Unset Default' : 'Set Default'}
                  >
                    {selectedLoadoutIsDefault ? 'Unset Default' : 'Set Default'}
                  </button>
                  <button
                    type="button"
                    className="btn-cancel btn-sm"
                    onClick={onDeleteLoadout}
                    title="Delete Loadout"
                  >
                    Delete
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        )}

        {onSaveLoadout && (
          <div className="content-library-filter-row users-filter-save-row">
            <span className="content-library-filter-name">Save As Loadout</span>
            <div className="content-library-filter-value users-filter-save-controls">
              <input
                type="text"
                value={loadoutNameInput || ''}
                onChange={(event) => onLoadoutNameInputChange?.(event.target.value)}
                placeholder={placeholderLoadoutName || 'Preset name…'}
                className="price-range-input users-filter-save-input"
              />
              <button
                type="button"
                className="btn-secondary btn-sm"
                onClick={onAutofillLoadoutName}
              >
                Autofill
              </button>
              <button
                type="button"
                className="btn-secondary btn-sm"
                onClick={onSaveLoadout}
              >
                Save
              </button>
            </div>
          </div>
        )}

        <div className="content-library-filter-row">
          <span className="content-library-filter-name">Active Status</span>
          <FilterToggle
            checked={draftActiveOnly}
            onChange={onDraftActiveOnlyChange}
            label="Active Only"
          />
        </div>

        <div className="content-library-filter-row">
          <span className="content-library-filter-name">Sex</span>
          <div className="content-library-filter-value">
            <div className="sex-filter-options">
              {SEX_FILTER_OPTIONS.map((option) => (
                <label key={option.value} className="sex-filter-option">
                  <input
                    type="checkbox"
                    checked={draftSexFilter.includes(option.value)}
                    onChange={(event) => {
                      if (event.target.checked) {
                        onDraftSexFilterChange([...draftSexFilter, option.value].sort());
                        return;
                      }

                      onDraftSexFilterChange(
                        draftSexFilter.filter((value) => value !== option.value)
                      );
                    }}
                  />
                  <span>{option.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>

        <div className="content-library-filter-row">
          <span className="content-library-filter-name">Gender</span>
          <div className="content-library-filter-value">
            <div className="sex-filter-options">
              {GENDER_FILTER_OPTIONS.map((option) => (
                <label key={option.value} className="sex-filter-option">
                  <input
                    type="checkbox"
                    checked={draftGenderFilter.includes(option.value)}
                    onChange={(event) => {
                      if (event.target.checked) {
                        onDraftGenderFilterChange([...draftGenderFilter, option.value].sort());
                        return;
                      }

                      onDraftGenderFilterChange(
                        draftGenderFilter.filter((value) => value !== option.value)
                      );
                    }}
                  />
                  <span>{option.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>

        <div className="content-library-filter-row">
          <span className="content-library-filter-name">Profile Type</span>
          <div className="content-library-filter-value">
            <div className="sex-filter-options">
              {PROFILE_TYPE_FILTER_OPTIONS.map((option) => (
                <label key={option.value} className="sex-filter-option">
                  <input
                    type="checkbox"
                    checked={draftProfileTypeFilter.includes(option.value)}
                    onChange={(event) => {
                      if (event.target.checked) {
                        onDraftProfileTypeFilterChange(
                          [...draftProfileTypeFilter, option.value].sort()
                        );
                        return;
                      }

                      onDraftProfileTypeFilterChange(
                        draftProfileTypeFilter.filter((value) => value !== option.value)
                      );
                    }}
                  />
                  <span>{option.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>

        <div className="content-library-filter-row">
          <span className="content-library-filter-name">Sexual Content</span>
          <div className="content-library-filter-value">
            <div className="sex-filter-options">
              {SEXUAL_CONTENT_FILTER_OPTIONS.map((option) => (
                <label key={option.value} className="sex-filter-option">
                  <input
                    type="checkbox"
                    checked={draftSexualContentFilter.includes(option.value)}
                    onChange={(event) => {
                      if (event.target.checked) {
                        onDraftSexualContentFilterChange(
                          [...draftSexualContentFilter, option.value].sort()
                        );
                        return;
                      }

                      onDraftSexualContentFilterChange(
                        draftSexualContentFilter.filter((value) => value !== option.value)
                      );
                    }}
                  />
                  <span>{option.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>

        <div className="content-library-filter-list">
          {USER_FILTER_OPTIONS.map((option) => {
            const state = draftUserFilters[option.key];

            return (
              <div key={option.key} className="content-library-filter-row">
                <span className="content-library-filter-name">{option.label}</span>
                <div className="content-library-filter-actions">
                  <button
                    type="button"
                    className={`content-library-filter-state-btn ${
                      state === 'exclude' ? 'active' : ''
                    }`}
                    onClick={() =>
                      onDraftUserFiltersChange(
                        setDraftUserFilterState(
                          draftUserFilters,
                          option.key,
                          state === 'exclude' ? 'none' : 'exclude'
                        )
                      )
                    }
                    title="Exclude (-)"
                  >
                    -
                  </button>
                  <button
                    type="button"
                    className={`content-library-filter-state-btn ${
                      state === 'none' ? 'active' : ''
                    }`}
                    onClick={() =>
                      onDraftUserFiltersChange(
                        setDraftUserFilterState(draftUserFilters, option.key, 'none')
                      )
                    }
                    title="No filter"
                  >
                    ·
                  </button>
                  <button
                    type="button"
                    className={`content-library-filter-state-btn ${
                      state === 'include' ? 'active' : ''
                    }`}
                    onClick={() =>
                      onDraftUserFiltersChange(
                        setDraftUserFilterState(
                          draftUserFilters,
                          option.key,
                          state === 'include' ? 'none' : 'include'
                        )
                      )
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

        <div className="content-library-filter-row price-range-row">
          <span className="content-library-filter-name">Price Range</span>
          <div className="content-library-filter-value">
            <div className="price-range-inputs-inline">
            <input
              type="number"
              aria-label="Minimum price"
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
              aria-label="Maximum price"
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

        <div className="content-library-filter-row price-range-row">
          <span className="content-library-filter-name">Post Count Range</span>
          <div className="content-library-filter-value">
            <div className="price-range-inputs-inline">
            <input
              type="number"
              aria-label="Minimum post count"
              value={draftMinPostCount}
              onChange={(event) => onDraftMinPostCountChange(event.target.value)}
              placeholder="Min"
              min="0"
              step="1"
              className="price-range-input"
            />
            <span className="price-range-separator">to</span>
            <input
              type="number"
              aria-label="Maximum post count"
              value={draftMaxPostCount}
              onChange={(event) => onDraftMaxPostCountChange(event.target.value)}
              placeholder="Max"
              min="0"
              step="1"
              className="price-range-input"
            />
            </div>
          </div>
        </div>

        <div className="content-library-filter-row price-range-row">
          <span className="content-library-filter-name">Image Count Range</span>
          <div className="content-library-filter-value">
            <div className="price-range-inputs-inline">
            <input
              type="number"
              aria-label="Minimum image count"
              value={draftMinImageCount}
              onChange={(event) => onDraftMinImageCountChange(event.target.value)}
              placeholder="Min"
              min="0"
              step="1"
              className="price-range-input"
            />
            <span className="price-range-separator">to</span>
            <input
              type="number"
              aria-label="Maximum image count"
              value={draftMaxImageCount}
              onChange={(event) => onDraftMaxImageCountChange(event.target.value)}
              placeholder="Max"
              min="0"
              step="1"
              className="price-range-input"
            />
            </div>
          </div>
        </div>

        <div className="content-library-filter-row price-range-row">
          <span className="content-library-filter-name">Video Count Range</span>
          <div className="content-library-filter-value">
            <div className="price-range-inputs-inline">
            <input
              type="number"
              aria-label="Minimum video count"
              value={draftMinVideoCount}
              onChange={(event) => onDraftMinVideoCountChange(event.target.value)}
              placeholder="Min"
              min="0"
              step="1"
              className="price-range-input"
            />
            <span className="price-range-separator">to</span>
            <input
              type="number"
              aria-label="Maximum video count"
              value={draftMaxVideoCount}
              onChange={(event) => onDraftMaxVideoCountChange(event.target.value)}
              placeholder="Max"
              min="0"
              step="1"
              className="price-range-input"
            />
            </div>
          </div>
        </div>

        <div className="content-library-filter-footer">
          <button type="button" className="btn-secondary" onClick={handleClear}>
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
