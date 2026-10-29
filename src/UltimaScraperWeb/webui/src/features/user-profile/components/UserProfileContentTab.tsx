import type { RefObject } from 'react';

import type { ContentLibraryItem } from '../../../api/types/content';
import { ContentCard } from '../../../components/content/ContentCard';
import {
  ADVANCED_FILTER_OPTIONS,
  SORT_OPTIONS,
  type AdvancedFilterKey,
  type AdvancedFilterMap,
  type AdvancedFilterState,
} from '../lib/userProfileUtils';

interface ContentTypeOption {
  value: string;
  label: string;
}

interface UserProfileContentTabProps {
  activeTab: 'content' | 'paid';
  activeContentTypeOptions: readonly ContentTypeOption[];
  contentType: string;
  onContentTypeChange: (value: string) => void;
  contentSearchInput: string;
  onSearchInput: (value: string) => void;
  contentSortBy: string;
  onContentSortByChange: (value: string) => void;
  contentOrder: 'asc' | 'desc';
  onToggleContentOrder: () => void;
  onOpenContentFilters: () => void;
  activeContentAdvancedFilterCount: number;
  contentTotal: number;
  contentLoading: boolean;
  contentItems: ContentLibraryItem[];
  contentError: string | null;
  onRetryContent: () => void;
  onBuyLockedContent: (item: ContentLibraryItem) => void;
  buyPendingKey: string | null;
  buyPending: boolean;
  sentinelRef: RefObject<HTMLDivElement | null>;
  contentHasMore: boolean;
  contentFilterModalOpen: boolean;
  onCloseContentFilterModal: () => void;
  contentDraftAdvancedFilters: AdvancedFilterMap;
  onSetContentDraftFilterState: (key: AdvancedFilterKey, state: AdvancedFilterState) => void;
  onClearContentDraftFilters: () => void;
  onApplyContentFilters: () => void;
}

const MEDIA_TYPES = [
  { key: 'has_video' as const, label: 'Videos' },
  { key: 'has_photo' as const, label: 'Photos' },
  { key: 'has_audio' as const, label: 'Audio' },
] as const;

