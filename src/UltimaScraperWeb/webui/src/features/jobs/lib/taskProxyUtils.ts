import type { TaskDetail, TaskRouteHop } from '../../../api/types/jobs';
import type { NetworkProxy } from '../../../api/types/network';

/**
 * Mask proxy credentials for safe UI presentation (passwords never exposed).
 */
export function maskProxyUrl(url: string | null | undefined): string {
  if (!url || typeof url !== 'string') {
    return 'Direct';
  }
  const trimmed = url.trim();
  if (!trimmed || trimmed.toLowerCase() === 'direct') {
    return 'Direct';
  }

  try {
    // Standard URL parser (handles http, https, socks5, socks5h)
    const parsed = new URL(trimmed);
    if (parsed.username || parsed.password) {
      parsed.username = '***';
      parsed.password = '***';
    }
    const result = parsed.toString();
    return result.endsWith('/') && !trimmed.endsWith('/') ? result.slice(0, -1) : result;
  } catch {
    // Regex fallback for non-standard protocol strings
    return trimmed.replace(
      /^([a-zA-Z0-9+.-]+:\/\/)((?:[^:@]+)(?::(?:[^@]+))?@)/,
      '$1***:***@',
    );
  }
}

/**
 * Format a proxy URL to a clean, compact host:port string.
 */
export function formatProxyHost(url: string | null | undefined): string {
  if (!url || typeof url !== 'string') {
    return 'Direct';
  }
  const trimmed = url.trim();
  if (!trimmed || trimmed.toLowerCase() === 'direct') {
    return 'Direct';
  }

  try {
    const parsed = new URL(trimmed);
    return parsed.port ? `${parsed.hostname}:${parsed.port}` : parsed.hostname;
  } catch {
    const match = trimmed.match(/(?:@|^|\/\/)([a-zA-Z0-9.-]+)(?::([0-9]+))?/);
    if (match) {
      return match[2] ? `${match[1]}:${match[2]}` : match[1];
    }
    return trimmed;
  }
}

/**
 * Normalize proxy URL to host:port key for map lookups against networkProxies.
 */
function normalizeProxyKey(url: string | null | undefined): string {
  if (!url) return '';
  return formatProxyHost(url).toLowerCase();
}

/**
 * Reconstructs or reads the ordered sequence of proxy route hops configured for a task.
 * Marks evaluated hops as used, failed, or untried.
 */
