import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { browseContentLibrary } from '../../../api/content';
import {
  clearDefaultSearchLoadout,
  deleteSearchLoadout,
  getSearchLoadouts,
  saveSearchLoadout,
  setDefaultSearchLoadout,
} from '../../../api/loadouts';
import type { ContentLibraryItem } from '../../../api/types/content';
import type { SearchLoadoutItem } from '../../../api/types/loadouts';
import {
  applyContentLoadoutState,
  DEFAULT_ADVANCED_FILTERS,
  PAGE_SIZE,
  type AdvancedFilterKey,
  type AdvancedFilterMap,
  type AdvancedFilterState,
} from '../lib/contentLibraryUtils';

export function useContentLibraryController() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [items, setItems] = useState<ContentLibraryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [totalIsExact, setTotalIsExact] = useState(true);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const hasUrlState = searchParams.toString().length > 0;
  const [site, setSite] = useState(() => searchParams.get('site') || '');
  const [contentType, setContentType] = useState(() => searchParams.get('content_type') || '');
  const [search, setSearch] = useState(() => searchParams.get('identifier') || '');
  const [searchInput, setSearchInput] = useState(() => searchParams.get('identifier') || '');
  const [sortBy, setSortBy] = useState(() => searchParams.get('sort_by') || 'created_at');
  const [order, setOrder] = useState<'asc' | 'desc'>(() =>
    searchParams.get('order') === 'asc' ? 'asc' : 'desc',
  );
  const [advancedFilters, setAdvancedFilters] = useState<AdvancedFilterMap>(() => {
    const next = { ...DEFAULT_ADVANCED_FILTERS };
    const initialMediaType = searchParams.get('media_type');
    if (initialMediaType === 'video') next.has_video = 'include';
    if (initialMediaType === 'photo') next.has_photo = 'include';
    if (initialMediaType === 'audio') next.has_audio = 'include';
    for (const key of Object.keys(DEFAULT_ADVANCED_FILTERS) as AdvancedFilterKey[]) {
      const raw = searchParams.get(`filter_${key}`);
      if (raw === 'include' || raw === 'exclude' || raw === 'none') {
        next[key] = raw;
      }
    }
    return next;
  });

  const mediaType = useMemo(() => {
    if (advancedFilters.has_video === 'include') return 'video';
    if (advancedFilters.has_photo === 'include') return 'photo';
    if (advancedFilters.has_audio === 'include') return 'audio';
    return '';
  }, [advancedFilters]);

  const setMediaType = useCallback((value: string) => {
    setAdvancedFilters((current) => ({
      ...current,
      has_video: value === 'video' ? 'include' : 'none',
      has_photo: value === 'photo' ? 'include' : 'none',
      has_audio: value === 'audio' ? 'include' : 'none',
    }));
  }, []);
  const [draftAdvancedFilters, setDraftAdvancedFilters] = useState<AdvancedFilterMap>(
    DEFAULT_ADVANCED_FILTERS,
  );
  const [advancedModalOpen, setAdvancedModalOpen] = useState(false);
  const [loadoutModalOpen, setLoadoutModalOpen] = useState(false);
  const [loadouts, setLoadouts] = useState<SearchLoadoutItem[]>([]);
  const [loadoutNameInput, setLoadoutNameInput] = useState('');
  const [selectedLoadoutName, setSelectedLoadoutName] = useState(
    () => searchParams.get('loadout') || '',
  );
  const [defaultLoadoutApplied, setDefaultLoadoutApplied] = useState(false);
  const [excludedUserIds, setExcludedUserIds] = useState<number[]>(() => {
    const raw = searchParams.get('exclude_user_ids');
    if (!raw) return [];
    return raw
      .split(',')
      .map(Number)
      .filter((id) => !isNaN(id) && id > 0);
  });
  const [excludedUsernames, setExcludedUsernames] = useState<Record<number, string>>({});

  const sentinelRef = useRef<HTMLDivElement>(null);
  const searchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const loadingRef = useRef(false);
  const hasMoreRef = useRef(true);
  const nextPageRef = useRef(2);
  const requestSequence = useRef(0);
  const failedRequest = useRef<{ page: number; append: boolean } | null>(null);
  const advancedFilterSignature = JSON.stringify(advancedFilters);
  const excludedUserIdsSignature = excludedUserIds.join(',');

  const includeFlags = useMemo(
    () =>
      Object.entries(advancedFilters)
        .filter(([, state]) => state === 'include')
        .map(([key]) => key as AdvancedFilterKey),
    [advancedFilters],
  );
  const excludeFlags = useMemo(
    () =>
      Object.entries(advancedFilters)
        .filter(([, state]) => state === 'exclude')
        .map(([key]) => key as AdvancedFilterKey),
    [advancedFilters],
  );
  const activeAdvancedFilterCount = includeFlags.length + excludeFlags.length;
  const selectedLoadout = loadouts.find((loadout) => loadout.name === selectedLoadoutName);
  const selectedLoadoutIsDefault = Boolean(selectedLoadout?.is_default);

  const applyContentLoadout = useCallback((loadout: SearchLoadoutItem) => {
    const next = applyContentLoadoutState(loadout);
    setSite(next.site);
    setSearchInput(next.identifier);
    setSearch(next.identifier);
    setContentType(next.contentType);
    setSortBy(next.sortBy);
    setOrder(next.order);
    setAdvancedFilters(next.advancedFilters);
    setDraftAdvancedFilters(next.advancedFilters);
    setExcludedUserIds(next.excludedUserIds || []);
  }, []);

  const refreshLoadouts = useCallback(async () => {
    const response = await getSearchLoadouts('content');
    if (!response.success) {
      return;
    }

    setLoadouts(response.loadouts);
    if (!defaultLoadoutApplied && hasUrlState) {
      setDefaultLoadoutApplied(true);
      return;
    }

    if (!defaultLoadoutApplied && response.default_name) {
      const defaultLoadout = response.loadouts.find((loadout) => loadout.name === response.default_name);
      if (defaultLoadout) {
        applyContentLoadout(defaultLoadout);
        setSelectedLoadoutName(defaultLoadout.name);
      }
      setDefaultLoadoutApplied(true);
      return;
    }

    if (!defaultLoadoutApplied) {
      setDefaultLoadoutApplied(true);
    }
  }, [applyContentLoadout, defaultLoadoutApplied, hasUrlState]);

  useEffect(() => {
    void refreshLoadouts();
  }, [refreshLoadouts]);

  useEffect(() => {
    if (!defaultLoadoutApplied) {
      return;
    }

    const nextParams = new URLSearchParams();
    nextParams.set('sort_by', sortBy);
    nextParams.set('order', order);
    if (site) nextParams.set('site', site);
    if (contentType) nextParams.set('content_type', contentType);
    if (selectedLoadoutName) nextParams.set('loadout', selectedLoadoutName);
    if (search) nextParams.set('identifier', search);
    if (excludedUserIds.length > 0) {
      nextParams.set('exclude_user_ids', excludedUserIds.join(','));
    }
    for (const key of Object.keys(advancedFilters) as AdvancedFilterKey[]) {
      const value = advancedFilters[key];
      if (value !== 'none') {
        nextParams.set(`filter_${key}`, value);
      }
    }

    if (nextParams.toString() !== searchParams.toString()) {
      setSearchParams(nextParams, { replace: true });
    }
  }, [
    advancedFilters,
    contentType,
    defaultLoadoutApplied,
    excludedUserIds,
    order,
    search,
    searchParams,
    selectedLoadoutName,
    setSearchParams,
    site,
    sortBy,
  ]);

  const fetchContent = useCallback(
    async (pageNum: number, append: boolean) => {
      // IntersectionObserver may emit more than once before React commits the
      // loading state. Guard synchronously so a page can only be requested once.
      if (append && loadingRef.current) {
        return;
      }

      activeRequest.current?.abort();
      const controller = new AbortController();
      activeRequest.current = controller;
      const sequence = ++requestSequence.current;
      loadingRef.current = true;
      setLoading(true);
      setError(null);
      try {
        const response = await browseContentLibrary({
          site: site || undefined,
          contentType: contentType || undefined,
          search: search || undefined,
          sortBy,
          order,
          includeFlags: includeFlags.length ? includeFlags : undefined,
          excludeFlags: excludeFlags.length ? excludeFlags : undefined,
          excludeUserIds: excludedUserIds.length ? excludedUserIds : undefined,
          page: pageNum,
          pageSize: PAGE_SIZE,
          includeTotal: !append,
          signal: controller.signal,
        });

        if (controller.signal.aborted || sequence !== requestSequence.current) {
          return;
        }

        if (response.success) {
          setItems((current) => {
            if (!append) return response.content;

            // Offset pagination can overlap when new content is inserted while
            // scrolling. Keep React keys stable and avoid duplicate media cards.
            const seen = new Set(
              current.map((item) => `${item.site}:${item.content_type}:${item.id}`),
            );
            return [
              ...current,
              ...response.content.filter((item) => {
                const key = `${item.site}:${item.content_type}:${item.id}`;
                if (seen.has(key)) return false;
                seen.add(key);
                return true;
              }),
            ];
          });
          const loadedCount = (pageNum - 1) * PAGE_SIZE + response.content.length;
          const moreAvailable = response.has_more ?? (
            response.content.length === PAGE_SIZE && loadedCount < response.total
          );
          const responseTotalIsExact = response.total_is_exact ?? true;
          if (!append) {
            setTotal(responseTotalIsExact ? response.total : loadedCount);
            setTotalIsExact(responseTotalIsExact || !moreAvailable);
          } else if (!responseTotalIsExact) {
            setTotal((current) => Math.max(current, loadedCount));
          }
          if (!moreAvailable) {
            setTotal(loadedCount);
            setTotalIsExact(true);
          }
          hasMoreRef.current = moreAvailable;
          nextPageRef.current = pageNum + 1;
          failedRequest.current = null;
          setHasMore(moreAvailable);
        } else {
          failedRequest.current = { page: pageNum, append };
          setError(response.error ?? 'Failed to load content');
        }
      } catch (fetchError) {
        if (controller.signal.aborted || sequence !== requestSequence.current) {
          return;
        }
        failedRequest.current = { page: pageNum, append };
        setError(fetchError instanceof Error ? fetchError.message : 'Network error');
      } finally {
        if (sequence === requestSequence.current) {
          activeRequest.current = null;
          loadingRef.current = false;
          setLoading(false);
        }
      }
    },
    [contentType, excludeFlags, excludedUserIds, includeFlags, order, search, site, sortBy],
  );

  useEffect(() => {
    if (!defaultLoadoutApplied) {
      return;
    }
    activeRequest.current?.abort();
    loadingRef.current = false;
    hasMoreRef.current = true;
    nextPageRef.current = 2;
    failedRequest.current = null;
    setHasMore(true);
    void fetchContent(1, false);
  }, [
    advancedFilterSignature,
    contentType,
    defaultLoadoutApplied,
    excludedUserIdsSignature,
    fetchContent,
    order,
    search,
    site,
    sortBy,
  ]);

  useEffect(() => {
    if (!defaultLoadoutApplied || !sentinelRef.current) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (
          entries[0]?.isIntersecting &&
          hasMoreRef.current &&
          !loadingRef.current
        ) {
          void fetchContent(nextPageRef.current, true);
        }
      },
      { rootMargin: '300px' },
    );

    observer.observe(sentinelRef.current);
    return () => observer.disconnect();
  }, [defaultLoadoutApplied, fetchContent]);

  useEffect(
    () => () => {
      activeRequest.current?.abort();
      if (searchTimeout.current) {
        clearTimeout(searchTimeout.current);
      }
    },
    [],
  );

  const handleSearchInput = useCallback((value: string) => {
    setSearchInput(value);
    if (searchTimeout.current) {
      clearTimeout(searchTimeout.current);
    }
    searchTimeout.current = setTimeout(() => {
      setSearch(value);
    }, 400);
  }, []);

  const toggleOrder = useCallback(() => {
    setOrder((current) => (current === 'desc' ? 'asc' : 'desc'));
  }, []);

  const openAdvancedFilters = useCallback(() => {
    setDraftAdvancedFilters(advancedFilters);
    setAdvancedModalOpen(true);
  }, [advancedFilters]);

  const openLoadoutModal = useCallback((placeholderName: string) => {
    setLoadoutNameInput(selectedLoadoutName || placeholderName);
    setLoadoutModalOpen(true);
  }, [selectedLoadoutName]);

  const setDraftFilterState = useCallback((key: AdvancedFilterKey, state: AdvancedFilterState) => {
    setDraftAdvancedFilters((current) => ({
      ...current,
      [key]: state,
    }));
  }, []);

  const applyAdvancedFilters = useCallback(() => {
    setAdvancedFilters(draftAdvancedFilters);
    setAdvancedModalOpen(false);
  }, [draftAdvancedFilters]);

  const clearDraftAdvancedFilters = useCallback(() => {
    setDraftAdvancedFilters(DEFAULT_ADVANCED_FILTERS);
  }, []);

  const hideUser = useCallback((userId: number, username?: string | null) => {
    if (!userId) return;
    if (username) {
      setExcludedUsernames((prev) => ({ ...prev, [userId]: username }));
    }
    setExcludedUserIds((prev) => (prev.includes(userId) ? prev : [...prev, userId]));
    setItems((prev) => prev.filter((item) => item.user_id !== userId));
    setTotal((prev) => Math.max(0, prev - 1));
  }, []);

  const unhideUser = useCallback((userId: number) => {
    setExcludedUserIds((prev) => prev.filter((id) => id !== userId));
  }, []);

  const clearHiddenUsers = useCallback(() => {
    setExcludedUserIds([]);
  }, []);

  const saveCurrentLoadout = useCallback(
    async (name: string) => {
      await saveSearchLoadout('content', name, {
        identifier: search || searchInput,
        description: '',
        site,
        filters: {
          content_type: contentType,
          sort_by: sortBy,
          order,
          advanced_filters: advancedFilters,
          exclude_user_ids: excludedUserIds,
        },
      });
      setSelectedLoadoutName(name);
      setLoadoutNameInput(name);
      await refreshLoadouts();
    },
    [advancedFilters, contentType, excludedUserIds, order, refreshLoadouts, search, searchInput, site, sortBy],
  );

  const setSelectedAsDefaultLoadout = useCallback(async () => {
    if (!selectedLoadoutName) {
      return;
    }
    await setDefaultSearchLoadout('content', selectedLoadoutName);
    await refreshLoadouts();
  }, [refreshLoadouts, selectedLoadoutName]);

  const clearDefaultLoadout = useCallback(async () => {
    await clearDefaultSearchLoadout('content');
    await refreshLoadouts();
  }, [refreshLoadouts]);

  const deleteSelectedLoadout = useCallback(async () => {
    if (!selectedLoadoutName) {
      return;
    }
    await deleteSearchLoadout('content', selectedLoadoutName);
    setSelectedLoadoutName('');
    setLoadoutNameInput('');
    await refreshLoadouts();
  }, [refreshLoadouts, selectedLoadoutName]);

  const retryInitialPage = useCallback(() => {
    const failed = failedRequest.current;
    void fetchContent(failed?.page ?? 1, failed?.append ?? false);
  }, [fetchContent]);

  return {
    activeAdvancedFilterCount,
    advancedModalOpen,
    applyAdvancedFilters,
    applyContentLoadout,
    clearDefaultLoadout,
    clearDraftAdvancedFilters,
    clearHiddenUsers,
    contentType,
    mediaType,
    defaultLoadoutApplied,
    deleteSelectedLoadout,
    draftAdvancedFilters,
    error,
    excludedUserIds,
    excludedUsernames,
    fetchContent,
    handleSearchInput,
    hasMore,
    hideUser,
    items,
    loading,
    loadoutModalOpen,
    loadoutNameInput,
    loadouts,
    openAdvancedFilters,
    openLoadoutModal,
    order,
    retryInitialPage,
    saveCurrentLoadout,
    search,
    searchInput,
    selectedLoadoutName,
    selectedLoadoutIsDefault,
    sentinelRef,
    setAdvancedModalOpen,
    setContentType,
    setMediaType,
    setDraftFilterState,
    setLoadoutModalOpen,
    setLoadoutNameInput,
    setOrder,
    setSearch,
    setSearchInput,
    setSelectedAsDefaultLoadout,
    setSelectedLoadoutName,
    setSite,
    setSortBy,
    site,
    sortBy,
    toggleOrder,
    total,
    totalIsExact,
    unhideUser,
  };
}
