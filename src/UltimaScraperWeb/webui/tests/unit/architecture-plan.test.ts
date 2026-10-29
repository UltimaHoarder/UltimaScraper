import { describe, expect, it } from 'vitest';

import type { BackendCluster, ClusterHosts } from '../../src/api/webui';
import { buildDiagram, buildTiers, type PlannedInstall } from '../../src/features/setup-wizard/lib/architecturePlan';

const CLUSTERS: BackendCluster[] = [
  { cluster_id: 'home', name: 'Home', connection_ids: ['dev'], suggestions: [], conflicting_backend_ids: [] },
  { cluster_id: 'lab', name: 'Lab', connection_ids: ['lab'], suggestions: [], conflicting_backend_ids: [] },
];

const node = (role: 'backend' | 'workers' | 'webui' | 'postgres' | 'redis', detail: string | null = null) => ({
  role,
  name: role,
  state: 'healthy' as const,
  version: null,
  detail,
  last_seen: null,
  backend_id: null,
  client_id: null,
  connection_id: null,
  is_self: false,
  installed_only: false,
});

const HOME: ClusterHosts = {
  cluster_id: 'home',
  name: 'Home',
  answered_by: 'dev',
  error: null,
  hosts: [
    {
      key: '192.168.50.60',
      name: 'hoarder01',
      address: '192.168.50.60',
      roles: ['backend', 'workers', 'redis'],
      state: 'healthy',
      deployment_id: null,
      nodes: [node('backend'), node('workers'), node('redis', 'localhost:6379')],
    },
    {
      key: '192.168.50.40',
      name: 'nas01',
      address: '192.168.50.40',
      roles: ['postgres'],
      state: 'healthy',
      deployment_id: null,
      nodes: [node('postgres', '192.168.50.40:30432')],
    },
  ],
};

const plan = (overrides: Partial<PlannedInstall>): PlannedInstall => ({
  hostName: 'alpha',
  location: 'Remote',
  address: '192.168.50.120',
  installs: { backend: false, workers: true, webui: false, postgres: false, redis: false },
  postgres: '192.168.50.40:30432',
  redis: '192.168.50.60:6379',
  target: { kind: 'existing', clusterId: 'home', connectionId: null },
  ...overrides,
});

describe('buildDiagram', () => {
  it('adds the new host to the cluster it joins, next to the other clusters', () => {
    const { clusters } = buildDiagram(plan({}), CLUSTERS, { home: HOME, lab: null });

    expect(clusters.map((cluster) => [cluster.name, cluster.isTarget])).toEqual([
      ['Home', true],
      ['Lab', false],
    ]);
    const home = clusters[0];
    // Hosts only with backends, workers or a WebUI; PostgreSQL and Redis are the cluster's services.
    expect(home.hosts.map((host) => [host.name, host.roles, host.isNew])).toEqual([
      ['hoarder01', ['backend', 'workers'], false],
      ['alpha', ['workers'], true],
    ]);
    expect(home.postgres).toEqual({ label: '192.168.50.40:30432', isNew: false, host: 'nas01' });
    expect(home.redis).toEqual({ label: 'localhost:6379', isNew: false, host: 'hoarder01' });
  });

  it('finds the cluster from the connection a worker-only host works for', () => {
    const { clusters } = buildDiagram(
      plan({ target: { kind: 'existing', clusterId: null, connectionId: 'lab' } }),
      CLUSTERS,
      {},
    );

    expect(clusters.find((cluster) => cluster.isTarget)?.name).toBe('Lab');
  });

  it('draws a new cluster with its services on the new host', () => {
    const { clusters } = buildDiagram(
      plan({
        installs: { backend: true, workers: true, webui: false, postgres: true, redis: true },
        postgres: null,
        redis: null,
        target: { kind: 'new', name: 'Second' },
      }),
      CLUSTERS,
      {},
    );

    const created = clusters.find((cluster) => cluster.isNew);
    expect(created?.name).toBe('Second');
    expect(created?.postgres).toEqual({ label: 'on alpha', isNew: true, host: 'alpha' });
    expect(clusters).toHaveLength(3);
  });

  it('keeps PostgreSQL or Redis on their own out of every cluster', () => {
    const { standalone, clusters } = buildDiagram(
      plan({ installs: { backend: false, workers: false, webui: false, postgres: true, redis: false }, target: { kind: 'none' } }),
      CLUSTERS,
      {},
    );

    expect(standalone?.name).toBe('alpha');
    expect(clusters.every((cluster) => !cluster.isTarget)).toBe(true);
  });
});

describe('buildTiers', () => {
  const webui = (clientId: string, isSelf = false) => ({ ...node('webui'), client_id: clientId, is_self: isSelf });
  const LAB: ClusterHosts = {
    cluster_id: 'lab',
    name: 'Lab',
    answered_by: 'lab',
    error: null,
    hosts: [
      {
        key: '192.168.50.10',
        name: 'desk',
        address: '192.168.50.10',
        roles: ['webui', 'backend'],
        state: 'healthy',
        deployment_id: null,
        nodes: [webui('webui-desk', true), { ...node('backend'), backend_id: 'lab-backend' }],
      },
    ],
  };
  const homeWithWebui: ClusterHosts = {
    ...HOME,
    hosts: [
      ...HOME.hosts,
      {
        key: '192.168.50.10',
        name: 'desk',
        address: '192.168.50.10',
        roles: ['webui'],
        state: 'healthy',
        deployment_id: null,
        nodes: [webui('webui-desk', true)],
      },
      {
        key: '192.168.50.11',
        name: 'laptop',
        address: '192.168.50.11',
        roles: ['webui'],
        state: 'healthy',
        deployment_id: null,
        nodes: [webui('webui-laptop')],
      },
    ],
  };

  it('puts every WebUI on top once, naming each cluster and identifier below', () => {
    const { clusters, standalone } = buildDiagram(null, CLUSTERS, { home: homeWithWebui, lab: LAB });
    const tiers = buildTiers(clusters, standalone, null);

    expect(tiers.webuis.map((card) => [card.host, card.identifier, card.clusters, card.isSelf])).toEqual([
      ['desk', 'webui-desk', ['Home', 'Lab'], true],
      ['laptop', 'webui-laptop', ['Home'], false],
    ]);
    expect(tiers.backends.map((card) => [card.host, card.identifier, card.clusters])).toEqual([
      ['hoarder01', 'backend', ['Home']],
      ['desk', 'lab-backend', ['Lab']],
    ]);
    expect(tiers.data.map((card) => [card.role, card.identifier, card.host, card.clusters])).toEqual([
      ['postgres', '192.168.50.40:30432', 'nas01', ['Home']],
      ['redis', 'localhost:6379', 'hoarder01', ['Home']],
    ]);
  });

  it('adds this WebUI when no reported WebUI is it', () => {
    const { clusters, standalone } = buildDiagram(null, CLUSTERS, { home: HOME, lab: null });
    const tiers = buildTiers(clusters, standalone, null);

    expect(tiers.webuis).toHaveLength(1);
    expect(tiers.webuis[0]).toMatchObject({ host: 'This WebUI', isSelf: true, clusters: ['Home', 'Lab'] });
  });

  it('marks what a planned install adds in its tiers', () => {
    const { clusters, standalone } = buildDiagram(plan({}), CLUSTERS, { home: HOME, lab: null });
    const tiers = buildTiers(clusters, standalone, plan({}));

    expect(tiers.workers.find((card) => card.isNew)).toMatchObject({ host: 'alpha', clusters: ['Home'] });
  });
});
