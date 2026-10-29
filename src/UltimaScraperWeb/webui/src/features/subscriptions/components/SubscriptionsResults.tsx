import { useLocation } from 'react-router-dom';
import type { SubscriptionInfo } from '../../../api/types/subscriptions';
import { UserCard } from '../../../components/users/UserCard';
import { OperationsState } from '../../../shared/ui/operations/OperationsChrome';
import { formatNumber, formatPrice, getSubscriptionKey } from '../lib/subscriptionsUtils';

interface SubscriptionsResultsProps {
  visibleSubscriptions: SubscriptionInfo[];
  subscriptionsTotal: number;
  priceRangeActive: boolean;
  isLoading: boolean;
  error: unknown;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  isActionPending: boolean;
  selectedSubscriptions: Set<string>;
  watchedKeys: Set<string>;
  ignoredKeys: Set<string>;
  isWatchPending: boolean;
  isIgnorePending: boolean;
  isUpdatePending: boolean;
  loadMoreSentinelRef: React.RefObject<HTMLDivElement | null>;
  onFetchNextPage: () => void;
  onScrape: (sub: SubscriptionInfo) => void;
  onView: (sub: SubscriptionInfo) => void;
  onSelect: (sub: SubscriptionInfo) => void;
  onWatchToggle: (sub: SubscriptionInfo) => void;
  onIgnoreToggle: (sub: SubscriptionInfo) => void;
  onEdit: (sub: SubscriptionInfo) => void;
  onOpenLightbox?: (url: string | null, alt?: string) => void;
}

export function SubscriptionsResults({
  visibleSubscriptions,
  subscriptionsTotal,
  priceRangeActive,
  isLoading,
  error,
  hasNextPage,
  isFetchingNextPage,
  isActionPending,
  selectedSubscriptions,
  watchedKeys,
  ignoredKeys,
  isWatchPending,
  isIgnorePending,
  isUpdatePending,
  loadMoreSentinelRef,
  onFetchNextPage,
  onScrape,
  onView,
  onSelect,
  onWatchToggle,
  onIgnoreToggle,
  onEdit,
  onOpenLightbox,
}: SubscriptionsResultsProps) {
  const location = useLocation();
  const returnTo = `${location.pathname}${location.search}`;

  return (
    <div className="subscriptions-content">
      {isLoading ? (
        <OperationsState
          compact
          variant="loading"
          title="Loading subscriptions"
          description="Refreshing active performers and applied filter state."
        />
      ) : error ? (
        <OperationsState
          compact
          variant="error"
          title="Failed to load subscriptions"
          description={error instanceof Error ? error.message : 'Unknown error'}
        />
      ) : (
        <>
          <div className="results-count">
            Showing {visibleSubscriptions.length} of {subscriptionsTotal} subscription
            {subscriptionsTotal !== 1 ? 's' : ''}
          </div>

          {!visibleSubscriptions.length ? (
            <OperationsState
              compact
              title="No subscriptions found"
              description={
                priceRangeActive
                  ? 'No currently loaded subscriptions match the selected price range.'
                  : 'Start scraping creators to populate the subscription view.'
              }
            />
          ) : (
            <div className="user-card-grid-container">
              <div className="subscriptions-grid user-card-grid">
                {visibleSubscriptions.map((sub) => (
                  <UserCard
                    key={`${sub.site}-${sub.id}`}
                    item={{ ...sub, is_subscribed: sub.is_active }}
                    profileUrl={`/users/${sub.user_id}?site=${encodeURIComponent(sub.site)}&source=subscriptions&return_to=${encodeURIComponent(returnTo)}`}
                    rootClassName="user-card"
                    inactiveLabel="Expired"
                    formatNumber={formatNumber}
                    formatPrice={formatPrice}
                    onScrape={onScrape}
                    onView={onView}
                    isCreatingJob={isActionPending}
                    isSelected={selectedSubscriptions.has(getSubscriptionKey(sub))}
                    onSelect={onSelect}
                    onWatchToggle={onWatchToggle}
                    isWatched={watchedKeys.has(`${sub.site}-${sub.user_id}`)}
                    isWatchPending={isWatchPending}
                    onIgnoreToggle={onIgnoreToggle}
                    isIgnored={ignoredKeys.has(`${sub.site}-${sub.user_id}`)}
                    isIgnorePending={isIgnorePending}
                    extraMenuActions={[
                      {
                        key: 'edit-user',
                        label: 'Edit User',
                        title: 'Edit user profile fields',
                        onClick: () => onEdit(sub),
                        disabled: isUpdatePending,
                      },
                    ]}
                    onOpenLightbox={onOpenLightbox}
                  />
                ))}
              </div>
            </div>
          )}

          <div ref={loadMoreSentinelRef} className="subscriptions-scroll-sentinel" />

          {isFetchingNextPage && (
            <div className="subscriptions-loading-more">Loading more subscriptions...</div>
          )}
          {hasNextPage && (
            <div className="subscriptions-load-more-wrap">
              <button
                type="button"
                className="subscriptions-load-more-btn"
                onClick={onFetchNextPage}
                disabled={isFetchingNextPage}
              >
                {isFetchingNextPage ? 'Loading...' : 'Load More'}
              </button>
            </div>
          )}
          {!hasNextPage && subscriptionsTotal > 0 && (
            <div className="subscriptions-end">All subscriptions loaded</div>
          )}
        </>
      )}
    </div>
  );
}
