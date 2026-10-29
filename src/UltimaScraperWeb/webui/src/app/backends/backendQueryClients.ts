import { QueryClient } from '@tanstack/react-query';

/** Recently used backends keep their cache, so switching back is instant. */
const KEPT_CLIENTS = 3;

const clients = new Map<string, QueryClient>();

export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        retry: 1,
      },
    },
  });
}

/**
 * The query cache for one backend. Query keys carry no backend, so each
 * backend gets its own client instead of sharing one cache.
 */
export function queryClientFor(connectionId: string): QueryClient {
  let client = clients.get(connectionId);
  if (client) {
    // Most recently used last.
    clients.delete(connectionId);
  } else {
    client = createAppQueryClient();
  }
  clients.set(connectionId, client);
  for (const [id, stale] of clients) {
    if (clients.size <= KEPT_CLIENTS) break;
    clients.delete(id);
    stale.clear();
  }
  return client;
}

/** For tests. */
export function forgetQueryClients(): void {
  for (const client of clients.values()) client.clear();
  clients.clear();
}
