import { FavouriteButton } from '../../../../features/favourites/FavouriteButton';
import { DirectChatModal } from '../../../../components/chats/DirectChatModal';
import { UserProfileAuthPickerModal } from '../../../../features/user-profile/components/UserProfileAuthPickerModal';
import { UserProfileContentTab } from '../../../../features/user-profile/components/UserProfileContentTab';
import { UserProfileEditModal } from '../../../../features/user-profile/components/UserProfileEditModal';
import { UserConflictNavigator } from '../../../../features/user-profile/components/UserConflictNavigator';
import { UserIdentifierMatches } from '../../../../features/user-profile/components/UserIdentifierMatches';
import { UserProfileOverviewTab } from '../../../../features/user-profile/components/UserProfileOverviewTab';
import { ScrapeSplitButton } from '../../../../features/user-profile/components/ScrapeSplitButton';
import { UserProfileSubscriptionsTab } from '../../../../features/user-profile/components/UserProfileSubscriptionsTab';
import { UserProfileSexModal } from '../../../../features/user-profile/components/UserProfileSexModal';
import { useUserProfileController } from '../../../../features/user-profile/hooks/useUserProfileController';
import { PluginSlot } from '../../../../features/plugins/components/PluginSlot';
import {
  formatBytes,
  formatNumber,
  formatPrice,
  getSocialUrl,
} from '../../../../features/user-profile/lib/userProfileUtils';
import { ImageLightbox } from '../../../../shared/ui/ImageLightbox';
import { ImageHoverPreview } from '../../../../shared/ui/ImageHoverPreview';
import { useImageHoverPreview } from '../../../../shared/ui/useImageHoverPreview';
import { ToastPortal } from '../../../../shared/ui/ToastPortal';
import { OperationsState } from '../../patterns/OperationsChrome';
import './UserProfilePage.css';

function profileMetricLabel(value: string, label: string, meta?: string) {
  return (
    <div className="stat-pill ultimur-profile-stat">
      <span className="stat-pill-icon ultimur-profile-stat__icon" aria-hidden="true">
        //
      </span>
      <span className="stat-pill-value">{value}</span>
      <span className="stat-pill-label">{label}</span>
      {meta ? <span className="stat-pill-meta">{meta}</span> : null}
    </div>
  );
}

function profileMetricButton(
  value: string,
  label: string,
  onClick: () => void,
  meta?: string,
  title?: string,
) {
  return (
    <div
      role="button"
      tabIndex={0}
      className="stat-pill stat-pill-button ultimur-profile-stat ultimur-profile-stat--button"
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onClick();
        }
      }}
      title={title}
    >
      <span className="stat-pill-icon ultimur-profile-stat__icon" aria-hidden="true">
        //
      </span>
      <span className="stat-pill-value">{value}</span>
      <span className="stat-pill-label">{label}</span>
      {meta ? <span className="stat-pill-meta">{meta}</span> : null}
    </div>
  );
}

