/**
 * Shared FilterBar component used by Subscriptions, Users, and Content pages.
 *
 * Structure:
 *   Primary row  — search input + primaryExtras (site, auth, etc.)
 *   Secondary row — sort-field select + direction-arrow button + secondaryExtras (toggles, filter btn)
 */

import React from 'react';
import './FilterBar.css';

export interface SortOption {
  value: string;
  label: string;
}

export interface FilterBarProps {
  // ── Search ──────────────────────────────────────────────────────────────
  searchValue: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder?: string;

  // ── Sort ────────────────────────────────────────────────────────────────
  sortOptions: SortOption[];
  sortBy: string;
  onSortByChange: (value: string) => void;
  sortOrder: 'asc' | 'desc';
  onSortOrderToggle: () => void;

  // ── Extensible slots ────────────────────────────────────────────────────
  /** Extra controls placed after the search input in the primary row (site/auth selects, etc.) */
  primaryExtras?: React.ReactNode;
  /** Extra controls placed after the sort controls in the secondary row (toggles, filter buttons, etc.) */
  secondaryExtras?: React.ReactNode;
}

export function FilterBar({
  searchValue,
  onSearchChange,
  searchPlaceholder = 'Search…',
  sortOptions,
  sortBy,
  onSortByChange,
  sortOrder,
  onSortOrderToggle,
  primaryExtras,
  secondaryExtras,
}: FilterBarProps) {
  return (
    <div className="filter-bar">
      {/* ── Primary row: search + extra selects ── */}
      <div className="filter-bar__row filter-bar__row--primary">
        <div className="filter-bar__search-wrap">
          <svg
            className="filter-bar__search-icon"
            viewBox="0 0 20 20"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <circle cx="8.5" cy="8.5" r="5.5" stroke="#666" strokeWidth="1.5" />
            <path d="M13 13l4 4" stroke="#666" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <input
            type="text"
            className="filter-bar__search-input"
            placeholder={searchPlaceholder}
            value={searchValue}
            onChange={(e) => onSearchChange(e.target.value)}
          />
          {searchValue && (
            <button
              type="button"
              className="filter-bar__search-clear"
              onClick={() => onSearchChange('')}
              aria-label="Clear search"
            >
              ×
            </button>
          )}
        </div>

        {primaryExtras}
      </div>

      {/* ── Secondary row: sort + extras ── */}
      <div className="filter-bar__row filter-bar__row--secondary">
        <div className="filter-bar__sort-group">
          <label className="filter-bar__label">Sort</label>
          <div className="filter-bar__sort-controls">
            <select
              className="filter-bar__select"
              value={sortBy}
              onChange={(e) => onSortByChange(e.target.value)}
            >
              {sortOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="filter-bar__order-btn"
              onClick={onSortOrderToggle}
              title={
                sortOrder === 'desc'
                  ? 'Descending — click to sort ascending'
                  : 'Ascending — click to sort descending'
              }
            >
              {sortOrder === 'desc' ? '↓' : '↑'}
            </button>
          </div>
        </div>

        {secondaryExtras}
      </div>
    </div>
  );
}

// ─── Helper sub-components for common extras ─────────────────────────────────

interface SelectGroupProps {
  label: string;
  value: string | number;
  onChange: (value: string) => void;
  children: React.ReactNode;
  minWidth?: number;
}

/** A labelled select dropdown for use inside primaryExtras / secondaryExtras. */
export function FilterSelect({ label, value, onChange, children, minWidth }: SelectGroupProps) {
  return (
    <div className="filter-bar__group">
      <label className="filter-bar__label">{label}</label>
      <select
        className="filter-bar__select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={minWidth ? { minWidth } : undefined}
      >
        {children}
      </select>
    </div>
  );
}

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}

/** A toggle switch for use inside secondaryExtras. */
export function FilterToggle({ checked, onChange, label }: ToggleProps) {
  return (
    <label className="filter-bar__toggle">
      <span className="filter-bar__toggle-track">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span className="filter-bar__toggle-thumb" />
      </span>
      <span className="filter-bar__toggle-label">{label}</span>
    </label>
  );
}
