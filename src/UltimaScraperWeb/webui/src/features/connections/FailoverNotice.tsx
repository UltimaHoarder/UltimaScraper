import { useSyncExternalStore } from 'react';

import { getServedBy, subscribeToFailover } from '../../api/failover';
import { getActiveConnectionId } from '../../api/http';

/**
 * Shown while the open backend is unreachable and another member of its
 * cluster answers reads of their shared data. Per-backend pages and changes
 * still need the open backend.
 */
export function FailoverNotice() {
  const servedBy = useSyncExternalStore(subscribeToFailover, getServedBy);
  const activeId = getActiveConnectionId();
  if (!servedBy || servedBy === activeId) return null;
  return (
    <span
      className="connection-failover"
      role="status"
      title="Jobs, users, content and other shared data come from another backend in the same cluster. Changes, settings and this backend's own pages wait until it is back."
    >
      {activeId} unreachable · reading from {servedBy}
    </span>
  );
}
