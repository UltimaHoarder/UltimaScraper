import type { BackendCluster, BackendClusters, BackendConnection } from '../../../api/webui';

export interface ConnectionGroup {
  /** Null for backends that stand alone. */
  cluster: BackendCluster | null;
  connections: BackendConnection[];
}

/**
 * Clusters first, then the backends that stand alone. A cluster is shown as
 * one even with a single connection here: its other members and workers are
 * still part of it.
 */
export function groupConnections(
  connections: BackendConnection[],
  clusters: BackendClusters | null,
): ConnectionGroup[] {
  const byId = new Map(connections.map((connection) => [connection.id, connection]));
  const placed = new Set<string>();
  const groups: ConnectionGroup[] = [];
  for (const cluster of clusters?.clusters ?? []) {
    const members = cluster.connection_ids.flatMap((id) => byId.get(id) ?? []);
    if (members.length === 0) continue;
    members.forEach((member) => placed.add(member.id));
    groups.push({ cluster, connections: members });
  }
  const alone = connections.filter((connection) => !placed.has(connection.id));
  if (alone.length > 0) groups.push({ cluster: null, connections: alone });
  return groups;
}

/** A reachable connection in the same cluster, to open while this one is down. */
export function reachableAlternative(
  connectionId: string,
  clusters: BackendClusters | null,
): string | null {
  if (!clusters) return null;
  const reachable = new Set(clusters.members.filter((member) => member.reachable).map((member) => member.connection_id));
  if (reachable.has(connectionId)) return null;
  const cluster = clusters.clusters.find((entry) => entry.connection_ids.includes(connectionId));
  return cluster?.connection_ids.find((id) => id !== connectionId && reachable.has(id)) ?? null;
}

export type NodeLink =
  | { kind: 'open'; connectionId: string }
  | { kind: 'add'; name: string; apiUrl: string | null };

/** How this WebUI reaches a backend listed by a cluster member. */
export function nodeLink(backendId: string, clusters: BackendClusters | null): NodeLink {
  const member = clusters?.members.find((entry) => entry.identity?.backend_id === backendId);
  if (member) return { kind: 'open', connectionId: member.connection_id };
  const suggestion = clusters?.clusters
    .flatMap((cluster) => cluster.suggestions)
    .find((entry) => entry.backend_id === backendId);
  return { kind: 'add', name: backendId, apiUrl: suggestion?.api_url ?? null };
}

/** The Backends page with the add form prefilled. */
export function addConnectionHref(name: string, apiUrl: string | null): string {
  const query = new URLSearchParams({ add: name });
  if (apiUrl) query.set('url', apiUrl);
  return `/connections?${query.toString()}`;
}

/**
 * The member to open for a cluster: the preferred one (e.g. the one in use)
 * while it is reachable, else the first reachable member, else the first.
 */
export function pickClusterMember(
  cluster: BackendCluster,
  clusters: BackendClusters | null,
  preferred: string | null,
): string | null {
  const reachable = new Set(clusters?.members.filter((member) => member.reachable).map((member) => member.connection_id));
  const ids = cluster.connection_ids;
  if (preferred && ids.includes(preferred) && reachable.has(preferred)) return preferred;
  return ids.find((id) => reachable.has(id)) ?? ids[0] ?? null;
}

/** The name a cluster has until this WebUI names it (the server's default too). */
export const defaultClusterName = (clusterId: string) => `Cluster ${clusterId.slice(0, 8)}`;
