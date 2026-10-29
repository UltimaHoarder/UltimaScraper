import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

import { getAuthList } from '../../../api/auths';
import { createJob } from '../../../api/jobs';
import { createOrderedPerformer } from '../../../api/orders';
import { browseContentLibrary } from '../../../api/content';
import {
  clearDefaultSearchLoadout,
  deleteSearchLoadout,
  getSearchLoadouts,
  saveSearchLoadout,
  setDefaultSearchLoadout,
} from '../../../api/loadouts';
import { submitDelegatedJob } from '../../../api/plugins';
import { getSubscriptions } from '../../../api/subscriptions';
import {
  addToWatchList,
  deleteUserAlias,
  getEligibleAuths,
  getUserAliases,
  getUserHistory,
  getUserProfile,
  removeFromWatchList,
  refreshUserProfile,
  searchUsernameDirectories,
  resolveUserIdentifier,
  updateUser,
} from '../../../api/users';
import { getWatchList } from '../../../api/webhooks';
import { getUserProfileDocumentTitle } from '../../../components/layout/navigation';
import type {
  DetailedUserResponse,
  EligibleAuth,
  HistoUserInfoItem,
  HistoUserInfoResponse,
  UserAliasResponse,
  UserIdentifierResolutionResponse,
  UserUpdateRequest,
} from '../../../api/types/users';
import {
  EMPTY_IDENTITY_DRAFT,
  identityDraftFromUser,
  parseIdentityDraft,
} from '../lib/identityDraft';
import { useIdentityDraft } from './useIdentityDraft';
import { stripHtml } from '../../../utils/sanitize';

import type { TaskPayload } from '../../../api/types/jobs';
import type { AuthCredential } from '../../../api/types/auths';
import type {
  ContentLibraryItem,
  ContentLibraryResponse,
} from '../../../api/types/content';
import type { SearchLoadoutItem } from '../../../api/types/loadouts';
import type { OrderedPerformerCreateResponse } from '../../../api/types/orders';
import type { SubscriptionInfo } from '../../../api/types/subscriptions';
import {
  CONTENT_TYPES,
  DEFAULT_ADVANCED_FILTERS,
  PAGE_SIZE,
  PAID_CONTENT_TYPES,
  decodeHtmlEntities,
  formatNumber,
  getSubscriptionCountdown,
  type AdvancedFilterKey,
  type AdvancedFilterMap,
  type AdvancedFilterState,
  type UserOverviewVersion,
} from '../lib/userProfileUtils';

const IDENTIFIER_CHOOSER_PAGE_SIZE = 100;

function filtersFromSearchParams(searchParams: URLSearchParams): AdvancedFilterMap {
  const filters = { ...DEFAULT_ADVANCED_FILTERS };
  for (const key of Object.keys(DEFAULT_ADVANCED_FILTERS) as AdvancedFilterKey[]) {
    const value = searchParams.get(`filter_${key}`);
    if (value === 'include' || value === 'exclude') {
      filters[key] = value;
    }
  }
  return filters;
}

