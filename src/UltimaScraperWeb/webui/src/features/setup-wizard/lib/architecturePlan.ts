import type { BackendCluster, ClusterHosts, ClusterNode, NodeRole, NodeState } from '../../../api/webui';

/** What the install puts where, as the Review step knows it. */
export interface PlannedInstall {
  hostName: string;
  location: 'Local' | 'Remote';
  address: string | null;
  installs: { backend: boolean; workers: boolean; webui: boolean; postgres: boolean; redis: boolean };
  /** An existing PostgreSQL or Redis the host uses ("host:port"), when not installed on it. */
  postgres: string | null;
  redis: string | null;
  /**
   * The cluster it ends up in: an existing one (by id, or by a connection in
   * it), a new one (named), or none (only PostgreSQL or Redis).
   */
  target:
    | { kind: 'existing'; clusterId: string | null; connectionId: string | null }
    | { kind: 'new'; name: string }
    | { kind: 'none' };
}

/** One service a host runs, with what identifies it. */
export interface DiagramNode {
  role: NodeRole;
  identifier: string | null;
  state: NodeState | null;
  isSelf: boolean;
}

export interface DiagramHost {
  key: string;
  name: string;
  address: string | null;
  roles: NodeRole[];
  /** The reported services behind roles; empty for a planned host. */
  nodes: DiagramNode[];
  isNew: boolean;
}

export interface DiagramService {
  label: string;
  isNew: boolean;
  /** The host it runs on, when the cluster reports it. */
  host: string | null;
}

export interface DiagramCluster {
  key: string;
  name: string;
  hosts: DiagramHost[];
  postgres: DiagramService | null;
  redis: DiagramService | null;
  isTarget: boolean;
  isNew: boolean;
}

/** What names a service: the backend id, the WebUI client, or the service's address. */
function nodeIdentifier(node: ClusterNode): string | null {
  if (node.role === 'webui') return node.client_id ?? node.connection_id ?? node.name;
  if (node.role === 'postgres' || node.role === 'redis') return node.detail ?? node.name;
  return node.backend_id ?? node.client_id ?? node.name;
}

function existingClusters(
  clusters: BackendCluster[],
  hosts: Record<string, ClusterHosts | null>,
): DiagramCluster[] {
  return clusters.map((cluster) => {
    const described = hosts[cluster.cluster_id];
    const service = (role: 'postgres' | 'redis'): DiagramService | null => {
      for (const host of described?.hosts ?? []) {
        const node = host.nodes.find((item) => item.role === role);
        if (node) return { label: node.detail ?? node.name, isNew: false, host: host.name };
      }
      return null;
    };
    return {
      key: cluster.cluster_id,
      name: described?.name || cluster.name || `Cluster ${cluster.cluster_id.slice(0, 8)}`,
      hosts: (described?.hosts ?? [])
        .map((host) => ({
          key: host.key,
          name: host.name,
          address: host.address,
          roles: host.roles.filter((role) => role !== 'postgres' && role !== 'redis'),
          nodes: host.nodes
            .filter((node) => node.role !== 'postgres' && node.role !== 'redis')
            .map((node) => ({
              role: node.role,
              identifier: nodeIdentifier(node),
              state: node.state,
              isSelf: node.is_self,
            })),
          isNew: false,
        }))
        .filter((host) => host.roles.length > 0),
      postgres: service('postgres'),
      redis: service('redis'),
      isTarget: false,
      isNew: false,
    };
  });
}

