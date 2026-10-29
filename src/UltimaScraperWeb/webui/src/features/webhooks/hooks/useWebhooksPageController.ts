import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  getWatchList,
  getWatchStats,
  getWebhooks,
  pauseWatches,
  resumeWatches,
} from '../../../api/webhooks';
import { addToWatchList, browseUsers, removeFromWatchList } from '../../../api/users';
import { useWebhookStream } from '../../../hooks/useWebhookStream';
import {
  filterWebhookMessages,
  type CategoryFilter,
} from '../lib/webhooksUtils';

type WebhooksTab = 'overview' | 'config' | 'messages' | 'watchlist';

export function useWebhooksPageController(initialTab: WebhooksTab = 'config') {
  const [activeTab, setActiveTab] = useState<WebhooksTab>(initialTab);
  const [filterText, setFilterText] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<CategoryFilter>('all');
  const [showAllEvents, setShowAllEvents] = useState(false);
  const [watchSiteFilter, setWatchSiteFilter] = useState<string | undefined>(undefined);
  const [watchSearch, setWatchSearch] = useState('');
  const [watchLimit, setWatchLimit] = useState(50);
  const [addSearch, setAddSearch] = useState('');
  const [addSite, setAddSite] = useState('onlyfans');
  const queryClient = useQueryClient();

  const { messages, isConnected, lastActivity, clearMessages } = useWebhookStream();

  const webhooksQuery = useQuery({
    queryKey: ['webhooks'],
    queryFn: getWebhooks,
  });

  const watchListQuery = useQuery({
    queryKey: ['watchList', watchSiteFilter, watchSearch, watchLimit],
    queryFn: async () => {
      // The API caps each site's page at 500; larger rosters need offsets.
      const users = [];
      let total = 0;
      for (let offset = 0; offset < watchLimit; offset += 500) {
        const limit = Math.min(500, watchLimit - offset);
        const page = offset === 0
          ? await getWatchList(watchSiteFilter, watchSearch || undefined, limit)
          : await getWatchList(watchSiteFilter, watchSearch || undefined, limit, offset);
        users.push(...page.users);
        total = page.total;
        if (!page.users.length || users.length >= total) break;
      }
      return { users, total };
    },
    enabled: activeTab === 'watchlist',
  });

  const overviewWatchQuery = useQuery({
    queryKey: ['watchList', 'overview'],
    queryFn: () => getWatchList(undefined, undefined, 5),
    enabled: activeTab === 'overview',
  });

  const watchStatsQuery = useQuery({
    queryKey: ['watchStats'],
    queryFn: getWatchStats,
  });

  const userSearchQuery = useQuery({
    queryKey: ['userSearch', addSearch, addSite],
    queryFn: () => browseUsers(addSite, addSearch, false, false, 1, 10),
    enabled: addSearch.trim().length >= 2 && activeTab === 'watchlist',
  });

  const addToWatchMutation = useMutation({
    mutationFn: ({ userId, site }: { userId: number; site: string }) => addToWatchList(userId, site),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchList'] });
      queryClient.invalidateQueries({ queryKey: ['watchStats'] });
    },
  });

  const removeFromWatchMutation = useMutation({
    mutationFn: ({ userId, site }: { userId: number; site: string }) =>
      removeFromWatchList(userId, site),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchList'] });
      queryClient.invalidateQueries({ queryKey: ['watchStats'] });
    },
  });

  const pauseWatchesMutation = useMutation({
    mutationFn: pauseWatches,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchStats'] });
    },
  });

  const resumeWatchesMutation = useMutation({
    mutationFn: resumeWatches,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['watchStats'] });
    },
  });

  const categoryCounts = useMemo(() => {
    const counts: Record<CategoryFilter, number> = {
      all: messages.length,
      backend: 0,
      usapi: 0,
      system: 0,
    };
    for (const message of messages) {
      counts[message.category]++;
    }
    return counts;
  }, [messages]);

  const filteredMessages = useMemo(
    () => filterWebhookMessages(messages, categoryFilter, showAllEvents, filterText),
    [categoryFilter, filterText, messages, showAllEvents],
  );

  return {
    activeTab,
    addSearch,
    addSite,
    addToWatchMutation,
    categoryCounts,
    categoryFilter,
    clearMessages,
    filteredMessages,
    filterText,
    isConnected,
    lastActivity,
    messages,
    overviewWatchQuery,
    pauseWatchesMutation,
    removeFromWatchMutation,
    resumeWatchesMutation,
    setActiveTab,
    setAddSearch,
    setAddSite,
    setCategoryFilter,
    setFilterText,
    setShowAllEvents,
    setWatchSiteFilter,
    setWatchSearch,
    setWatchLimit,
    showAllEvents,
    watchListQuery,
    watchSiteFilter,
    watchSearch,
    watchLimit,
    watchStatsQuery,
    webhooksQuery,
    userSearchQuery,
  };
}