export function buildTaskRouteSequence(
  task: TaskDetail,
  networkProxies?: NetworkProxy[],
): TaskRouteHop[] {
  // 1. Resolve route candidates
  let rawRoutes: Array<string | null> = [];

  if (Array.isArray(task.proxy_routes) && task.proxy_routes.length > 0) {
    rawRoutes = [...task.proxy_routes];
  } else {
    // Check output / metrics from execution
    const output = task.result?.output as Record<string, unknown> | undefined;
    const metrics = (task.result?.metrics || {}) as Record<string, unknown>;

    if (Array.isArray(output?.proxy_routes) && output.proxy_routes.length > 0) {
      rawRoutes = [...output.proxy_routes];
    } else if (Array.isArray(metrics?.proxy_routes) && metrics.proxy_routes.length > 0) {
      rawRoutes = [...metrics.proxy_routes];
    } else {
      // Check payload for guest fallback configurations
      const payload = (task.payload || {}) as Record<string, unknown>;
      const guestProxyUrl = typeof payload.guest_proxy_url === 'string' ? payload.guest_proxy_url : null;
      const guestFallbackUrls = Array.isArray(payload.guest_fallback_proxy_urls)
        ? (payload.guest_fallback_proxy_urls.filter((u): u is string => typeof u === 'string'))
        : [];
      const guestDirectIndex =
        typeof payload.guest_direct_route_index === 'number'
          ? payload.guest_direct_route_index
          : null;

      if (guestProxyUrl || guestFallbackUrls.length > 0 || guestDirectIndex !== null) {
        if (guestProxyUrl) {
          rawRoutes.push(guestProxyUrl);
        }
        for (const fallbackUrl of guestFallbackUrls) {
          if (fallbackUrl && !rawRoutes.includes(fallbackUrl)) {
            rawRoutes.push(fallbackUrl);
          }
        }
        if (guestDirectIndex !== null && guestDirectIndex >= 0) {
          const insertIdx = Math.min(guestDirectIndex, rawRoutes.length);
          rawRoutes.splice(insertIdx, 0, null);
        }
      } else if (typeof task.proxy_url === 'string' || typeof payload.proxy_url === 'string') {
        rawRoutes.push(task.proxy_url || (payload.proxy_url as string));
      } else if (typeof output?.proxy_url === 'string' || typeof metrics?.proxy_url === 'string') {
        rawRoutes.push((output?.proxy_url || metrics?.proxy_url) as string);
      } else if (payload.auth_id && networkProxies && networkProxies.length > 0) {
        const authId = Number(payload.auth_id);
        const matched = networkProxies.find((p) => p.assigned_auths?.includes(authId));
        if (matched) {
          rawRoutes.push(matched.url);
        }
      }
    }
  }

  // If no routes found, check if direct is explicitly recorded or proxy_url is null
  if (rawRoutes.length === 0) {
    const output = task.result?.output as Record<string, unknown> | undefined;
    const isInvalidUser = Boolean(output?.invalid_user);
    const msg = String(task.message || task.result?.message || '');
    const mentionsProxyRoutes = /attempted \d+ proxy route/i.test(msg);
    const payload = (task.payload || {}) as Record<string, unknown>;
    const directDisabled = payload.include_direct_connection === false;

    if (
      task.proxy_url === null &&
      task.status === 'completed' &&
      !isInvalidUser &&
      !mentionsProxyRoutes &&
      !directDisabled
    ) {
      rawRoutes = [null];
    } else {
      return [];
    }
  }

  // 2. Determine resolved used hop index
  const output = task.result?.output as Record<string, unknown> | undefined;
  const metrics = (task.result?.metrics || {}) as Record<string, unknown>;
  const isInvalidUser = Boolean(output?.invalid_user);
  let usedHopIndex: number | null = null;

  if (typeof task.proxy_hop_used === 'number') {
    usedHopIndex = task.proxy_hop_used;
  } else if (typeof output?.proxy_hop_used === 'number') {
    usedHopIndex = output.proxy_hop_used;
  } else if (typeof metrics?.proxy_hop_used === 'number') {
    usedHopIndex = metrics.proxy_hop_used;
  } else if (!isInvalidUser) {
    // Match proxy_url in routes only if not invalid user (invalid user has proxy_url=null because no route resolved the user)
    const activeUrl = task.proxy_url ?? (output?.proxy_url as string | null | undefined) ?? (metrics?.proxy_url as string | null | undefined);
    if (activeUrl !== undefined) {
      if (activeUrl === null) {
        const directIdx = rawRoutes.indexOf(null);
        if (directIdx >= 0) usedHopIndex = directIdx;
      } else {
        const activeKey = normalizeProxyKey(activeUrl);
        const matchedIdx = rawRoutes.findIndex((r) => r !== null && normalizeProxyKey(r) === activeKey);
        if (matchedIdx >= 0) usedHopIndex = matchedIdx;
      }
    } else if (task.status === 'completed' && rawRoutes.length === 1) {
      usedHopIndex = 0;
    }
  }

  // 3. Build proxy metadata map from networkProxies
  const proxyMap = new Map<string, NetworkProxy>();
  if (networkProxies) {
    for (const proxy of networkProxies) {
      const key = normalizeProxyKey(proxy.url);
      if (key && !proxyMap.has(key)) {
        proxyMap.set(key, proxy);
      }
    }
  }

  // 4. Build hops
  const taskStatus = String(task.status || '').toLowerCase();
  const isFailedTask = ['failed', 'cancelled'].includes(taskStatus);
  const isRunningTask = ['running', 'inflight'].includes(taskStatus);

  const attemptedIndices = Array.isArray(output?.proxy_routes_attempted)
    ? (output?.proxy_routes_attempted as number[])
    : Array.isArray(metrics?.proxy_routes_attempted)
      ? (metrics?.proxy_routes_attempted as number[])
      : null;
  const msg = String(task.message || task.result?.message || '');
  const attemptedMatch = msg.match(/attempted (\d+) proxy route/i);
  const attemptedCountFromMsg = attemptedMatch ? parseInt(attemptedMatch[1], 10) : null;

  return rawRoutes.map((routeUrl, index) => {
    const isDirect = routeUrl === null || routeUrl === '' || routeUrl.toLowerCase() === 'direct';
    const hopNumber = index + 1;

    let roleLabel = 'Primary';
    if (rawRoutes.length === 1) {
      roleLabel = isDirect ? 'Direct' : 'Primary';
    } else if (index === 0) {
      roleLabel = isDirect ? 'Primary (Direct)' : 'Primary';
    } else {
      roleLabel = isDirect ? `Fallback ${index} (Direct)` : `Fallback ${index}`;
    }

    let hopStatus: TaskRouteHop['status'] = 'untried';
    if (usedHopIndex !== null) {
      if (index < usedHopIndex) {
        hopStatus = 'failed';
      } else if (index === usedHopIndex) {
        hopStatus = isFailedTask ? 'failed' : isRunningTask ? 'pending' : 'used';
      } else {
        hopStatus = 'untried';
      }
    } else if (isFailedTask) {
      // Failed across the route chain
      hopStatus = 'failed';
    } else if (isRunningTask) {
      hopStatus = index === 0 ? 'pending' : 'untried';
    } else if (isInvalidUser || (taskStatus === 'completed' && usedHopIndex === null)) {
      // Conclusive miss / invalid user: evaluated routes did not resolve the profile
      if (attemptedIndices !== null) {
        hopStatus = attemptedIndices.includes(index) ? 'failed' : 'untried';
      } else if (attemptedCountFromMsg !== null) {
        hopStatus = index < attemptedCountFromMsg ? 'failed' : 'untried';
      } else {
        hopStatus = 'failed';
      }
    }

    const matchedProxy = !isDirect && routeUrl ? proxyMap.get(normalizeProxyKey(routeUrl)) : undefined;

    return {
      hop_number: hopNumber,
      url: routeUrl,
      masked_url: maskProxyUrl(routeUrl),
      is_direct: isDirect,
      status: hopStatus,
      role_label: roleLabel,
      country: matchedProxy?.geolocation?.country,
      country_code: matchedProxy?.geolocation?.country_code,
      flag_emoji: matchedProxy?.geolocation?.flag?.emoji,
      group: matchedProxy?.group,
    };
  });
}