/** The clusters this WebUI manages, with this install drawn into them. */
export function buildDiagram(
  plan: PlannedInstall | null,
  clusters: BackendCluster[],
  hosts: Record<string, ClusterHosts | null>,
): { clusters: DiagramCluster[]; standalone: DiagramHost | null } {
  const drawn = existingClusters(clusters, hosts);
  // No install planned: the system as it is.
  if (!plan) return { clusters: drawn, standalone: null };
  const roles: NodeRole[] = (['backend', 'workers', 'webui'] as const).filter((role) => plan.installs[role]);
  const newHost: DiagramHost = {
    key: 'new-host',
    name: plan.hostName,
    address: plan.address,
    roles,
    nodes: [],
    isNew: true,
  };
  const services = {
    postgres: plan.installs.postgres
      ? { label: `on ${plan.hostName}`, isNew: true, host: plan.hostName }
      : plan.postgres
        ? { label: plan.postgres, isNew: false, host: null }
        : null,
    redis: plan.installs.redis
      ? { label: `on ${plan.hostName}`, isNew: true, host: plan.hostName }
      : plan.redis
        ? { label: plan.redis, isNew: false, host: null }
        : null,
  };

  if (plan.target.kind === 'none') return { clusters: drawn, standalone: { ...newHost, roles: [] } };
  if (plan.target.kind === 'new') {
    drawn.push({
      key: 'new-cluster',
      name: plan.target.name || 'New cluster',
      hosts: [newHost],
      ...services,
      isTarget: true,
      isNew: true,
    });
    return { clusters: drawn, standalone: null };
  }
  const { clusterId, connectionId } = plan.target;
  const targetId =
    clusterId ?? clusters.find((cluster) => connectionId && cluster.connection_ids.includes(connectionId))?.cluster_id;
  const target = drawn.find((cluster) => cluster.key === targetId);
  if (!target) {
    drawn.push({
      key: 'joined-cluster',
      name: 'Existing cluster',
      hosts: [newHost],
      ...services,
      isTarget: true,
      isNew: false,
    });
    return { clusters: drawn, standalone: null };
  }
  target.isTarget = true;
  const same = target.hosts.find((host) => plan.address && host.address === plan.address);
  if (same) {
    same.isNew = true;
    same.roles = [...new Set([...same.roles, ...roles])];
  } else {
    target.hosts.push(newHost);
  }
  target.postgres = services.postgres?.isNew ? services.postgres : target.postgres ?? services.postgres;
  target.redis = services.redis?.isNew ? services.redis : target.redis ?? services.redis;
  return { clusters: drawn, standalone: null };
}

/** One service drawn in a tier, saying where it runs. */
export interface TierCard {
  key: string;
  role: NodeRole;
  host: string;
  address: string | null;
  /** Every cluster it is part of; a WebUI can serve several. */
  clusters: string[];
  identifier: string | null;
  state: NodeState | null;
  isNew: boolean;
  isSelf: boolean;
}

export interface DiagramTiers {
  webuis: TierCard[];
  backends: TierCard[];
  workers: TierCard[];
  data: TierCard[];
}

/**
 * The system top-down: every WebUI first, then backends, workers and the
 * PostgreSQL and Redis they use, each labelled with its cluster and identifier.
 */
export function buildTiers(
  clusters: DiagramCluster[],
  standalone: DiagramHost | null,
  plan: PlannedInstall | null,
): DiagramTiers {
  const tiers: DiagramTiers = { webuis: [], backends: [], workers: [], data: [] };
  const tierFor = (role: NodeRole) =>
    role === 'webui' ? tiers.webuis : role === 'backend' ? tiers.backends : role === 'workers' ? tiers.workers : tiers.data;
  const add = (card: TierCard) => {
    const tier = tierFor(card.role);
    // The same service reported by several clusters is one box naming them all.
    const same = tier.find((existing) => existing.key === card.key);
    if (same) {
      same.clusters = [...new Set([...same.clusters, ...card.clusters])];
      same.isNew ||= card.isNew;
    } else {
      tier.push(card);
    }
  };

  for (const cluster of clusters) {
    for (const host of cluster.hosts) {
      const nodes: DiagramNode[] = host.nodes.length
        ? host.nodes
        : host.roles.map((role) => ({ role, identifier: null, state: null, isSelf: false }));
      for (const node of nodes) {
        add({
          key: `${node.role}:${host.key}:${node.identifier ?? ''}`,
          role: node.role,
          host: host.name,
          address: host.address,
          clusters: [cluster.name],
          identifier: node.identifier,
          state: node.state,
          isNew: host.isNew,
          isSelf: node.isSelf,
        });
      }
    }
    for (const [role, service] of [['postgres', cluster.postgres], ['redis', cluster.redis]] as const) {
      if (!service) continue;
      add({
        key: `${role}:${service.label}`,
        role,
        host: service.host ?? 'external',
        address: null,
        clusters: [cluster.name],
        identifier: service.label,
        state: null,
        isNew: service.isNew,
        isSelf: false,
      });
    }
  }

  if (standalone) {
    for (const role of ['postgres', 'redis'] as const) {
      if (!plan?.installs[role]) continue;
      add({
        key: `${role}:standalone`,
        role,
        host: standalone.name,
        address: standalone.address,
        clusters: [],
        identifier: 'for other hosts',
        state: null,
        isNew: true,
        isSelf: false,
      });
    }
  }

  if (!tiers.webuis.some((card) => card.isSelf)) {
    tiers.webuis.unshift({
      key: 'webui:self',
      role: 'webui',
      host: 'This WebUI',
      address: null,
      clusters: clusters.filter((cluster) => !cluster.isNew).map((cluster) => cluster.name),
      identifier: null,
      state: null,
      isNew: false,
      isSelf: true,
    });
  }
  return tiers;
}
