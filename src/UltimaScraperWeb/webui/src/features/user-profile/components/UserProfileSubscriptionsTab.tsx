import { Link, useLocation } from 'react-router-dom';

import { FilterBar, FilterSelect } from '../../../components/shared/FilterBar';
import type { AuthCredential } from '../../../api/types/auths';
import type { SearchLoadoutsResponse } from '../../../api/types/loadouts';
import type { SubscriptionInfo } from '../../../api/types/subscriptions';
import { SubscriptionsFiltersModal } from '../../subscriptions/components/SubscriptionsFiltersModal';
import { SubscriptionsLoadoutModal } from '../../subscriptions/components/SubscriptionsLoadoutModal';
import { SUBSCRIPTION_SORT_OPTIONS } from '../../subscriptions/lib/subscriptionsUtils';
import { OperationsState } from '../../../shared/ui/operations/OperationsChrome';
import { formatNumber, formatPrice } from '../lib/userProfileUtils';
import { stripHtml } from '../../../utils/sanitize';

interface UserProfileSubscriptionsTabProps {
  authLookupLoading: boolean;
  authLookupError: unknown;
  authOptions: AuthCredential[];
  selectedAuthId: number | '';
  onSelectedAuthIdChange: (authId: number) => void;
  searchValue: string;
  onSearchChange: (value: string) => void;
  sortBy: string;
  onSortByChange: (value: string) => void;
  sortOrder: 'asc' | 'desc';
  onSortOrderToggle: () => void;
  activeFilterCount: number;
  loadoutModalOpen: boolean;
  loadoutsData: SearchLoadoutsResponse | undefined;
  selectedLoadoutName: string;
  selectedLoadoutIsDefault: boolean;
  loadoutNameInput: string;
  filtersModalOpen: boolean;
  draftActiveOnly: boolean;
  draftMinPrice: string;
  draftMaxPrice: string;
  draftSexFilter: number[];
  onOpenLoadoutModal: () => void;
  onCloseLoadoutModal: () => void;
  onLoadoutSelect: (value: string) => void;
  onLoadoutNameInputChange: (value: string) => void;
  onAutofillLoadoutName: () => void;
  onDeleteLoadout: () => void;
  onToggleDefaultLoadout: () => void;
  onSaveLoadout: () => void;
  buildAutoLoadoutName: () => string;
  onOpenFilters: () => void;
  onCloseFilters: () => void;
  onDraftActiveOnlyChange: (value: boolean) => void;
  onDraftMinPriceChange: (value: string) => void;
  onDraftMaxPriceChange: (value: string) => void;
  onDraftSexFilterChange: (value: number[]) => void;
  onClearFilters: () => void;
  onApplyFilters: () => void;
  subscriptions: SubscriptionInfo[];
  subscriptionsTotal: number;
  subscriptionsLoading: boolean;
  subscriptionsError: unknown;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onFetchNextPage: () => void;
  onScrapeSubscription: (subscription: SubscriptionInfo) => void;
  isCreatingJob: boolean;
}

