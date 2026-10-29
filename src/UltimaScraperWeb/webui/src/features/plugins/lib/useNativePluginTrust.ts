import { useQuery } from '@tanstack/react-query';

import { getActiveConnectionId } from '../../../api/http';
import { listConnections } from '../../../api/webui';

export interface NativePluginTrust {
  /** Native plugin code may run in this page. */
  allowed: boolean;
  /** The answer is known; false while it loads. */
  known: boolean;
  connectionName: string | null;
}

/**
 * One page holds the session for every backend this WebUI reaches, so a
 * backend's native plugin code runs only when the user trusts that backend.
 */
export function useNativePluginTrust(): NativePluginTrust {
  const connectionId = getActiveConnectionId();
  const { data, isError } = useQuery({
    queryKey: ['webui-plugin-trust', connectionId],
    queryFn: async () => (await listConnections()).find((connection) => connection.id === connectionId) ?? null,
    enabled: connectionId !== null,
    staleTime: 30_000,
  });
  return {
    allowed: data?.trust_plugins === true,
    known: data !== undefined || isError,
    connectionName: data?.name ?? null,
  };
}
