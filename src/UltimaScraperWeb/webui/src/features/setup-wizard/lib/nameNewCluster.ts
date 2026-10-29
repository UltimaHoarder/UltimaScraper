import { listClusters, renameCluster } from '../../../api/webui';

const ATTEMPTS = 5;
const WAIT_MS = 3000;

/**
 * Names the cluster a new backend created. It reports its cluster once its
 * database is ready, which can take a moment after the install finishes.
 */
export async function nameNewCluster(connectionId: string, name: string): Promise<boolean> {
  const cleaned = name.trim();
  if (!cleaned) return false;
  for (let attempt = 0; attempt < ATTEMPTS; attempt += 1) {
    try {
      const clusters = await listClusters();
      const found = clusters.clusters.find((cluster) => cluster.connection_ids.includes(connectionId));
      if (found) {
        await renameCluster(found.cluster_id, cleaned);
        return true;
      }
    } catch {
      // Not answering yet.
    }
    await new Promise((resolve) => setTimeout(resolve, WAIT_MS));
  }
  return false;
}
