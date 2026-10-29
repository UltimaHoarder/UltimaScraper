import { useState } from 'react';

import { getClusterInvite, type ClusterInvite } from '../../../api/webui';

/** Creates an invite for another WebUI to join the cluster, and copies it. */
export function useClusterInvite(clusterId: string | null) {
  const [invite, setInvite] = useState<ClusterInvite | null>(null);
  const [error, setError] = useState('');

  const copy = async () => {
    if (!clusterId) return;
    setError('');
    try {
      const created = await getClusterInvite(clusterId);
      await navigator.clipboard.writeText(created.invite);
      setInvite(created);
    } catch (failure) {
      setInvite(null);
      setError(failure instanceof Error ? failure.message : 'Could not create an invite.');
    }
  };

  return { invite, error, copy };
}
