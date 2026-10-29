import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';

import { getAuthList } from '../../../api/auths';
import { createJob } from '../../../api/jobs';
import {
  clearDefaultSearchLoadout,
  deleteSearchLoadout,
  getSearchLoadouts,
  saveSearchLoadout,
  setDefaultSearchLoadout,
} from '../../../api/loadouts';
import {
  getSubscriptions,
  getSubscriptionStats,
} from '../../../api/subscriptions';
import {
  addToIgnoreList,
  addToWatchList,
  getEligibleAuths,
  removeFromIgnoreList,
  removeFromWatchList,
  updateUser,
} from '../../../api/users';
import type { TaskPayload } from '../../../api/types/jobs';
import type {
  SearchLoadoutItem,
  SearchLoadoutsResponse,
} from '../../../api/types/loadouts';
import type { SubscriptionInfo } from '../../../api/types/subscriptions';
import type { EligibleAuth, UserUpdateRequest } from '../../../api/types/users';
import { isTypingTarget } from '../../../shared/lib/keyboard';
import { getSubscriptionKey } from '../lib/subscriptionsUtils';
import { appUrl } from '../../../api/http';

export function useSubscriptionsPageController() {
  const [searchParams, setSearchParams] = useSearchParams();
  const pageSize = 100;
  const hasUrlState = searchParams.toString().length > 0;
  const queryClient = useQueryClient();

  const [selectedSite, setSelectedSite] = useState<string>(() => searchParams.get('site') || '');
  const [selectedAuthId, setSelectedAuthId] = useState<number | ''>(() => {
    const raw = searchParams.get('auth_id');
    return raw && /^\d+$/.test(raw) ? Number(raw) : '';
  });
  const [searchTerm, setSearchTerm] = useState(() => searchParams.get('identifier') || '');
  const [searchQuery, setSearchQuery] = useState(() => searchParams.get('identifier') || '');
  const [activeOnly, setActiveOnly] = useState(() => {
    const raw = searchParams.get('active_only');
    return raw === null ? true : raw === 'true' || raw === '1';
  });
  const [minPrice, setMinPrice] = useState(() => {
    const raw = searchParams.get('min_price');
    if (raw !== null) {
      return raw;
    }
    const legacyHideFree = searchParams.get('hide_free');
    return legacyHideFree === 'true' || legacyHideFree === '1' ? '0.01' : '';
  });
  const [maxPrice, setMaxPrice] = useState(() => searchParams.get('max_price') || '');
  const [sexFilter, setSexFilter] = useState<number[]>(() => {
    const raw = searchParams.get('sex');
    if (!raw) return [];
    return raw
      .split(',')
      .map(Number)
      .filter((value) => Number.isInteger(value) && [0, 1, 2].includes(value));
  });
  const [filtersModalOpen, setFiltersModalOpen] = useState(false);
  const [draftActiveOnly, setDraftActiveOnly] = useState(true);
  const [draftMinPrice, setDraftMinPrice] = useState('');
  const [draftMaxPrice, setDraftMaxPrice] = useState('');
  const [draftSexFilter, setDraftSexFilter] = useState<number[]>([]);
  const [orderBy, setOrderBy] = useState<string>(() => searchParams.get('sort_by') || 'id');
  const [orderDir, setOrderDir] = useState<'asc' | 'desc'>(() =>
    searchParams.get('sort_order') === 'asc' ? 'asc' : 'desc'
  );
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [isScrapeMultipleDialogOpen, setIsScrapeMultipleDialogOpen] = useState(false);
  const [isWatchMultipleDialogOpen, setIsWatchMultipleDialogOpen] = useState(false);
  const [isIgnoreMultipleDialogOpen, setIsIgnoreMultipleDialogOpen] = useState(false);
  const [selectedSubscriptions, setSelectedSubscriptions] = useState<Set<string>>(new Set());
  const [authPickerOpen, setAuthPickerOpen] = useState(false);
  const [authPickerLoading, setAuthPickerLoading] = useState(false);
  const [eligibleAuths, setEligibleAuths] = useState<EligibleAuth[]>([]);
  const [authPickerTarget, setAuthPickerTarget] = useState<SubscriptionInfo | null>(null);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<SubscriptionInfo | null>(null);
  const [editName, setEditName] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editSex, setEditSex] = useState('');
  const [loadoutModalOpen, setLoadoutModalOpen] = useState(false);
  const [loadoutNameInput, setLoadoutNameInput] = useState('');
  const [selectedLoadoutName, setSelectedLoadoutName] = useState(
    () => searchParams.get('loadout') || ''
  );
  const [defaultLoadoutApplied, setDefaultLoadoutApplied] = useState(false);
  const [watchedKeys, setWatchedKeys] = useState<Set<string>>(new Set());
  const [ignoredKeys, setIgnoredKeys] = useState<Set<string>>(new Set());
  const [lightboxUrl, setLightboxUrl] = useState<string | null>(null);
  const [lightboxAlt, setLightboxAlt] = useState<string>('Image preview');

  const openLightbox = useCallback((url: string | null, alt = 'Image preview') => {
    setLightboxUrl(url);
    setLightboxAlt(alt);
  }, []);

  const closeLightbox = useCallback(() => {
    setLightboxUrl(null);
  }, []);

  const loadMoreSentinelRef = useRef<HTMLDivElement>(null);

  const showToast = (message: string, type: 'success' | 'error') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  const { data: loadoutsData, isFetched: loadoutsFetched } = useQuery({
    queryKey: ['search-loadouts', 'subscriptions'],
    queryFn: () => getSearchLoadouts('subscriptions'),
  });
  const selectedLoadout = loadoutsData?.loadouts.find((entry) => entry.name === selectedLoadoutName);
  const selectedLoadoutIsDefault = Boolean(selectedLoadout?.is_default);

  const { data: stats, isLoading: statsLoading } = useQuery({
    queryKey: ['subscription-stats'],
    queryFn: getSubscriptionStats,
  });

  const { data: auths } = useQuery({
    queryKey: ['auths', 'subscription-filter', selectedSite],
    queryFn: () => getAuthList(selectedSite || undefined, true),
  });

  const {
    data: subscriptionsData,
    isLoading,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: [
      'subscriptions',
      selectedSite,
      searchQuery,
      activeOnly,
      sexFilter.join(','),
      selectedAuthId,
      orderBy,
      orderDir,
    ],
    enabled: defaultLoadoutApplied,
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      getSubscriptions(
        selectedSite || undefined,
        searchQuery || undefined,
        activeOnly,
        selectedAuthId === '' ? undefined : selectedAuthId,
        pageSize,
        typeof pageParam === 'number' ? pageParam : 0,
        orderBy,
        orderDir,
        sexFilter.length ? sexFilter : undefined,
      ),
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, page) => sum + page.subscriptions.length, 0);
      return loaded < lastPage.total ? loaded : undefined;
    },
  });

  const subscriptions = useMemo(
    () => (subscriptionsData?.pages ?? []).flatMap((page) => page.subscriptions),
    [subscriptionsData],
  );
  const subscriptionsTotal = subscriptionsData?.pages?.[0]?.total ?? 0;
  const parsedMinPrice = Number.parseFloat(minPrice);
  const parsedMaxPrice = Number.parseFloat(maxPrice);
  const normalizedMinPrice = Number.isFinite(parsedMinPrice) ? parsedMinPrice : null;
  const normalizedMaxPrice = Number.isFinite(parsedMaxPrice) ? parsedMaxPrice : null;
  const visibleSubscriptions = useMemo(() => {
    return subscriptions.filter((subscription) => {
      const price = subscription.price ?? 0;
      if (normalizedMinPrice !== null && price < normalizedMinPrice) {
        return false;
      }
      if (normalizedMaxPrice !== null && price > normalizedMaxPrice) {
        return false;
      }
      return true;
    });
  }, [normalizedMaxPrice, normalizedMinPrice, subscriptions]);

  useEffect(() => {
    const mainContent = document.querySelector('.main-content');
    const isScrollable =
      mainContent instanceof HTMLElement &&
      ['auto', 'scroll'].includes(getComputedStyle(mainContent).overflowY);
    const scrollEl = isScrollable ? (mainContent as HTMLElement) : document.documentElement;
    const eventTarget: EventTarget = isScrollable ? scrollEl : window;

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = scrollEl;
      const distanceFromBottom = scrollHeight - scrollTop - clientHeight;

      if (
        scrollTop > 0 &&
        distanceFromBottom <= 350 &&
        hasNextPage &&
        !isFetchingNextPage
      ) {
        void fetchNextPage();
      }
    };

    eventTarget.addEventListener('scroll', handleScroll, { passive: true } as AddEventListenerOptions);
    return () => eventTarget.removeEventListener('scroll', handleScroll);
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  useEffect(() => {
    const timer = setTimeout(() => {
      const trimmedSearch = searchTerm.trim();
      if (trimmedSearch || searchQuery) {
        setSearchQuery(trimmedSearch);
      }
    }, 500);

    return () => clearTimeout(timer);
  }, [searchTerm, searchQuery]);

  useEffect(() => {
    if (!defaultLoadoutApplied) return;
    const nextParams = new URLSearchParams();
    nextParams.set('active_only', String(activeOnly));
    nextParams.set('sort_by', orderBy);
    nextParams.set('sort_order', orderDir);
    if (selectedSite) nextParams.set('site', selectedSite);
    if (selectedAuthId !== '') nextParams.set('auth_id', String(selectedAuthId));
    if (selectedLoadoutName) nextParams.set('loadout', selectedLoadoutName);
    if (searchQuery) nextParams.set('identifier', searchQuery);
    if (minPrice.trim()) nextParams.set('min_price', minPrice.trim());
    if (maxPrice.trim()) nextParams.set('max_price', maxPrice.trim());
    if (sexFilter.length) nextParams.set('sex', sexFilter.join(','));
    if (nextParams.toString() !== searchParams.toString()) {
      setSearchParams(nextParams, { replace: true });
    }
  }, [
    activeOnly,
    defaultLoadoutApplied,
    maxPrice,
    minPrice,
    orderBy,
    orderDir,
    searchParams,
    searchQuery,
    selectedAuthId,
    selectedLoadoutName,
    selectedSite,
    setSearchParams,
    sexFilter,
  ]);

  const activeFilterCount =
    (activeOnly ? 1 : 0) + ((minPrice.trim() || maxPrice.trim()) ? 1 : 0) + (sexFilter.length ? 1 : 0);

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

  const dispatchScrapeUser = (subscription: SubscriptionInfo, authId?: number) => {
    const params: Record<string, unknown> = {
      site: subscription.site,
      username: subscription.username || '',
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

    createJobMutation.mutate({
      job_name: `Scrape + Download @${subscription.username} (${subscription.site})`,
      tasks: [task],
      created_by: 'webui',
    });
  };

  const resolveAndScrapeUser = async (subscription: SubscriptionInfo) => {
    setAuthPickerLoading(true);
    try {
      const response = await getEligibleAuths(subscription.user_id, subscription.site);
      if (response.error) {
        showToast(response.error, 'error');
        return;
      }
      const auths = response.auths ?? [];
      if (auths.length <= 1) {
        dispatchScrapeUser(subscription, auths[0]?.auth_id);
        return;
      }
      setAuthPickerTarget(subscription);
      setEligibleAuths(auths);
      setAuthPickerOpen(true);
    } catch (error) {
      showToast(
        `Failed to fetch eligible auths: ${error instanceof Error ? error.message : 'Unknown error'}`,
        'error',
      );
    } finally {
      setAuthPickerLoading(false);
    }
  };

  const handleScrapeUser = (subscription: SubscriptionInfo) => {
    void resolveAndScrapeUser(subscription);
  };

  const handleViewUser = (subscription: SubscriptionInfo) => {
    const params = new URLSearchParams({
      site: subscription.site,
      username: subscription.username || '',
    });
    window.location.href = appUrl(`/media?${params.toString()}`);
  };

  const toggleSubscriptionSelection = useCallback((subscription: SubscriptionInfo) => {
    const key = getSubscriptionKey(subscription);
    setSelectedSubscriptions((previous) => {
      const next = new Set(previous);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);

  const clearSelections = useCallback(() => {
    setSelectedSubscriptions(new Set());
  }, []);

  const selectAll = useCallback(() => {
    setSelectedSubscriptions(new Set(visibleSubscriptions.map(getSubscriptionKey)));
  }, [visibleSubscriptions]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented ||
        authPickerOpen ||
        editModalOpen ||
        filtersModalOpen ||
        loadoutModalOpen ||
        isScrapeMultipleDialogOpen ||
        isWatchMultipleDialogOpen ||
        isIgnoreMultipleDialogOpen ||
        isTypingTarget(event.target)
      ) {
        return;
      }

      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'a') {
        if (!visibleSubscriptions.length) {
          return;
        }
        event.preventDefault();
        selectAll();
        return;
      }

      if (event.key === 'Escape' && selectedSubscriptions.size > 0) {
        event.preventDefault();
        clearSelections();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    authPickerOpen,
    clearSelections,
    editModalOpen,
    filtersModalOpen,
    isIgnoreMultipleDialogOpen,
    isScrapeMultipleDialogOpen,
    isWatchMultipleDialogOpen,
    loadoutModalOpen,
    selectAll,
    selectedSubscriptions.size,
    visibleSubscriptions.length,
  ]);

  const handleScrapeMultiple = () => {
    if (selectedSubscriptions.size === 0) {
      showToast('No subscriptions selected', 'error');
      return;
    }
    setIsScrapeMultipleDialogOpen(true);
  };

  const handleWatchMultiple = () => {
    if (selectedSubscriptions.size === 0) {
      showToast('No subscriptions selected', 'error');
      return;
    }
    setIsWatchMultipleDialogOpen(true);
  };

  const handleIgnoreMultiple = () => {
    if (selectedSubscriptions.size === 0) {
      showToast('No subscriptions selected', 'error');
      return;
    }
    setIsIgnoreMultipleDialogOpen(true);
  };

  const watchMutation = useMutation({
    mutationFn: ({ userId, site }: { userId: number; site: string }) =>
      addToWatchList(userId, site),
    onSuccess: (_, variables) => {
      showToast(`Added @${variables.site} user to watch list`, 'success');
      queryClient.invalidateQueries({ queryKey: ['watchList'] });
      queryClient.invalidateQueries({ queryKey: ['watchStats'] });
      setWatchedKeys((previous) => new Set(previous).add(`${variables.site}-${variables.userId}`));
    },
    onError: (error: Error) => {
      showToast(`Failed to add to watch list: ${error.message}`, 'error');
    },
  });

  const unwatchMutation = useMutation({
    mutationFn: ({ userId, site }: { userId: number; site: string }) =>
      removeFromWatchList(userId, site),
    onSuccess: (_, variables) => {
      showToast('Removed from watch list', 'success');
      queryClient.invalidateQueries({ queryKey: ['watchList'] });
      queryClient.invalidateQueries({ queryKey: ['watchStats'] });
      setWatchedKeys((previous) => {
        const next = new Set(previous);
        next.delete(`${variables.site}-${variables.userId}`);
        return next;
      });
    },
    onError: (error: Error) => {
      showToast(`Failed to remove from watch list: ${error.message}`, 'error');
    },
  });

  const ignoreMutation = useMutation({
    mutationFn: ({ userId, site }: { userId: number; site: string }) =>
      addToIgnoreList(userId, site),
    onSuccess: (_, variables) => {
      showToast('User ignored — they will be skipped when scraping', 'success');
      setIgnoredKeys((previous) => new Set(previous).add(`${variables.site}-${variables.userId}`));
    },
    onError: (error: Error) => {
      showToast(`Failed to ignore user: ${error.message}`, 'error');
    },
  });

  const unignoreMutation = useMutation({
    mutationFn: ({ userId, site }: { userId: number; site: string }) =>
      removeFromIgnoreList(userId, site),
    onSuccess: (_, variables) => {
      showToast('User unignored — they will be included when scraping', 'success');
      setIgnoredKeys((previous) => {
        const next = new Set(previous);
        next.delete(`${variables.site}-${variables.userId}`);
        return next;
      });
    },
    onError: (error: Error) => {
      showToast(`Failed to unignore user: ${error.message}`, 'error');
    },
  });

  const selectedSubscriptionObjects = useMemo(
    () => visibleSubscriptions.filter((subscription) => selectedSubscriptions.has(getSubscriptionKey(subscription))),
    [selectedSubscriptions, visibleSubscriptions],
  );

  const selectedScrapableSubscriptions = useMemo(
    () =>
      selectedSubscriptionObjects.filter(
        (subscription) => !ignoredKeys.has(`${subscription.site}-${subscription.user_id}`),
      ),
    [ignoredKeys, selectedSubscriptionObjects],
  );

  const selectedWatchableSubscriptions = useMemo(
    () =>
      selectedSubscriptionObjects.filter(
        (subscription) => !watchedKeys.has(`${subscription.site}-${subscription.user_id}`),
      ),
    [selectedSubscriptionObjects, watchedKeys],
  );

  const selectedIgnorableSubscriptions = useMemo(
    () =>
      selectedSubscriptionObjects.filter(
        (subscription) => !ignoredKeys.has(`${subscription.site}-${subscription.user_id}`),
      ),
    [ignoredKeys, selectedSubscriptionObjects],
  );

  const confirmWatchMultiple = async () => {
    await Promise.allSettled(
      selectedWatchableSubscriptions.map((subscription) =>
        addToWatchList(subscription.user_id, subscription.site).then(() => {
          setWatchedKeys((previous) =>
            new Set(previous).add(`${subscription.site}-${subscription.user_id}`)
          );
        }),
      ),
    );
    showToast(
      `Added ${selectedWatchableSubscriptions.length} user${selectedWatchableSubscriptions.length !== 1 ? 's' : ''} to watch list`,
      'success',
    );
    queryClient.invalidateQueries({ queryKey: ['watchList'] });
    queryClient.invalidateQueries({ queryKey: ['watchStats'] });
    setIsWatchMultipleDialogOpen(false);
    clearSelections();
  };

  const confirmIgnoreMultiple = async () => {
    await Promise.allSettled(
      selectedIgnorableSubscriptions.map((subscription) =>
        addToIgnoreList(subscription.user_id, subscription.site).then(() => {
          setIgnoredKeys((previous) =>
            new Set(previous).add(`${subscription.site}-${subscription.user_id}`)
          );
        }),
      ),
    );
    showToast(
      `Ignored ${selectedIgnorableSubscriptions.length} user${selectedIgnorableSubscriptions.length !== 1 ? 's' : ''} — they will be skipped when scraping`,
      'success',
    );
    setIsIgnoreMultipleDialogOpen(false);
    clearSelections();
  };

  useEffect(() => {
    if (!subscriptions.length) {
      setWatchedKeys(new Set());
      setIgnoredKeys(new Set());
      return;
    }
    const nextWatched = new Set<string>();
    const nextIgnored = new Set<string>();
    for (const subscription of subscriptions) {
      const key = `${subscription.site}-${subscription.user_id}`;
      if (subscription.watched) nextWatched.add(key);
      if (subscription.ignored) nextIgnored.add(key);
    }
    setWatchedKeys(nextWatched);
    setIgnoredKeys(nextIgnored);
  }, [subscriptions]);

  useEffect(() => {
    const visibleKeys = new Set(visibleSubscriptions.map(getSubscriptionKey));
    setSelectedSubscriptions((previous) => {
      const next = new Set([...previous].filter((key) => visibleKeys.has(key)));
      return next.size === previous.size ? previous : next;
    });
  }, [visibleSubscriptions]);

  const handleWatchToggle = (subscription: SubscriptionInfo) => {
    const key = `${subscription.site}-${subscription.user_id}`;
    if (watchedKeys.has(key)) {
      unwatchMutation.mutate({ userId: subscription.user_id, site: subscription.site });
    } else {
      watchMutation.mutate({ userId: subscription.user_id, site: subscription.site });
    }
  };

  const updateUserMutation = useMutation({
    mutationFn: ({ subscription, payload }: { subscription: SubscriptionInfo; payload: UserUpdateRequest }) =>
      updateUser(subscription.user_id, subscription.site, payload),
    onSuccess: (_, variables) => {
      showToast(`Updated @${variables.subscription.username || variables.subscription.user_id}`, 'success');
      setEditModalOpen(false);
      setEditTarget(null);
      queryClient.invalidateQueries({ queryKey: ['subscriptions'] });
      queryClient.invalidateQueries({ queryKey: ['users-list'] });
    },
    onError: (error: Error) => {
      showToast(`Failed to update user: ${error.message}`, 'error');
    },
  });

  const handleIgnoreToggle = (subscription: SubscriptionInfo) => {
    const key = `${subscription.site}-${subscription.user_id}`;
    if (ignoredKeys.has(key)) {
      unignoreMutation.mutate({ userId: subscription.user_id, site: subscription.site });
    } else {
      ignoreMutation.mutate({ userId: subscription.user_id, site: subscription.site });
    }
  };

  const openEditModal = (subscription: SubscriptionInfo) => {
    setEditTarget(subscription);
    setEditName(subscription.name ?? '');
    setEditDescription(subscription.description ?? '');
    setEditSex(subscription.sex === null ? '' : String(subscription.sex));
    setEditModalOpen(true);
  };

  const handleSaveUserEdit = () => {
    if (!editTarget) return;
    const normalizedSex = editSex === '' ? null : Number(editSex);
    if (normalizedSex !== null && ![0, 1, 2].includes(normalizedSex)) {
      showToast('Invalid sex value', 'error');
      return;
    }

    updateUserMutation.mutate({
      subscription: editTarget,
      payload: {
        name: editName.trim() || null,
        description: editDescription.trim() || null,
        sex: normalizedSex,
      },
    });
  };

  const confirmScrapeMultiple = () => {
    if (selectedScrapableSubscriptions.length === 0) {
      showToast('All selected users are ignored — nothing to scrape', 'error');
      setIsScrapeMultipleDialogOpen(false);
      return;
    }

    const tasks: TaskPayload[] = selectedScrapableSubscriptions.map((subscription) => ({
      task_type: 'scrape_and_download',
      params: {
        site: subscription.site,
        username: subscription.username || '',
        content_types: ['Posts', 'ArchivedPosts', 'Messages', 'Stories', 'Highlights', 'Profile'],
        rescrape_existing: true,
      },
    }));

    createJobMutation.mutate({
      job_name: `Scrape Selected (${selectedScrapableSubscriptions.length} users)`,
      tasks,
      created_by: 'webui',
    });
    setIsScrapeMultipleDialogOpen(false);
    clearSelections();
  };

  const openFiltersModal = () => {
    setDraftActiveOnly(activeOnly);
    setDraftMinPrice(minPrice);
    setDraftMaxPrice(maxPrice);
    setDraftSexFilter([...sexFilter]);
    setFiltersModalOpen(true);
  };

  const applyFilters = () => {
    setActiveOnly(draftActiveOnly);
    setMinPrice(draftMinPrice.trim());
    setMaxPrice(draftMaxPrice.trim());
    setSexFilter([...draftSexFilter]);
    setFiltersModalOpen(false);
  };

  const clearFilters = () => {
    setDraftActiveOnly(true);
    setDraftMinPrice('');
    setDraftMaxPrice('');
    setDraftSexFilter([]);
  };

  const buildAutoLoadoutName = () => {
    const normalize = (value: string, maxLength: number) =>
      value.trim().replace(/\s+/g, ' ').slice(0, maxLength);

    const siteValue = normalize(selectedSite || 'all', 24) || 'all';
    const identifierValue = normalize(searchQuery || searchTerm, 36);
    const parts = [`site:${siteValue}`];
    if (identifierValue) parts.push(`identifier:${identifierValue}`);
    if (minPrice.trim() || maxPrice.trim()) {
      parts.push(`price:${minPrice.trim() || 'any'}-${maxPrice.trim() || 'any'}`);
    }
    return parts.join(' | ');
  };

  const autofillLoadoutName = () => {
    setLoadoutNameInput(buildAutoLoadoutName());
  };

  const openLoadoutModal = () => {
    setLoadoutNameInput(selectedLoadoutName || buildAutoLoadoutName());
    setLoadoutModalOpen(true);
  };

  const applySubscriptionsLoadout = useCallback((loadout: SearchLoadoutItem) => {
    const identifier = loadout.identifier || '';
    const siteValue = loadout.site || '';
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

    setSearchTerm(identifier);
    setSearchQuery(identifier);
    setSelectedSite(siteValue);
    setActiveOnly(typeof filters.active_only === 'boolean' ? filters.active_only : true);
    setMinPrice(nextMinPrice);
    setMaxPrice(nextMaxPrice);
    setSexFilter(nextSex);
    setSelectedAuthId(nextAuthId);
    setOrderBy(typeof filters.order_by === 'string' ? filters.order_by : 'id');
    setOrderDir(filters.order_dir === 'asc' ? 'asc' : 'desc');
  }, []);

  useEffect(() => {
    if (defaultLoadoutApplied || !loadoutsFetched) return;
    if (hasUrlState) {
      setDefaultLoadoutApplied(true);
      return;
    }
    if (!loadoutsData) return;
    if (loadoutsData.default_name) {
      const defaultLoadout = loadoutsData.loadouts.find(
        (entry) => entry.name === loadoutsData.default_name,
      );
      if (defaultLoadout) {
        applySubscriptionsLoadout(defaultLoadout);
        setSelectedLoadoutName(defaultLoadout.name);
      }
    }
    setDefaultLoadoutApplied(true);
  }, [
    applySubscriptionsLoadout,
    defaultLoadoutApplied,
    hasUrlState,
    loadoutsData,
    loadoutsFetched,
  ]);

  const saveCurrentLoadout = async () => {
    const name = loadoutNameInput.trim() || buildAutoLoadoutName();
    if (!name) return;

    await saveSearchLoadout('subscriptions', name, {
      identifier: searchQuery || searchTerm.trim(),
      description: '',
      site: selectedSite,
      filters: {
        active_only: activeOnly,
        min_price: minPrice.trim() || null,
        max_price: maxPrice.trim() || null,
        sex: sexFilter,
        auth_id: selectedAuthId === '' ? null : selectedAuthId,
        order_by: orderBy,
        order_dir: orderDir,
      },
    });
    setSelectedLoadoutName(name);
    setLoadoutNameInput(name);
    await queryClient.invalidateQueries({ queryKey: ['search-loadouts', 'subscriptions'] });
    showToast(`Saved loadout "${name}"`, 'success');
  };

  const setSelectedAsDefaultLoadout = async () => {
    if (!selectedLoadoutName) return;
    await setDefaultSearchLoadout('subscriptions', selectedLoadoutName);
    await queryClient.invalidateQueries({ queryKey: ['search-loadouts', 'subscriptions'] });
    showToast(`Default loadout set to "${selectedLoadoutName}"`, 'success');
  };

  const clearDefaultLoadout = async () => {
    await clearDefaultSearchLoadout('subscriptions');
    await queryClient.invalidateQueries({ queryKey: ['search-loadouts', 'subscriptions'] });
    showToast('Default loadout cleared', 'success');
  };

  const deleteSelectedLoadout = async () => {
    if (!selectedLoadoutName) return;
    await deleteSearchLoadout('subscriptions', selectedLoadoutName);
    setSelectedLoadoutName('');
    setLoadoutNameInput('');
    await queryClient.invalidateQueries({ queryKey: ['search-loadouts', 'subscriptions'] });
    showToast('Deleted loadout', 'success');
  };

  const handleSelectLoadout = (value: string, loadouts: SearchLoadoutsResponse | undefined) => {
    setSelectedLoadoutName(value);
    setLoadoutNameInput(value);
    const loadout = loadouts?.loadouts.find((entry) => entry.name === value);
    if (loadout) {
      applySubscriptionsLoadout(loadout);
    }
  };

  return {
    pageSize,
    selectedSite,
    setSelectedSite,
    selectedAuthId,
    setSelectedAuthId,
    searchTerm,
    setSearchTerm,
    setSearchQuery,
    orderBy,
    setOrderBy,
    orderDir,
    setOrderDir,
    toast,
    setToast,
    stats,
    statsLoading,
    auths,
    activeFilterCount,
    createJobMutation,
    authPickerOpen,
    setAuthPickerOpen,
    authPickerTarget,
    eligibleAuths,
    dispatchScrapeUser,
    editModalOpen,
    setEditModalOpen,
    editTarget,
    editName,
    setEditName,
    editDescription,
    setEditDescription,
    editSex,
    setEditSex,
    updateUserMutation,
    handleSaveUserEdit,
    isScrapeMultipleDialogOpen,
    setIsScrapeMultipleDialogOpen,
    selectedScrapableSubscriptions,
    selectedSubscriptions,
    isIgnoreMultipleDialogOpen,
    setIsIgnoreMultipleDialogOpen,
    selectedIgnorableSubscriptions,
    selectedSubscriptionObjects,
    confirmIgnoreMultiple,
    isWatchMultipleDialogOpen,
    setIsWatchMultipleDialogOpen,
    selectedWatchableSubscriptions,
    confirmWatchMultiple,
    authPickerLoading,
    loadoutModalOpen,
    setLoadoutModalOpen,
    loadoutsData,
    selectedLoadoutName,
    loadoutNameInput,
    setLoadoutNameInput,
    selectedLoadoutIsDefault,
    minPrice,
    maxPrice,
    buildAutoLoadoutName,
    autofillLoadoutName,
    deleteSelectedLoadout,
    clearDefaultLoadout,
    setSelectedAsDefaultLoadout,
    saveCurrentLoadout,
    handleSelectLoadout,
    filtersModalOpen,
    setFiltersModalOpen,
    draftActiveOnly,
    setDraftActiveOnly,
    draftMinPrice,
    setDraftMinPrice,
    draftMaxPrice,
    setDraftMaxPrice,
    draftSexFilter,
    setDraftSexFilter,
    clearFilters,
    applyFilters,
    visibleSubscriptions,
    subscriptionsTotal,
    isLoading,
    error,
    hasNextPage,
    isFetchingNextPage,
    watchedKeys,
    ignoredKeys,
    watchMutation,
    unwatchMutation,
    ignoreMutation,
    unignoreMutation,
    loadMoreSentinelRef,
    fetchNextPage,
    handleScrapeUser,
    handleViewUser,
    toggleSubscriptionSelection,
    handleWatchToggle,
    handleIgnoreToggle,
    openEditModal,
    openLoadoutModal,
    openFiltersModal,
    selectAll,
    clearSelections,
    handleScrapeMultiple,
    handleWatchMultiple,
    handleIgnoreMultiple,
    confirmScrapeMultiple,
    lightboxUrl,
    lightboxAlt,
    openLightbox,
    closeLightbox,
  };
}
