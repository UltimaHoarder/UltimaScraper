import { QueryClientProvider } from '@tanstack/react-query';
import { useEffect, useState, type ReactNode } from 'react';

import { setScopedConnectionId } from '../../api/http';
import { closeUnusedSockets } from '../../hooks/useWebSocket';
import { queryClientFor } from './backendQueryClients';

/**
 * Everything that belongs to one backend: its query cache, and (through the
 * remount its key forces) its sockets, plugin host and bootstrap state.
 * Leaving it stops the old backend's work, so nothing it started reaches
 * the next one: requests resolve their address when they are sent.
 */
export function BackendScope({ connectionId, children }: { connectionId: string; children: ReactNode }) {
  const [client] = useState(() => queryClientFor(connectionId));
  setScopedConnectionId(connectionId || null);

  useEffect(() => {
    setScopedConnectionId(connectionId || null);
    return () => {
      setScopedConnectionId(null);
      // No retries or refetches for the old backend once the address changed.
      void client.cancelQueries();
      // Children's listeners detach after this cleanup; close their sockets then.
      window.setTimeout(closeUnusedSockets, 0);
    };
  }, [client, connectionId]);

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

