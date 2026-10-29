import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  addProxy,
  analyzeProxyLevel,
  assignProxy,
  bulkAddProxies,
  bulkAssignGroup,
  bulkDeleteProxies,
  bulkEditProxies,
  bulkSyncProxies,
  bulkTestProxies,
  bulkUpdateProxyState,
  deleteProxy,
  getProxyAuths,
  getProxyGeolocation,
  getProxyMediaPool,
  listProxies,
  testProxy,
  updateGroupSettings,
  updateProxy,
  updateProxySettings,
} from '../../../api/network';
import {
  DIRECT_CONNECTION_PROXY,
  type AnalyzerErrorDetail,
  type AnalyzerTab,
  type AuthAccount,
  type BulkProxyItem,
  type BulkSyncProxiesRequest,
  type BulkTestItem,
  type BulkTestItemResult,
  type GeolocationData,
  type NetworkProxy,
  type ProxyAnalyzerResponse,
  type ProxyAnalyzerResult,
  type ProxyTestStatus,
} from '../../../api/types/network';

export function useNetworkPageController() {
  const queryClient = useQueryClient();
  const invalidateMpsProxyPreview = () => {
    void queryClient.invalidateQueries({ queryKey: ['mps-proxy-preview'] });
  };
  const proxyRouteSettingsChanged = (
    proxyUrl: string,
    next: { enabled?: boolean; max_connections?: number | null },
  ) => {
    const hasRouteSettings = next.enabled !== undefined || next.max_connections != null;
    if (!hasRouteSettings) return false;

    const currentProxies = queryClient.getQueryData<NetworkProxy[]>(['proxies']);
    if (!currentProxies) return true;

    const currentProxy = currentProxies.find((proxy) => proxy.url === proxyUrl);
    if (!currentProxy) return true;

    return (
      (next.enabled !== undefined && (currentProxy.enabled ?? true) !== next.enabled) ||
      (next.max_connections != null && currentProxy.max_connections !== next.max_connections)
    );
  };
  const anyProxyRouteSettingsChanged = (
    proxyUrls: string[],
    next: { enabled?: boolean; max_connections?: number | null },
  ) => proxyUrls.some((proxyUrl) => proxyRouteSettingsChanged(proxyUrl, next));
  const [expandedProxy, setExpandedProxy] = useState<string | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingProxy, setEditingProxy] = useState<NetworkProxy | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [newProxyUrl, setNewProxyUrl] = useState('');
  const [newProxyUsername, setNewProxyUsername] = useState('');
  const [newProxyPassword, setNewProxyPassword] = useState('');
  const [newProxyGroup, setNewProxyGroup] = useState('');
  const [newProxyMaxConnections, setNewProxyMaxConnections] = useState(-1);
  const [newProxyGuestLookupTimeout, setNewProxyGuestLookupTimeout] = useState<number | null>(null);
  const [showBulkModal, setShowBulkModal] = useState(false);
  const [bulkModalMode, setBulkModalMode] = useState<'import' | 'edit'>('import');
  const [showBulkEditModal, setShowBulkEditModal] = useState(false);
  const [selectedGroupFilter, setSelectedGroupFilter] = useState<string | null>(null);
  const [selectedProxyIds, setSelectedProxyIds] = useState<Set<string>>(new Set());
  const [showAnalyzerModal, setShowAnalyzerModal] = useState(false);
  const [activeAnalyzerProxy, setActiveAnalyzerProxy] = useState<NetworkProxy | null>(null);
  const [analyzerModalTab, setAnalyzerModalTab] = useState<AnalyzerTab>('settings');
  const [analyzerProgress, setAnalyzerProgress] = useState('');
  const [analyzerRequestCount, setAnalyzerRequestCount] = useState(256);
  const [useLiveCdn, setUseLiveCdn] = useState(true);
  const [mediaPoolUrls, setMediaPoolUrls] = useState<string[]>([]);
  const [mediaPoolLoading, setMediaPoolLoading] = useState(false);
  const [mediaPoolError, setMediaPoolError] = useState<string | null>(null);
  const [geoLoading, setGeoLoading] = useState(false);
  const [geoError, setGeoError] = useState<string | null>(null);
  const [compareSelection, setCompareSelection] = useState<string[]>([]);
  const [formError, setFormError] = useState<string | null>(null);
  const [testStatus, setTestStatus] = useState<ProxyTestStatus>('idle');
  const [testMessage, setTestMessage] = useState<string | null>(null);
  const [testLatencyMs, setTestLatencyMs] = useState<number | null>(null);
  const [analyzerLoading, setAnalyzerLoading] = useState<Record<string, boolean>>({});
  const [analyzerResults, setAnalyzerResults] = useState<
    Record<string, ProxyAnalyzerResponse | null>
  >({});
  const [analyzerErrors, setAnalyzerErrors] = useState<Record<string, string | null>>({});
  const [proxyStatePending, setProxyStatePending] = useState<Record<string, boolean>>({});
  const [proxyStateErrors, setProxyStateErrors] = useState<Record<string, string | null>>({});
  const [expandedConcurrency, setExpandedConcurrency] = useState<number | null>(null);
  const [errorDetailModal, setErrorDetailModal] = useState<AnalyzerErrorDetail | null>(null);
  const [applySettingsPending, setApplySettingsPending] = useState(false);
  const [applySettingsNotice, setApplySettingsNotice] = useState<{
    tone: 'success' | 'danger';
    title: string;
    detail: string;
  } | null>(null);
  const [isBulkTesting, setIsBulkTesting] = useState(false);
  const [proxyQuickTestResults, setProxyQuickTestResults] = useState<
    Record<string, { testing?: boolean; success?: boolean; latency_ms?: number | null; message: string }>
  >({});
  const analyzerAbortControllerRef = useRef<AbortController | null>(null);

  const {
    data: proxies = [],
    isLoading,
    isError,
    error,
  } = useQuery<NetworkProxy[]>({
    queryKey: ['proxies'],
    queryFn: listProxies,
    refetchInterval: 5000,
  });

  const { data: proxyAuths, isLoading: isProxyAuthsLoading } = useQuery<AuthAccount[]>({
    queryKey: ['proxy-auths', expandedProxy],
    queryFn: () => (expandedProxy ? getProxyAuths(expandedProxy) : Promise.resolve([])),
    enabled: Boolean(expandedProxy),
  });

  const existingGroups = useMemo(() => {
    const groups = new Set<string>();
    for (const p of proxies) {
      if (p.group && p.group.trim()) {
        groups.add(p.group.trim());
      }
    }
    return Array.from(groups).sort();
  }, [proxies]);

  const resetProxyFormState = () => {
    setNewProxyUrl('');
    setNewProxyUsername('');
    setNewProxyPassword('');
    setNewProxyGroup('');
    setNewProxyMaxConnections(-1);
    setNewProxyGuestLookupTimeout(null);
    setFormError(null);
    setTestStatus('idle');
    setTestMessage(null);
    setTestLatencyMs(null);
  };

  const updateCachedProxyGeolocation = (proxyMatcher: (proxy: NetworkProxy) => boolean, geolocation: GeolocationData) => {
    queryClient.setQueryData<NetworkProxy[]>(['proxies'], (existingProxies) =>
      existingProxies?.map((proxy) =>
        proxyMatcher(proxy) ? { ...proxy, geolocation } : proxy
      ),
    );
  };

  const fetchProxyGeolocation = async (proxyUrl: string) => {
    try {
      const geolocation = await getProxyGeolocation(proxyUrl);
      updateCachedProxyGeolocation((proxy) => proxy.url === proxyUrl, geolocation);
    } catch {
      // Geolocation is best-effort after save or connectivity testing.
    }
  };

  const refreshProxyGeolocations = (proxyUrls: string[]) => {
    const uniqueProxyUrls = Array.from(new Set(proxyUrls.filter(Boolean)));
    void Promise.allSettled(uniqueProxyUrls.map((proxyUrl) => fetchProxyGeolocation(proxyUrl)));
  };

  const addProxyMutation = useMutation({
    mutationFn: addProxy,
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: ['proxies'] });
    },
    onSuccess: (proxy) => {
      queryClient.setQueryData<NetworkProxy[]>(['proxies'], (existingProxies = []) => {
        const withoutStaleCopy = existingProxies.filter(
          (existingProxy) => existingProxy.id !== proxy.id && existingProxy.url !== proxy.url,
        );
        return [...withoutStaleCopy, proxy];
      });
      void queryClient.invalidateQueries({ queryKey: ['proxies'] });
      invalidateMpsProxyPreview();
      void fetchProxyGeolocation(proxy.url);
      closeProxyFormModal();
    },
    onError: (mutationError: Error) => {
      setFormError(mutationError.message);
    },
  });

  const editProxyMutation = useMutation({
    mutationFn: ({ proxyUrl, data }: { proxyUrl: string; data: Parameters<typeof updateProxy>[1] }) =>
      updateProxy(proxyUrl, data),
    onSuccess: (_result, variables) => {
      queryClient.invalidateQueries({ queryKey: ['proxies'] });
      if (proxyRouteSettingsChanged(variables.proxyUrl, variables.data)) {
        invalidateMpsProxyPreview();
      }
      void fetchProxyGeolocation(variables.proxyUrl);
      closeProxyFormModal();
    },
    onError: (mutationError: Error) => {
      setFormError(mutationError.message);
    },
  });

  const proxyStateMutation = useMutation({
    mutationFn: ({ proxyUrl, enabled }: { proxyUrl: string; enabled: boolean }) =>
      updateProxy(proxyUrl, { enabled }),
    onMutate: ({ proxyUrl }) => {
      setProxyStatePending((current) => ({ ...current, [proxyUrl]: true }));
      setProxyStateErrors((current) => ({ ...current, [proxyUrl]: null }));
    },
    onSuccess: (_result, { proxyUrl, enabled }) => {
      const routesChanged = proxyRouteSettingsChanged(proxyUrl, { enabled });
      queryClient.setQueryData<NetworkProxy[]>(['proxies'], (existingProxies) =>
        existingProxies?.map((proxy) =>
          proxy.url === proxyUrl ? { ...proxy, enabled } : proxy
        ),
      );
      void queryClient.invalidateQueries({ queryKey: ['proxies'] });
      if (routesChanged) invalidateMpsProxyPreview();
    },
    onError: (mutationError: Error, { proxyUrl }) => {
      setProxyStateErrors((current) => ({
        ...current,
        [proxyUrl]: mutationError.message,
      }));
    },
    onSettled: (_result, _error, { proxyUrl }) => {
      setProxyStatePending((current) => ({ ...current, [proxyUrl]: false }));
    },
  });

  const deleteProxyMutation = useMutation({
    mutationFn: deleteProxy,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proxies'] });
      invalidateMpsProxyPreview();
    },
  });

  const assignProxyMutation = useMutation({
    mutationFn: assignProxy,
    onSuccess: (_result, variables) => {
      const currentProxies = queryClient.getQueryData<NetworkProxy[]>(['proxies']);
      const previousProxyUrl = currentProxies?.find((proxy) =>
        proxy.assigned_auths.includes(variables.auth_id),
      )?.url ?? null;
      queryClient.invalidateQueries({ queryKey: ['proxies'] });
      queryClient.invalidateQueries({ queryKey: ['proxy-auths'] });
      queryClient.invalidateQueries({ queryKey: ['auths'] });
      if (!currentProxies || previousProxyUrl !== variables.proxy_url) {
        invalidateMpsProxyPreview();
      }
    },
  });

  const testProxyMutation = useMutation({
    mutationFn: () =>
      testProxy({
        url: newProxyUrl.trim(),
        username: newProxyUsername.trim() || undefined,
        password: newProxyPassword || undefined,
      }),
    onMutate: () => {
      setTestStatus('testing');
      setTestMessage(null);
      setTestLatencyMs(null);
    },
    onSuccess: (result) => {
      setTestStatus(result.success ? 'success' : 'error');
      setTestMessage(result.message);
      setTestLatencyMs(result.latency_ms ?? null);
    },
    onError: (mutationError: Error) => {
      setTestStatus('error');
      setTestMessage(mutationError.message);
    },
    onSettled: () => {
      refreshProxyGeolocations([newProxyUrl.trim()]);
    },
  });

  const closeProxyFormModal = () => {
    setShowAddModal(false);
    setEditingProxy(null);
    resetProxyFormState();
  };

  const openAddModal = () => {
    setEditingProxy(null);
    resetProxyFormState();
    setShowAddModal(true);
  };

  const openEditModal = (proxy: NetworkProxy) => {
    setEditingProxy(proxy);
    setNewProxyUrl(proxy.url);
    setNewProxyUsername(proxy.username || '');
    setNewProxyPassword('');
    setNewProxyGroup(proxy.group || '');
    setNewProxyMaxConnections(proxy.max_connections);
    setNewProxyGuestLookupTimeout(proxy.guest_lookup_timeout ?? null);
    setShowAddModal(true);
    setFormError(null);
    setTestStatus('idle');
    setTestMessage(null);
    setTestLatencyMs(null);
  };

  const openBulkModal = () => {
    setBulkModalMode('import');
    setShowBulkModal(true);
  };

  const openBulkEditProxiesModal = () => {
    setBulkModalMode('edit');
    setShowBulkModal(true);
  };

  const closeBulkModal = () => {
    setShowBulkModal(false);
  };

  useEffect(() => {
    setTestStatus('idle');
    setTestMessage(null);
    setTestLatencyMs(null);
  }, [newProxyGroup, newProxyPassword, newProxyUrl, newProxyUsername]);

  const filteredProxies = useMemo(() => {
    let list = proxies;

    if (selectedGroupFilter) {
      if (selectedGroupFilter === '__ungrouped__') {
        list = list.filter((p) => !p.group?.trim());
      } else {
        list = list.filter((p) => p.group?.trim() === selectedGroupFilter);
      }
    }

    const normalizedQuery = searchQuery.trim().toLowerCase();
    if (!normalizedQuery) {
      return list;
    }
    return list.filter((proxy) => {
      const searchableFields = [
        proxy.url,
        proxy.username,
        proxy.group,
        proxy.enabled === false ? 'disabled' : 'enabled active',
        proxy.geolocation?.ip,
        proxy.geolocation?.city,
        proxy.geolocation?.region,
        proxy.geolocation?.country,
        proxy.geolocation?.country_code,
        proxy.geolocation?.connection?.isp,
        proxy.geolocation?.connection?.org,
      ];
      return searchableFields.some((value) => value?.toLowerCase().includes(normalizedQuery));
    });
  }, [proxies, searchQuery, selectedGroupFilter]);

  const totalAssigned = useMemo(
    () => proxies.reduce((sum, proxy) => sum + proxy.assigned_auths.length, 0),
    [proxies],
  );

  const enabledCount = useMemo(
    () => proxies.filter((proxy) => proxy.enabled !== false).length,
    [proxies],
  );

  const disabledCount = proxies.length - enabledCount;

  const unassignedCount = useMemo(
    () =>
      proxies.filter(
        (proxy) => proxy.enabled !== false && (proxy.active_assigned_count ?? 0) === 0,
      ).length,
    [proxies],
  );

  const handleSaveProxy = () => {
    const trimmedUrl = newProxyUrl.trim();
    if (!trimmedUrl) {
      setFormError('Proxy URL is required.');
      return;
    }

    setFormError(null);

    if (editingProxy) {
      editProxyMutation.mutate({
        proxyUrl: editingProxy.url,
        data: {
          username: newProxyUsername.trim() || '',
          password: newProxyPassword || undefined,
          max_connections: newProxyMaxConnections,
          group: newProxyGroup.trim() || null,
          guest_lookup_timeout: newProxyGuestLookupTimeout,
        },
      });
      return;
    }

    addProxyMutation.mutate({
      url: trimmedUrl,
      username: newProxyUsername.trim() || undefined,
      password: newProxyPassword || undefined,
      max_connections: newProxyMaxConnections,
      group: newProxyGroup.trim() || undefined,
      guest_lookup_timeout: newProxyGuestLookupTimeout,
    });
  };

  const openAnalyzerModal = (proxy: NetworkProxy) => {
    setActiveAnalyzerProxy(proxy);
    setShowAnalyzerModal(true);
    setExpandedConcurrency(null);
    setCompareSelection([]);

    setAnalyzerModalTab('settings');

    if (!analyzerLoading[proxy.id]) {
      setAnalyzerProgress('');
    }
    setApplySettingsNotice(null);
  };

  const fetchMediaPool = async () => {
    setMediaPoolLoading(true);
    setMediaPoolError(null);
    try {
      const response = await getProxyMediaPool();
      if (response.success) {
        setMediaPoolUrls(response.urls);
      } else {
        setMediaPoolError(response.message || 'No videos found');
      }
    } catch (fetchError) {
      setMediaPoolError(
        fetchError instanceof Error ? fetchError.message : 'Failed to fetch media pool',
      );
    } finally {
      setMediaPoolLoading(false);
    }
  };

  const fetchGeolocation = async () => {
    if (!activeAnalyzerProxy) {
      return;
    }

    setGeoLoading(true);
    setGeoError(null);

    try {
      const proxyUrl =
        activeAnalyzerProxy.id === DIRECT_CONNECTION_PROXY.id
          ? 'direct'
          : activeAnalyzerProxy.url;
      const geolocation = await getProxyGeolocation(proxyUrl);
      const targetProxyId = activeAnalyzerProxy.id;

      setActiveAnalyzerProxy((previousProxy) =>
        previousProxy ? { ...previousProxy, geolocation } : previousProxy,
      );
      updateCachedProxyGeolocation((proxy) => proxy.id === targetProxyId, geolocation);
    } catch (fetchError) {
      setGeoError(
        fetchError instanceof Error ? fetchError.message : 'Failed to fetch geolocation',
      );
    } finally {
      setGeoLoading(false);
    }
  };

  const stopAnalysis = () => {
    if (analyzerAbortControllerRef.current) {
      analyzerAbortControllerRef.current.abort();
      analyzerAbortControllerRef.current = null;
    }
  };

  const startAnalysis = async () => {
    const proxy = activeAnalyzerProxy;
    if (!proxy) {
      return;
    }

    const abortController = new AbortController();
    analyzerAbortControllerRef.current = abortController;

    setAnalyzerModalTab('results');
    setAnalyzerProgress('');
    setAnalyzerResults((previousResults) => ({ ...previousResults, [proxy.id]: null }));
    setAnalyzerLoading((previousLoading) => ({ ...previousLoading, [proxy.id]: true }));
    setAnalyzerErrors((previousErrors) => ({ ...previousErrors, [proxy.id]: null }));
    setExpandedConcurrency(null);
    setCompareSelection([]);

    const collectedResults: ProxyAnalyzerResult[] = [];
    let recommendedConcurrency: number | null = null;
    let recommendedConnections: number | null = null;
    let bestEfficiency = 0;

    const testLevel = async (level: number): Promise<boolean> => {
      if (abortController.signal.aborted) {
        throw new DOMException('Aborted', 'AbortError');
      }

      return analyzeProxyLevel({
        proxy,
        concurrencyLevel: level,
        requestCount: analyzerRequestCount,
        useLiveCdn,
        signal: abortController.signal,
        onWarmup: (ip) => {
          setAnalyzerProgress(`Warmup complete (IP: ${ip || 'unknown'})`);
        },
        onProgress: (event) => {
          setAnalyzerProgress(
            `analyzing x${event.concurrency} concurrency - ${event.connections} connections - ${event.requests} requests`,
          );
        },
        onResult: (result) => {
          collectedResults.push(result);

          setAnalyzerResults((previousResults) => ({
            ...previousResults,
            [proxy.id]: {
              success: true,
              message: 'In progress...',
              results: [...collectedResults].sort(
                (left, right) =>
                  left.concurrency - right.concurrency ||
                  left.max_connections - right.max_connections,
              ),
              recommended_concurrency: recommendedConcurrency,
              recommended_connections: recommendedConnections,
              best_configs: {},
              warmup_ip: null,
              warmup_latency_ms: null,
            },
          }));

          const successRate = result.successes / result.requests;
          if (successRate >= 0.95 && result.efficiency_score > bestEfficiency) {
            bestEfficiency = result.efficiency_score;
            recommendedConcurrency = result.concurrency;
            recommendedConnections = result.max_connections;
          }
        },
        onComplete: (event) => {
          if (event.recommended_concurrency) {
            recommendedConcurrency = event.recommended_concurrency;
          }
          if (event.recommended_connections) {
            recommendedConnections = event.recommended_connections;
          }
        },
      });
    };

    try {
      const startLevel = 32;
      const minLevel = 1;
      const maxLevel = 1024;
      const testedLevels = new Set<number>();
      const efficiencyMap = new Map<number, number>();

      const testAndGetEfficiency = async (level: number): Promise<number | null> => {
        if (testedLevels.has(level) || level < minLevel || level > maxLevel) {
          return efficiencyMap.get(level) ?? null;
        }

        testedLevels.add(level);

        const hadResults = await testLevel(level);
        if (!hadResults) {
          return null;
        }

        const levelResults = collectedResults.filter((result) => result.concurrency === level);
        const bestLevelResult = levelResults.reduce((best, current) => {
          const currentSuccessRate = current.successes / current.requests;
          if (currentSuccessRate >= 0.95 && current.efficiency_score > best.efficiency_score) {
            return current;
          }
          return best;
        }, levelResults[0]);

        if (!bestLevelResult) {
          return null;
        }

        const successRate = bestLevelResult.successes / bestLevelResult.requests;
        if (successRate < 0.95) {
          setAnalyzerProgress(
            `⚠️ x${level} has errors (${Math.round(successRate * 100)}% success)`,
          );
          return null;
        }

        efficiencyMap.set(level, bestLevelResult.efficiency_score);
        return bestLevelResult.efficiency_score;
      };

      const baselineEfficiency = await testAndGetEfficiency(startLevel);
      const upEfficiency = await testAndGetEfficiency(startLevel * 2);
      const downEfficiency = await testAndGetEfficiency(startLevel / 2);

      const baseline = baselineEfficiency ?? 0;
      const up = upEfficiency ?? 0;
      const down = downEfficiency ?? 0;

      let bestLevel = startLevel;
      let bestLevelEfficiency = baseline;

      if (up > bestLevelEfficiency) {
        bestLevel = startLevel * 2;
        bestLevelEfficiency = up;
      }

      if (down > bestLevelEfficiency) {
        bestLevel = startLevel / 2;
        bestLevelEfficiency = down;
      }

      if (bestLevel > startLevel) {
        let currentLevel = bestLevel * 2;
        let previousEfficiency = bestLevelEfficiency;

        while (currentLevel <= maxLevel) {
          const efficiency = await testAndGetEfficiency(currentLevel);
          if (efficiency === null || efficiency < previousEfficiency) {
            break;
          }
          previousEfficiency = efficiency;
          currentLevel *= 2;
        }
      } else if (bestLevel < startLevel) {
        let currentLevel = Math.floor(bestLevel / 2);
        let previousEfficiency = bestLevelEfficiency;

        while (currentLevel >= minLevel) {
          const efficiency = await testAndGetEfficiency(currentLevel);
          if (efficiency === null || efficiency < previousEfficiency) {
            break;
          }
          previousEfficiency = efficiency;
          currentLevel = Math.floor(currentLevel / 2);
        }
      }

      bestEfficiency = 0;
      recommendedConcurrency = null;
      recommendedConnections = null;

      for (const result of collectedResults) {
        const successRate = result.successes / result.requests;
        if (successRate >= 0.95 && result.efficiency_score > bestEfficiency) {
          bestEfficiency = result.efficiency_score;
          recommendedConcurrency = result.concurrency;
          recommendedConnections = result.max_connections;
        }
      }

      setAnalyzerProgress('✓ Analysis complete!');
      setAnalyzerResults((previousResults) => ({
        ...previousResults,
        [proxy.id]: {
          success: true,
          message: 'Performance analysis complete',
          results: collectedResults.sort(
            (left, right) =>
              left.concurrency - right.concurrency ||
              left.max_connections - right.max_connections,
          ),
          recommended_concurrency: recommendedConcurrency,
          recommended_connections: recommendedConnections,
          best_configs: {},
          warmup_ip: null,
          warmup_latency_ms: null,
        },
      }));
      setAnalyzerModalTab('settings');
    } catch (analysisError) {
      if (analysisError instanceof DOMException && analysisError.name === 'AbortError') {
        setAnalyzerProgress('⏹ Analysis stopped');
        if (collectedResults.length > 0) {
          setAnalyzerResults((previousResults) => ({
            ...previousResults,
            [proxy.id]: {
              success: true,
              message: 'Performance analysis stopped',
              results: collectedResults.sort(
                (left, right) =>
                  left.concurrency - right.concurrency ||
                  left.max_connections - right.max_connections,
              ),
              recommended_concurrency: recommendedConcurrency,
              recommended_connections: recommendedConnections,
              best_configs: {},
              warmup_ip: null,
              warmup_latency_ms: null,
            },
          }));
        }
      } else {
        setAnalyzerErrors((previousErrors) => ({
          ...previousErrors,
          [proxy.id]:
            analysisError instanceof Error
              ? analysisError.message
              : 'Performance analysis failed',
        }));
        setAnalyzerProgress('✗ Analysis failed');
      }
    } finally {
      setAnalyzerLoading((previousLoading) => ({ ...previousLoading, [proxy.id]: false }));
      analyzerAbortControllerRef.current = null;
    }
  };

  const bulkAddProxiesMutation = useMutation({
    mutationFn: (items: BulkProxyItem[]) => bulkAddProxies({ proxies: items }),
    onSuccess: (data) => {
      const routesChanged =
        data.added.length > 0 ||
        data.updated.some((proxy) =>
          proxyRouteSettingsChanged(proxy.url, {
            enabled: proxy.enabled,
            max_connections: proxy.max_connections,
          }),
        );
      void queryClient.invalidateQueries({ queryKey: ['proxies'] });
      if (routesChanged) invalidateMpsProxyPreview();
      setShowBulkModal(false);
      setApplySettingsNotice({
        tone: 'success',
        title: 'Bulk Import Complete',
        detail: `Added ${data.added.length} routes, updated ${data.updated.length}, skipped ${data.skipped.length}.`,
      });
    },
    onError: (mutationError: Error) => {
      setApplySettingsNotice({
        tone: 'danger',
        title: 'Bulk Import Failed',
        detail: mutationError.message,
      });
    },
  });

  const bulkSyncProxiesMutation = useMutation({
    mutationFn: (request: BulkSyncProxiesRequest) => bulkSyncProxies(request),
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ['proxies'] });
      invalidateMpsProxyPreview();
      setShowBulkModal(false);
      setApplySettingsNotice({
        tone: 'success',
        title: 'Bulk Proxies Edit Complete',
        detail:
          data.message ||
          `Kept ${data.kept.length} existing proxies, added ${data.added.length} new routes, deleted ${data.deleted.length} omitted routes.`,
      });
    },
    onError: (mutationError: Error) => {
      setApplySettingsNotice({
        tone: 'danger',
        title: 'Bulk Edit Failed',
        detail: mutationError.message,
      });
    },
  });

  const bulkAssignGroupMutation = useMutation({
    mutationFn: ({ proxyUrls, group }: { proxyUrls: string[]; group: string | null }) =>
      bulkAssignGroup({ proxy_urls: proxyUrls, group }),
    onSuccess: (data, variables) => {
      if (data.updated_count === 0) {
        setApplySettingsNotice({
          tone: 'danger',
          title: 'No Routes Updated',
          detail: 'The API did not match any selected proxy URLs, so no group name was saved.',
        });
        return;
      }

      const nextGroup = variables.group?.trim() || null;
      queryClient.setQueryData<NetworkProxy[]>(['proxies'], (currentProxies) =>
        currentProxies?.map((proxy) =>
          variables.proxyUrls.includes(proxy.url) ? { ...proxy, group: nextGroup } : proxy,
        ),
      );
      void queryClient.invalidateQueries({ queryKey: ['proxies'] });
      setSelectedProxyIds(new Set());
      setApplySettingsNotice({
        tone: 'success',
        title: 'Group Assignment Updated',
        detail: data.message,
      });
    },
    onError: (mutationError: Error) => {
      setApplySettingsNotice({
        tone: 'danger',
        title: 'Group Assignment Failed',
        detail: mutationError.message,
      });
    },
  });

  const bulkUpdateStateMutation = useMutation({
    mutationFn: ({ proxyUrls, enabled }: { proxyUrls: string[]; enabled: boolean }) =>
      bulkUpdateProxyState({ proxy_urls: proxyUrls, enabled }),
    onSuccess: (data, variables) => {
      const routesChanged =
        data.updated_count > 0 &&
        anyProxyRouteSettingsChanged(variables.proxyUrls, { enabled: variables.enabled });
      queryClient.setQueryData<NetworkProxy[]>(['proxies'], (currentProxies) =>
        currentProxies?.map((proxy) =>
          variables.proxyUrls.includes(proxy.url) ? { ...proxy, enabled: variables.enabled } : proxy,
        ),
      );
      void queryClient.invalidateQueries({ queryKey: ['proxies'] });
      if (routesChanged) invalidateMpsProxyPreview();
      setApplySettingsNotice({
        tone: 'success',
        title: variables.enabled ? 'Proxies Enabled' : 'Proxies Disabled',
        detail: data.message,
      });
    },
    onError: (mutationError: Error) => {
      setApplySettingsNotice({
        tone: 'danger',
        title: 'Bulk State Update Failed',
        detail: mutationError.message,
      });
    },
  });

  const bulkDeleteMutation = useMutation({
    mutationFn: (proxyUrls: string[]) => bulkDeleteProxies({ proxy_urls: proxyUrls }),
    onSuccess: (data, proxyUrls) => {
      queryClient.setQueryData<NetworkProxy[]>(['proxies'], (currentProxies) =>
        currentProxies?.filter((proxy) => !proxyUrls.includes(proxy.url)),
      );
      void queryClient.invalidateQueries({ queryKey: ['proxies'] });
      if (data.deleted_count > 0) invalidateMpsProxyPreview();
      setSelectedProxyIds((prev) => {
        const next = new Set(prev);
        for (const url of proxyUrls) {
          next.delete(url);
        }
        return next;
      });
      setApplySettingsNotice({
        tone: 'success',
        title: 'Proxies Removed',
        detail: data.message,
      });
    },
    onError: (mutationError: Error) => {
      setApplySettingsNotice({
        tone: 'danger',
        title: 'Bulk Deletion Failed',
        detail: mutationError.message,
      });
    },
  });

  const bulkEditMutation = useMutation({
    mutationFn: ({
      proxyUrls,
      max_connections,
      max_concurrency,
      guest_lookup_timeout,
    }: {
      proxyUrls: string[];
      max_connections?: number | null;
      max_concurrency?: number | null;
      guest_lookup_timeout?: number | null;
    }) =>
      bulkEditProxies({
        proxy_urls: proxyUrls,
        max_connections: max_connections ?? undefined,
        max_concurrency: max_concurrency ?? undefined,
        guest_lookup_timeout: guest_lookup_timeout ?? undefined,
      }),
    onSuccess: (data, variables) => {
      const routesChanged =
        data.updated_count > 0 &&
        anyProxyRouteSettingsChanged(variables.proxyUrls, {
          max_connections: variables.max_connections,
        });
      queryClient.setQueryData<NetworkProxy[]>(['proxies'], (currentProxies) =>
        currentProxies?.map((proxy) => {
          if (!variables.proxyUrls.includes(proxy.url)) return proxy;
          const updated = { ...proxy };
          if (variables.max_connections != null) {
            updated.max_connections = variables.max_connections;
          }
          if (variables.guest_lookup_timeout !== undefined) {
            updated.guest_lookup_timeout = variables.guest_lookup_timeout;
          }
          return updated;
        }),
      );
      void queryClient.invalidateQueries({ queryKey: ['proxies'] });
      if (routesChanged) invalidateMpsProxyPreview();
      setShowBulkEditModal(false);
      setApplySettingsNotice({
        tone: 'success',
        title: 'Bulk Edit Applied',
        detail: data.message,
      });
    },
    onError: (mutationError: Error) => {
      setApplySettingsNotice({
        tone: 'danger',
        title: 'Bulk Edit Failed',
        detail: mutationError.message,
      });
    },
  });

  const handleBulkEditSelected = (settings: {
    max_connections?: number | null;
    max_concurrency?: number | null;
    guest_lookup_timeout?: number | null;
  }) => {
    const urls = Array.from(selectedProxyIds);
    if (urls.length === 0) return;
    bulkEditMutation.mutate({
      proxyUrls: urls,
      ...settings,
    });
  };

  const handleBulkEnableSelected = (urls: string[]) => {
    if (urls.length === 0) return;
    bulkUpdateStateMutation.mutate({ proxyUrls: urls, enabled: true });
  };

  const handleBulkDisableSelected = (urls: string[]) => {
    if (urls.length === 0) return;
    bulkUpdateStateMutation.mutate({ proxyUrls: urls, enabled: false });
  };

  const handleBulkDeleteSelected = (urls: string[]) => {
    if (urls.length === 0) return;
    if (typeof window !== 'undefined' && window.confirm && !window.confirm(`Are you sure you want to delete ${urls.length} proxy route${urls.length === 1 ? '' : 's'}?`)) {
      return;
    }
    bulkDeleteMutation.mutate(urls);
  };

  const handleToggleSelectGroup = (groupProxies: NetworkProxy[]) => {
    const allSelected = groupProxies.length > 0 && groupProxies.every((p) => selectedProxyIds.has(p.url));
    setSelectedProxyIds((prev) => {
      const next = new Set(prev);
      if (allSelected) {
        for (const p of groupProxies) {
          next.delete(p.url);
        }
      } else {
        for (const p of groupProxies) {
          next.add(p.url);
        }
      }
      return next;
    });
  };

  const handleBulkTestSelected = async (urls: string[]) => {
    if (urls.length === 0 || isBulkTesting) return;
    const targets = proxies.filter((p) => urls.includes(p.url));
    if (targets.length === 0) return;

    setIsBulkTesting(true);
    refreshProxyGeolocations(targets.map((target) => target.url));
    setProxyQuickTestResults((prev) => {
      const next = { ...prev };
      for (const t of targets) {
        next[t.url] = { testing: true, message: 'Probing route reachability…' };
      }
      return next;
    });

    try {
      const results = await bulkTestProxies({
        proxies: targets.map((t) => ({
          url: t.url,
          username: t.username || undefined,
        })),
      });

      const resultMap = new Map<string, BulkTestItemResult>();
      for (const r of results.results) {
        resultMap.set(r.url, r);
      }

      setProxyQuickTestResults((prev) => {
        const next = { ...prev };
        for (const t of targets) {
          const res = resultMap.get(t.url);
          if (res) {
            next[t.url] = {
              testing: false,
              success: res.success,
              latency_ms: res.latency_ms ?? null,
              message: res.message,
            };
          } else {
            next[t.url] = {
              testing: false,
              success: false,
              message: 'No response received',
            };
          }
        }
        return next;
      });

      const passed = results.results.filter((r) => r.success).length;
      setApplySettingsNotice({
        tone: passed === targets.length ? 'success' : 'danger',
        title: 'Bulk Connectivity Test Complete',
        detail: `${passed}/${targets.length} tested proxies are active and reachable.`,
      });
    } catch (err) {
      setProxyQuickTestResults((prev) => {
        const next = { ...prev };
        for (const t of targets) {
          next[t.url] = {
            testing: false,
            success: false,
            message: err instanceof Error ? err.message : 'Test failed',
          };
        }
        return next;
      });
      setApplySettingsNotice({
        tone: 'danger',
        title: 'Bulk Test Failed',
        detail: err instanceof Error ? err.message : 'Unknown error during bulk test',
      });
    } finally {
      setIsBulkTesting(false);
    }
  };

  const handleBulkTest = async (items: BulkTestItem[]): Promise<BulkTestItemResult[]> => {
    refreshProxyGeolocations(items.map((item) => item.url));
    const response = await bulkTestProxies({ proxies: items });
    return response.results;
  };

  const handleToggleSelectProxy = (proxy: NetworkProxy) => {
    setSelectedProxyIds((prev) => {
      const next = new Set(prev);
      if (next.has(proxy.url)) {
        next.delete(proxy.url);
      } else {
        next.add(proxy.url);
      }
      return next;
    });
  };

  const handleSelectAllProxies = () => {
    const allSelected = filteredProxies.length > 0 && filteredProxies.every((p) => selectedProxyIds.has(p.url));
    if (allSelected) {
      setSelectedProxyIds(new Set());
    } else {
      setSelectedProxyIds(new Set(filteredProxies.map((p) => p.url)));
    }
  };

  const handleClearSelectedProxies = () => {
    setSelectedProxyIds(new Set());
  };

  const testSingleReachability = async (proxy: NetworkProxy) => {
    try {
      return await testProxy({
        url: proxy.url,
        username: proxy.username || undefined,
      });
    } finally {
      refreshProxyGeolocations([proxy.url]);
    }
  };

  const analyzeGroupRepresentative = (groupName: string) => {
    const normalizedGroupName = groupName.trim();
    const rep = proxies.find((p) => p.group?.trim() === normalizedGroupName && p.enabled !== false) ||
                proxies.find((p) => p.group?.trim() === normalizedGroupName);
    if (rep) {
      openAnalyzerModal(rep);
    }
  };

  const applyOptimalSettings = async (applyToGroup: boolean = false) => {
    const analyzerData = activeAnalyzerProxy ? analyzerResults[activeAnalyzerProxy.id] : null;
    if (!activeAnalyzerProxy || !analyzerData?.recommended_connections || applySettingsPending) {
      return;
    }

    const recommendedConnections = analyzerData.recommended_connections;
    const recommendedConcurrency = analyzerData.recommended_concurrency;
    if (!recommendedConnections) {
      return;
    }

    try {
      setApplySettingsPending(true);
      setApplySettingsNotice(null);

      if (applyToGroup && activeAnalyzerProxy.group) {
        const result = await updateGroupSettings(activeAnalyzerProxy.group, {
          max_connections: recommendedConnections,
          max_concurrency: recommendedConcurrency,
        });

        const currentProxies = queryClient.getQueryData<NetworkProxy[]>(['proxies']);
        const groupProxies = currentProxies?.filter(
          (proxy) => proxy.group?.trim() === activeAnalyzerProxy.group?.trim(),
        );
        if (
          result.updated_count > 0 &&
          (!groupProxies || groupProxies.some((proxy) => proxy.max_connections !== recommendedConnections))
        ) {
          invalidateMpsProxyPreview();
        }

        await queryClient.invalidateQueries({ queryKey: ['proxies'] });
        setApplySettingsNotice({
          tone: 'success',
          title: `Updated Group "${activeAnalyzerProxy.group}"`,
          detail: `Saved max_connections=${recommendedConnections} and max_concurrency=${recommendedConcurrency} across all proxies in "${activeAnalyzerProxy.group}".`,
        });
      } else {
        const endpoint =
          activeAnalyzerProxy.id === DIRECT_CONNECTION_PROXY.id
            ? '/api/v1/proxies/network'
            : `/api/v1/proxies/${encodeURIComponent(activeAnalyzerProxy.url)}`;

        await updateProxySettings(endpoint, {
          max_connections: recommendedConnections,
          max_concurrency: recommendedConcurrency,
        });

        if (
          activeAnalyzerProxy.id !== DIRECT_CONNECTION_PROXY.id &&
          proxyRouteSettingsChanged(activeAnalyzerProxy.url, {
            max_connections: recommendedConnections,
          })
        ) {
          invalidateMpsProxyPreview();
        }

        await queryClient.invalidateQueries({ queryKey: ['proxies'] });
        const targetName =
          activeAnalyzerProxy.id === DIRECT_CONNECTION_PROXY.id
            ? 'Network (direct)'
            : activeAnalyzerProxy.url;
        setApplySettingsNotice({
          tone: 'success',
          title: `Updated ${targetName}`,
          detail: `Saved max_connections=${recommendedConnections} and max_concurrency=${recommendedConcurrency}.`,
        });
      }
      setShowAnalyzerModal(false);
    } catch (updateError) {
      setApplySettingsNotice({
        tone: 'danger',
        title: 'Failed to save network settings',
        detail:
          updateError instanceof Error ? updateError.message : 'Failed to apply settings',
      });
    } finally {
      setApplySettingsPending(false);
    }
  };

  const handleDeleteProxy = (proxy: NetworkProxy) => {
    deleteProxyMutation.mutate(proxy.url);
  };

  const handleToggleProxyEnabled = (proxy: NetworkProxy) => {
    proxyStateMutation.mutate({
      proxyUrl: proxy.url,
      enabled: proxy.enabled === false,
    });
  };

  const activeAnalyzerId = activeAnalyzerProxy?.id;
  const activeAnalyzerData = activeAnalyzerId ? analyzerResults[activeAnalyzerId] : undefined;
  const activeAnalyzerError = activeAnalyzerId ? analyzerErrors[activeAnalyzerId] : null;

  return {
    activeAnalyzerData,
    activeAnalyzerError,
    activeAnalyzerId,
    activeAnalyzerProxy,
    addProxyMutation,
    analyzeGroupRepresentative,
    analyzerErrors,
    analyzerLoading,
    analyzerModalTab,
    analyzerProgress,
    applyOptimalSettings,
    applySettingsNotice,
    applySettingsPending,
    assignProxyMutation,
    bulkAddProxiesMutation,
    bulkAssignGroupMutation,
    bulkDeleteMutation,
    bulkEditMutation,
    bulkModalMode,
    bulkSyncProxiesMutation,
    bulkUpdateStateMutation,
    closeBulkModal,
    closeProxyFormModal,
    compareSelection,
    deleteProxyMutation,
    disabledCount,
    editProxyMutation,
    editingProxy,
    enabledCount,
    error,
    errorDetailModal,
    existingGroups,
    expandedConcurrency,
    expandedProxy,
    fetchGeolocation,
    fetchMediaPool,
    filteredProxies,
    formError,
    handleBulkDeleteSelected,
    handleBulkDisableSelected,
    handleBulkEditSelected,
    handleBulkEnableSelected,
    handleBulkTest,
    handleBulkTestSelected,
    handleClearSelectedProxies,
    handleDeleteProxy,
    handleSaveProxy,
    handleSelectAllProxies,
    handleToggleProxyEnabled,
    handleToggleSelectGroup,
    handleToggleSelectProxy,
    isBulkTesting,
    isError,
    isLoading,
    isProxyAuthsLoading,
    mediaPoolError,
    mediaPoolLoading,
    mediaPoolUrls,
    newProxyGroup,
    newProxyMaxConnections,
    newProxyGuestLookupTimeout,
    newProxyPassword,
    newProxyUrl,
    newProxyUsername,
    openAddModal,
    openAnalyzerModal,
    openBulkEditProxiesModal,
    openBulkModal,
    openEditModal,
    proxies,
    proxyAuths,
    proxyQuickTestResults,
    proxyStateErrors,
    proxyStatePending,
    searchQuery,
    selectedGroupFilter,
    selectedProxyIds,
    setActiveAnalyzerProxy,
    setAnalyzerModalTab,
    setApplySettingsNotice,
    setAnalyzerRequestCount,
    setCompareSelection,
    setErrorDetailModal,
    setExpandedConcurrency,
    setExpandedProxy,
    setNewProxyGroup,
    setNewProxyMaxConnections,
    setNewProxyGuestLookupTimeout,
    setNewProxyPassword,
    setNewProxyUrl,
    setNewProxyUsername,
    setSearchQuery,
    setSelectedGroupFilter,
    setShowAnalyzerModal,
    setShowBulkModal,
    setShowBulkEditModal,
    setUseLiveCdn,
    showAddModal,
    showAnalyzerModal,
    showBulkModal,
    showBulkEditModal,
    startAnalysis,
    stopAnalysis,
    testLatencyMs,
    testMessage,
    testProxyMutation,
    testSingleReachability,
    testStatus,
    totalAssigned,
    unassignedCount,
    useLiveCdn,
    analyzerRequestCount,
    geoError,
    geoLoading,
  };
}