export function UserProfilePage() {
  const controller = useUserProfileController();
  const {
    preview,
    startHover,
    endHover,
    enterPreview,
    leavePreview,
    closeImmediate,
  } = useImageHoverPreview(1000);

  if (controller.resolvingUserId || controller.profileLoading) {
    return (
      <div className="user-profile-page ultimur-user-profile-page">
        <OperationsState
          variant="loading"
          title="Loading user profile"
          description={
            controller.resolvingUserId
              ? 'Resolving the target subject.'
              : 'Loading the saved profile snapshot.'
          }
        />
      </div>
    );
  }

  if (controller.identifierResolution?.status === 'ambiguous') {
    return (
      <UserIdentifierMatches
        identifier={controller.requestedIdentifier}
        resolution={controller.identifierResolution}
        onBack={controller.goBack}
        onSelect={controller.selectIdentifierCandidate}
      />
    );
  }

  if (
    controller.resolveUserError ||
    controller.profileError ||
    !controller.profileData?.success ||
    !controller.user
  ) {
    return (
      <div className="user-profile-page ultimur-user-profile-page">
        <OperationsState
          variant="error"
          title="User profile unavailable"
          description={
            controller.resolveUserError instanceof Error
              ? controller.resolveUserError.message
              : controller.profileData?.error ||
                (controller.profileError instanceof Error
                  ? controller.profileError.message
                  : 'User not found')
          }
          actions={
            <button className="ops-action ops-action-primary" onClick={controller.goBack}>
              Back
            </button>
          }
        />
      </div>
    );
  }

  const user = controller.user;
  const paidPreviewMeta = controller.paidPreviewLoading
    ? 'Loading purchases'
    : controller.paidPreviewTotal === 0
      ? ''
      : `${formatNumber(controller.paidPreviewMediaCount)} media mirrored`;
  const paidPreviewTooltip = controller.paidPreviewLoading
    ? 'Loading purchases'
    : controller.paidPreviewTotal === 0
      ? 'No purchases saved'
      : `${formatNumber(controller.paidPreviewMediaCount)} media mirrored`;

  return (
    <div className="user-profile-page ultimur-user-profile-page">
      <ToastPortal toast={controller.toast} onDismiss={() => controller.setToast(null)} />
      <PluginSlot name="user.profile.panels" context={{ user }} />

      {(controller.profileData.is_refreshing || controller.profileData.is_stale) && (
        <div
          className={`profile-freshness-notice${controller.profileData.is_refreshing ? '' : ' profile-freshness-notice--stale'}`}
          role="status"
        >
          {controller.profileData.is_refreshing
            ? 'Saved dossier loaded. Refreshing the upstream profile in the background.'
            : controller.profileData.refresh_error ||
              'Saved dossier loaded. The upstream refresh could not be completed yet.'}
          {!controller.profileData.is_refreshing && (
            <button
              type="button"
              className="profile-freshness-retry"
              disabled={controller.refreshProfileMutation.isPending}
              onClick={() => controller.refreshProfileMutation.mutate()}
            >
              {controller.refreshProfileMutation.isPending ? 'Starting…' : 'Retry refresh'}
            </button>
          )}
        </div>
      )}

      {controller.conflictNavigation ? (
        <UserConflictNavigator
          identifier={controller.conflictNavigation.identifier}
          page={controller.conflictNavigation.page}
          total={controller.conflictNavigation.total}
          loading={controller.conflictNavigation.loading}
          onPageChange={controller.navigateConflictPage}
        />
      ) : null}

      <section className="ultimur-profile-dossier">
        <div className="profile-card ultimur-profile-card">
          {user.header_url ? (
            <div
              className="profile-card-banner"
              style={{ backgroundImage: `url(${user.header_url})` }}
              onMouseEnter={(e) => {
                if (user.header_url) {
                  startHover(e.currentTarget, user.header_url, `${user.username} header`, 'header');
                }
              }}
              onMouseLeave={endHover}
              onClick={() => {
                closeImmediate();
                controller.openLightbox(user.header_url);
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  closeImmediate();
                  controller.openLightbox(user.header_url);
                }
              }}
              role="button"
              tabIndex={0}
            />
          ) : (
            <div className="profile-card-banner profile-card-banner-empty" />
          )}

          <div className="profile-card-body">
            <div className="profile-card-avatar-area">
              {user.avatar_url ? (
                <img
                  src={user.avatar_url}
                  alt={user.username}
                  className="profile-card-avatar"
                  onMouseEnter={(e) => {
                    if (user.avatar_url) {
                      startHover(e.currentTarget, user.avatar_url, `${user.username} profile image`, 'avatar');
                    }
                  }}
                  onMouseLeave={endHover}
                  onClick={() => {
                    closeImmediate();
                    controller.openLightbox(user.avatar_url);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      closeImmediate();
                      controller.openLightbox(user.avatar_url);
                    }
                  }}
                  role="button"
                  tabIndex={0}
                />
              ) : (
                <div className="profile-card-avatar profile-card-avatar-placeholder">
                  {user.username.charAt(0).toUpperCase()}
                </div>
              )}
            </div>

            <div className="ultimur-profile-card__body">
              <div className="ultimur-profile-card__identity">
                <div className="ultimur-profile-card__kickerline">
                  <span className="ultimur-profile-card__kicker">
                    Subject dossier // {user.is_active ? 'live watch' : 'cold archive'}
                  </span>
                  <span className="ultimur-profile-card__kicker-actions">
                    <button
                      type="button"
                      className="ultimur-profile-card__back"
                      onClick={controller.goBack}
                    >
                      Back
                    </button>
                    <span className="ultimur-profile-card__flag">
                      {user.favorite ? 'Priority file' : 'Operator file'}
                    </span>
                    <a
                      className="ultimur-profile-card__site-link"
                      href={controller.getProfileUrl()}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      View on {user.site === 'onlyfans' ? 'OnlyFans' : 'Fansly'} ↗
                    </a>
                  </span>
                </div>

                <div className="ultimur-profile-card__identity-line">
                  <h1 className="profile-card-name">{controller.profileDisplayName}</h1>
                  <span className="profile-card-username">@{user.username}</span>
                  <span className="profile-card-user-id">ID {user.user_id}</span>
                </div>

                <div className="profile-card-badges">
                  <span className={`badge-status ${user.is_active ? 'active' : 'inactive'}`}>
                    {user.is_active ? 'Watch Stable' : 'Watch Idle'}
                  </span>
                  <span className={`badge-site ${user.site}`}>
                    {user.site === 'onlyfans' ? 'OnlyFans' : 'Fansly'}
                  </span>
                  {user.performer ? <span className="badge-performer">Performer</span> : null}
                  {user.favorite ? <span className="badge-favorite">Priority</span> : null}
                </div>

                {user.socials.length > 0 ? (
                  <div className="profile-card-socials">
                    {user.socials.map((social, index) => {
                      const socialUrl = getSocialUrl(social.site, social.identifier);
                      return (
                        <div key={index} className="social-pill">
                          {socialUrl ? (
                            <a
                              href={socialUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="social-site social-site-link"
                            >
                              {social.site}
                            </a>
                          ) : (
                            <span className="social-site">{social.site}</span>
                          )}
                          <span className="social-id">{social.identifier}</span>
                        </div>
                      );
                    })}
                  </div>
                ) : null}

                {controller.userAliases.length > 0 ? (
                  <div className="profile-card-aliases">
                    <span className="profile-card-aliases-label">Known aliases</span>
                    <div className="profile-card-alias-pills">
                      {controller.userAliases.map((alias) => (
                        <span key={alias.id} className="alias-pill">
                          @{alias.username}
                          <button
                            type="button"
                            className="alias-pill-remove"
                            onClick={() => controller.handleRemoveAlias(alias)}
                            aria-label={`Remove alias ${alias.username}`}
                            title="Remove alias"
                          >
                            ×
                          </button>
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}

                {controller.profileDescription ? (
                  <p className="profile-card-bio">{controller.profileDescription}</p>
                ) : null}

                <div className="ultimur-profile-card__ledger" aria-label="Subject ledger">
                  <div className="ultimur-profile-card__ledger-cell">
                    <label>Subscription</label>
                    <span>{controller.subscriptionCountdown.value}</span>
                    <small>{controller.subscriptionCountdown.detail}</small>
                  </div>
                  <div className="ultimur-profile-card__ledger-cell">
                    <label>Paid archive</label>
                    <span>{formatNumber(controller.paidPreviewTotal)}</span>
                    <small>{paidPreviewTooltip}</small>
                  </div>
                  <div className="ultimur-profile-card__ledger-cell">
                    <label>Telemetry</label>
                    <span>{formatBytes(controller.resolvedProfileSize)}</span>
                    <small>{controller.sizeMeta}</small>
                  </div>
                </div>
              </div>

              <aside className="ultimur-profile-card__rail">
                <div className="ultimur-profile-card__rail-kicker">Subject record</div>
                <div className="ultimur-profile-card__rail-list">
                  <div className="ultimur-profile-card__rail-row">
                    <label>Subscription</label>
                    <span>{controller.subscriptionCountdown.value}</span>
                  </div>
                  <div className="ultimur-profile-card__rail-row">
                    <label>Paid assets</label>
                    <span>{formatNumber(controller.paidPreviewTotal)}</span>
                  </div>
                  <div className="ultimur-profile-card__rail-row">
                    <label>Profile size</label>
                    <span>{formatBytes(controller.resolvedProfileSize)}</span>
                  </div>
                  <div className="ultimur-profile-card__rail-row">
                    <label>Telemetry</label>
                    <span>{controller.sizeMeta}</span>
                  </div>
                </div>
              </aside>
            </div>

            <div className="profile-card-actions ultimur-profile-card__actions">
              <ScrapeSplitButton
                primaryLabel={
                  controller.authPickerLoading
                    ? 'Checking auths...'
                    : controller.createJobMutation.isPending
                      ? 'Creating...'
                      : 'Download'
                }
                onPrimaryClick={controller.handleScrape}
                onDelegateClick={controller.handleDelegateScrape}
                disabled={
                  controller.createJobMutation.isPending ||
                  controller.authPickerLoading ||
                  controller.delegateJobMutation.isPending
                }
                delegatePending={controller.delegateJobMutation.isPending}
              />
              <button className="btn-secondary" onClick={controller.handleViewMedia}>
                Browse Files
              </button>
              <button
                className="btn-secondary"
                onClick={controller.handleSubscribe}
                disabled={controller.subscribeMutation.isPending}
              >
                {controller.subscribeMutation.isPending ? 'Subscribing...' : 'Subscribe'}
              </button>
              <button
                className={
                  controller.watched
                    ? 'btn-primary btn-watch-toggle'
                    : 'btn-secondary btn-watch-toggle'
                }
                onClick={controller.handleToggleWatch}
                disabled={controller.watchMutation.isPending}
              >
                {controller.watchMutation.isPending
                  ? 'Saving...'
                  : controller.watched
                    ? 'Unwatch'
                    : 'Watch'}
              </button>
<FavouriteButton entity={{ site: user.site, entity_type: 'user', entity_id: user.user_id }} initialFavorite={user.favorite} displayLabel="Favourite" className="btn-secondary btn-favorite-toggle" fallback={              <button
                className={
                  user.favorite
                    ? 'btn-primary btn-favorite-toggle'
                    : 'btn-secondary btn-favorite-toggle'
                }
                onClick={controller.handleToggleFavorite}
                disabled={controller.favoriteMutation.isPending}
              >
                {controller.favoriteMutation.isPending
                  ? 'Saving...'
                  : user.favorite
                    ? 'Remove priority'
                    : 'Mark priority'}
              </button>} />
              <button
                className="btn-secondary"
                onClick={controller.openEditModal}
                disabled={controller.updateProfileMutation.isPending}
              >
                Edit Record
              </button>
              <button className="btn-secondary" onClick={() => controller.setChatModalOpen(true)}>
                Open Chat
              </button>
            </div>
          </div>
        </div>

        <div className="stat-pills ultimur-profile-stats">
          {profileMetricLabel(formatNumber(user.post_count), 'Posts')}
          {profileMetricLabel(formatNumber(user.image_count), 'Photos')}
          {profileMetricLabel(formatNumber(user.video_count), 'Videos')}
          {profileMetricLabel(formatPrice(user.price), 'Price')}
          {profileMetricButton(
            controller.paidPreviewLoading ? '…' : formatNumber(controller.paidPreviewTotal),
            'Paid Content',
            controller.openPaidTab,
            paidPreviewMeta,
            paidPreviewTooltip
          )}
          {profileMetricLabel(
            controller.subscriptionCountdown.value,
            'Subscription',
            controller.subscriptionCountdown.detail
          )}
          {profileMetricLabel(formatBytes(controller.resolvedProfileSize), controller.sizeLabel)}
        </div>

        <div className="profile-tabs ultimur-profile-tabs">
          <button
            className={`profile-tab ${controller.activeTab === 'overview' ? 'active' : ''}`}
            onClick={() => controller.handleTabClick('overview')}
          >
            Overview
          </button>
          <button
            className={`profile-tab ${controller.activeTab === 'content' ? 'active' : ''}`}
            onClick={() => controller.handleTabClick('content')}
          >
            Content
          </button>
          <button
            className={`profile-tab ${controller.activeTab === 'paid' ? 'active' : ''}`}
            onClick={() => controller.handleTabClick('paid')}
          >
            {controller.paidTabLabel}
          </button>
          {controller.hasSubscriptionsTab && (
            <button
              className={`profile-tab ${controller.activeTab === 'subscriptions' ? 'active' : ''}`}
              onClick={() => controller.handleTabClick('subscriptions')}
            >
              Subscriptions
            </button>
          )}
        </div>
      </section>

      {controller.activeTab === 'overview' && (
        <UserProfileOverviewTab
          user={user}
          activeOverviewVersion={controller.activeOverviewVersion}
          activeOverviewData={controller.activeOverviewData}
          historySnapshotsLength={controller.historySnapshots.length}
          historyLoading={controller.historyLoading}
          hasOlderOverviewVersion={controller.hasOlderOverviewVersion}
          hasNewerOverviewVersion={controller.hasNewerOverviewVersion}
          onSelectOlderVersion={() =>
            controller.setOverviewVersionIndex((previous) =>
              Math.min(previous + 1, controller.overviewVersions.length - 1)
            )
          }
          onSelectNewerVersion={() =>
            controller.setOverviewVersionIndex((previous) => Math.max(previous - 1, 0))
          }
          subscriptionCountdown={controller.subscriptionCountdown}
          onOpenSexModal={controller.openSexModal}
          updateProfilePending={controller.updateProfileMutation.isPending}
          estimatedProfileSize={controller.estimatedProfileSize}
          showEstimatedProfileSize={controller.showEstimatedProfileSize}
          estimatedSizeMeta={controller.estimatedSizeMeta}
          directoryLookup={controller.directoryLookup}
          directoryLookupFetched={controller.directoryLookupFetched}
          directoryLookupLoading={controller.directoryLookupLoading}
          directoryLookupError={controller.directoryLookupError}
          onFindDirectory={controller.handleFindDirectory}
          copiedDirPath={controller.copiedDirPath}
          onCopyDir={controller.handleCopyDir}
        />
      )}

      {(controller.activeTab === 'content' || controller.activeTab === 'paid') && (
        <UserProfileContentTab
          activeTab={controller.activeTab}
          activeContentTypeOptions={controller.activeContentTypeOptions}
          contentType={controller.contentType}
          onContentTypeChange={controller.setContentType}
          contentSearchInput={controller.contentSearchInput}
          onSearchInput={controller.handleSearchInput}
          contentSortBy={controller.contentSortBy}
          onContentSortByChange={controller.setContentSortBy}
          contentOrder={controller.contentOrder}
          onToggleContentOrder={() =>
            controller.setContentOrder((previous) => (previous === 'desc' ? 'asc' : 'desc'))
          }
          onOpenContentFilters={controller.openContentFilters}
          activeContentAdvancedFilterCount={controller.activeContentAdvancedFilterCount}
          contentTotal={controller.contentTotal}
          contentLoading={controller.contentLoading}
          contentItems={controller.contentItems}
          contentError={controller.contentError}
          onRetryContent={() => {
            void controller.fetchContent(1, false);
          }}
          onBuyLockedContent={controller.handleBuyLockedContent}
          buyPendingKey={controller.buyingContentKey}
          buyPending={controller.addLockedContentToOrderMutation.isPending}
          sentinelRef={controller.sentinelRef}
          contentHasMore={controller.contentHasMore}
          contentFilterModalOpen={controller.contentFilterModalOpen}
          onCloseContentFilterModal={() => controller.setContentFilterModalOpen(false)}
          contentDraftAdvancedFilters={controller.contentDraftAdvancedFilters}
          onSetContentDraftFilterState={controller.setContentDraftFilterState}
          onClearContentDraftFilters={controller.clearContentDraftFilters}
          onApplyContentFilters={controller.applyContentFilters}
        />
      )}

      {controller.activeTab === 'subscriptions' && (
        <UserProfileSubscriptionsTab
          authLookupLoading={controller.profileAuthsLoading}
          authLookupError={controller.profileAuthsError}
          authOptions={controller.profileAuths}
          selectedAuthId={controller.selectedProfileAuthId}
          onSelectedAuthIdChange={controller.setSelectedProfileAuthId}
          searchValue={controller.profileSubscriptionsSearchTerm}
          onSearchChange={controller.setProfileSubscriptionsSearchTerm}
          sortBy={controller.profileSubscriptionsOrderBy}
          onSortByChange={controller.setProfileSubscriptionsOrderBy}
          sortOrder={controller.profileSubscriptionsOrderDir}
          onSortOrderToggle={() =>
            controller.setProfileSubscriptionsOrderDir((previous) =>
              previous === 'asc' ? 'desc' : 'asc'
            )
          }
          activeFilterCount={controller.profileSubscriptionsActiveFilterCount}
          loadoutModalOpen={controller.profileSubscriptionsLoadoutModalOpen}
          loadoutsData={controller.profileSubscriptionsLoadoutsData}
          selectedLoadoutName={controller.profileSubscriptionsSelectedLoadoutName}
          selectedLoadoutIsDefault={controller.profileSubscriptionsSelectedLoadoutIsDefault}
          loadoutNameInput={controller.profileSubscriptionsLoadoutNameInput}
          filtersModalOpen={controller.profileSubscriptionsFiltersModalOpen}
          draftActiveOnly={controller.profileSubscriptionsDraftActiveOnly}
          draftMinPrice={controller.profileSubscriptionsDraftMinPrice}
          draftMaxPrice={controller.profileSubscriptionsDraftMaxPrice}
          draftSexFilter={controller.profileSubscriptionsDraftSexFilter}
          onOpenLoadoutModal={controller.openProfileSubscriptionsLoadoutModal}
          onCloseLoadoutModal={() => controller.setProfileSubscriptionsLoadoutModalOpen(false)}
          onLoadoutSelect={controller.handleSelectProfileSubscriptionsLoadout}
          onLoadoutNameInputChange={controller.setProfileSubscriptionsLoadoutNameInput}
          onAutofillLoadoutName={controller.autofillProfileSubscriptionsLoadoutName}
          onDeleteLoadout={() => {
            void controller.deleteProfileSubscriptionsSelectedLoadout();
          }}
          onToggleDefaultLoadout={() => {
            if (controller.profileSubscriptionsSelectedLoadoutIsDefault) {
              void controller.clearProfileSubscriptionsDefaultLoadout();
            } else {
              void controller.setProfileSubscriptionsSelectedAsDefaultLoadout();
            }
          }}
          onSaveLoadout={() => {
            void controller.saveProfileSubscriptionsLoadout();
          }}
          buildAutoLoadoutName={controller.buildProfileSubscriptionsLoadoutName}
          onOpenFilters={controller.openProfileSubscriptionsFilters}
          onCloseFilters={controller.closeProfileSubscriptionsFilters}
          onDraftActiveOnlyChange={controller.setProfileSubscriptionsDraftActiveOnly}
          onDraftMinPriceChange={controller.setProfileSubscriptionsDraftMinPrice}
          onDraftMaxPriceChange={controller.setProfileSubscriptionsDraftMaxPrice}
          onDraftSexFilterChange={controller.setProfileSubscriptionsDraftSexFilter}
          onClearFilters={controller.clearProfileSubscriptionsFilters}
          onApplyFilters={controller.applyProfileSubscriptionsFilters}
          subscriptions={controller.visibleProfileSubscriptions}
          subscriptionsTotal={controller.profileSubscriptionsTotal}
          subscriptionsLoading={controller.profileSubscriptionsLoading}
          subscriptionsError={controller.profileSubscriptionsError}
          hasNextPage={Boolean(controller.profileSubscriptionsHasNextPage)}
          isFetchingNextPage={controller.profileSubscriptionsIsFetchingNextPage}
          onFetchNextPage={() => {
            void controller.fetchNextProfileSubscriptionsPage();
          }}
          onScrapeSubscription={controller.handleScrapeSubscription}
          isCreatingJob={controller.createJobMutation.isPending}
        />
      )}

      <ImageLightbox
        imageUrl={controller.lightboxUrl}
        alt={`${user.username} profile media`}
        onClose={controller.closeLightbox}
      />

      <ImageHoverPreview
        preview={preview}
        onEnter={enterPreview}
        onLeave={leavePreview}
        onClick={(url) => {
          closeImmediate();
          controller.openLightbox(url);
        }}
      />

      <UserProfileAuthPickerModal
        isOpen={controller.authPickerOpen}
        username={user.username}
        eligibleAuths={controller.eligibleAuths}
        isCreatingJob={
          controller.createJobMutation.isPending || controller.delegateJobMutation.isPending
        }
        onClose={controller.closeAuthPicker}
        onSelectAuth={controller.handleAuthSelection}
      />

      <UserProfileEditModal
        isOpen={controller.editModalOpen}
        username={user.username}
        editName={controller.editName}
        editAlias={controller.editAlias}
        editDescription={controller.editDescription}
        editSex={controller.identityFields.editSex}
        editGender={controller.identityFields.editGender}
        isSaving={controller.updateProfileMutation.isPending}
        onClose={() => controller.setEditModalOpen(false)}
        onEditNameChange={controller.setEditName}
        onEditAliasChange={controller.setEditAlias}
        onEditDescriptionChange={controller.setEditDescription}
        onEditSexChange={controller.identityFields.onEditSexChange}
        onEditGenderChange={controller.identityFields.onEditGenderChange}
        onSave={controller.handleSaveUserEdit}
      />

      <UserProfileSexModal
        isOpen={controller.sexModalOpen}
        username={user.username}
        {...controller.identityFields}
        isSaving={controller.updateProfileMutation.isPending}
        onClose={() => controller.setSexModalOpen(false)}
        onSave={controller.handleSaveSex}
      />

      <DirectChatModal
        isOpen={controller.chatModalOpen}
        onClose={() => controller.setChatModalOpen(false)}
        site={controller.site}
        userId={user.user_id}
        username={user.username}
        displayName={user.name}
        avatarUrl={user.avatar_url}
      />
    </div>
  );
}
