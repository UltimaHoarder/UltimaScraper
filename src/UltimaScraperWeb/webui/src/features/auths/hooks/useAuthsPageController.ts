import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query';

import { createJob } from '../../../api/jobs';
import type { CreateJobRequest, TaskPayload } from '../../../api/types/jobs';
import type { Job } from '../../../api/types/jobs';
import {
  deleteAuth,
  getAuthList,
  testAuth,
  toggleAuthStatus,
  updateAuth,
} from '../../../api/auths';
import type {
  AuthCredential,
  AuthEditRequest,
} from '../../../api/types/auths';
import {
  createVerificationRequestKey,
  matchesStateFilter,
  type AuthStateFilter,
  type RefreshSubscriptionTarget,
  type VerificationSession,
} from '../lib/authsUtils';

export function useAuthsPageController() {
  const pageSize = 100;
  const [siteFilter, setSiteFilter] = useState('');
  const [stateFilter, setStateFilter] = useState<AuthStateFilter>('enabled');
  const [identifierSearch, setIdentifierSearch] = useState('');
  const [sortBy, setSortBy] = useState('created_at');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');
  const [testingAuth, setTestingAuth] = useState<AuthCredential | null>(null);
  const [editingAuth, setEditingAuth] = useState<AuthCredential | null>(null);
  const [verifyingAuth, setVerifyingAuth] = useState<VerificationSession | null>(null);
  const [identityVerifyingAuth, setIdentityVerifyingAuth] =
    useState<VerificationSession | null>(null);
  const [showAddCurlModal, setShowAddCurlModal] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);
  const [refreshingAuthRecordId, setRefreshingAuthRecordId] = useState<number | null>(null);
  const [scrapingPaidContentAuthId, setScrapingPaidContentAuthId] =
    useState<number | null>(null);
  const loadMoreSentinelRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const parsedUserId = useMemo(
    () => (identifierSearch ? parseInt(identifierSearch, 10) : undefined),
    [identifierSearch],
  );
  const validUserId =
    parsedUserId !== undefined && !Number.isNaN(parsedUserId) ? parsedUserId : undefined;
  const usernameSearch = validUserId === undefined ? identifierSearch.trim() : undefined;

  const {
    data,
    isLoading,
    error,
    refetch,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ['auths', siteFilter, stateFilter, usernameSearch, validUserId],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => {
      let activeFlag: boolean | undefined;
      if (stateFilter === 'enabled') {
        activeFlag = true;
      } else if (stateFilter === 'disabled') {
        activeFlag = false;
      }
      return getAuthList(
        siteFilter || undefined,
        activeFlag,
        usernameSearch || undefined,
        validUserId,
        pageSize,
        typeof pageParam === 'number' ? pageParam : 0,
      );
    },
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((sum, page) => sum + page.auths.length, 0);
      return loaded < lastPage.total ? loaded : undefined;
    },
  });

  const authPages = useMemo(() => data?.pages ?? [], [data?.pages]);
  const auths = useMemo(
    () => authPages.flatMap((page) => page.auths),
    [authPages],
  );
  const totalAuths = authPages[0]?.total ?? 0;
  const filteredAuths = useMemo(
    () => auths.filter((auth) => matchesStateFilter(auth, stateFilter)),
    [auths, stateFilter],
  );
  const loadedEnabledCount = filteredAuths.filter((auth) => auth.active).length;
  const loadedDisabledCount = filteredAuths.length - loadedEnabledCount;
  const apiError = authPages.find((page) => !page.success)?.error;
  const sortedAuths = useMemo(() => {
    return [...filteredAuths].sort((a, b) => {
      const direction = sortOrder === 'asc' ? 1 : -1;

      if (sortBy === 'username') {
        return (a.username || '').localeCompare(b.username || '') * direction;
      }
      if (sortBy === 'user_id') {
        return (a.user_id - b.user_id) * direction;
      }
      if (sortBy === 'status') {
        return a.status.localeCompare(b.status) * direction;
      }
      if (sortBy === 'site') {
        return a.site.localeCompare(b.site) * direction;
      }
      if (sortBy === 'last_tested_at') {
        const aTime = a.last_tested_at ? new Date(a.last_tested_at).getTime() : 0;
        const bTime = b.last_tested_at ? new Date(b.last_tested_at).getTime() : 0;
        return (aTime - bTime) * direction;
      }

      const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
      const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;
      return (aTime - bTime) * direction;
    });
  }, [filteredAuths, sortBy, sortOrder]);

  useEffect(() => {
    const sentinel = loadMoreSentinelRef.current;
    if (!sentinel) {
      return;
    }

    const scrollContainer = document.querySelector('.main-content');
    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry && entry.isIntersecting && hasNextPage && !isFetchingNextPage) {
          void fetchNextPage();
        }
      },
      {
        root: scrollContainer,
        rootMargin: '350px',
        threshold: 0,
      },
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  const invalidateAuths = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['auths'] });
  }, [queryClient]);

  const toggleMutation = useMutation({
    mutationFn: ({ id, site, active }: { id: number; site: string; active: boolean }) =>
      toggleAuthStatus(id, site, active),
    onSuccess: () => {
      invalidateAuths();
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      site,
      data,
    }: {
      id: number;
      site: string;
      data: AuthEditRequest;
    }) => updateAuth(id, site, data),
    onSuccess: () => {
      invalidateAuths();
      setEditingAuth(null);
    },
  });

  const refreshSubscriptionsMutation = useMutation({
    mutationFn: async (targets: RefreshSubscriptionTarget[]) => {
      const results = await Promise.allSettled(
        targets.map(({ site, authRecordId, accountUserId }) => {
          const task: TaskPayload = {
            task_type: 'refresh_subscriptions',
            params: {
              site: site === 'fansly' ? 'Fansly' : 'OnlyFans',
              ...(authRecordId !== undefined ? { auth_id: authRecordId } : {}),
            },
          };

          const request: CreateJobRequest = {
            job_name:
              authRecordId !== undefined
                ? `Refresh Subscriptions (${site} #${accountUserId ?? authRecordId})`
                : `Refresh Subscriptions (${site})`,
            tasks: [task],
            created_by: 'webui',
          };

          return createJob(request);
        }),
      );

      const fulfilled = results.filter(
        (result): result is PromiseFulfilledResult<Job> => result.status === 'fulfilled',
      );
      const rejected = results.filter(
        (result): result is PromiseRejectedResult => result.status === 'rejected',
      );

      return { fulfilled, rejected };
    },
    onSuccess: ({ fulfilled, rejected }) => {
      const parts: string[] = [];
      if (fulfilled.length > 0) {
        parts.push(`Queued ${fulfilled.length} subscription refresh job(s).`);
      }
      if (rejected.length > 0) {
        const reasons = rejected.map((result) => {
          const resultError = result.reason;
          if (resultError?.response?.data?.detail) {
            return resultError.response.data.detail;
          }
          if (resultError instanceof Error) {
            return resultError.message;
          }
          return 'Unknown error';
        });
        parts.push(`${rejected.length} site(s) skipped: ${reasons.join('; ')}`);
      }
      setRefreshMessage(parts.join(' '));
    },
    onError: (mutationError) => {
      setRefreshMessage(
        mutationError instanceof Error
          ? mutationError.message
          : 'Failed to update subscriptions.',
      );
    },
  });

  const batchActiveMutation = useMutation({
    mutationFn: async ({ targets, active }: { targets: AuthCredential[]; active: boolean }) => {
      const changing = targets.filter((auth) => auth.active !== active);
      const results = await Promise.allSettled(
        changing.map((auth) => toggleAuthStatus(auth.id, auth.site, active)),
      );
      return {
        changed: results.filter((result) => result.status === 'fulfilled').length,
        failed: results.filter((result) => result.status === 'rejected').length,
        active,
      };
    },
    onSuccess: ({ changed, failed, active }) => {
      const parts = [`${active ? 'Enabled' : 'Disabled'} ${changed} account(s).`];
      if (failed > 0) {
        parts.push(`${failed} could not be changed.`);
      }
      setRefreshMessage(parts.join(' '));
      invalidateAuths();
    },
  });

  const batchTestMutation = useMutation({
    mutationFn: async (targets: AuthCredential[]) => {
      let valid = 0;
      let failed = 0;
      // One at a time, so a large selection doesn't hit the site all at once.
      for (const auth of targets) {
        try {
          const result = await testAuth(auth.id, auth.site);
          if (result.success) {
            valid += 1;
          } else {
            failed += 1;
          }
        } catch {
          failed += 1;
        }
      }
      return { valid, failed };
    },
    onSuccess: ({ valid, failed }) => {
      setRefreshMessage(`Tested ${valid + failed} account(s): ${valid} valid, ${failed} failed.`);
      invalidateAuths();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: ({ id, site }: { id: number; site: string }) => deleteAuth(id, site),
    onSuccess: () => {
      invalidateAuths();
    },
  });

  const scrapePaidContentMutation = useMutation({
    mutationFn: async ({ site, authId }: { site: string; authId: number }) => {
      const task: TaskPayload = {
        task_type: 'scrape_paid_content',
        params: {
          site: site === 'fansly' ? 'Fansly' : 'OnlyFans',
          auth_id: authId,
        },
      };

      const request: CreateJobRequest = {
        job_name: `Scrape Paid Content (${site} #${authId})`,
        tasks: [task],
        created_by: 'webui',
      };

      return createJob(request);
    },
    onSuccess: (_job, variables) => {
      setRefreshMessage(
        `Queued paid content scrape for ${variables.site} auth #${variables.authId}.`,
      );
    },
    onError: (mutationError) => {
      setRefreshMessage(
        mutationError instanceof Error
          ? mutationError.message
          : 'Failed to queue paid content scrape.',
      );
    },
  });

  const handleToggle = (auth: AuthCredential) => {
    toggleMutation.mutate({ id: auth.id, site: auth.site, active: !auth.active });
  };

  const handleSaveEdit = (data: AuthEditRequest) => {
    if (!editingAuth) {
      return;
    }
    updateMutation.mutate({ id: editingAuth.id, site: editingAuth.site, data });
  };

  const handleDelete = (auth: AuthCredential) => {
    deleteMutation.mutate({ id: auth.id, site: auth.site });
  };

  const handleBatchSetActive = (targets: AuthCredential[], active: boolean) => {
    setRefreshMessage(null);
    batchActiveMutation.mutate({ targets, active });
  };

  const handleBatchTest = (targets: AuthCredential[]) => {
    setRefreshMessage(null);
    batchTestMutation.mutate(targets);
  };

  const handleUpdateSubscriptionsForAuth = (auth: AuthCredential) => {
    setRefreshMessage(null);
    setRefreshingAuthRecordId(auth.id);
    refreshSubscriptionsMutation.mutate(
      [
        {
          site: auth.site.toLowerCase(),
          authRecordId: auth.id,
          accountUserId: auth.user_id,
        },
      ],
      {
        onSettled: () => {
          setRefreshingAuthRecordId(null);
        },
      },
    );
  };

  const handleUpdateSubscriptions = () => {
    const targets = (siteFilter ? [siteFilter] : ['onlyfans', 'fansly']).map((site) => ({
      site,
    }));
    setRefreshMessage(null);
    refreshSubscriptionsMutation.mutate(targets);
  };

  const handleScrapePaidContentForAuth = (auth: AuthCredential) => {
    setRefreshMessage(null);
    setScrapingPaidContentAuthId(auth.user_id);
    scrapePaidContentMutation.mutate(
      { site: auth.site.toLowerCase(), authId: auth.user_id },
      {
        onSettled: () => {
          setScrapingPaidContentAuthId(null);
        },
      },
    );
  };

  const openAgeVerification = (auth: AuthCredential) => {
    setVerifyingAuth({
      auth,
      requestKey: createVerificationRequestKey(),
    });
  };

  const openIdentityVerification = (auth: AuthCredential) => {
    setIdentityVerifyingAuth({
      auth,
      requestKey: createVerificationRequestKey(),
    });
  };

  return {
    siteFilter,
    setSiteFilter,
    stateFilter,
    setStateFilter,
    identifierSearch,
    setIdentifierSearch,
    sortBy,
    setSortBy,
    sortOrder,
    setSortOrder,
    testingAuth,
    setTestingAuth,
    editingAuth,
    setEditingAuth,
    verifyingAuth,
    setVerifyingAuth,
    identityVerifyingAuth,
    setIdentityVerifyingAuth,
    showAddCurlModal,
    setShowAddCurlModal,
    refreshMessage,
    refreshingAuthRecordId,
    scrapingPaidContentAuthId,
    loadMoreSentinelRef,
    invalidateAuths,
    isLoading,
    error,
    refetch,
    hasNextPage,
    isFetchingNextPage,
    apiError,
    filteredAuths,
    totalAuths,
    loadedEnabledCount,
    loadedDisabledCount,
    sortedAuths,
    toggleMutation,
    updateMutation,
    refreshSubscriptionsMutation,
    scrapePaidContentMutation,
    deleteMutation,
    batchActiveMutation,
    batchTestMutation,
    handleToggle,
    handleBatchSetActive,
    handleBatchTest,
    handleSaveEdit,
    handleDelete,
    handleUpdateSubscriptionsForAuth,
    handleUpdateSubscriptions,
    handleScrapePaidContentForAuth,
    openAgeVerification,
    openIdentityVerification,
  };
}
