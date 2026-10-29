import type { RefObject } from 'react';

import type { ContentLibraryItem } from '../../../api/types/content';
import { ContentCard } from '../../../components/content/ContentCard';
import { OperationsState } from '../../../shared/ui/operations/OperationsChrome';

interface ContentLibraryResultsProps {
  error: string | null;
  hasMore: boolean;
  items: ContentLibraryItem[];
  loading: boolean;
  onRetry: () => void;
  sentinelRef: RefObject<HTMLDivElement | null>;
  searchText: string;
  total: number;
  totalIsExact: boolean;
  onHideUser?: (userId: number, username?: string | null) => void;
}

export function ContentLibraryResults({
  error,
  hasMore,
  items,
  loading,
  onRetry,
  sentinelRef,
  searchText,
  total,
  totalIsExact,
  onHideUser,
}: ContentLibraryResultsProps) {
  const totalLabel = `${total.toLocaleString()}${totalIsExact ? '' : '+'}`;

  return (
    <>
      <div className="content-library-stats">
        <span>{totalLabel} items</span>
        {loading && items.length > 0 && (
          <span className="content-library-loading-text">Loading more...</span>
        )}
      </div>

      {error && (
        <OperationsState
          variant="error"
          title="Library load failed"
          description={error}
          compact
          actions={
            <button className="ops-action ops-action-primary" onClick={onRetry}>
              Retry
            </button>
          }
        />
      )}

      {items.length > 0 ? (
        <div className="content-library-grid">
          {items.map((item) => (
            <ContentCard
              key={`${item.content_type}-${item.id}-${item.site}`}
              item={item}
              highlightText={searchText}
              onHideUser={onHideUser}
            />
          ))}
        </div>
      ) : !loading ? (
        <OperationsState
          title="No content found"
          description="Adjust the current filters, search query, or loadout to widen the result set."
        />
      ) : null}

      {loading && items.length === 0 && (
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
        {loading && items.length > 0 && (
          <div className="content-library-spinner" role="status">
            <div className="content-library-spinner-ring" aria-hidden="true" />
            <span>Loading more content...</span>
          </div>
        )}
        {!hasMore && items.length > 0 && (
          <div className="content-library-end">
            All {total.toLocaleString()} items loaded
          </div>
        )}
      </div>
    </>
  );
}