export function useUserProfileController() {
  type ScrapeDispatchMode = 'local' | 'delegate';
  type UserProfileTab = 'overview' | 'content' | 'paid' | 'subscriptions';

  const { userId } = useParams<{ userId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const site = searchParams.get('site') || 'onlyfans';
  const source = searchParams.get('source')?.toLowerCase();
  const rawReturnTo = searchParams.get('return_to');
  const backTarget = rawReturnTo && rawReturnTo.startsWith('/') ? rawReturnTo : '/users';
  const tabParam = searchParams.get('tab')?.toLowerCase();
  const requestedTab: UserProfileTab =
    tabParam === 'subscriptions'
      ? 'subscriptions'
      : tabParam === 'paid'
        ? 'paid'
        : tabParam === 'content'
          ? 'content'
          : source === 'paid'
            ? 'paid'
            : source === 'content'
              ? 'content'
              : 'overview';
  const userIdentifier = (userId || '').trim();
  const normalizedIdentifier = userIdentifier.replace(/^@/, '').toLowerCase();
  const conflictIdentifier = (searchParams.get('conflict') || '').replace(/^@/, '').trim().toLowerCase();
  const parsedConflictPage = Number.parseInt(searchParams.get('conflict_page') || '1', 10);
  const conflictPage = Number.isFinite(parsedConflictPage) && parsedConflictPage > 0
    ? parsedConflictPage
    : 1;

  const {
    data: identifierResolution,
    isLoading: resolvingUserId,
    error: identifierResolutionRequestError,
  } = useQuery<UserIdentifierResolutionResponse>({
    queryKey: [
      'user-profile-identifier-resolution',
      normalizedIdentifier,
      site,
      1,
      IDENTIFIER_CHOOSER_PAGE_SIZE,
    ],
    enabled: Boolean(normalizedIdentifier),
    queryFn: () =>
      resolveUserIdentifier(
        normalizedIdentifier,
        site,
        1,
        IDENTIFIER_CHOOSER_PAGE_SIZE,
      ),
  });

  const {
    data: conflictNavigationResolution,
    isLoading: conflictNavigationLoading,
  } = useQuery<UserIdentifierResolutionResponse>({
    queryKey: ['user-profile-conflict-navigation', conflictIdentifier, site, conflictPage],
    enabled: Boolean(conflictIdentifier && /^\d+$/.test(normalizedIdentifier)),
    queryFn: () => resolveUserIdentifier(conflictIdentifier, site, conflictPage, 1),
  });

  const resolveUserError =
    identifierResolutionRequestError ||
    (!identifierResolution?.success
      ? new Error(identifierResolution?.error || 'User could not be resolved')
      : null);
  const resolvedNumericUserId =
    identifierResolution?.status === 'resolved' && identifierResolution.user_id !== null
      ? identifierResolution.user_id
      : NaN;

  const [activeTab, setActiveTab] = useState<UserProfileTab>(requestedTab);
  const [countdownNowMs, setCountdownNowMs] = useState(() => Date.now());
  const [overviewVersionIndex, setOverviewVersionIndex] = useState(0);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [conflictNavigationPending, setConflictNavigationPending] = useState(false);
  const toastTimeout = useRef<number | null>(null);

  const [contentItems, setContentItems] = useState<ContentLibraryItem[]>([]);
  const [contentTotal, setContentTotal] = useState(0);
  const [contentPage, setContentPage] = useState(1);
  const [contentLoading, setContentLoading] = useState(false);
  const [contentHasMore, setContentHasMore] = useState(true);
  const [contentError, setContentError] = useState<string | null>(null);
  const [contentType, setContentType] = useState('');
  const [contentSearch, setContentSearch] = useState('');
  const [contentSearchInput, setContentSearchInput] = useState('');
  const [contentSortBy, setContentSortBy] = useState('created_at');
  const [contentOrder, setContentOrder] = useState<'asc' | 'desc'>('desc');
  const [contentAdvancedFilters, setContentAdvancedFilters] =
    useState<AdvancedFilterMap>(() => filtersFromSearchParams(searchParams));
  const [contentDraftAdvancedFilters, setContentDraftAdvancedFilters] =
    useState<AdvancedFilterMap>(() => filtersFromSearchParams(searchParams));
  const [contentFilterModalOpen, setContentFilterModalOpen] = useState(false);
  const [buyingContentKey, setBuyingContentKey] = useState<string | null>(null);
  const sentinelRef = useRef<HTMLDivElement>(null);
  const searchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [authPickerOpen, setAuthPickerOpen] = useState(false);
  const [eligibleAuths, setEligibleAuths] = useState<EligibleAuth[]>([]);
  const [authPickerLoading, setAuthPickerLoading] = useState(false);
  const [pendingScrapeAction, setPendingScrapeAction] = useState<ScrapeDispatchMode | null>(null);
  const [chatModalOpen, setChatModalOpen] = useState(false);
  const [copiedDirPath, setCopiedDirPath] = useState<string | null>(null);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [sexModalOpen, setSexModalOpen] = useState(false);
  const [editName, setEditName] = useState('');
  const [editAlias, setEditAlias] = useState('');
  const [editDescription, setEditDescription] = useState('');
  // Shared by the edit modal (sex/gender only) and the identity modal.
  const identity = useIdentityDraft();
  const [selectedProfileAuthId, setSelectedProfileAuthId] = useState<number | ''>('');
  const [profileSubscriptionsSearchTerm, setProfileSubscriptionsSearchTerm] = useState('');
  const [profileSubscriptionsSearchQuery, setProfileSubscriptionsSearchQuery] = useState('');
  const [profileSubscriptionsActiveOnly, setProfileSubscriptionsActiveOnly] = useState(true);
  const [profileSubscriptionsMinPrice, setProfileSubscriptionsMinPrice] = useState('');
  const [profileSubscriptionsMaxPrice, setProfileSubscriptionsMaxPrice] = useState('');
  const [profileSubscriptionsSexFilter, setProfileSubscriptionsSexFilter] =
    useState<number[]>([]);
  const [profileSubscriptionsOrderBy, setProfileSubscriptionsOrderBy] = useState('username');
  const [profileSubscriptionsOrderDir, setProfileSubscriptionsOrderDir] =
    useState<'asc' | 'desc'>('asc');
  const [profileSubscriptionsFiltersModalOpen, setProfileSubscriptionsFiltersModalOpen] =
    useState(false);
  const [profileSubscriptionsDraftActiveOnly, setProfileSubscriptionsDraftActiveOnly] =
    useState(true);
  const [profileSubscriptionsDraftMinPrice, setProfileSubscriptionsDraftMinPrice] = useState('');
  const [profileSubscriptionsDraftMaxPrice, setProfileSubscriptionsDraftMaxPrice] = useState('');
  const [profileSubscriptionsDraftSexFilter, setProfileSubscriptionsDraftSexFilter] =
    useState<number[]>([]);
  const [profileSubscriptionsLoadoutModalOpen, setProfileSubscriptionsLoadoutModalOpen] =
    useState(false);
  const [profileSubscriptionsLoadoutNameInput, setProfileSubscriptionsLoadoutNameInput] =
    useState('');
  const [profileSubscriptionsSelectedLoadoutName, setProfileSubscriptionsSelectedLoadoutName] =
    useState('');
  const [profileSubscriptionsDefaultLoadoutApplied, setProfileSubscriptionsDefaultLoadoutApplied] =
    useState(false);
  const copyDirTimeout = useRef<number | null>(null);

  useEffect(() => {
    setActiveTab(requestedTab);
  }, [requestedTab, userId]);

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      setCountdownNowMs(Date.now());
    }, 60_000);
    return () => window.clearInterval(intervalId);
  }, []);

  useEffect(() => {
    return () => {
      if (searchTimeout.current) {
        clearTimeout(searchTimeout.current);
      }
      if (copyDirTimeout.current !== null) {
        window.clearTimeout(copyDirTimeout.current);
      }
      if (toastTimeout.current !== null) {
        window.clearTimeout(toastTimeout.current);
      }
    };
  }, []);

  const showToast = (message: string, type: 'success' | 'error') => {
    if (toastTimeout.current !== null) {
      window.clearTimeout(toastTimeout.current);
    }
    setToast({ message, type });
    toastTimeout.current = window.setTimeout(() => {
      setToast(null);
      toastTimeout.current = null;
    }, 3000);
  };

  const openLightbox = useCallback((url: string | null) => {
    if (url) setLightboxUrl(url);
  }, []);
  const closeLightbox = useCallback(() => setLightboxUrl(null), []);

  const setTabInQuery = useCallback(
    (tab: UserProfileTab) => {
      const next = new URLSearchParams(searchParams);
      if (tab === 'content') {
        next.set('source', 'content');
        next.set('tab', 'content');
      } else if (tab === 'paid') {
        next.set('source', 'paid');
        next.set('tab', 'paid');
      } else if (tab === 'subscriptions') {
        next.delete('source');
        next.set('tab', 'subscriptions');
      } else {
        next.delete('source');
        next.delete('tab');
      }
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams]
  );

  const handleTabClick = useCallback(
    (tab: UserProfileTab) => {
      setActiveTab(tab);
      setTabInQuery(tab);
    },
    [setTabInQuery]
  );

  const goBack = useCallback(() => {
    navigate(backTarget);
  }, [backTarget, navigate]);

  const selectIdentifierCandidate = useCallback(
    (candidateUserId: number) => {
      const next = new URLSearchParams(searchParams);
      const candidateIndex = identifierResolution?.candidates.findIndex(
        (candidate) => candidate.user_id === candidateUserId,
      ) ?? -1;
      const absolutePosition = candidateIndex >= 0
        ? ((identifierResolution?.page ?? 1) - 1) * (identifierResolution?.page_size ?? IDENTIFIER_CHOOSER_PAGE_SIZE) + candidateIndex + 1
        : 1;
      next.set('conflict', normalizedIdentifier);
      next.set('conflict_page', String(absolutePosition));
      const query = next.toString();
      navigate(`/users/${candidateUserId}${query ? `?${query}` : ''}`);
    },
    [identifierResolution, navigate, normalizedIdentifier, searchParams]
  );

  const navigateConflictPage = useCallback(
    async (targetPage: number) => {
      if (!conflictIdentifier || targetPage < 1) return;
      setConflictNavigationPending(true);
      try {
        const resolution = await queryClient.fetchQuery({
          queryKey: ['user-profile-conflict-navigation', conflictIdentifier, site, targetPage],
          queryFn: () => resolveUserIdentifier(conflictIdentifier, site, targetPage, 1),
        });
        const candidate = resolution.candidates[0];
        if (resolution.status !== 'ambiguous' || !candidate) {
          throw new Error('The requested conflicting profile is no longer available');
        }
        const next = new URLSearchParams(searchParams);
        next.set('conflict', conflictIdentifier);
        next.set('conflict_page', String(targetPage));
        navigate(`/users/${candidate.user_id}?${next.toString()}`);
      } catch (error) {
        showToast(
          error instanceof Error ? error.message : 'Unable to open the conflicting profile',
          'error',
        );
      } finally {
        setConflictNavigationPending(false);
      }
    },
    [conflictIdentifier, navigate, queryClient, searchParams, site],
  );

  const contentIncludeFlags = useMemo(
    () =>
      Object.entries(contentAdvancedFilters)
        .filter(([, state]) => state === 'include')
        .map(([key]) => key as AdvancedFilterKey),
    [contentAdvancedFilters]
  );
  const contentExcludeFlags = useMemo(
    () =>
      Object.entries(contentAdvancedFilters)
        .filter(([, state]) => state === 'exclude')
        .map(([key]) => key as AdvancedFilterKey),
    [contentAdvancedFilters]
  );

  const handleCopyDir = (path: string) => {
    navigator.clipboard.writeText(path).then(() => {
      if (copyDirTimeout.current !== null) {
        window.clearTimeout(copyDirTimeout.current);
      }
      setCopiedDirPath(path);
      copyDirTimeout.current = window.setTimeout(() => {
        setCopiedDirPath(null);
        copyDirTimeout.current = null;
      }, 1500);
    });
  };

  const { data: profileData, isLoading: profileLoading, error: profileError } =
    useQuery<DetailedUserResponse>({
      queryKey: ['user-profile', resolvedNumericUserId, site],
      queryFn: () => getUserProfile(resolvedNumericUserId, site),
      enabled: Number.isFinite(resolvedNumericUserId),
      staleTime: 30_000,
      // API processes can observe the same refresh at different stages. Keep
      // checking saved stale data so an old process-local error cannot stop us
      // from seeing another process's committed refresh.
      refetchInterval: (query) => query.state.data?.is_refreshing
        ? 1_500
        : query.state.data?.is_stale ? 5_000 : false,
    });

  const user = profileData?.user ?? null;

  const refreshProfileMutation = useMutation({
    mutationFn: () => refreshUserProfile(resolvedNumericUserId, site),
    onSuccess: (result) => {
      if (!result.accepted) {
        showToast(result.error || 'Profile refresh could not be started', 'error');
        return;
      }
      showToast('Profile refresh started', 'success');
      queryClient.invalidateQueries({
        queryKey: ['user-profile', resolvedNumericUserId, site],
      });
    },
    onError: (error: Error) => {
      showToast(`Failed to refresh profile: ${error.message}`, 'error');
    },
  });

  useEffect(() => {
    document.title = getUserProfileDocumentTitle(user?.username);
  }, [user?.username]);

  const subscriptionCountdown = useMemo(
    () =>
      getSubscriptionCountdown(
        user?.subscription_expires_at ?? null,
        user?.is_subscribed ?? false,
        countdownNowMs
      ),
    [countdownNowMs, user?.is_subscribed, user?.subscription_expires_at]
  );

  const {
    data: directoryLookup,
    isFetching: directoryLookupLoading,
    isError: directoryLookupError,
    isFetched: directoryLookupFetched,
    refetch: refetchDirectoryLookup,
  } = useQuery({
    queryKey: ['user-directory-lookup', user?.site, user?.user_id, user?.username],
    queryFn: () => searchUsernameDirectories(user!.username, user!.site, user!.user_id),
    enabled: Boolean(user?.site && user?.user_id),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });

  const handleFindDirectory = useCallback(async () => {
    if (!user?.site || !user?.user_id) {
      return;
    }

    await refetchDirectoryLookup();
  }, [refetchDirectoryLookup, user?.site, user?.user_id]);

  const { data: watched = false } = useQuery<boolean>({
    queryKey: ['user-watch-status', user?.site, user?.user_id, user?.username],
    enabled: Boolean(user?.site && user?.user_id && user?.username),
    staleTime: 60_000,
    queryFn: async () => {
      if (!user?.site || !user?.user_id || !user?.username) {
        return false;
      }

      const response = await getWatchList(user.site, user.username, 100, 0);
      const normalizedUsername = user.username.toLowerCase();
      return response.users.some(
        (candidate) =>
          candidate.site === user.site &&
          candidate.watched &&
          ((candidate.username?.toLowerCase() ?? '') === normalizedUsername ||
            candidate.id === user.user_id),
      );
    },
  });

  const { data: historyData, isLoading: historyLoading } = useQuery<HistoUserInfoResponse>({
    queryKey: ['user-history', resolvedNumericUserId, site],
    enabled: Number.isFinite(resolvedNumericUserId),
    staleTime: 60_000,
    queryFn: () => getUserHistory(resolvedNumericUserId, site),
  });

  const {
    data: profileAuthsData,
    isLoading: profileAuthsLoading,
    isFetched: profileAuthsFetched,
    error: profileAuthsError,
  } = useQuery({
    queryKey: ['user-profile-auths', user?.site, user?.user_id],
    enabled: Boolean(user?.site && user?.user_id),
    staleTime: 60_000,
    queryFn: () => getAuthList(user!.site, undefined, undefined, user!.user_id),
  });

  const { data: aliasData } = useQuery<UserAliasResponse>({
    queryKey: ['user-aliases', resolvedNumericUserId, site],
    enabled: Number.isFinite(resolvedNumericUserId),
    staleTime: 60_000,
    refetchInterval: profileData?.is_refreshing ? 1_500 : false,
    queryFn: () => getUserAliases(resolvedNumericUserId, site),
  });

  const observedProfileRefreshRef = useRef({
    profileKey: '',
    wasRefreshing: false,
  });

  useEffect(() => {
    if (!Number.isFinite(resolvedNumericUserId)) return;

    const profileKey = `${site}:${resolvedNumericUserId}`;
    if (observedProfileRefreshRef.current.profileKey !== profileKey) {
      observedProfileRefreshRef.current = { profileKey, wasRefreshing: false };
    }

    if (profileData?.is_refreshing) {
      observedProfileRefreshRef.current.wasRefreshing = true;
      return;
    }

    if (!observedProfileRefreshRef.current.wasRefreshing) return;

    observedProfileRefreshRef.current.wasRefreshing = false;
    void queryClient.invalidateQueries({
      queryKey: ['user-aliases', resolvedNumericUserId, site],
    });
    void queryClient.invalidateQueries({
      queryKey: ['user-profile-identifier-resolution', normalizedIdentifier, site],
    });
  }, [normalizedIdentifier, profileData?.is_refreshing, queryClient, resolvedNumericUserId, site]);

  const deleteAliasMutation = useMutation({
    mutationFn: (aliasId: number) => deleteUserAlias(resolvedNumericUserId, site, aliasId),
    onSuccess: (data) => {
      if (!data.success) {
        showToast(data.error || 'Failed to remove alias', 'error');
        return;
      }
      showToast('Alias removed', 'success');
      queryClient.invalidateQueries({ queryKey: ['user-aliases', resolvedNumericUserId, site] });
    },
    onError: (error: Error) => {
      showToast(`Failed to remove alias: ${error.message}`, 'error');
    },
  });

  const handleRemoveAlias = (alias: UserAliasResponse['aliases'][number]) => {
    if (deleteAliasMutation.isPending) return;
    if (!window.confirm(`Remove @${alias.username} from this user's aliases?`)) return;
    deleteAliasMutation.mutate(alias.id);
  };

  const { data: paidPreviewData, isLoading: paidPreviewLoading } =
    useQuery<ContentLibraryResponse>({
      queryKey: ['user-paid-preview', resolvedNumericUserId, site],
      enabled: Number.isFinite(resolvedNumericUserId),
      staleTime: 60_000,
      queryFn: () =>
        browseContentLibrary({
          site,
          userId: resolvedNumericUserId,
          includeFlags: ['purchased'],
          sortBy: 'created_at',
          order: 'desc',
          page: 1,
          pageSize: 4,
        }),
    });

  const historySnapshots = useMemo(
    () => (historyData?.success ? historyData.snapshots : []),
    [historyData]
  );
  const profileAuths = useMemo<AuthCredential[]>(
    () => (profileAuthsData?.success ? profileAuthsData.auths : []),
    [profileAuthsData]
  );
  const { data: profileSubscriptionsLoadoutsData, isFetched: profileSubscriptionsLoadoutsFetched } =
    useQuery({
      queryKey: ['search-loadouts', 'subscriptions'],
      queryFn: () => getSearchLoadouts('subscriptions'),
    });
  const hasSubscriptionsTab = profileAuths.length > 0;
  const preferredProfileAuthId = useMemo(
    () => profileAuths.find((auth) => auth.active)?.id ?? profileAuths[0]?.id ?? '',
    [profileAuths]
  );
  const selectedProfileSubscriptionsLoadout = profileSubscriptionsLoadoutsData?.loadouts.find(
    (loadout) => loadout.name === profileSubscriptionsSelectedLoadoutName
  );
  const profileSubscriptionsSelectedLoadoutIsDefault = Boolean(
    selectedProfileSubscriptionsLoadout?.is_default
  );
  const selectedProfileAuth =
    profileAuths.find((auth) => auth.id === selectedProfileAuthId) ?? null;
  const userAliases = aliasData?.success
    ? aliasData.aliases.filter((alias) => alias.username && alias.username !== user?.username)
    : [];
  const paidPreviewItems = useMemo(
    () => (paidPreviewData?.success ? paidPreviewData.content : []),
    [paidPreviewData]
  );
  const paidPreviewTotal = paidPreviewData?.success ? paidPreviewData.total : 0;
  const paidPreviewMediaCount = useMemo(
    () => paidPreviewItems.reduce((sum, item) => sum + item.media_count, 0),
    [paidPreviewItems]
  );
  const paidTabLabel = paidPreviewTotal > 0 ? `Paid (${formatNumber(paidPreviewTotal)})` : 'Paid';
  const activeContentTypeOptions = activeTab === 'paid' ? PAID_CONTENT_TYPES : CONTENT_TYPES;
  const activeContentAdvancedFilterCount =
    contentIncludeFlags.length + contentExcludeFlags.length;
  const effectiveContentIncludeFlags = useMemo(() => {
    const flags = new Set(contentIncludeFlags);
    if (activeTab === 'paid') {
      flags.add('purchased');
    }
    return Array.from(flags);
  }, [activeTab, contentIncludeFlags]);
  const effectiveContentExcludeFlags = useMemo(
    () =>
      activeTab === 'paid'
        ? contentExcludeFlags.filter((flag) => flag !== 'purchased')
        : contentExcludeFlags,
    [activeTab, contentExcludeFlags]
  );

  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    for (const key of Object.keys(DEFAULT_ADVANCED_FILTERS) as AdvancedFilterKey[]) {
      const paramName = `filter_${key}`;
      const value = contentAdvancedFilters[key];
      if (value === 'none') {
        next.delete(paramName);
      } else {
        next.set(paramName, value);
      }
    }
    if (next.toString() !== searchParams.toString()) {
      setSearchParams(next, { replace: true });
    }
  }, [contentAdvancedFilters, searchParams, setSearchParams]);

  useEffect(() => {
    setSelectedProfileAuthId((current) => {
      if (current !== '' && profileAuths.some((auth) => auth.id === current)) {
        return current;
      }
      return preferredProfileAuthId;
    });
  }, [preferredProfileAuthId, profileAuths]);

  useEffect(() => {
    if (
      activeTab === 'subscriptions' &&
      profileAuthsFetched &&
      !profileAuthsError &&
      !hasSubscriptionsTab
    ) {
      setActiveTab('overview');
      setTabInQuery('overview');
    }
  }, [
    activeTab,
    hasSubscriptionsTab,
    profileAuthsError,
    profileAuthsFetched,
    setTabInQuery,
  ]);

  useEffect(() => {
    if (activeTab !== 'paid') return;
    if (!PAID_CONTENT_TYPES.some((option) => option.value === contentType)) {
      setContentType('');
    }
  }, [activeTab, contentType]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setProfileSubscriptionsSearchQuery(profileSubscriptionsSearchTerm.trim());
    }, 400);

    return () => window.clearTimeout(timer);
  }, [profileSubscriptionsSearchTerm]);

  const applyProfileSubscriptionsLoadout = useCallback(
    (loadout: SearchLoadoutItem) => {
      const identifier = loadout.identifier || '';
      const filters = loadout.filters || {};
      const nextSex = Array.isArray(filters.sex)
        ? filters.sex
            .map((value) => Number(value))
            .filter((value) => Number.isInteger(value) && [0, 1, 2].includes(value))
        : [];
      const authIdRaw = filters.auth_id;
      const nextAuthId =
        typeof authIdRaw === 'number' && Number.isInteger(authIdRaw) ? authIdRaw : '';
      const loadoutMinPrice = filters.min_price;
      const loadoutMaxPrice = filters.max_price;
      const legacyHideFree = filters.hide_free_subscriptions;
      const nextMinPrice =
        typeof loadoutMinPrice === 'number'
          ? String(loadoutMinPrice)
          : typeof loadoutMinPrice === 'string'
            ? loadoutMinPrice
            : legacyHideFree === true
              ? '0.01'
              : '';
      const nextMaxPrice =
        typeof loadoutMaxPrice === 'number'
          ? String(loadoutMaxPrice)
          : typeof loadoutMaxPrice === 'string'
            ? loadoutMaxPrice
            : '';

      setProfileSubscriptionsSearchTerm(identifier);
      setProfileSubscriptionsSearchQuery(identifier);
      setProfileSubscriptionsActiveOnly(
        typeof filters.active_only === 'boolean' ? filters.active_only : true
      );
      setProfileSubscriptionsMinPrice(nextMinPrice);
      setProfileSubscriptionsMaxPrice(nextMaxPrice);
      setProfileSubscriptionsSexFilter(nextSex);
      setSelectedProfileAuthId(nextAuthId);
      setProfileSubscriptionsOrderBy(
        typeof filters.order_by === 'string' ? filters.order_by : 'username'
      );
      setProfileSubscriptionsOrderDir(filters.order_dir === 'desc' ? 'desc' : 'asc');
    },
    []
  );

  useEffect(() => {
    if (profileSubscriptionsDefaultLoadoutApplied || !profileSubscriptionsLoadoutsFetched) {
      return;
    }
    const defaultLoadoutName = profileSubscriptionsLoadoutsData?.default_name;
    if (defaultLoadoutName) {
      const defaultLoadout = profileSubscriptionsLoadoutsData?.loadouts.find(
        (loadout) => loadout.name === defaultLoadoutName
      );
      if (defaultLoadout) {
        applyProfileSubscriptionsLoadout(defaultLoadout);
        setProfileSubscriptionsSelectedLoadoutName(defaultLoadout.name);
      }
    }
    setProfileSubscriptionsDefaultLoadoutApplied(true);
  }, [
    applyProfileSubscriptionsLoadout,
    profileSubscriptionsDefaultLoadoutApplied,
    profileSubscriptionsLoadoutsData,
    profileSubscriptionsLoadoutsFetched,
  ]);

  useEffect(() => {
    setOverviewVersionIndex(0);
  }, [site, resolvedNumericUserId, historySnapshots.length]);

  const overviewVersions = useMemo<UserOverviewVersion[]>(() => {
    if (!user) return [];
    return [
      {
        key: 'current',
        label: 'Current',
        createdAt: user.last_checked_at || user.created_at || null,
        data: {
          description: user.description ? stripHtml(user.description) : '',
          price: user.price,
          media_count: user.media_count,
          audio_count: user.audio_count,
          stream_count: user.stream_count,
          archived_post_count: user.archived_post_count,
          favourited_count: user.favourited_count,
          subscribers_count: user.subscribers_count,
          location: user.location,
          website: user.website,
          sex: user.sex,
          join_date: user.join_date,
          last_checked_at: user.last_checked_at,
          downloaded_at: user.downloaded_at,
          first_downloaded_at: user.first_downloaded_at,
          created_at: user.created_at,
        },
      },
      ...historySnapshots.map((snapshot: HistoUserInfoItem, index: number) => ({
        key: `history-${snapshot.id}`,
        label: `Snapshot ${historySnapshots.length - index}`,
        createdAt: snapshot.created_at,
        data: {
          description: snapshot.about ? stripHtml(snapshot.about) : '',
          price: snapshot.price,
          media_count: snapshot.media_count,
          audio_count: snapshot.audio_count,
          stream_count: 0,
          archived_post_count: snapshot.archived_post_count,
          favourited_count: 0,
          subscribers_count: snapshot.subscriber_count,
          location: user.location,
          website: user.website,
          sex: user.sex,
          join_date: user.join_date,
          last_checked_at: snapshot.created_at,
          downloaded_at: user.downloaded_at,
          first_downloaded_at: user.first_downloaded_at,
          created_at: snapshot.created_at,
        },
      })),
    ];
  }, [user, historySnapshots]);

  const activeOverviewVersion =
    overviewVersions[
      Math.min(Math.max(overviewVersionIndex, 0), Math.max(overviewVersions.length - 1, 0))
    ];
  const activeOverviewData = activeOverviewVersion?.data ?? null;
  const hasOlderOverviewVersion = overviewVersionIndex < overviewVersions.length - 1;
  const hasNewerOverviewVersion = overviewVersionIndex > 0;

  const fetchContent = useCallback(
    async (pageNum: number, append: boolean) => {
      // Username routes resolve asynchronously. Do not issue an unscoped
      // library request while the numeric user id is still unknown.
      if (!Number.isFinite(resolvedNumericUserId)) {
        return;
      }
      setContentLoading(true);
      setContentError(null);
      try {
        const response: ContentLibraryResponse = await browseContentLibrary({
          site: site || undefined,
          contentType: contentType || undefined,
          userId: resolvedNumericUserId,
          search: contentSearch || undefined,
          sortBy: contentSortBy,
          order: contentOrder,
          includeFlags: effectiveContentIncludeFlags.length ? effectiveContentIncludeFlags : undefined,
          excludeFlags: effectiveContentExcludeFlags.length ? effectiveContentExcludeFlags : undefined,
          page: pageNum,
          pageSize: PAGE_SIZE,
        });
        if (response.success) {
          setContentItems((previous) =>
            append ? [...previous, ...response.content] : response.content
          );
          setContentTotal(response.total);
          const loadedCount = (pageNum - 1) * PAGE_SIZE + response.content.length;
          setContentHasMore(response.content.length === PAGE_SIZE && loadedCount < response.total);
        } else {
          setContentError(response.error ?? 'Failed to load content');
        }
      } catch (error) {
        setContentError(error instanceof Error ? error.message : 'Network error');
      } finally {
        setContentLoading(false);
      }
    },
    [
      site,
      contentType,
      resolvedNumericUserId,
      contentSearch,
      contentSortBy,
      contentOrder,
      effectiveContentIncludeFlags,
      effectiveContentExcludeFlags,
    ]
  );

  useEffect(() => {
    if (activeTab !== 'content' && activeTab !== 'paid') return;
    setContentPage(1);
    if (!Number.isFinite(resolvedNumericUserId)) {
      setContentItems([]);
      setContentTotal(0);
      setContentHasMore(false);
      return;
    }
    setContentHasMore(true);
    void fetchContent(1, false);
  }, [
    site,
    contentType,
    contentSearch,
    contentSortBy,
    contentOrder,
    contentIncludeFlags,
    contentExcludeFlags,
    activeTab,
    fetchContent,
    resolvedNumericUserId,
  ]);

  const {
    data: profileSubscriptionsData,
    isLoading: profileSubscriptionsLoading,
    error: profileSubscriptionsError,
    fetchNextPage: fetchNextProfileSubscriptionsPage,
    hasNextPage: profileSubscriptionsHasNextPage,
    isFetchingNextPage: profileSubscriptionsIsFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: [
      'user-profile-subscriptions',
      user?.site,
      selectedProfileAuthId,
      profileSubscriptionsSearchQuery,
      profileSubscriptionsActiveOnly,
      profileSubscriptionsSexFilter.join(','),
      profileSubscriptionsOrderBy,
      profileSubscriptionsOrderDir,
    ],
    enabled: activeTab === 'subscriptions' && selectedProfileAuthId !== '' && Boolean(user?.site),
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      getSubscriptions(
        user?.site || undefined,
        profileSubscriptionsSearchQuery || undefined,
        profileSubscriptionsActiveOnly,
        selectedProfileAuthId === '' ? undefined : selectedProfileAuthId,
        100,
        typeof pageParam === 'number' ? pageParam : 0,
        profileSubscriptionsOrderBy,
        profileSubscriptionsOrderDir,
        profileSubscriptionsSexFilter.length ? profileSubscriptionsSexFilter : undefined,
      ),
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, page) => sum + page.subscriptions.length, 0);
      return loaded < lastPage.total ? loaded : undefined;
    },
  });

  const profileSubscriptions = useMemo<SubscriptionInfo[]>(
    () => (profileSubscriptionsData?.pages ?? []).flatMap((page) => page.subscriptions),
    [profileSubscriptionsData]
  );
  const profileSubscriptionsTotal = profileSubscriptionsData?.pages?.[0]?.total ?? 0;
  const parsedProfileSubscriptionsMinPrice = Number.parseFloat(profileSubscriptionsMinPrice);
  const parsedProfileSubscriptionsMaxPrice = Number.parseFloat(profileSubscriptionsMaxPrice);
  const normalizedProfileSubscriptionsMinPrice = Number.isFinite(parsedProfileSubscriptionsMinPrice)
    ? parsedProfileSubscriptionsMinPrice
    : null;
  const normalizedProfileSubscriptionsMaxPrice = Number.isFinite(parsedProfileSubscriptionsMaxPrice)
    ? parsedProfileSubscriptionsMaxPrice
    : null;
  const visibleProfileSubscriptions = useMemo(
    () =>
      profileSubscriptions.filter((subscription) => {
        const price = subscription.price ?? 0;
        if (
          normalizedProfileSubscriptionsMinPrice !== null &&
          price < normalizedProfileSubscriptionsMinPrice
        ) {
          return false;
        }
        if (
          normalizedProfileSubscriptionsMaxPrice !== null &&
          price > normalizedProfileSubscriptionsMaxPrice
        ) {
          return false;
        }
        return true;
      }),
    [
      normalizedProfileSubscriptionsMaxPrice,
      normalizedProfileSubscriptionsMinPrice,
      profileSubscriptions,
    ]
  );
  const profileSubscriptionsActiveFilterCount =
    (profileSubscriptionsActiveOnly ? 1 : 0) +
    ((profileSubscriptionsMinPrice.trim() || profileSubscriptionsMaxPrice.trim()) ? 1 : 0) +
    (profileSubscriptionsSexFilter.length ? 1 : 0);

  useEffect(() => {
    if ((activeTab !== 'content' && activeTab !== 'paid') || !sentinelRef.current) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && contentHasMore && !contentLoading) {
          const nextPage = contentPage + 1;
          setContentPage(nextPage);
          void fetchContent(nextPage, true);
        }
      },
      { rootMargin: '300px' }
    );
    observer.observe(sentinelRef.current);
    return () => observer.disconnect();
  }, [contentHasMore, contentLoading, contentPage, fetchContent, activeTab]);

  const handleSearchInput = useCallback((value: string) => {
    setContentSearchInput(value);
    if (searchTimeout.current) clearTimeout(searchTimeout.current);
    searchTimeout.current = setTimeout(() => setContentSearch(value), 400);
  }, []);

  const openContentFilters = () => {
    setContentDraftAdvancedFilters(contentAdvancedFilters);
    setContentFilterModalOpen(true);
  };

  const setContentDraftFilterState = (key: AdvancedFilterKey, state: AdvancedFilterState) => {
    setContentDraftAdvancedFilters((previous) => ({
      ...previous,
      [key]: state,
    }));
  };

  const applyContentFilters = () => {
    setContentAdvancedFilters(contentDraftAdvancedFilters);
    setContentFilterModalOpen(false);
  };

  const clearContentDraftFilters = () => {
    setContentDraftAdvancedFilters(DEFAULT_ADVANCED_FILTERS);
  };

  const createJobMutation = useMutation({
    mutationFn: createJob,
    onSuccess: (data: { job_name: string }) => {
      showToast(`Job "${data.job_name}" created successfully!`, 'success');
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: (error: Error) => {
      showToast(`Failed to create job: ${error.message}`, 'error');
    },
  });

  const delegateJobMutation = useMutation({
    mutationFn: (request: { pluginId: string; payload: Record<string, unknown> }) =>
      submitDelegatedJob(request.pluginId, {
        payload: request.payload,
        idempotency_key:
          typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
            ? crypto.randomUUID()
            : undefined,
      }),
    onSuccess: (data) => {
      if (data.status !== 'submitted') {
        showToast(data.last_error || 'Failed to delegate scrape', 'error');
        return;
      }
      showToast(
        `Delegated scrape queued (${data.external_job_id || data.correlation_id})`,
        'success'
      );
    },
    onError: (error: Error) => {
      showToast(`Failed to delegate scrape: ${error.message}`, 'error');
    },
  });

  const subscribeMutation = useMutation({
    mutationFn: (request: {
      site: string;
      user_id: number;
      username: string;
      price: number;
      auto_execute: boolean;
    }) => createOrderedPerformer(request),
    onSuccess: (data: OrderedPerformerCreateResponse) => {
      if (data.success) {
        showToast(
          data.status === 'completed'
            ? `Subscribed to @${data.username || 'user'}`
            : `Order queued for @${data.username || 'user'}`,
          'success'
        );
      } else {
        showToast(data.error || 'Failed to subscribe', 'error');
      }
      queryClient.invalidateQueries({ queryKey: ['orders-performers'] });
    },
    onError: (error: Error) => {
      showToast(`Failed to subscribe: ${error.message}`, 'error');
    },
  });

  const favoriteMutation = useMutation({
    mutationFn: (favorite: boolean) => {
      if (!user) {
        throw new Error('User not loaded');
      }
      return updateUser(user.user_id, user.site, { favorite });
    },
    onSuccess: (data) => {
      if (!user) return;
      showToast(data.favorite ? 'User marked as favorite' : 'User removed from favorites', 'success');
      queryClient.invalidateQueries({ queryKey: ['user-profile', resolvedNumericUserId, site] });
      queryClient.invalidateQueries({ queryKey: ['users-list'] });
      queryClient.invalidateQueries({ queryKey: ['subscriptions'] });
    },
    onError: (error: Error) => {
      showToast(`Failed to update favorite: ${error.message}`, 'error');
    },
  });

  const watchMutation = useMutation({
    mutationFn: (nextWatched: boolean) => {
      if (!user) {
        throw new Error('User not loaded');
      }
      return nextWatched
        ? addToWatchList(user.user_id, user.site)
        : removeFromWatchList(user.user_id, user.site);
    },
    onSuccess: (data) => {
      if (!user) return;
      showToast(
        data.message || (data.watched ? `Watching @${user.username}` : `Stopped watching @${user.username}`),
        'success',
      );
      queryClient.setQueryData(
        ['user-watch-status', user.site, user.user_id, user.username],
        data.watched,
      );
      queryClient.invalidateQueries({ queryKey: ['watchList'] });
      queryClient.invalidateQueries({ queryKey: ['watchStats'] });
    },
    onError: (error: Error) => {
      showToast(`Failed to update watch status: ${error.message}`, 'error');
    },
  });

  const updateProfileMutation = useMutation({
    mutationFn: (payload: UserUpdateRequest) => {
      if (!user) {
        throw new Error('User not loaded');
      }
      return updateUser(user.user_id, user.site, payload);
    },
    onSuccess: () => {
      showToast(`Updated @${user?.username || 'user'}`, 'success');
      setEditModalOpen(false);
      setSexModalOpen(false);
      setEditAlias('');
      queryClient.invalidateQueries({ queryKey: ['user-profile', resolvedNumericUserId, site] });
      queryClient.invalidateQueries({ queryKey: ['user-aliases', resolvedNumericUserId, site] });
      queryClient.invalidateQueries({ queryKey: ['users-list'] });
      queryClient.invalidateQueries({ queryKey: ['subscriptions'] });
    },
    onError: (error: Error) => {
      showToast(`Failed to update user: ${error.message}`, 'error');
    },
  });

  const addLockedContentToOrderMutation = useMutation({
    mutationFn: (item: ContentLibraryItem) =>
      createOrderedPerformer({
        site: item.site,
        user_id: item.user_id,
        username: item.username,
        price: item.price > 0 ? item.price : user?.price,
        post_id: item.id,
        content_type: item.content_type,
        auto_execute: false,
      }),
    onSuccess: (data: OrderedPerformerCreateResponse, item: ContentLibraryItem) => {
      if (data.success) {
        showToast(
          `Queued PPV from @${item.username || item.user_id} — go to Orders to buy`,
          'success'
        );
        queryClient.invalidateQueries({ queryKey: ['orders'] });
        queryClient.invalidateQueries({ queryKey: ['orders-performers'] });
      } else {
        showToast(data.error || 'Failed to add locked content to orders', 'error');
      }
    },
    onError: (error: Error) => {
      showToast(`Failed to add locked content: ${error.message}`, 'error');
    },
    onSettled: () => {
      setBuyingContentKey(null);
    },
  });

  const buildScrapeTask = (authId?: number): TaskPayload | null => {
    if (!user) return null;
    const params: Record<string, unknown> = {
      site: user.site,
      username: user.username,
      content_types: ['Posts', 'ArchivedPosts', 'Messages', 'Stories', 'Highlights', 'Profile'],
      rescrape_existing: true,
    };
    if (authId !== undefined) {
      params.auth_id = authId;
    }
    const task: TaskPayload = {
      task_type: 'scrape_and_download',
      params,
    };
    return task;
  };

  const buildDelegatedWorkflowPayload = (authId: number): Record<string, unknown> | null => {
    if (!user) return null;
    const siteName = user.site === 'onlyfans' ? 'OnlyFans' : user.site === 'fansly' ? 'Fansly' : user.site;
    const contentTypes = ['Posts', 'ArchivedPosts', 'Messages', 'Stories', 'Highlights', 'Profile'];
    const tasks = contentTypes.flatMap((contentType) => {
      const aliasSuffix = contentType.toLowerCase().replace(/[^a-z0-9]+/g, '_');
      const scrapeAlias = `scrape_${aliasSuffix}`;
      return [
        {
          kind: 'scrape',
          alias: scrapeAlias,
          site_name: siteName,
          user_id: user.user_id,
          user_username: user.username,
          content_type: contentType,
          rescrape_existing: true,
        },
        {
          kind: 'download',
          alias: `download_${aliasSuffix}`,
          depends_on_aliases: [scrapeAlias],
          site_name: siteName,
          user_id: user.user_id,
          user_username: user.username,
          content_type: contentType,
        },
      ];
    });
    return {
      job_name: `Scrape + Download @${user.username} (${user.site})`,
      site: user.site,
      user_id: user.user_id,
      username: user.username,
      auth_id: authId,
      created_by: 'webui',
      origin: {
        source: 'user_profile',
        action: 'scrape_and_download',
      },
      tasks,
    };
  };

  const closeAuthPicker = () => {
    setAuthPickerOpen(false);
    setPendingScrapeAction(null);
  };

  const dispatchScrapeJob = (authId?: number) => {
    const task = buildScrapeTask(authId);
    if (!task || !user) return;
    createJobMutation.mutate({
      job_name: `Scrape + Download @${user.username} (${user.site})`,
      tasks: [task],
      created_by: 'webui',
    });
    closeAuthPicker();
  };

  const dispatchDelegatedScrape = (authId: number) => {
    const payload = buildDelegatedWorkflowPayload(authId);
    if (!payload) return;
    delegateJobMutation.mutate({
      pluginId: 'usweb-remote',
      payload,
    });
    closeAuthPicker();
  };

  const handleAuthSelection = (authId: number) => {
    if (pendingScrapeAction === 'delegate') {
      dispatchDelegatedScrape(authId);
      return;
    }
    dispatchScrapeJob(authId);
  };

  const openScrapeAuthPicker = async (mode: ScrapeDispatchMode) => {
    if (!user) return;
    setPendingScrapeAction(mode);
    setAuthPickerLoading(true);
    try {
      const response = await getEligibleAuths(user.user_id, user.site);
      if (response.error) {
        showToast(response.error, 'error');
        setPendingScrapeAction(null);
        return;
      }
      const auths = response.auths;
      if (auths.length === 0) {
        showToast(
          `No auth account with subscription history found for @${user.username}. Add or sync an auth that has subscribed before, then run Scrape + Download.`,
          'error'
        );
        setPendingScrapeAction(null);
      } else if (auths.length === 1) {
        if (mode === 'delegate') {
          dispatchDelegatedScrape(auths[0].auth_id);
        } else {
          dispatchScrapeJob(auths[0].auth_id);
        }
      } else {
        setEligibleAuths(auths);
        setAuthPickerOpen(true);
      }
    } catch (error) {
      showToast(
        `Failed to fetch eligible auths: ${error instanceof Error ? error.message : 'Unknown'}`,
        'error'
      );
      setPendingScrapeAction(null);
    } finally {
      setAuthPickerLoading(false);
    }
  };

  const handleScrape = async () => {
    await openScrapeAuthPicker('local');
  };

  const handleDelegateScrape = async () => {
    await openScrapeAuthPicker('delegate');
  };

  const handleSubscribe = () => {
    if (!user) return;
    subscribeMutation.mutate({
      site: user.site,
      user_id: user.user_id,
      username: user.username,
      price: user.price,
      auto_execute: false,
    });
  };

  const handleToggleFavorite = () => {
    if (!user || favoriteMutation.isPending) return;
    favoriteMutation.mutate(!user.favorite);
  };

  const handleToggleWatch = () => {
    if (!user || watchMutation.isPending) return;
    watchMutation.mutate(!watched);
  };

  const openEditModal = () => {
    if (!user) return;
    setEditName(user.name ?? '');
    setEditAlias('');
    setEditDescription(user.description ?? '');
    const fromUser = identityDraftFromUser(user);
    identity.setDraft((current) => ({ ...current, sex: fromUser.sex, gender: fromUser.gender }));
    setEditModalOpen(true);
  };

  const openSexModal = () => {
    if (!user) return;
    identity.setDraft(identityDraftFromUser(user));
    setSexModalOpen(true);
  };

  const handleSaveUserEdit = () => {
    // The edit modal only shows sex and gender, so only those are validated here.
    const parsed = parseIdentityDraft({
      ...EMPTY_IDENTITY_DRAFT,
      sex: identity.draft.sex,
      gender: identity.draft.gender,
    });
    if (!parsed.ok) {
      showToast(parsed.error, 'error');
      return;
    }

    updateProfileMutation.mutate({
      name: editName.trim() || null,
      alias: editAlias.trim() || null,
      description: editDescription.trim() || null,
      sex: parsed.values.sex,
      gender: parsed.values.gender,
    });
  };

  const handleSaveSex = () => {
    const parsed = parseIdentityDraft(identity.draft);
    if (!parsed.ok) {
      showToast(parsed.error, 'error');
      return;
    }

    updateProfileMutation.mutate({
      name: user?.name ?? null,
      alias: null,
      description: user?.description ?? null,
      ...parsed.values,
      ai_assisted: false,
      verified: true,
    });
  };

  const handleBuyLockedContent = (item: ContentLibraryItem) => {
    const contentKey = `${item.content_type}-${item.id}-${item.site}`;
    setBuyingContentKey(contentKey);
    addLockedContentToOrderMutation.mutate(item);
  };

  const handleViewMedia = () => {
    if (!user) return;
    navigate(`/media?site=${user.site}&username=${user.username}`);
  };

  const handleScrapeSubscription = (subscription: SubscriptionInfo) => {
    if (selectedProfileAuthId === '') {
      showToast('Select an auth account before scraping subscriptions.', 'error');
      return;
    }
    if (!subscription.username) {
      showToast(`Subscription #${subscription.user_id} has no username to scrape.`, 'error');
      return;
    }

    const task: TaskPayload = {
      task_type: 'scrape_and_download',
      params: {
        site: subscription.site,
        username: subscription.username,
        content_types: ['Posts', 'ArchivedPosts', 'Messages', 'Stories', 'Highlights', 'Profile'],
        rescrape_existing: true,
        auth_id: selectedProfileAuthId,
      },
    };

    createJobMutation.mutate({
      job_name: `Scrape + Download @${subscription.username} (${subscription.site})`,
      tasks: [task],
      created_by: 'webui',
    });
  };

  const openPaidTab = useCallback(() => {
    setActiveTab('paid');
    setTabInQuery('paid');
  }, [setTabInQuery]);

  const openProfileSubscriptionsFilters = () => {
    setProfileSubscriptionsDraftActiveOnly(profileSubscriptionsActiveOnly);
    setProfileSubscriptionsDraftMinPrice(profileSubscriptionsMinPrice);
    setProfileSubscriptionsDraftMaxPrice(profileSubscriptionsMaxPrice);
    setProfileSubscriptionsDraftSexFilter([...profileSubscriptionsSexFilter]);
    setProfileSubscriptionsFiltersModalOpen(true);
  };

  const closeProfileSubscriptionsFilters = () => {
    setProfileSubscriptionsFiltersModalOpen(false);
  };

  const applyProfileSubscriptionsFilters = () => {
    setProfileSubscriptionsActiveOnly(profileSubscriptionsDraftActiveOnly);
    setProfileSubscriptionsMinPrice(profileSubscriptionsDraftMinPrice.trim());
    setProfileSubscriptionsMaxPrice(profileSubscriptionsDraftMaxPrice.trim());
    setProfileSubscriptionsSexFilter([...profileSubscriptionsDraftSexFilter]);
    setProfileSubscriptionsFiltersModalOpen(false);
  };

  const clearProfileSubscriptionsFilters = () => {
    setProfileSubscriptionsDraftActiveOnly(true);
    setProfileSubscriptionsDraftMinPrice('');
    setProfileSubscriptionsDraftMaxPrice('');
    setProfileSubscriptionsDraftSexFilter([]);
  };

  const buildProfileSubscriptionsLoadoutName = useCallback(() => {
    const normalize = (value: string, maxLength: number) =>
      value.trim().replace(/\s+/g, ' ').slice(0, maxLength);

    const profileValue = normalize(user?.username || String(user?.id || ''), 24) || 'profile';
    const authValue = normalize(
      selectedProfileAuth?.username || String(selectedProfileAuth?.user_id || ''),
      24
    );
    const identifierValue = normalize(profileSubscriptionsSearchQuery || profileSubscriptionsSearchTerm, 36);
    const parts = [`profile:${profileValue}`, `auth:${authValue || 'auth'}`];
    if (identifierValue) parts.push(`identifier:${identifierValue}`);
    if (profileSubscriptionsMinPrice.trim() || profileSubscriptionsMaxPrice.trim()) {
      parts.push(
        `price:${profileSubscriptionsMinPrice.trim() || 'any'}-${profileSubscriptionsMaxPrice.trim() || 'any'}`
      );
    }
    return parts.join(' | ');
  }, [
    profileSubscriptionsMaxPrice,
    profileSubscriptionsMinPrice,
    profileSubscriptionsSearchQuery,
    profileSubscriptionsSearchTerm,
    selectedProfileAuth,
    user,
  ]);

  const autofillProfileSubscriptionsLoadoutName = useCallback(() => {
    setProfileSubscriptionsLoadoutNameInput(buildProfileSubscriptionsLoadoutName());
  }, [buildProfileSubscriptionsLoadoutName]);

  const openProfileSubscriptionsLoadoutModal = useCallback(() => {
    setProfileSubscriptionsLoadoutNameInput(
      profileSubscriptionsSelectedLoadoutName || buildProfileSubscriptionsLoadoutName()
    );
    setProfileSubscriptionsLoadoutModalOpen(true);
  }, [buildProfileSubscriptionsLoadoutName, profileSubscriptionsSelectedLoadoutName]);

  const saveProfileSubscriptionsLoadout = useCallback(async () => {
    const name =
      profileSubscriptionsLoadoutNameInput.trim() || buildProfileSubscriptionsLoadoutName();
    if (!name) {
      return;
    }

    await saveSearchLoadout('subscriptions', name, {
      identifier: profileSubscriptionsSearchQuery || profileSubscriptionsSearchTerm.trim(),
      description: '',
      site: user?.site || '',
      filters: {
        active_only: profileSubscriptionsActiveOnly,
        min_price: profileSubscriptionsMinPrice.trim() || null,
        max_price: profileSubscriptionsMaxPrice.trim() || null,
        sex: profileSubscriptionsSexFilter,
        auth_id: selectedProfileAuthId === '' ? null : selectedProfileAuthId,
        order_by: profileSubscriptionsOrderBy,
        order_dir: profileSubscriptionsOrderDir,
      },
    });
    setProfileSubscriptionsSelectedLoadoutName(name);
    setProfileSubscriptionsLoadoutNameInput(name);
    await queryClient.invalidateQueries({ queryKey: ['search-loadouts', 'subscriptions'] });
    showToast(`Saved loadout "${name}"`, 'success');
  }, [
    buildProfileSubscriptionsLoadoutName,
    profileSubscriptionsActiveOnly,
    profileSubscriptionsLoadoutNameInput,
    profileSubscriptionsMaxPrice,
    profileSubscriptionsMinPrice,
    profileSubscriptionsOrderBy,
    profileSubscriptionsOrderDir,
    profileSubscriptionsSearchQuery,
    profileSubscriptionsSearchTerm,
    profileSubscriptionsSexFilter,
    queryClient,
    selectedProfileAuthId,
    user?.site,
  ]);

  const setProfileSubscriptionsSelectedAsDefaultLoadout = useCallback(async () => {
    if (!profileSubscriptionsSelectedLoadoutName) {
      return;
    }
    await setDefaultSearchLoadout('subscriptions', profileSubscriptionsSelectedLoadoutName);
    await queryClient.invalidateQueries({ queryKey: ['search-loadouts', 'subscriptions'] });
    showToast(`Default loadout set to "${profileSubscriptionsSelectedLoadoutName}"`, 'success');
  }, [profileSubscriptionsSelectedLoadoutName, queryClient]);

  const clearProfileSubscriptionsDefaultLoadout = useCallback(async () => {
    await clearDefaultSearchLoadout('subscriptions');
    await queryClient.invalidateQueries({ queryKey: ['search-loadouts', 'subscriptions'] });
    showToast('Default loadout cleared', 'success');
  }, [queryClient]);

  const deleteProfileSubscriptionsSelectedLoadout = useCallback(async () => {
    if (!profileSubscriptionsSelectedLoadoutName) {
      return;
    }
    await deleteSearchLoadout('subscriptions', profileSubscriptionsSelectedLoadoutName);
    setProfileSubscriptionsSelectedLoadoutName('');
    setProfileSubscriptionsLoadoutNameInput('');
    await queryClient.invalidateQueries({ queryKey: ['search-loadouts', 'subscriptions'] });
    showToast('Deleted loadout', 'success');
  }, [profileSubscriptionsSelectedLoadoutName, queryClient]);

  const handleSelectProfileSubscriptionsLoadout = useCallback(
    (value: string) => {
      setProfileSubscriptionsSelectedLoadoutName(value);
      setProfileSubscriptionsLoadoutNameInput(value);
      const loadout = profileSubscriptionsLoadoutsData?.loadouts.find(
        (entry) => entry.name === value
      );
      if (loadout) {
        applyProfileSubscriptionsLoadout(loadout);
      }
    },
    [applyProfileSubscriptionsLoadout, profileSubscriptionsLoadoutsData]
  );

  const getProfileUrl = (): string => {
    if (!user) return '#';
    if (user.site === 'onlyfans') return `https://onlyfans.com/${user.username}`;
    if (user.site === 'fansly') return `https://fansly.com/${user.username}`;
    return '#';
  };

  const profileDescription = user?.description ? stripHtml(user.description) : '';
  const profileDisplayName = user
    ? decodeHtmlEntities(user.name || user.username)
    : '';
  const confirmedProfileSize = user?.size ?? 0;
  const estimatedProfileSize = Math.max(user?.estimated_size ?? 0, confirmedProfileSize);
  const resolvedProfileSize =
    user ? (confirmedProfileSize > 0 ? confirmedProfileSize : user.display_size || estimatedProfileSize) : 0;
  const sizeLabel = confirmedProfileSize > 0 ? 'Size' : user?.size_source === 'estimated' ? 'Est. Size' : 'Size';
  const sizeMeta =
    confirmedProfileSize > 0
      ? 'Measured from saved media bytes'
      : user?.size_source === 'estimated'
        ? `Estimated from ${user.statistics_bucket_date ?? 'daily'} averages`
        : 'No byte data available yet';
  const showEstimatedProfileSize =
    estimatedProfileSize > resolvedProfileSize;
  const estimatedSizeMeta =
    !showEstimatedProfileSize
      ? 'No expanded estimate available yet'
      : confirmedProfileSize > 0
        ? `Confirmed bytes + ${user?.statistics_bucket_date ?? 'daily'} estimate`
        : `Estimated from ${user?.statistics_bucket_date ?? 'daily'} averages`;

  return {
    navigate,
    goBack,
    backTarget,
    site,
    requestedIdentifier: normalizedIdentifier,
    user,
    resolvingUserId,
    resolveUserError,
    identifierResolution,
    selectIdentifierCandidate,
    conflictNavigation:
      conflictNavigationResolution?.status === 'ambiguous' && conflictNavigationResolution.total > 1
        ? {
            identifier: conflictIdentifier,
            page: conflictPage,
            total: conflictNavigationResolution.total,
            loading: conflictNavigationLoading || conflictNavigationPending,
          }
        : null,
    navigateConflictPage,
    profileLoading,
    profileError,
    profileData,
    refreshProfileMutation,
    activeTab,
    handleTabClick,
    hasSubscriptionsTab,
    paidTabLabel,
    toast,
    setToast,
    profileDisplayName,
    profileDescription,
    userAliases,
    handleRemoveAlias,
    deleteAliasMutation,
    openLightbox,
    lightboxUrl,
    closeLightbox,
    handleScrape,
    handleDelegateScrape,
    createJobMutation,
    delegateJobMutation,
    authPickerLoading,
    handleViewMedia,
    handleSubscribe,
    subscribeMutation,
    watched,
    handleToggleWatch,
    watchMutation,
    handleToggleFavorite,
    favoriteMutation,
    openEditModal,
    updateProfileMutation,
    paidPreviewLoading,
    paidPreviewTotal,
    paidPreviewMediaCount,
    openPaidTab,
    subscriptionCountdown,
    confirmedProfileSize,
    estimatedProfileSize,
    showEstimatedProfileSize,
    estimatedSizeMeta,
    resolvedProfileSize,
    sizeLabel,
    sizeMeta,
    historySnapshots,
    historyLoading,
    activeOverviewVersion,
    activeOverviewData,
    hasOlderOverviewVersion,
    hasNewerOverviewVersion,
    setOverviewVersionIndex,
    overviewVersions,
    directoryLookup,
    directoryLookupFetched,
    directoryLookupLoading,
    directoryLookupError,
    handleFindDirectory,
    copiedDirPath,
    handleCopyDir,
    openSexModal,
    activeContentTypeOptions,
    contentType,
    setContentType,
    contentSearchInput,
    handleSearchInput,
    contentSortBy,
    setContentSortBy,
    contentOrder,
    setContentOrder,
    openContentFilters,
    activeContentAdvancedFilterCount,
    contentTotal,
    contentLoading,
    contentItems,
    contentError,
    fetchContent,
    handleBuyLockedContent,
    buyingContentKey,
    addLockedContentToOrderMutation,
    sentinelRef,
    contentHasMore,
    contentFilterModalOpen,
    setContentFilterModalOpen,
    contentDraftAdvancedFilters,
    setContentDraftFilterState,
    clearContentDraftFilters,
    applyContentFilters,
    profileAuths,
    profileAuthsLoading,
    profileAuthsError,
    selectedProfileAuth,
    selectedProfileAuthId,
    setSelectedProfileAuthId,
    profileSubscriptionsSearchTerm,
    setProfileSubscriptionsSearchTerm,
    profileSubscriptionsOrderBy,
    setProfileSubscriptionsOrderBy,
    profileSubscriptionsOrderDir,
    setProfileSubscriptionsOrderDir,
    profileSubscriptionsActiveFilterCount,
    profileSubscriptionsFiltersModalOpen,
    profileSubscriptionsDraftActiveOnly,
    setProfileSubscriptionsDraftActiveOnly,
    profileSubscriptionsDraftMinPrice,
    setProfileSubscriptionsDraftMinPrice,
    profileSubscriptionsDraftMaxPrice,
    setProfileSubscriptionsDraftMaxPrice,
    profileSubscriptionsDraftSexFilter,
    setProfileSubscriptionsDraftSexFilter,
    openProfileSubscriptionsFilters,
    closeProfileSubscriptionsFilters,
    applyProfileSubscriptionsFilters,
    clearProfileSubscriptionsFilters,
    profileSubscriptionsLoadoutModalOpen,
    setProfileSubscriptionsLoadoutModalOpen,
    profileSubscriptionsLoadoutsData,
    profileSubscriptionsSelectedLoadoutName,
    setProfileSubscriptionsSelectedLoadoutName,
    profileSubscriptionsLoadoutNameInput,
    setProfileSubscriptionsLoadoutNameInput,
    profileSubscriptionsSelectedLoadoutIsDefault,
    buildProfileSubscriptionsLoadoutName,
    autofillProfileSubscriptionsLoadoutName,
    openProfileSubscriptionsLoadoutModal,
    saveProfileSubscriptionsLoadout,
    setProfileSubscriptionsSelectedAsDefaultLoadout,
    clearProfileSubscriptionsDefaultLoadout,
    deleteProfileSubscriptionsSelectedLoadout,
    handleSelectProfileSubscriptionsLoadout,
    profileSubscriptions,
    visibleProfileSubscriptions,
    profileSubscriptionsTotal,
    profileSubscriptionsLoading,
    profileSubscriptionsError,
    fetchNextProfileSubscriptionsPage,
    profileSubscriptionsHasNextPage,
    profileSubscriptionsIsFetchingNextPage,
    handleScrapeSubscription,
    authPickerOpen,
    closeAuthPicker,
    eligibleAuths,
    dispatchScrapeJob,
    handleAuthSelection,
    editModalOpen,
    setEditModalOpen,
    editName,
    setEditName,
    editAlias,
    setEditAlias,
    editDescription,
    setEditDescription,
    identityFields: identity.fields,
    handleSaveUserEdit,
    sexModalOpen,
    setSexModalOpen,
    handleSaveSex,
    chatModalOpen,
    setChatModalOpen,
    getProfileUrl,
  };
}
