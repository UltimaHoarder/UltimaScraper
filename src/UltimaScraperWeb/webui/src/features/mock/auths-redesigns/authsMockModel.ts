import { useState, useMemo, useCallback } from 'react';
import type { AuthCredential, AuthEditRequest } from '../../../api/types/auths';

export interface MockProxyInfo {
  id: string;
  name: string;
  protocol: 'http' | 'socks5';
  ip: string;
  region: string;
  latencyMs: number;
  healthy: boolean;
}

export const MOCK_PROXIES: MockProxyInfo[] = [
  {
    id: 'us-east-residential-01',
    name: 'US East Residential #01',
    protocol: 'socks5',
    ip: '142.250.190.46',
    region: 'US (Virginia)',
    latencyMs: 42,
    healthy: true,
  },
  {
    id: 'us-west-datacenter-02',
    name: 'US West Datacenter #02',
    protocol: 'http',
    ip: '104.244.42.1',
    region: 'US (Oregon)',
    latencyMs: 78,
    healthy: true,
  },
  {
    id: 'eu-central-residential-04',
    name: 'EU Central Residential #04',
    protocol: 'socks5',
    ip: '195.181.168.10',
    region: 'DE (Frankfurt)',
    latencyMs: 112,
    healthy: true,
  },
  {
    id: 'asia-jp-01',
    name: 'Tokyo Mobile Edge #01',
    protocol: 'socks5',
    ip: '133.242.18.99',
    region: 'JP (Tokyo)',
    latencyMs: 165,
    healthy: true,
  },
];

export const INITIAL_MOCK_AUTHS: AuthCredential[] = [
  {
    id: 101,
    site: 'onlyfans',
    username: 'vip_operator_01',
    user_id: 104218,
    status: 'valid',
    active: true,
    last_tested_at: new Date(Date.now() - 1000 * 60 * 18).toISOString(),
    created_at: '2026-08-14T10:30:00Z',
    cookie_preview: 'sess=9f82a1...; auth_id=104218; csrf=882e...',
    has_authorization: true,
    user_agent_preview: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0',
    proxy_id: 'us-east-residential-01',
    worker_shard: 1,
    is_age_verified: true,
    age_verification_required: false,
    spend: true,
    spender_type: 'paid',
  },
  {
    id: 102,
    site: 'onlyfans',
    username: 'luna_archive_vault',
    user_id: 104218, // same performer, secondary rotation token
    status: 'valid',
    active: true,
    last_tested_at: new Date(Date.now() - 1000 * 60 * 45).toISOString(),
    created_at: '2026-09-02T14:15:00Z',
    cookie_preview: 'sess=7b12c4...; auth_id=104218; fp_id=1992...',
    has_authorization: true,
    user_agent_preview: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/129.0',
    proxy_id: 'us-west-datacenter-02',
    worker_shard: 2,
    is_age_verified: true,
    age_verification_required: false,
    spend: false,
    spender_type: null,
  },
  {
    id: 103,
    site: 'fansly',
    username: 'nova_archivist',
    user_id: 829104,
    status: 'valid',
    active: true,
    last_tested_at: new Date(Date.now() - 1000 * 60 * 120).toISOString(),
    created_at: '2026-07-20T08:00:00Z',
    cookie_preview: 'fansly_token=8f029a...; session=d831...',
    has_authorization: true,
    user_agent_preview: 'Mozilla/5.0 (X11; Linux x86_64) Firefox/131.0',
    proxy_id: 'eu-central-residential-04',
    worker_shard: 3,
    is_age_verified: true,
    age_verification_required: false,
    spend: true,
    spender_type: 'all',
  },
  {
    id: 104,
    site: 'onlyfans',
    username: 'sky_crawler_uk',
    user_id: 391824,
    status: 'challenge_required',
    active: true,
    last_tested_at: new Date(Date.now() - 1000 * 60 * 15).toISOString(),
    created_at: '2026-10-01T12:00:00Z',
    cookie_preview: 'sess=19a82b...; auth_id=391824',
    has_authorization: false,
    user_agent_preview: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0',
    proxy_id: null,
    worker_shard: 1,
    is_age_verified: false,
    age_verification_required: true,
    spend: false,
    spender_type: null,
  },
  {
    id: 105,
    site: 'fansly',
    username: 'aurora_backup',
    user_id: 592810,
    status: 'expired',
    active: false,
    last_tested_at: new Date(Date.now() - 1000 * 60 * 60 * 48).toISOString(),
    created_at: '2026-06-11T16:45:00Z',
    cookie_preview: 'fansly_token=stale_0091...; session=expired',
    has_authorization: false,
    user_agent_preview: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    proxy_id: null,
    worker_shard: null,
    is_age_verified: null,
    age_verification_required: null,
    spend: false,
    spender_type: null,
  },
  {
    id: 106,
    site: 'onlyfans',
    username: 'cyber_sentinel',
    user_id: 772190,
    status: 'valid',
    active: true,
    last_tested_at: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
    created_at: '2026-09-28T09:30:00Z',
    cookie_preview: 'sess=aa8172...; auth_id=772190; x_bc=2049182...',
    has_authorization: true,
    user_agent_preview: 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64) Chrome/128.0',
    proxy_id: 'asia-jp-01',
    worker_shard: 2,
    is_age_verified: true,
    age_verification_required: false,
    spend: true,
    spender_type: 'free',
  },
];