function formatExpiry(expiresAt: string | null) {
  if (!expiresAt) return 'No expiry recorded';
  const parsed = new Date(expiresAt);
  if (Number.isNaN(parsed.getTime())) {
    return 'Expiry unknown';
  }
  return parsed.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export function UserProfileSubscriptionsTab({
  authLookupLoading,
  authLookupError,
  authOptions,
  selectedAuthId,
  onSelectedAuthIdChange,
  searchValue,
  onSearchChange,
  sortBy,
  onSortByChange,
  sortOrder,
  onSortOrderToggle,
  activeFilterCount,
  loadoutModalOpen,
  loadoutsData,
  selectedLoadoutName,
  selectedLoadoutIsDefault,
  loadoutNameInput,
  filtersModalOpen,
  draftActiveOnly,
  draftMinPrice,
  draftMaxPrice,
  draftSexFilter,
  onOpenLoadoutModal,
  onCloseLoadoutModal,
  onLoadoutSelect,
  onLoadoutNameInputChange,
  onAutofillLoadoutName,
  onDeleteLoadout,
  onToggleDefaultLoadout,
  onSaveLoadout,
  buildAutoLoadoutName,
  onOpenFilters,
  onCloseFilters,
  onDraftActiveOnlyChange,
  onDraftMinPriceChange,
  onDraftMaxPriceChange,
  onDraftSexFilterChange,
  onClearFilters,
  onApplyFilters,
  subscriptions,
  subscriptionsTotal,
  subscriptionsLoading,
  subscriptionsError,
  hasNextPage,
  isFetchingNextPage,
  onFetchNextPage,
  onScrapeSubscription,
  isCreatingJob,
}: UserProfileSubscriptionsTabProps) {
  const location = useLocation();
  const returnTo = `${location.pathname}${location.search}`;
  const selectedAuth =
    authOptions.find((auth) => auth.id === selectedAuthId) ?? authOptions[0] ?? null;

  if (authLookupLoading) {
    return (
      <section className="profile-subscriptions-tab">
        <OperationsState
          compact
          variant="loading"
          title="Loading auth subscriptions"
          description="Checking whether this profile has a linked USR auth account."
        />
      </section>
    );
  }

  if (authLookupError) {
    return (
      <section className="profile-subscriptions-tab">
        <OperationsState
          compact
          variant="error"
          title="Auth lookup failed"
          description={
            authLookupError instanceof Error
              ? authLookupError.message
              : 'Unable to look up linked auth accounts.'
          }
        />
      </section>
    );
  }

  return (
    <section className="profile-subscriptions-tab">
      <FilterBar
        searchValue={searchValue}
        onSearchChange={onSearchChange}
        searchPlaceholder="Search by identifier…"
        sortOptions={SUBSCRIPTION_SORT_OPTIONS}
        sortBy={sortBy}
        onSortByChange={onSortByChange}
        sortOrder={sortOrder}
        onSortOrderToggle={onSortOrderToggle}
        primaryExtras={
          authOptions.length > 1 ? (
            <FilterSelect
              label="Auth"
              value={String(selectedAuthId)}
              onChange={(value) => onSelectedAuthIdChange(Number(value))}
            >
              {authOptions.map((auth) => (
                <option key={auth.id} value={auth.id}>
                  @{auth.username || auth.user_id}
                  {auth.active ? '' : ' • Inactive'}
                </option>
              ))}
            </FilterSelect>
          ) : null
        }
        secondaryExtras={
          <>
            <button
              type="button"
              className="filter-bar__filters-btn"
              onClick={onOpenLoadoutModal}
            >
              Loadouts
            </button>
            <button
              type="button"
              className="filter-bar__filters-btn"
              onClick={onOpenFilters}
            >
              Filters
              {activeFilterCount > 0 ? ` (${activeFilterCount})` : ''}
            </button>
          </>
        }
      />

      {subscriptionsLoading ? (
        <OperationsState
          compact
          variant="loading"
          title="Loading subscriptions"
          description="Fetching the auth-scoped subscription roster."
        />
      ) : subscriptionsError ? (
        <OperationsState
          compact
          variant="error"
          title="Failed to load subscriptions"
          description={
            subscriptionsError instanceof Error
              ? subscriptionsError.message
              : 'Unknown subscription error'
          }
        />
      ) : subscriptions.length === 0 ? (
        <OperationsState
          compact
          title="No subscriptions found"
          description="This auth account does not have any active subscriptions saved right now."
        />
      ) : (
        <>
          <div className="profile-subscriptions-results-count">
            Showing {subscriptions.length} of {subscriptionsTotal} subscription
            {subscriptionsTotal !== 1 ? 's' : ''}
            {selectedAuth ? ` for @${selectedAuth.username || selectedAuth.user_id}` : ''}
          </div>

          <div className="profile-subscriptions-grid">
            {subscriptions.map((subscription) => {
              const description = stripHtml(subscription.description);
              const profileHref = `/users/${subscription.user_id}?site=${encodeURIComponent(subscription.site)}&source=subscriptions&return_to=${encodeURIComponent(returnTo)}`;

              return (
                <article
                  key={`${subscription.site}-${subscription.id}-${subscription.user_id}`}
                  className="profile-subscription-card"
                >
                  <div className="profile-subscription-card__head">
                    <div className="profile-subscription-card__identity">
                      {subscription.avatar_url ? (
                        <img
                          src={subscription.avatar_url}
                          alt={subscription.username || 'Subscription avatar'}
                          className="profile-subscription-card__avatar"
                        />
                      ) : (
                        <div className="profile-subscription-card__avatar profile-subscription-card__avatar--placeholder">
                          {(subscription.username || '?').charAt(0).toUpperCase()}
                        </div>
                      )}

                      <div className="profile-subscription-card__copy">
                        <div className="profile-subscription-card__title-row">
                          <h3>{subscription.name || `@${subscription.username || subscription.user_id}`}</h3>
                          <span
                            className={`profile-subscription-card__status ${subscription.is_active ? 'active' : 'inactive'}`}
                          >
                            {subscription.is_active ? 'Active' : 'Inactive'}
                          </span>
                        </div>
                        <p className="profile-subscription-card__username">
                          @{subscription.username || subscription.user_id}
                        </p>
                        <p className="profile-subscription-card__meta">
                          {subscription.site === 'onlyfans' ? 'OnlyFans' : 'Fansly'} · Expires{' '}
                          {formatExpiry(subscription.expires_at)}
                        </p>
                      </div>
                    </div>

                    <div className="profile-subscription-card__price">
                      {formatPrice(subscription.price)}
                    </div>
                  </div>

                  <div className="profile-subscription-card__stats">
                    <div>
                      <span>Posts</span>
                      <strong>{formatNumber(subscription.post_count)}</strong>
                    </div>
                    <div>
                      <span>Photos</span>
                      <strong>{formatNumber(subscription.image_count)}</strong>
                    </div>
                    <div>
                      <span>Videos</span>
                      <strong>{formatNumber(subscription.video_count)}</strong>
                    </div>
                    <div>
                      <span>Media</span>
                      <strong>{formatNumber(subscription.media_count)}</strong>
                    </div>
                  </div>

                  {description ? (
                    <p className="profile-subscription-card__description">{description}</p>
                  ) : null}

                  <div className="profile-subscription-card__actions">
                    <button
                      type="button"
                      className="profile-subscription-card__scrape"
                      onClick={() => onScrapeSubscription(subscription)}
                      disabled={isCreatingJob}
                    >
                      {isCreatingJob ? 'Creating…' : 'Scrape + Download'}
                    </button>
                    <Link to={profileHref} className="profile-subscription-card__link">
                      Open Profile
                    </Link>
                  </div>
                </article>
              );
            })}
          </div>

          {(isFetchingNextPage || hasNextPage) && (
            <div className="profile-subscriptions-footer">
              <button
                type="button"
                className="profile-subscriptions-load-more"
                onClick={onFetchNextPage}
                disabled={isFetchingNextPage}
              >
                {isFetchingNextPage ? 'Loading…' : 'Load More'}
              </button>
            </div>
          )}
        </>
      )}

      {loadoutModalOpen && (
        <SubscriptionsLoadoutModal
          loadoutsData={loadoutsData}
          selectedLoadoutName={selectedLoadoutName}
          loadoutNameInput={loadoutNameInput}
          selectedLoadoutIsDefault={selectedLoadoutIsDefault}
          autoNamePlaceholder={buildAutoLoadoutName()}
          onClose={onCloseLoadoutModal}
          onLoadoutSelect={onLoadoutSelect}
          onInputChange={onLoadoutNameInputChange}
          onAutofill={onAutofillLoadoutName}
          onDelete={onDeleteLoadout}
          onToggleDefault={onToggleDefaultLoadout}
          onSaveCurrent={onSaveLoadout}
        />
      )}

      {filtersModalOpen && (
        <SubscriptionsFiltersModal
          draftActiveOnly={draftActiveOnly}
          draftMinPrice={draftMinPrice}
          draftMaxPrice={draftMaxPrice}
          draftSexFilter={draftSexFilter}
          onClose={onCloseFilters}
          onDraftActiveOnlyChange={onDraftActiveOnlyChange}
          onDraftMinPriceChange={onDraftMinPriceChange}
          onDraftMaxPriceChange={onDraftMaxPriceChange}
          onDraftSexFilterChange={onDraftSexFilterChange}
          onClear={onClearFilters}
          onApply={onApplyFilters}
        />
      )}
    </section>
  );
}
