import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';

import { createJob } from '../../../api/jobs';
import {
  clearDefaultSearchLoadout,
  deleteSearchLoadout,
  getSearchLoadouts,
  saveSearchLoadout,
  setDefaultSearchLoadout,
} from '../../../api/loadouts';
import { createOrderedPerformer } from '../../../api/orders';
import {
  addToIgnoreList,
  addToWatchList,
  getEligibleAuths,
  getUsersList,
  removeFromIgnoreList,
  removeFromWatchList,
  updateUser,
} from '../../../api/users';
import type { CreateJobRequest, TaskPayload } from '../../../api/types/jobs';
import type { SearchLoadoutItem } from '../../../api/types/loadouts';
import type { OrderedPerformerCreateResponse } from '../../../api/types/orders';
import type { EligibleAuth, UserUpdateRequest } from '../../../api/types/users';
import { isTypingTarget } from '../../../shared/lib/keyboard';
import {
  DEFAULT_USER_FILTERS,
  applyUsersLoadoutState,
  buildUsersLoadoutName,
  buildUsersStats,
  getUsersSortOptions,
  normalizeUsersSortBy,
  parseBooleanParam,
  parseIntListParam,
  type UserFilterMap,
  type UserFilterState,
  type UserInfo,
  type UsersListResponse,
} from '../lib/usersUtils';
import { useIdentityDraft } from '../../user-profile/hooks/useIdentityDraft';
import {
  EMPTY_IDENTITY_DRAFT,
  identityDraftFromUser,
  parseIdentityDraft,
} from '../../user-profile/lib/identityDraft';

interface UseUsersPageControllerOptions {
  favoriteOnly: boolean;
}