export function UserProfileContentTab({
  activeTab,
  activeContentTypeOptions,
  contentType,
  onContentTypeChange,
  contentSearchInput,
  onSearchInput,
  contentSortBy,
  onContentSortByChange,
  contentOrder,
  onToggleContentOrder,
  onOpenContentFilters,
  activeContentAdvancedFilterCount,
  contentTotal,
  contentLoading,
  contentItems,
  contentError,
  onRetryContent,
  onBuyLockedContent,
  buyPendingKey,
  buyPending,
  sentinelRef,
  contentHasMore,
  contentFilterModalOpen,
  onCloseContentFilterModal,
  contentDraftAdvancedFilters,
  onSetContentDraftFilterState,
  onClearContentDraftFilters,
  onApplyContentFilters,
}: UserProfileContentTabProps) {
  return (
    <div className="content-tab">
      <div className="content-library-toolbar">
        <div className="content-library-filters">
          {activeTab === 'paid' && (
            <div className="paid-content-banner">
              <span className="paid-content-banner-icon">💎</span>
              <span className="paid-content-banner-text">
                Showing content this user has purchased.
              </span>
            </div>
          )}
          <div className="content-library-tabs">
            {activeContentTypeOptions.map((contentOption) => (
              <button
                key={contentOption.value}
                className={`content-library-tab ${contentType === contentOption.value ? 'active' : ''}`}
                onClick={() => onContentTypeChange(contentOption.value)}
              >
                {contentOption.label}
              </button>
            ))}
          </div>
        </div>
        <div className="content-library-controls">
          <div className="content-library-search">
            <span className="content-library-search-icon">🔍</span>
            <input
              type="text"
              className="content-library-search-input"
              placeholder={activeTab === 'paid' ? 'Search paid content...' : 'Search content...'}
              value={contentSearchInput}
              onChange={(event) => onSearchInput(event.target.value)}
            />
          </div>
          <div className="content-library-sort">
            <label className="content-library-sort-label">Sort by:</label>
            <select
              className="content-library-select"
              value={contentSortBy}
              onChange={(event) => onContentSortByChange(event.target.value)}
            >
              {SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <button
              className="content-library-order-btn"
              onClick={onToggleContentOrder}
              title={contentOrder === 'desc' ? 'Newest first' : 'Oldest first'}
            >
              {contentOrder === 'desc' ? '↓' : '↑'}
            </button>
            <button className="content-library-filter-btn" onClick={onOpenContentFilters}>
              Filters
              {activeContentAdvancedFilterCount > 0
                ? ` (${activeContentAdvancedFilterCount})`
                : ''}
            </button>
          </div>
        </div>
      </div>

      <div className="content-library-stats">
        <span>
          {contentTotal.toLocaleString()} {activeTab === 'paid' ? 'paid item' : 'item'}
          {contentTotal === 1 ? '' : 's'}
        </span>
        {contentLoading && contentItems.length > 0 && (
          <span className="content-library-loading-text">Loading more...</span>
        )}
      </div>

      {contentError && (
        <div className="content-library-error">
          <span>⚠️ {contentError}</span>
          <button onClick={onRetryContent}>Retry</button>
        </div>
      )}

      {contentItems.length > 0 ? (
        <div className="content-library-grid">
          {contentItems.map((item) => (
            <ContentCard
              key={`${item.content_type}-${item.id}-${item.site}`}
              item={item}
              onBuyLocked={onBuyLockedContent}
              buyPending={buyPending && buyPendingKey === `${item.content_type}-${item.id}-${item.site}`}
            />
          ))}
        </div>
      ) : !contentLoading ? (
        <div className="content-library-empty">
          <span className="content-library-empty-icon">{activeTab === 'paid' ? '💎' : '📭'}</span>
          <p>{activeTab === 'paid' ? 'No paid content found' : 'No content found'}</p>
          <p className="content-library-empty-hint">
            {activeTab === 'paid'
              ? 'Purchased posts and messages will show up here once they are saved.'
              : 'Try adjusting your filters or search query'}
          </p>
        </div>
      ) : null}

      {contentLoading && contentItems.length === 0 && (
        <div className="content-library-grid" role="status" aria-label="Loading content" aria-busy="true">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="content-card-skeleton" aria-hidden="true">
              <div className="skeleton skeleton-header" />
              <div className="skeleton skeleton-text" />
              <div className="skeleton skeleton-text short" />
              <div className="skeleton skeleton-media" />
              <div className="skeleton skeleton-footer" />
            </div>
          ))}
        </div>
      )}

      <div ref={sentinelRef} className="content-library-sentinel">
        {contentLoading && contentItems.length > 0 && (
          <div className="content-library-spinner" role="status">
            <div className="content-library-spinner-ring" aria-hidden="true" />
            <span>Loading more content...</span>
          </div>
        )}
        {!contentHasMore && contentItems.length > 0 && (
          <div className="content-library-end">
            All {contentTotal.toLocaleString()} items loaded
          </div>
        )}
      </div>

      {contentFilterModalOpen && (
        <div className="modal-overlay" onClick={onCloseContentFilterModal}>
          <div
            className="modal-content content-library-filter-modal"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="content-library-filter-modal-header">
              <h3>Advanced Filters</h3>
              <button className="content-library-filter-close" onClick={onCloseContentFilterModal}>
                ×
              </button>
            </div>
            <p className="content-library-filter-help">
              Use <strong>+</strong> to include and <strong>-</strong> to exclude matching content.
            </p>
            {activeTab === 'paid' && (
              <p className="content-library-filter-help">
                Purchased content is always included on this tab.
              </p>
            )}
            <div className="content-library-filter-list">
              <div className="content-library-filter-row media-types-multi-row">
                <span className="content-library-filter-name">Media Types</span>
                <div className="media-types-toggle-group">
                  {MEDIA_TYPES.map((type) => {
                    const isSelected = contentDraftAdvancedFilters[type.key] === 'include';
                    return (
                      <button
                        key={type.key}
                        type="button"
                        className={`media-type-toggle-btn ${isSelected ? 'active' : ''}`}
                        onClick={() =>
                          onSetContentDraftFilterState(type.key, isSelected ? 'none' : 'include')
                        }
                      >
                        {isSelected ? '✓ ' : ''}{type.label}
                      </button>
                    );
                  })}
                </div>
              </div>
              {ADVANCED_FILTER_OPTIONS.filter(
                (option) => !(activeTab === 'paid' && option.key === 'purchased')
              ).map((option) => {
                const state = contentDraftAdvancedFilters[option.key];
                return (
                  <div key={option.key} className="content-library-filter-row">
                    <span className="content-library-filter-name">{option.label}</span>
                    <div className="content-library-filter-actions">
                      <button
                        className={`content-library-filter-state-btn ${state === 'exclude' ? 'active' : ''}`}
                        onClick={() =>
                          onSetContentDraftFilterState(
                            option.key,
                            state === 'exclude' ? 'none' : 'exclude'
                          )
                        }
                        title="Exclude (-)"
                      >
                        -
                      </button>
                      <button
                        className={`content-library-filter-state-btn ${state === 'none' ? 'active' : ''}`}
                        onClick={() => onSetContentDraftFilterState(option.key, 'none')}
                        title="No filter"
                      >
                        ·
                      </button>
                      <button
                        className={`content-library-filter-state-btn ${state === 'include' ? 'active' : ''}`}
                        onClick={() =>
                          onSetContentDraftFilterState(
                            option.key,
                            state === 'include' ? 'none' : 'include'
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
            <div className="content-library-filter-footer">
              <button className="btn-secondary" onClick={onClearContentDraftFilters}>
                Clear
              </button>
              <button className="btn-secondary" onClick={onCloseContentFilterModal}>
                Cancel
              </button>
              <button className="btn-primary" onClick={onApplyContentFilters}>
                Apply
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