export type AuthScenarioPreset =
  | 'standard'
  | 'all_healthy'
  | 'verification_alert'
  | 'stale_tokens'
  | 'multi_account_stress';

export interface AuthsNotification {
  message: string;
  type: 'info' | 'success' | 'warn' | 'error';
}

export function useAuthsMockModel() {
  const [auths, setAuths] = useState<AuthCredential[]>(INITIAL_MOCK_AUTHS);
  const [notification, setNotification] = useState<AuthsNotification | null>(null);

  // Filters & Sorting
  const [searchTerm, setSearchTerm] = useState('');
  const [siteFilter, setSiteFilter] = useState('');
  const [stateFilter, setStateFilter] = useState<'all' | 'active' | 'disabled'>('all');
  const [statusFilter, setStatusFilter] = useState<'all' | 'valid' | 'challenge' | 'expired'>('all');
  const [sortBy, setSortBy] = useState<'id' | 'username' | 'site' | 'last_tested_at' | 'created_at'>('id');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc');

  // Modal States
  const [testingAuth, setTestingAuth] = useState<AuthCredential | null>(null);
  const [editingAuth, setEditingAuth] = useState<AuthCredential | null>(null);
  const [verifyingAuth, setVerifyingAuth] = useState<{
    auth: AuthCredential;
    kind: 'age' | 'identity';
  } | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);

  // Stats calculation
  const stats = useMemo(() => {
    const total = auths.length;
    const active = auths.filter((a) => a.active).length;
    const valid = auths.filter((a) => a.status === 'valid').length;
    const challenges = auths.filter(
      (a) => a.status === 'challenge_required' || a.age_verification_required
    ).length;
    const expired = auths.filter((a) => a.status === 'expired').length;
    const spenders = auths.filter((a) => a.spend).length;
    const withProxy = auths.filter((a) => a.proxy_id !== null).length;
    const onlyfansCount = auths.filter((a) => a.site.toLowerCase() === 'onlyfans').length;
    const fanslyCount = auths.filter((a) => a.site.toLowerCase() === 'fansly').length;

    return {
      total,
      active,
      disabled: total - active,
      valid,
      validRate: total > 0 ? Math.round((valid / total) * 100) : 100,
      challenges,
      expired,
      spenders,
      withProxy,
      proxyRate: total > 0 ? Math.round((withProxy / total) * 100) : 0,
      onlyfansCount,
      fanslyCount,
    };
  }, [auths]);

  const showNotification = useCallback(
    (message: string, type: 'info' | 'success' | 'warn' | 'error' = 'success') => {
      setNotification({ message, type });
      window.setTimeout(() => {
        setNotification((current) => (current?.message === message ? null : current));
      }, 4500);
    },
    []
  );

  // Actions
  const toggleActive = useCallback(
    (id: number) => {
      setAuths((prev) =>
        prev.map((a) => {
          if (a.id === id) {
            const nextActive = !a.active;
            showNotification(
              `${a.username || `Auth #${a.id}`} is now ${nextActive ? 'Active' : 'Disabled'}`,
              nextActive ? 'success' : 'warn'
            );
            return { ...a, active: nextActive };
          }
          return a;
        })
      );
    },
    [showNotification]
  );

  const deleteAuth = useCallback(
    (id: number) => {
      const target = auths.find((a) => a.id === id);
      setAuths((prev) => prev.filter((a) => a.id !== id));
      showNotification(`Deleted credential ${target?.username || `#${id}`}`, 'info');
      if (editingAuth?.id === id) setEditingAuth(null);
      if (testingAuth?.id === id) setTestingAuth(null);
    },
    [auths, editingAuth, testingAuth, showNotification]
  );

  const updateAuth = useCallback(
    (id: number, updates: AuthEditRequest) => {
      setAuths((prev) =>
        prev.map((a) => {
          if (a.id === id) {
            return {
              ...a,
              username: updates.username !== undefined ? updates.username : a.username,
              active: updates.active !== undefined ? updates.active : a.active,
              proxy_id: updates.proxy_id !== undefined ? updates.proxy_id : a.proxy_id,
              spend: updates.spend !== undefined ? updates.spend : a.spend,
              spender_type: updates.spender_type !== undefined ? updates.spender_type : a.spender_type,
              cookie_preview: updates.cookie
                ? `${updates.cookie.slice(0, 18)}...`
                : a.cookie_preview,
              user_agent_preview: updates.user_agent
                ? `${updates.user_agent.slice(0, 32)}...`
                : a.user_agent_preview,
            };
          }
          return a;
        })
      );
      showNotification(`Updated credential parameters for Auth #${id}`, 'success');
      setEditingAuth(null);
    },
    [showNotification]
  );

  const addAuth = useCallback(
    (newAuth: Omit<AuthCredential, 'id'>) => {
      const nextId = Math.max(...auths.map((a) => a.id), 100) + 1;
      const created: AuthCredential = {
        ...newAuth,
        id: nextId,
        created_at: new Date().toISOString(),
        last_tested_at: new Date().toISOString(),
      };
      setAuths((prev) => [created, ...prev]);
      showNotification(
        `Added new ${created.site} credential for @${created.username || `u${created.user_id}`} (Auth #${nextId})`,
        'success'
      );
      setShowAddModal(false);
    },
    [auths, showNotification]
  );

  const handleTestAuth = useCallback(
    (id: number) => {
      setAuths((prev) =>
        prev.map((a) => {
          if (a.id === id) {
            return {
              ...a,
              status: 'valid',
              last_tested_at: new Date().toISOString(),
            };
          }
          return a;
        })
      );
      showNotification(`Health probe passed for Auth #${id}: 200 OK (Latency: 54ms)`, 'success');
    },
    [showNotification]
  );

  const handleUpdateSubscriptions = useCallback(
    (id?: number) => {
      if (id) {
        showNotification(`Synced subscriptions for Auth #${id}: 34 creators refreshed`, 'success');
      } else {
        showNotification(
          `Fleet subscription sync initiated for all ${stats.active} active credentials`,
          'info'
        );
      }
    },
    [showNotification, stats.active]
  );

  const handleScrapePaidContent = useCallback(
    (id: number) => {
      showNotification(
        `Enqueued automated PPV / Paid media unlock crawler for Auth #${id}`,
        'success'
      );
    },
    [showNotification]
  );

  const batchToggleActive = useCallback(
    (ids: number[], active: boolean) => {
      setAuths((prev) =>
        prev.map((a) => (ids.includes(a.id) ? { ...a, active } : a))
      );
      showNotification(
        `${active ? 'Enabled' : 'Disabled'} ${ids.length} selected credentials`,
        'info'
      );
    },
    [showNotification]
  );

  const batchTest = useCallback(
    (ids: number[]) => {
      setAuths((prev) =>
        prev.map((a) =>
          ids.includes(a.id)
            ? { ...a, status: 'valid', last_tested_at: new Date().toISOString() }
            : a
        )
      );
      showNotification(
        `Batch probe complete: verified ${ids.length} credentials with upstream platforms`,
        'success'
      );
    },
    [showNotification]
  );

  // Preset switch
  const applyScenario = useCallback(
    (preset: AuthScenarioPreset) => {
      switch (preset) {
        case 'all_healthy':
          setAuths((prev) =>
            prev.map((a) => ({
              ...a,
              status: 'valid',
              active: true,
              is_age_verified: true,
              age_verification_required: false,
              last_tested_at: new Date().toISOString(),
            }))
          );
          showNotification('Scenario applied: 100% Healthy Fleet', 'success');
          break;
        case 'verification_alert':
          setAuths((prev) =>
            prev.map((a, idx) => ({
              ...a,
              status: idx % 2 === 0 ? 'challenge_required' : a.status,
              age_verification_required: idx % 2 === 0,
              is_age_verified: idx % 2 === 0 ? false : a.is_age_verified,
            }))
          );
          showNotification('Scenario applied: Verification Challenge Outbreak', 'warn');
          break;
        case 'stale_tokens':
          setAuths((prev) =>
            prev.map((a, idx) => ({
              ...a,
              status: idx > 2 ? 'expired' : a.status,
              active: idx <= 2,
            }))
          );
          showNotification('Scenario applied: Stale Session Token Alert', 'error');
          break;
        case 'multi_account_stress':
          setAuths([
            ...INITIAL_MOCK_AUTHS,
            {
              id: 107,
              site: 'onlyfans',
              username: 'burner_alpha_99',
              user_id: 104218,
              status: 'valid',
              active: true,
              last_tested_at: new Date().toISOString(),
              created_at: '2026-10-20T10:00:00Z',
              cookie_preview: 'sess=cc7162...; auth_id=104218',
              has_authorization: true,
              user_agent_preview: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4)',
              proxy_id: 'us-east-residential-01',
              worker_shard: 1,
              is_age_verified: true,
              age_verification_required: false,
              spend: false,
              spender_type: null,
            },
            {
              id: 108,
              site: 'fansly',
              username: 'nova_archivist_sub',
              user_id: 829104,
              status: 'valid',
              active: true,
              last_tested_at: new Date().toISOString(),
              created_at: '2026-10-22T14:00:00Z',
              cookie_preview: 'fansly_token=77192a...',
              has_authorization: true,
              user_agent_preview: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
              proxy_id: 'eu-central-residential-04',
              worker_shard: 3,
              is_age_verified: true,
              age_verification_required: false,
              spend: true,
              spender_type: 'free',
            },
          ]);
          showNotification('Scenario applied: Multi-Device High Density Sharding (8 accounts)', 'info');
          break;
        case 'standard':
        default:
          setAuths(INITIAL_MOCK_AUTHS);
          showNotification('Reset to baseline operational credentials', 'info');
          break;
      }
    },
    [showNotification]
  );

  const resetAll = useCallback(() => {
    setAuths(INITIAL_MOCK_AUTHS);
    setSearchTerm('');
    setSiteFilter('');
    setStateFilter('all');
    setStatusFilter('all');
    setSortBy('id');
    setSortOrder('desc');
    setTestingAuth(null);
    setEditingAuth(null);
    setVerifyingAuth(null);
    setShowAddModal(false);
    showNotification('Auths Design Lab preview state has been reset.', 'info');
  }, [showNotification]);

  // Filtered & sorted list
  const filteredAuths = useMemo(() => {
    return auths.filter((auth) => {
      if (searchTerm) {
        const query = searchTerm.toLowerCase();
        const matchesName = (auth.username || '').toLowerCase().includes(query);
        const matchesId = String(auth.id).includes(query);
        const matchesUserId = String(auth.user_id).includes(query);
        const matchesSite = auth.site.toLowerCase().includes(query);
        const matchesProxy = (auth.proxy_id || '').toLowerCase().includes(query);
        if (!matchesName && !matchesId && !matchesUserId && !matchesSite && !matchesProxy) {
          return false;
        }
      }

      if (siteFilter && auth.site.toLowerCase() !== siteFilter.toLowerCase()) {
        return false;
      }

      if (stateFilter === 'active' && !auth.active) return false;
      if (stateFilter === 'disabled' && auth.active) return false;

      if (statusFilter === 'valid' && auth.status !== 'valid') return false;
      if (
        statusFilter === 'challenge' &&
        auth.status !== 'challenge_required' &&
        !auth.age_verification_required
      ) {
        return false;
      }
      if (statusFilter === 'expired' && auth.status !== 'expired') return false;

      return true;
    });
  }, [auths, searchTerm, siteFilter, stateFilter, statusFilter]);

  const sortedAuths = useMemo(() => {
    return [...filteredAuths].sort((a, b) => {
      let result = 0;
      if (sortBy === 'id') result = a.id - b.id;
      else if (sortBy === 'username') {
        result = (a.username || '').localeCompare(b.username || '');
      } else if (sortBy === 'site') {
        result = a.site.localeCompare(b.site);
      } else if (sortBy === 'last_tested_at') {
        const tA = a.last_tested_at ? new Date(a.last_tested_at).getTime() : 0;
        const tB = b.last_tested_at ? new Date(b.last_tested_at).getTime() : 0;
        result = tA - tB;
      } else if (sortBy === 'created_at') {
        const tA = a.created_at ? new Date(a.created_at).getTime() : 0;
        const tB = b.created_at ? new Date(b.created_at).getTime() : 0;
        result = tA - tB;
      }
      return sortOrder === 'desc' ? -result : result;
    });
  }, [filteredAuths, sortBy, sortOrder]);

  return {
    auths,
    sortedAuths,
    stats,
    proxies: MOCK_PROXIES,
    notification,
    searchTerm,
    setSearchTerm,
    siteFilter,
    setSiteFilter,
    stateFilter,
    setStateFilter,
    statusFilter,
    setStatusFilter,
    sortBy,
    setSortBy,
    sortOrder,
    setSortOrder,
    // Modals
    testingAuth,
    setTestingAuth,
    editingAuth,
    setEditingAuth,
    verifyingAuth,
    setVerifyingAuth,
    showAddModal,
    setShowAddModal,
    // Actions
    toggleActive,
    deleteAuth,
    updateAuth,
    addAuth,
    handleTestAuth,
    handleUpdateSubscriptions,
    handleScrapePaidContent,
    batchToggleActive,
    batchTest,
    applyScenario,
    resetAll,
    showNotification,
  };
}

export type AuthsMockModel = ReturnType<typeof useAuthsMockModel>;