export function useUsersPageController({
  favoriteOnly,
}: UseUsersPageControllerOptions) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const pageSize = 100;
  const hasUrlState = searchParams.toString().length > 0;

  const [selectedSite, setSelectedSite] = useState<string>(
    () => searchParams.get('site') || 'onlyfans'
  );
  const [searchTerm, setSearchTerm] = useState(() => searchParams.get('identifier') || '');
  const [searchQuery, setSearchQuery] = useState(() => searchParams.get('identifier') || '');
  const [searchDescriptionTerm, setSearchDescriptionTerm] = useState(
    () => searchParams.get('description') || ''
  );
  const [searchDescriptionQuery, setSearchDescriptionQuery] = useState(
    () => searchParams.get('description') || ''
  );
  const [activeOnly, setActiveOnly] = useState(() =>
    parseBooleanParam(searchParams.get('active_only'), true)
  );
  const [draftActiveOnly, setDraftActiveOnly] = useState(true);
  const [sexFilter, setSexFilter] = useState<number[]>(() =>
    parseIntListParam(searchParams.get('sex'), [-1, 0, 1, 2])
  );
  const [draftSexFilter, setDraftSexFilter] = useState<number[]>([]);
  const [genderFilter, setGenderFilter] = useState<number[]>(() =>
    parseIntListParam(searchParams.get('gender'), [-1, 0, 1, 2])
  );
  const [draftGenderFilter, setDraftGenderFilter] = useState<number[]>([]);
  const [profileTypeFilter, setProfileTypeFilter] = useState<number[]>(() =>
    parseIntListParam(searchParams.get('profile_type'), [-1, 0, 1, 2, 3])
  );
  const [draftProfileTypeFilter, setDraftProfileTypeFilter] = useState<number[]>([]);
  const [sexualContentFilter, setSexualContentFilter] = useState<number[]>(() =>
    parseIntListParam(searchParams.get('sexual_content'), [-1, 0, 1, 2, 3, 4, 5, 6])
  );
  const [draftSexualContentFilter, setDraftSexualContentFilter] = useState<number[]>([]);
  const [minPrice, setMinPrice] = useState(() => searchParams.get('min_price') || '');
  const [maxPrice, setMaxPrice] = useState(() => searchParams.get('max_price') || '');
  const [draftMinPrice, setDraftMinPrice] = useState('');
  const [draftMaxPrice, setDraftMaxPrice] = useState('');
  const [minPostCount, setMinPostCount] = useState(
    () => searchParams.get('min_post_count') || ''
  );
  const [maxPostCount, setMaxPostCount] = useState(
    () => searchParams.get('max_post_count') || ''
  );
  const [draftMinPostCount, setDraftMinPostCount] = useState('');
  const [draftMaxPostCount, setDraftMaxPostCount] = useState('');
  const [minImageCount, setMinImageCount] = useState(
    () => searchParams.get('min_image_count') || ''
  );
  const [maxImageCount, setMaxImageCount] = useState(
    () => searchParams.get('max_image_count') || ''
  );
  const [draftMinImageCount, setDraftMinImageCount] = useState('');
  const [draftMaxImageCount, setDraftMaxImageCount] = useState('');
  const [minVideoCount, setMinVideoCount] = useState(
    () => searchParams.get('min_video_count') || ''
  );
  const [maxVideoCount, setMaxVideoCount] = useState(
    () => searchParams.get('max_video_count') || ''
  );
  const [draftMinVideoCount, setDraftMinVideoCount] = useState('');
  const [draftMaxVideoCount, setDraftMaxVideoCount] = useState('');
  const [userFilters, setUserFilters] = useState<UserFilterMap>(() => ({
    performer:
      searchParams.get('performer_filter') === 'exclude' ||
      searchParams.get('performer_filter') === 'none'
        ? (searchParams.get('performer_filter') as UserFilterState)
        : 'include',
    subscribed:
      searchParams.get('subscribed_filter') === 'include' ||
      searchParams.get('subscribed_filter') === 'exclude'
        ? (searchParams.get('subscribed_filter') as UserFilterState)
        : 'none',
  }));
  const [draftUserFilters, setDraftUserFilters] =
    useState<UserFilterMap>(DEFAULT_USER_FILTERS);
  const [filtersModalOpen, setFiltersModalOpen] = useState(false);
  const [viewMode, setViewMode] = useState<'table' | 'grid'>('grid');
  const [sortBy, setSortBy] = useState<string>(() =>
    normalizeUsersSortBy(searchParams.get('sort_by'), favoriteOnly)
  );
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>(() =>
    searchParams.get('sort_order') === 'asc' ? 'asc' : 'desc'
  );
  const [selectedUsers, setSelectedUsers] = useState<Set<string>>(new Set());
  const [allUsers, setAllUsers] = useState<UserInfo[]>([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const loadMoreSentinelRef = useRef<HTMLDivElement>(null);
  const autoLoadLockRef = useRef(false);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(
    null
  );
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [lightboxAlt, setLightboxAlt] = useState<string>('Image preview');

  const openLightbox = useCallback((url: string | null, alt = 'Image preview') => {
    setLightboxUrl(url);
    setLightboxAlt(alt);
  }, []);

  const closeLightbox = useCallback(() => {
    setLightboxUrl(null);
  }, []);
  const [authPickerOpen, setAuthPickerOpen] = useState(false);
  const [authPickerLoading, setAuthPickerLoading] = useState(false);
  const [eligibleAuths, setEligibleAuths] = useState<EligibleAuth[]>([]);
  const [authPickerTarget, setAuthPickerTarget] = useState<UserInfo | null>(null);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<UserInfo | null>(null);
  const [editName, setEditName] = useState('');
  const [editAlias, setEditAlias] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const userEditIdentity = useIdentityDraft();
  const [bulkIdentityModalOpen, setBulkIdentityModalOpen] = useState(false);
  const bulkIdentity = useIdentityDraft();
  const [bulkIdentitySaving, setBulkIdentitySaving] = useState(false);
  const [watchedKeys, setWatchedKeys] = useState<Set<string>>(new Set());
  const [ignoredKeys, setIgnoredKeys] = useState<Set<string>>(new Set());
  const [loadoutModalOpen, setLoadoutModalOpen] = useState(false);
  const [loadoutNameInput, setLoadoutNameInput] = useState('');
  const [selectedLoadoutName, setSelectedLoadoutName] = useState(
    () => searchParams.get('loadout') || ''
  );
  const [defaultLoadoutApplied, setDefaultLoadoutApplied] = useState(false);

  const performerFilterState = userFilters.performer;
  const performerOnly = performerFilterState === 'include';
  const excludePerformers = performerFilterState === 'exclude';
  const subscribedFilterState = userFilters.subscribed;
  const subscribedOnly = subscribedFilterState === 'include';
  const excludeSubscribed = subscribedFilterState === 'exclude';
  const sortOptions = useMemo(() => getUsersSortOptions(favoriteOnly), [favoriteOnly]);
  const userFilterSignature = JSON.stringify(userFilters);
  const sexFilterSignature = sexFilter.join(',');
  const genderFilterSignature = genderFilter.join(',');
  const profileTypeFilterSignature = profileTypeFilter.join(',');
  const sexualContentFilterSignature = sexualContentFilter.join(',');

  const activeUserFilterCount = useMemo(() => {
    let count = Object.values(userFilters).filter((state) => state !== 'none').length;
    if (activeOnly) count++;
    if (minPrice || maxPrice) count++;
    if (sexFilter.length > 0) count++;
    if (genderFilter.length > 0) count++;
    if (profileTypeFilter.length > 0) count++;
    if (sexualContentFilter.length > 0) count++;
    if (minPostCount || maxPostCount) count++;
    if (minImageCount || maxImageCount) count++;
    if (minVideoCount || maxVideoCount) count++;
    return count;
  }, [
    userFilters,
    activeOnly,
    sexFilter,
    genderFilter,
    profileTypeFilter,
    sexualContentFilter,
    minPrice,
    maxPrice,
    minPostCount,
    maxPostCount,
    minImageCount,
    maxImageCount,
    minVideoCount,
    maxVideoCount,
  ]);

  const { data: loadoutsData, isFetched: loadoutsFetched } = useQuery({
    queryKey: ['search-loadouts', 'users'],
    queryFn: () => getSearchLoadouts('users'),
  });

  const selectedLoadout = loadoutsData?.loadouts.find((loadout) => loadout.name === selectedLoadoutName);
  const selectedLoadoutIsDefault = Boolean(selectedLoadout?.is_default);

  const buildAutoLoadoutName = useCallback(
    () =>
      buildUsersLoadoutName({
        selectedSite,
        searchQuery,
        searchTerm,
        searchDescriptionQuery,
        searchDescriptionTerm,
      }),
    [selectedSite, searchQuery, searchTerm, searchDescriptionQuery, searchDescriptionTerm]
  );

  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  useEffect(() => {
    setAllUsers([]);
    setPage(1);
    setHasMore(true);
    setSelectedUsers(new Set());
  }, [
    selectedSite,
    searchQuery,
    searchDescriptionQuery,
    activeOnly,
    sortBy,
    sortOrder,
    userFilterSignature,
    sexFilterSignature,
    genderFilterSignature,
    profileTypeFilterSignature,
    sexualContentFilterSignature,
    minPrice,
    maxPrice,
    minPostCount,
    maxPostCount,
    minImageCount,
    maxImageCount,
    minVideoCount,
    maxVideoCount,
  ]);

  useEffect(() => {
    const timer = setTimeout(() => {
      const trimmedIdentifier = searchTerm.trim();
      const trimmedDescription = searchDescriptionTerm.trim();
      if (trimmedIdentifier || searchQuery) {
        setSearchQuery(trimmedIdentifier);
      }
      if (trimmedDescription || searchDescriptionQuery) {
        setSearchDescriptionQuery(trimmedDescription);
      }
    }, 500);

    return () => clearTimeout(timer);
  }, [searchTerm, searchQuery, searchDescriptionTerm, searchDescriptionQuery]);

  useEffect(() => {
    const normalizedSortBy = normalizeUsersSortBy(sortBy, favoriteOnly);
    if (normalizedSortBy !== sortBy) {
      setSortBy(normalizedSortBy);
    }
  }, [favoriteOnly, sortBy]);

  useEffect(() => {
    if (!defaultLoadoutApplied) {
      return;
    }

    const nextParams = new URLSearchParams();
    nextParams.set('site', selectedSite || 'onlyfans');
    nextParams.set('active_only', String(activeOnly));
    nextParams.set('sort_by', sortBy);
    nextParams.set('sort_order', sortOrder);
    nextParams.set('performer_filter', userFilters.performer);
    nextParams.set('subscribed_filter', userFilters.subscribed);
    if (selectedLoadoutName) nextParams.set('loadout', selectedLoadoutName);
    if (searchQuery) nextParams.set('identifier', searchQuery);
    if (searchDescriptionQuery) nextParams.set('description', searchDescriptionQuery);
    if (sexFilter.length) nextParams.set('sex', sexFilter.join(','));
    if (genderFilter.length) nextParams.set('gender', genderFilter.join(','));
    if (profileTypeFilter.length) nextParams.set('profile_type', profileTypeFilter.join(','));
    if (sexualContentFilter.length) nextParams.set('sexual_content', sexualContentFilter.join(','));
    if (minPrice) nextParams.set('min_price', minPrice);
    if (maxPrice) nextParams.set('max_price', maxPrice);
    if (minPostCount) nextParams.set('min_post_count', minPostCount);
    if (maxPostCount) nextParams.set('max_post_count', maxPostCount);
    if (minImageCount) nextParams.set('min_image_count', minImageCount);
    if (maxImageCount) nextParams.set('max_image_count', maxImageCount);
    if (minVideoCount) nextParams.set('min_video_count', minVideoCount);
    if (maxVideoCount) nextParams.set('max_video_count', maxVideoCount);

    if (nextParams.toString() !== searchParams.toString()) {
      setSearchParams(nextParams, { replace: true });
    }
  }, [
    defaultLoadoutApplied,
    selectedSite,
    activeOnly,
    sortBy,
    sortOrder,
    userFilters,
    selectedLoadoutName,
    searchQuery,
    searchDescriptionQuery,
    sexFilter,
    genderFilter,
    profileTypeFilter,
    sexualContentFilter,
    minPrice,
    maxPrice,
    minPostCount,
    maxPostCount,
    minImageCount,
    maxImageCount,
    minVideoCount,
    maxVideoCount,
    searchParams,
    setSearchParams,
  ]);

  const usersFilterKey = [
      favoriteOnly,
      selectedSite,
      searchQuery,
      searchDescriptionQuery,
      subscribedOnly,
      excludeSubscribed,
      sexFilter.join(','),
      genderFilter.join(','),
      profileTypeFilter.join(','),
      sexualContentFilter.join(','),
      minPrice,
      maxPrice,
      minPostCount,
      maxPostCount,
      minImageCount,
      maxImageCount,
      minVideoCount,
      maxVideoCount,
      performerOnly,
      excludePerformers,
      activeOnly,
  ];
  const usersFilters = {
        site: selectedSite,
        search: searchQuery,
        searchDescription: searchDescriptionQuery,
        activeOnly,
        favoriteOnly,
        sex: sexFilter,
        gender: genderFilter,
        profileType: profileTypeFilter,
        sexualContent: sexualContentFilter,
        subscribedOnly,
        excludeSubscribed,
        minPrice,
        maxPrice,
        minPostCount,
        maxPostCount,
        minImageCount,
        maxImageCount,
        minVideoCount,
        maxVideoCount,
        performerOnly,
        excludePerformers,
  };
  const { data: usersData, isLoading, error } = useQuery<UsersListResponse>({
    queryKey: ['users-list', ...usersFilterKey, sortBy, sortOrder, page],
    queryFn: async () => {
      const result = await getUsersList({ ...usersFilters, sortBy, sortOrder,
        limit: pageSize, offset: (page - 1) * pageSize, includeStats: false });
      if (!result.success) throw new Error(result.error || 'Failed to load users');
      return result;
    },
    enabled: defaultLoadoutApplied,
  });
  const totalsQuery = useQuery<UsersListResponse>({
    queryKey: ['users-stats', ...usersFilterKey],
    queryFn: async () => {
      const result = await getUsersList({ ...usersFilters, includeStats: true,
        statsOnly: true, limit: 1, offset: 0 });
      if (!result.success) throw new Error(result.error || 'Totals unavailable');
      return result;
    },
    enabled: defaultLoadoutApplied && usersData?.success === true,
    staleTime: 30_000,
    retry: false,
    refetchOnWindowFocus: false,
  });

  const openUserFilters = () => {
    setDraftUserFilters(userFilters);
    setDraftActiveOnly(activeOnly);
    setDraftMinPrice(minPrice);
    setDraftMaxPrice(maxPrice);
    setDraftSexFilter([...sexFilter]);
    setDraftGenderFilter([...genderFilter]);
    setDraftProfileTypeFilter([...profileTypeFilter]);
    setDraftSexualContentFilter([...sexualContentFilter]);
    setDraftMinPostCount(minPostCount);
    setDraftMaxPostCount(maxPostCount);
    setDraftMinImageCount(minImageCount);
    setDraftMaxImageCount(maxImageCount);
    setDraftMinVideoCount(minVideoCount);
    setDraftMaxVideoCount(maxVideoCount);
    setFiltersModalOpen(true);
  };

  const applyUserFilters = () => {
    setUserFilters(draftUserFilters);
    setActiveOnly(draftActiveOnly);
    setSexFilter([...draftSexFilter]);
    setGenderFilter([...draftGenderFilter]);
    setProfileTypeFilter([...draftProfileTypeFilter]);
    setSexualContentFilter([...draftSexualContentFilter]);
    setMinPrice(draftMinPrice);
    setMaxPrice(draftMaxPrice);
    setMinPostCount(draftMinPostCount);
    setMaxPostCount(draftMaxPostCount);
    setMinImageCount(draftMinImageCount);
    setMaxImageCount(draftMaxImageCount);
    setMinVideoCount(draftMinVideoCount);
    setMaxVideoCount(draftMaxVideoCount);
    setFiltersModalOpen(false);
  };

  const openLoadoutModal = () => {
    setLoadoutNameInput(selectedLoadoutName || buildAutoLoadoutName());
    setLoadoutModalOpen(true);
  };

  const applyUsersLoadout = useCallback((loadout: SearchLoadoutItem) => {
    const state = applyUsersLoadoutState(loadout, favoriteOnly);
    setSearchTerm(state.identifier);
    setSearchQuery(state.identifier);
    setSearchDescriptionTerm(state.description);
    setSearchDescriptionQuery(state.description);
    setSelectedSite(state.siteValue);
    setActiveOnly(state.activeOnly);
    setSexFilter(state.nextSex);
    setGenderFilter(state.nextGender);
    setUserFilters({
      performer: state.performerFilter,
      subscribed: state.subscribedFilter,
    });
    setMinPrice(state.minPrice);
    setMaxPrice(state.maxPrice);
    setMinPostCount(state.minPostCount);
    setMaxPostCount(state.maxPostCount);
    setMinImageCount(state.minImageCount);
    setMaxImageCount(state.maxImageCount);
    setMinVideoCount(state.minVideoCount);
    setMaxVideoCount(state.maxVideoCount);
    setSortBy(state.sortByValue);
    setSortOrder(state.sortOrderValue);
    setDraftUserFilters({
      performer: state.performerFilter,
      subscribed: state.subscribedFilter,
    });
    setDraftActiveOnly(state.activeOnly);
    setDraftSexFilter(state.nextSex);
    setDraftGenderFilter(state.nextGender);
    setDraftMinPrice(state.minPrice);
    setDraftMaxPrice(state.maxPrice);
    setDraftMinPostCount(state.minPostCount);
    setDraftMaxPostCount(state.maxPostCount);
    setDraftMinImageCount(state.minImageCount);
    setDraftMaxImageCount(state.maxImageCount);
    setDraftMinVideoCount(state.minVideoCount);
    setDraftMaxVideoCount(state.maxVideoCount);
  }, [favoriteOnly]);

  useEffect(() => {
    if (defaultLoadoutApplied || !loadoutsFetched) {
      return;
    }

    if (hasUrlState) {
      setDefaultLoadoutApplied(true);
      return;
    }

    if (loadoutsData?.default_name) {
      const defaultLoadout = loadoutsData.loadouts.find(
        (loadout) => loadout.name === loadoutsData.default_name
      );
      if (defaultLoadout) {
        applyUsersLoadout(defaultLoadout);
        setSelectedLoadoutName(defaultLoadout.name);
      }
    }

    setDefaultLoadoutApplied(true);
  }, [
    loadoutsData,
    loadoutsFetched,
    defaultLoadoutApplied,
    applyUsersLoadout,
    hasUrlState,
  ]);

  const saveCurrentLoadout = async () => {
    const name = loadoutNameInput.trim() || buildAutoLoadoutName();
    if (!name) {
      return;
    }

    await saveSearchLoadout('users', name, {
      identifier: searchQuery || searchTerm.trim(),
      description: searchDescriptionQuery || searchDescriptionTerm.trim(),
      site: selectedSite,
      filters: {
        active_only: activeOnly,
        sex: sexFilter,
        gender: genderFilter,
        performer_filter: userFilters.performer,
        subscribed_filter: userFilters.subscribed,
        min_price: minPrice,
        max_price: maxPrice,
        min_post_count: minPostCount,
        max_post_count: maxPostCount,
        min_image_count: minImageCount,
        max_image_count: maxImageCount,
        min_video_count: minVideoCount,
        max_video_count: maxVideoCount,
        sort_by: sortBy,
        sort_order: sortOrder,
      },
    });
    setSelectedLoadoutName(name);
    setLoadoutNameInput(name);
    await queryClient.invalidateQueries({ queryKey: ['search-loadouts', 'users'] });
    showToast(`Saved loadout "${name}"`, 'success');
  };

  const setSelectedAsDefaultLoadout = async () => {
    if (!selectedLoadoutName) {
      return;
    }

    await setDefaultSearchLoadout('users', selectedLoadoutName);
    await queryClient.invalidateQueries({ queryKey: ['search-loadouts', 'users'] });
    showToast(`Default loadout set to "${selectedLoadoutName}"`, 'success');
  };

  const clearDefaultLoadout = async () => {
    await clearDefaultSearchLoadout('users');
    await queryClient.invalidateQueries({ queryKey: ['search-loadouts', 'users'] });
    showToast('Default loadout cleared', 'success');
  };

  const deleteSelectedLoadout = async () => {
    if (!selectedLoadoutName) {
      return;
    }

    await deleteSearchLoadout('users', selectedLoadoutName);
    setSelectedLoadoutName('');
    setLoadoutNameInput('');
    await queryClient.invalidateQueries({ queryKey: ['search-loadouts', 'users'] });
    showToast('Deleted loadout', 'success');
  };

  useEffect(() => {
    if (!usersData?.users) {
      return;
    }

    setAllUsers((previousUsers) => {
      if (page === 1) {
        return usersData.users;
      }

      const existingIds = new Set(previousUsers.map((user) => `${user.site}-${user.id}`));
      const newUsers = usersData.users.filter(
        (user) => !existingIds.has(`${user.site}-${user.id}`)
      );
      if (newUsers.length === 0) {
        return previousUsers;
      }
      return [...previousUsers, ...newUsers];
    });

    const loadedCount = (page - 1) * pageSize + usersData.users.length;
    setHasMore(usersData.has_more ?? (usersData.total != null ? loadedCount < usersData.total : usersData.users.length === pageSize));
  }, [usersData, page, pageSize]);

  useEffect(() => {
    setSelectedUsers((previousSelection) => {
      if (previousSelection.size === 0) {
        return previousSelection;
      }
      const visibleKeys = new Set(allUsers.map((user) => `${user.site}-${user.id}`));
      let changed = false;
      const nextSelection = new Set<string>();
      previousSelection.forEach((key) => {
        if (visibleKeys.has(key)) {
          nextSelection.add(key);
        } else {
          changed = true;
        }
      });
      return changed ? nextSelection : previousSelection;
    });
  }, [allUsers]);

  const stats = useMemo(() => buildUsersStats(totalsQuery.data), [totalsQuery.data]);

  const visibleUsers = allUsers;

  const totalRosterCount = stats?.total ?? null;
  const activeRosterCount = stats?.active ?? null;
  const watchedCount = useMemo(() => {
    const matching = allUsers.filter(
      (u) =>
        watchedKeys.has(`${u.site}-${u.id}`) ||
        watchedKeys.has(`${u.site}-${u.user_id}`)
    ).length;
    return matching > 0 ? matching : watchedKeys.size;
  }, [allUsers, watchedKeys]);
  const unscrapedCount = useMemo(
    () => allUsers.filter((u) => !u.downloaded_at).length,
    [allUsers]
  );
  const avgPrice = stats?.avgPrice ?? null;
  const totalsStatus: 'loading' | 'unavailable' | 'ready' = totalsQuery.error ? 'unavailable' : stats ? 'ready' : 'loading';
  const retryTotals = () => { void totalsQuery.refetch(); };
  const loadedCount = allUsers.length;
  const totalCount = stats?.total ?? null;
  const isLoadingInitialPage = isLoading && page === 1 && allUsers.length === 0;
  const isLoadingNextPage = isLoading && page > 1;
  const usersError = error instanceof Error ? error : error ? new Error('Unknown error') : null;

  const handleLoadMore = useCallback(() => {
    if (autoLoadLockRef.current || isLoadingInitialPage || isLoadingNextPage || !hasMore) {
      return;
    }
    autoLoadLockRef.current = true;
    setPage((currentPage) => currentPage + 1);
  }, [hasMore, isLoadingInitialPage, isLoadingNextPage]);

  useEffect(() => {
    if (!isLoading) {
      autoLoadLockRef.current = false;
    }
  }, [isLoading]);

  useEffect(() => {
    if (!allUsers.length || !hasMore) {
      return;
    }

    const mainContent = document.querySelector('.main-content');
    const scrollContainer =
      mainContent instanceof HTMLElement &&
      ['auto', 'scroll'].includes(getComputedStyle(mainContent).overflowY)
        ? mainContent
        : null;
    const eventTarget: EventTarget = scrollContainer ?? window;

    const getScrollMetrics = () => {
      if (scrollContainer) {
        return {
          scrollTop: scrollContainer.scrollTop,
          clientHeight: scrollContainer.clientHeight,
          scrollHeight: scrollContainer.scrollHeight,
        };
      }

      const docEl = document.documentElement;
      const body = document.body;
      return {
        scrollTop: window.scrollY || docEl.scrollTop || body.scrollTop || 0,
        clientHeight: window.innerHeight || docEl.clientHeight,
        scrollHeight: Math.max(docEl.scrollHeight, body.scrollHeight, docEl.clientHeight),
      };
    };

    const handleScroll = () => {
      if (autoLoadLockRef.current || isLoadingInitialPage || isLoadingNextPage || !hasMore) {
        return;
      }

      const { scrollTop, scrollHeight, clientHeight } = getScrollMetrics();
      const scrollableHeight = scrollHeight - clientHeight;
      if (scrollableHeight <= 0) {
        return;
      }

      const scrollProgress = scrollTop / scrollableHeight;

      if (scrollProgress >= 0.6) {
        handleLoadMore();
      }
    };

    eventTarget.addEventListener('scroll', handleScroll, { passive: true } as AddEventListenerOptions);
    handleScroll();
    return () => eventTarget.removeEventListener('scroll', handleScroll);
  }, [allUsers.length, handleLoadMore, hasMore, isLoadingInitialPage, isLoadingNextPage]);

  useEffect(() => {
    const sentinel = loadMoreSentinelRef.current;
    if (!sentinel || !allUsers.length || !hasMore) {
      return;
    }

    const mainContent = document.querySelector('.main-content');
    const scrollRoot =
      mainContent instanceof HTMLElement &&
      ['auto', 'scroll'].includes(getComputedStyle(mainContent).overflowY)
        ? mainContent
        : null;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          handleLoadMore();
        }
      },
      {
        root: scrollRoot,
        rootMargin: '0px 0px 40% 0px',
        threshold: 0,
      }
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [allUsers.length, handleLoadMore, hasMore]);

  const createJobMutation = useMutation({
    mutationFn: createJob,
    onSuccess: (data: { job_name: string }) => {
      showToast(`Job "${data.job_name}" created successfully!`, 'success');
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
    },
    onError: (mutationError: Error) => {
      showToast(`Failed to create job: ${mutationError.message}`, 'error');
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
        if (data.status === 'completed') {
          showToast(`Subscribed to @${data.username || 'user'} (${data.site})`, 'success');
        } else {
          showToast(
            data.message || `Order queued for @${data.username || 'user'} (${data.site})`,
            'success'
          );
        }
      } else {
        showToast(data.error || 'Failed to subscribe', 'error');
      }
      queryClient.invalidateQueries({ queryKey: ['orders-performers'] });
    },
    onError: (mutationError: Error) => {
      showToast(`Failed to subscribe: ${mutationError.message}`, 'error');
    },
  });

  const updateUserMutation = useMutation({
    mutationFn: ({ user, payload }: { user: UserInfo; payload: UserUpdateRequest }) =>
      updateUser(user.user_id, user.site, payload),
    onSuccess: (_, variables) => {
      showToast(`Updated @${variables.user.username}`, 'success');
      setEditModalOpen(false);
      setEditTarget(null);
      setEditAlias('');
      userEditIdentity.setDraft(EMPTY_IDENTITY_DRAFT);
      queryClient.invalidateQueries({ queryKey: ['users-list'] });
      queryClient.invalidateQueries({ queryKey: ['users-stats'] });
      queryClient.invalidateQueries({ queryKey: ['user-profile'] });
      queryClient.invalidateQueries({ queryKey: ['user-aliases'] });
      queryClient.invalidateQueries({ queryKey: ['subscriptions'] });
    },
    onError: (mutationError: Error) => {
      showToast(`Failed to update user: ${mutationError.message}`, 'error');
    },
  });

  const watchMutation = useMutation({
    mutationFn: ({ userId, site }: { userId: number; site: string }) =>
      addToWatchList(userId, site),
    onSuccess: (_, variables) => {
      showToast('Added to watch list', 'success');
      queryClient.invalidateQueries({ queryKey: ['watchList'] });
      setWatchedKeys((previousKeys) => new Set(previousKeys).add(`${variables.site}-${variables.userId}`));
    },
    onError: (mutationError: Error) => {
      showToast(`Failed to add to watch list: ${mutationError.message}`, 'error');
    },
  });

  const unwatchMutation = useMutation({
    mutationFn: ({ userId, site }: { userId: number; site: string }) =>
      removeFromWatchList(userId, site),
    onSuccess: (_, variables) => {
      showToast('Removed from watch list', 'success');
      queryClient.invalidateQueries({ queryKey: ['watchList'] });
      setWatchedKeys((previousKeys) => {
        const nextKeys = new Set(previousKeys);
        nextKeys.delete(`${variables.site}-${variables.userId}`);
        return nextKeys;
      });
    },
    onError: (mutationError: Error) => {
      showToast(`Failed to remove from watch list: ${mutationError.message}`, 'error');
    },
  });

  const ignoreMutation = useMutation({
    mutationFn: ({ userId, site }: { userId: number; site: string }) =>
      addToIgnoreList(userId, site),
    onSuccess: (_, variables) => {
      showToast('User ignored — they will be skipped when scraping', 'success');
      setIgnoredKeys((previousKeys) => new Set(previousKeys).add(`${variables.site}-${variables.userId}`));
    },
    onError: (mutationError: Error) => {
      showToast(`Failed to ignore user: ${mutationError.message}`, 'error');
    },
  });

  const unignoreMutation = useMutation({
    mutationFn: ({ userId, site }: { userId: number; site: string }) =>
      removeFromIgnoreList(userId, site),
    onSuccess: (_, variables) => {
      showToast('User unignored — they will be included when scraping', 'success');
      setIgnoredKeys((previousKeys) => {
        const nextKeys = new Set(previousKeys);
        nextKeys.delete(`${variables.site}-${variables.userId}`);
        return nextKeys;
      });
    },
    onError: (mutationError: Error) => {
      showToast(`Failed to unignore user: ${mutationError.message}`, 'error');
    },
  });

  const dispatchScrapeUser = (user: UserInfo, authId?: number) => {
    const params: Record<string, unknown> = {
      site: user.site,
      username: user.username,
      content_types: [
        'Posts',
        'ArchivedPosts',
        'Messages',
        'Stories',
        'Highlights',
        'Profile',
      ],
      rescrape_existing: true,
    };
    if (authId !== undefined) {
      params.auth_id = authId;
    }

    const task: TaskPayload = {
      task_type: 'scrape_and_download',
      params,
    };
    const request: CreateJobRequest = {
      job_name: `Scrape + Download @${user.username} (${user.site})`,
      tasks: [task],
      created_by: 'webui',
    };

    createJobMutation.mutate(request);
  };

  const resolveAndScrapeUser = async (user: UserInfo) => {
    setAuthPickerLoading(true);
    try {
      const response = await getEligibleAuths(user.user_id, user.site);
      if (response.error) {
        showToast(response.error, 'error');
        return;
      }

      const auths = response.auths ?? [];
      if (auths.length <= 1) {
        dispatchScrapeUser(user, auths[0]?.auth_id);
        return;
      }

      setAuthPickerTarget(user);
      setEligibleAuths(auths);
      setAuthPickerOpen(true);
    } catch (loadError) {
      showToast(
        `Failed to fetch eligible auths: ${
          loadError instanceof Error ? loadError.message : 'Unknown error'
        }`,
        'error'
      );
    } finally {
      setAuthPickerLoading(false);
    }
  };

  const handleScrapeSelected = () => {
    const selected = allUsers.filter(
      (user) =>
        selectedUsers.has(`${user.site}-${user.id}`) &&
        !ignoredKeys.has(`${user.site}-${user.user_id}`)
    );
    if (selected.length === 0) {
      showToast('All selected users are ignored — nothing to scrape', 'error');
      return;
    }

    if (selected.length === 1) {
      void resolveAndScrapeUser(selected[0]);
      setSelectedUsers(new Set());
      return;
    }

    const tasks: TaskPayload[] = selected.map((user) => ({
      task_type: 'scrape_and_download',
      params: {
        site: user.site,
        username: user.username,
        content_types: [
          'Posts',
          'ArchivedPosts',
          'Messages',
          'Stories',
          'Highlights',
          'Profile',
        ],
        rescrape_existing: true,
      },
    }));

    const request: CreateJobRequest = {
      job_name: `Scrape + Download ${selected.length} user${selected.length !== 1 ? 's' : ''}`,
      tasks,
      created_by: 'webui',
    };

    createJobMutation.mutate(request);
    setSelectedUsers(new Set());
  };

  const handleScrapeUser = (user: UserInfo) => {
    void resolveAndScrapeUser(user);
  };

  const handleSubscribeUser = (user: UserInfo) => {
    subscribeMutation.mutate({
      site: user.site,
      user_id: user.user_id,
      username: user.username,
      price: user.price,
      auto_execute: false,
    });
  };

  const handleWatchToggle = useCallback(
    (user: UserInfo) => {
      const key = `${user.site}-${user.user_id}`;
      if (watchedKeys.has(key)) {
        unwatchMutation.mutate({ userId: user.user_id, site: user.site });
      } else {
        watchMutation.mutate({ userId: user.user_id, site: user.site });
      }
    },
    [watchedKeys, watchMutation, unwatchMutation]
  );

  const handleIgnoreToggle = useCallback(
    (user: UserInfo) => {
      const key = `${user.site}-${user.user_id}`;
      if (ignoredKeys.has(key)) {
        unignoreMutation.mutate({ userId: user.user_id, site: user.site });
      } else {
        ignoreMutation.mutate({ userId: user.user_id, site: user.site });
      }
    },
    [ignoredKeys, ignoreMutation, unignoreMutation]
  );

  const handleWatchSelected = async () => {
    const selected = allUsers.filter((user) => selectedUsers.has(`${user.site}-${user.id}`));
    const unmatched = selected.filter(
      (user) => !watchedKeys.has(`${user.site}-${user.user_id}`)
    );
    if (unmatched.length === 0) {
      showToast('All selected users are already watched', 'error');
      return;
    }

    await Promise.allSettled(
      unmatched.map((user) =>
        addToWatchList(user.user_id, user.site).then(() => {
          setWatchedKeys((previousKeys) =>
            new Set(previousKeys).add(`${user.site}-${user.user_id}`)
          );
        })
      )
    );
    showToast(
      `Added ${unmatched.length} user${unmatched.length !== 1 ? 's' : ''} to watch list`,
      'success'
    );
    queryClient.invalidateQueries({ queryKey: ['watchList'] });
    queryClient.invalidateQueries({ queryKey: ['watchStats'] });
    setSelectedUsers(new Set());
  };

  const handleIgnoreSelected = async () => {
    const selected = allUsers.filter((user) => selectedUsers.has(`${user.site}-${user.id}`));
    const unignored = selected.filter(
      (user) => !ignoredKeys.has(`${user.site}-${user.user_id}`)
    );
    if (unignored.length === 0) {
      showToast('All selected users are already ignored', 'error');
      return;
    }

    await Promise.allSettled(
      unignored.map((user) =>
        addToIgnoreList(user.user_id, user.site).then(() => {
          setIgnoredKeys((previousKeys) =>
            new Set(previousKeys).add(`${user.site}-${user.user_id}`)
          );
        })
      )
    );
    showToast(
      `Ignored ${unignored.length} user${unignored.length !== 1 ? 's' : ''} — they will be skipped when scraping`,
      'success'
    );
    setSelectedUsers(new Set());
  };

  const handleSelectAll = () => {
    if (selectedUsers.size === allUsers.length) {
      setSelectedUsers(new Set());
      return;
    }
    setSelectedUsers(new Set(allUsers.map((user) => `${user.site}-${user.id}`)));
  };

  const selectAllVisibleUsers = useCallback(() => {
    setSelectedUsers(new Set(allUsers.map((user) => `${user.site}-${user.id}`)));
  }, [allUsers]);

  const handleSelectUser = (user: UserInfo) => {
    const key = `${user.site}-${user.id}`;
    const nextSelection = new Set(selectedUsers);
    if (nextSelection.has(key)) {
      nextSelection.delete(key);
    } else {
      nextSelection.add(key);
    }
    setSelectedUsers(nextSelection);
  };

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented ||
        authPickerOpen ||
        editModalOpen ||
        bulkIdentityModalOpen ||
        filtersModalOpen ||
        loadoutModalOpen ||
        isTypingTarget(event.target)
      ) {
        return;
      }

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'a') {
        if (!allUsers.length) {
          return;
        }
        event.preventDefault();
        selectAllVisibleUsers();
        return;
      }

      if (event.key === 'Escape' && selectedUsers.size > 0) {
        event.preventDefault();
        setSelectedUsers(new Set());
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    allUsers.length,
    authPickerOpen,
    editModalOpen,
    bulkIdentityModalOpen,
    filtersModalOpen,
    loadoutModalOpen,
    selectAllVisibleUsers,
    selectedUsers.size,
  ]);

  const openEditModal = (user: UserInfo) => {
    setEditTarget(user);
    setEditName(user.name ?? '');
    setEditAlias('');
    setEditDescription(user.description ?? '');
    userEditIdentity.setDraft(identityDraftFromUser(user));
    setEditModalOpen(true);
  };

  const resetUserEditToOriginal = () => {
    if (!editTarget) return;
    userEditIdentity.setDraft(identityDraftFromUser(editTarget));
  };

  const handleSaveUserEdit = () => {
    if (!editTarget) {
      return;
    }

    const identity = parseIdentityDraft(userEditIdentity.draft);
    if (!identity.ok) {
      showToast(identity.error, 'error');
      return;
    }

    updateUserMutation.mutate({
      user: editTarget,
      payload: {
        name: editName.trim() || null,
        alias: editAlias.trim() || null,
        description: editDescription.trim() || null,
        ...identity.values,
        ai_assisted: false,
        verified: true,
      },
    });
  };

  const openBulkIdentityModal = () => {
    if (selectedUsers.size === 0) {
      showToast('Select at least one user first', 'error');
      return;
    }
    bulkIdentity.setDraft(EMPTY_IDENTITY_DRAFT);
    setBulkIdentityModalOpen(true);
  };

  const handleSaveBulkIdentity = async () => {
    const identity = parseIdentityDraft(bulkIdentity.draft);
    if (!identity.ok) {
      showToast(identity.error, 'error');
      return;
    }

    const selected = allUsers.filter((user) =>
      selectedUsers.has(`${user.site}-${user.id}`)
    );
    if (selected.length === 0) {
      showToast('No users selected', 'error');
      return;
    }

    setBulkIdentitySaving(true);
    const results = await Promise.allSettled(
      selected.map((user) =>
        updateUser(user.user_id, user.site, {
          ...identity.values,
          ai_assisted: false,
          verified: true,
        })
      )
    );
    setBulkIdentitySaving(false);

    const failures = results.filter((result) => result.status === 'rejected').length;
    const successes = results.length - failures;

    if (successes > 0) {
      showToast(
        `Updated identity for ${successes} user${successes !== 1 ? 's' : ''}` +
          (failures > 0 ? ` (${failures} failed)` : ''),
        failures > 0 ? 'error' : 'success'
      );
      queryClient.invalidateQueries({ queryKey: ['users-list'] });
      queryClient.invalidateQueries({ queryKey: ['users-stats'] });
      queryClient.invalidateQueries({ queryKey: ['user-profile'] });
    } else {
      showToast(`Failed to update identity for ${failures} user${failures !== 1 ? 's' : ''}`, 'error');
    }

    if (failures === 0) {
      setBulkIdentityModalOpen(false);
    }
  };

  return {
    navigate,
    pageSize,
    searchTerm,
    setSearchTerm,
    setSearchQuery,
    searchQuery,
    searchDescriptionTerm,
    setSearchDescriptionTerm,
    setSearchDescriptionQuery,
    selectedSite,
    setSelectedSite,
    viewMode,
    setViewMode,
    sortOptions,
    sortBy,
    setSortBy,
    sortOrder,
    setSortOrder,
    activeUserFilterCount,
    stats,
    selectedUsers,
    setSelectedUsers,
    allUsers,
    visibleUsers,
    totalRosterCount,
    totalsStatus,
    retryTotals,
    activeRosterCount,
    watchedCount,
    unscrapedCount,
    avgPrice,
    loadedCount,
    totalCount,
    usersError,
    watchedKeys,
    ignoredKeys,
    authPickerOpen,
    setAuthPickerOpen,
    authPickerTarget,
    eligibleAuths,
    editModalOpen,
    setEditModalOpen,
    editTarget,
    editName,
    setEditName,
    editAlias,
    setEditAlias,
    editDescription,
    setEditDescription,
    userEditIdentityFields: userEditIdentity.fields,
    bulkIdentityModalOpen,
    setBulkIdentityModalOpen,
    bulkIdentityFields: bulkIdentity.fields,
    bulkIdentitySaving,
    openBulkIdentityModal,
    handleSaveBulkIdentity,
    loadoutModalOpen,
    setLoadoutModalOpen,
    loadoutsData,
    selectedLoadoutName,
    setSelectedLoadoutName,
    selectedLoadoutIsDefault,
    loadoutNameInput,
    setLoadoutNameInput,
    filtersModalOpen,
    setFiltersModalOpen,
    draftActiveOnly,
    setDraftActiveOnly,
    draftSexFilter,
    setDraftSexFilter,
    draftGenderFilter,
    setDraftGenderFilter,
    draftProfileTypeFilter,
    setDraftProfileTypeFilter,
    draftSexualContentFilter,
    setDraftSexualContentFilter,
    draftUserFilters,
    setDraftUserFilters,
    draftMinPrice,
    setDraftMinPrice,
    draftMaxPrice,
    setDraftMaxPrice,
    draftMinPostCount,
    setDraftMinPostCount,
    draftMaxPostCount,
    setDraftMaxPostCount,
    draftMinImageCount,
    setDraftMinImageCount,
    draftMaxImageCount,
    setDraftMaxImageCount,
    draftMinVideoCount,
    setDraftMinVideoCount,
    draftMaxVideoCount,
    setDraftMaxVideoCount,
    isLoadingInitialPage,
    isLoadingNextPage,
    hasMore,
    loadMoreSentinelRef,
    toast,
    setToast,
    authPickerLoading,
    createJobMutation,
    subscribeMutation,
    watchMutation,
    unwatchMutation,
    ignoreMutation,
    unignoreMutation,
    updateUserMutation,
    buildAutoLoadoutName,
    openUserFilters,
    applyUserFilters,
    openLoadoutModal,
    applyUsersLoadout,
    saveCurrentLoadout,
    setSelectedAsDefaultLoadout,
    clearDefaultLoadout,
    deleteSelectedLoadout,
    handleLoadMore,
    handleSelectAll,
    handleSelectUser,
    handleScrapeSelected,
    handleScrapeUser,
    handleSubscribeUser,
    handleWatchToggle,
    handleIgnoreToggle,
    handleWatchSelected,
    handleIgnoreSelected,
    openEditModal,
    handleSaveUserEdit,
    resetUserEditToOriginal,
    dispatchScrapeUser,
    lightboxUrl,
    lightboxAlt,
    openLightbox,
    closeLightbox,
  };
}
