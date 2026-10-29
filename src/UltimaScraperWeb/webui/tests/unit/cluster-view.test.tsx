import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { BackendClusters, BackendConnection } from '../../src/api/webui';
import { ConnectionsPage } from '../../src/features/connections/ConnectionsPage';
import {
  addConnectionHref,
  groupConnections,
  nodeLink,
  reachableAlternative,
} from '../../src/features/connections/lib/clusterView';

function connection(id: string): BackendConnection {
  return {
    id,
    name: id.toUpperCase(),
    base_url: `http://${id}:21121`,
    tls_verify: true,
    managed: false,
    has_token: true,
    trust_plugins: false,
  };
}

const identity = (backend_id: string, cluster_id: string | null) => ({
  backend_id,
  instance: 'start-1',
  cluster_id,
  api_url: null,
  version: '1.0',
  api_version: 1,
});

const CONNECTIONS = ['nas', 'nas2', 'lone', 'old'].map(connection);
const CLUSTERS: BackendClusters = {
  members: [
    { connection_id: 'nas', name: 'NAS', reachable: false, identity: identity('nas-1', 'c1aaaaaaaa'), seen_at: 1 },
    { connection_id: 'nas2', name: 'NAS2', reachable: true, identity: identity('nas-2', 'c1aaaaaaaa'), seen_at: 1 },
    { connection_id: 'lone', name: 'LONE', reachable: true, identity: identity('lone', 'c9'), seen_at: 1 },
    { connection_id: 'old', name: 'OLD', reachable: true, identity: null, seen_at: null },
  ],
  clusters: [
    {
      cluster_id: 'c1aaaaaaaa',
      connection_ids: ['nas', 'nas2'],
      suggestions: [
        { backend_id: 'nas-3', hostname: 'nas3', status: 'online', last_seen: '', api_url: 'http://nas3:21121' },
        { backend_id: 'nas-4', hostname: 'nas4', status: 'online', last_seen: '', api_url: null },
      ],
      conflicting_backend_ids: [],
    },
    { cluster_id: 'c9', connection_ids: ['lone'], suggestions: [], conflicting_backend_ids: [] },
  ],
};

describe('cluster view', () => {
  it('shows every cluster, even with one connection here, then the backends that stand alone', () => {
    const groups = groupConnections(CONNECTIONS, CLUSTERS);

    expect(groups.map((group) => [group.cluster?.cluster_id ?? null, group.connections.map((c) => c.id)])).toEqual([
      ['c1aaaaaaaa', ['nas', 'nas2']],
      ['c9', ['lone']],
      [null, ['old']],
    ]);
    // Until the clusters answer, everything is listed as before.
    expect(groupConnections(CONNECTIONS, null)).toEqual([{ cluster: null, connections: CONNECTIONS }]);
  });

  it('offers a reachable member of the same cluster while one is down', () => {
    expect(reachableAlternative('nas', CLUSTERS)).toBe('nas2');
    expect(reachableAlternative('nas2', CLUSTERS)).toBeNull();
    expect(reachableAlternative('lone', CLUSTERS)).toBeNull();
  });

  it('links each fleet node to its connection, or to adding one', () => {
    expect(nodeLink('nas-2', CLUSTERS)).toEqual({ kind: 'open', connectionId: 'nas2' });
    expect(nodeLink('nas-3', CLUSTERS)).toEqual({ kind: 'add', name: 'nas-3', apiUrl: 'http://nas3:21121' });
    expect(nodeLink('elsewhere', CLUSTERS)).toEqual({ kind: 'add', name: 'elsewhere', apiUrl: null });
    expect(addConnectionHref('nas-3', 'http://nas3:21121')).toBe('/connections?add=nas-3&url=http%3A%2F%2Fnas3%3A21121');
  });
});

describe('Backends page clusters', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.replaceState(null, '', '/');
  });

  function stubServer() {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/connections')) return new Response(JSON.stringify(CONNECTIONS));
        if (url.endsWith('/clusters')) return new Response(JSON.stringify(CLUSTERS));
        if (url.endsWith('/deployments')) return new Response('[]');
        if (url.includes('/clusters/c1aaaaaaaa/overview')) {
          return new Response(
            JSON.stringify({
              cluster_id: 'c1aaaaaaaa',
              name: 'Cluster c1aaaaaa',
              backends: [
                { backend_id: 'nas-2', name: 'nas2', address: 'http://nas2:21121', version: '1.0', status: 'online', last_seen: '', connection_id: 'nas2' },
                { backend_id: 'nas-3', name: 'nas3', address: 'http://nas3:21121', version: '1.0', status: 'online', last_seen: '', connection_id: null },
              ],
              worker_hosts: [],
              answered_by: 'nas2',
              error: null,
            }),
          );
        }
        if (url.endsWith('/test')) {
          return new Response(JSON.stringify({ reachable: true, authenticated: true, message: 'Connected', latency_ms: 1 }));
        }
        return new Response('{}', { status: 404 });
      }),
    );
  }

  it('groups members, points at a reachable one and prefills other backends in the cluster', async () => {
    stubServer();
    render(<ConnectionsPage />);

    const cluster = await screen.findByRole('region', { name: 'Cluster c1aaaaaa' });
    expect(within(cluster).getByText('NAS2')).toBeInTheDocument();
    expect(within(cluster).getByRole('link', { name: 'Open NAS2' })).toHaveAttribute('href', '/b/nas2/');
    // A cluster with one connection here is still a cluster.
    expect(within(screen.getByRole('region', { name: 'Cluster c9' })).getByText('LONE')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Independent backends' })).getByText('OLD')).toBeInTheDocument();

    // API servers this WebUI is not connected to (from the overview) can be added.
    fireEvent.click(await within(cluster).findByRole('button', { name: 'Add' }));
    expect(screen.getByLabelText('Name')).toHaveValue('nas-3');
    expect(screen.getByLabelText(/^Address/)).toHaveValue('http://nas3:21121');
  });

  it('opens the add form prefilled from the fleet page link', async () => {
    stubServer();
    window.history.replaceState(null, '', addConnectionHref('nas-3', 'http://nas3:21121'));
    render(<ConnectionsPage />);

    expect(await screen.findByLabelText('Name')).toHaveValue('nas-3');
    expect(screen.getByLabelText(/^Address/)).toHaveValue('http://nas3:21121');
  });
});