export interface TaskProxySummary {
  activeHop: TaskRouteHop | null;
  hops: TaskRouteHop[];
  hasHops: boolean;
  hopCount: number;
  usedHopNumber: number | null;
  summaryText: string;
  badgeLabel: string | null;
  flagEmoji: string | null;
}

/**
 * Summarizes the proxy route configuration and evaluation for badges and summary cards.
 */
export function getTaskProxySummary(
  task: TaskDetail,
  networkProxies?: NetworkProxy[],
): TaskProxySummary {
  const hops = buildTaskRouteSequence(task, networkProxies);
  const hasHops = hops.length > 0;
  const hopCount = hops.length;

  if (!hasHops) {
    return {
      activeHop: null,
      hops: [],
      hasHops: false,
      hopCount: 0,
      usedHopNumber: null,
      summaryText: 'Direct / None',
      badgeLabel: null,
      flagEmoji: null,
    };
  }

  const output = task.result?.output as Record<string, unknown> | undefined;
  const isInvalidUser = Boolean(output?.invalid_user);
  const usedHop = hops.find((h) => h.status === 'used');
  const usedHopNumber = usedHop?.hop_number ?? null;

  const activeHop =
    usedHop ||
    hops.find((h) => h.status === 'pending') ||
    (task.status === 'failed' ? hops[hops.length - 1] : hops.find((h) => h.status === 'failed') || hops[0]) ||
    null;

  const flagEmoji = activeHop?.flag_emoji ?? null;
  const taskStatus = String(task.status || '').toLowerCase();
  const failedHops = hops.filter((h) => h.status === 'failed');

  let summaryText = '';
  let badgeLabel: string | null = null;

  if (isInvalidUser || (!usedHop && taskStatus === 'completed' && failedHops.length > 0)) {
    const checkedCount = failedHops.length > 0 ? failedHops.length : hopCount;
    summaryText = `${checkedCount} route${checkedCount === 1 ? '' : 's'} checked · Profile not found (404)`;
    badgeLabel = `${checkedCount} Hops Missed (404)`;
  } else if (hopCount === 1) {
    if (activeHop?.is_direct) {
      summaryText = 'Direct Route';
    } else {
      const geo = activeHop?.country ? `${activeHop.country}` : '';
      const group = activeHop?.group ? ` (${activeHop.group})` : '';
      const host = formatProxyHost(activeHop?.url);
      summaryText = geo ? `${flagEmoji ? `${flagEmoji} ` : ''}${geo}${group}` : host;
    }
  } else {
    if (['failed', 'cancelled'].includes(taskStatus) && !hops.some((h) => h.status === 'used')) {
      summaryText = `Failed across ${hopCount} hops`;
    } else {
      const target = activeHop?.is_direct
        ? 'Direct'
        : activeHop?.country || activeHop?.group || formatProxyHost(activeHop?.url);
      summaryText = `Hop ${usedHopNumber || 1} of ${hopCount} · ${flagEmoji ? `${flagEmoji} ` : ''}${target}`;
    }
  }

  if (!badgeLabel) {
    if (activeHop?.is_direct) {
      badgeLabel = hopCount > 1 ? `Direct (Hop ${usedHopNumber}/${hopCount})` : 'Direct';
    } else {
      const flag = flagEmoji || '🌐';
      if (hopCount > 1) {
        badgeLabel = `${flag} Hop ${usedHopNumber || 1}/${hopCount}`;
      } else {
        badgeLabel = `${flag} ${formatProxyHost(activeHop?.url)}`;
      }
    }
  }

  return {
    activeHop,
    hops,
    hasHops: true,
    hopCount,
    usedHopNumber,
    summaryText,
    badgeLabel,
    flagEmoji,
  };
}
