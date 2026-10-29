import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { BackendClusters } from '../../src/api/webui';
import { ConnectionSwitcher } from '../../src/features/connections/ConnectionSwitcher';

const CONNECTIONS = ['nas', 'nas2', 'pi'].map((id) => ({
  id,
  name: id.toUpperCase(),
  base_url: `http://${id}:21121`,
  tls_verify: true,
  managed: false,
  has_token: true,
  trust_plugins: false,
}));

const identity = (backend_id: string, cluster_id: string) => ({
  backend_id, instance: 'start-1', cluster_id, api_url: null, version: '1.0', api_version: 1,
});

const CLUSTERS: BackendClusters = {
  members: [
    { connection_id: 'nas', name: 'NAS', reachable: true, identity: identity('nas-1', 'c1aaaaaaaa'), seen_at: 1 },
    { connection_id: 'nas2', name: 'NAS2', reachable: false, identity: identity('nas-2', 'c1aaaaaaaa'), seen_at: 1 },
    { connection_id: 'pi', name: 'PI', reachable: true, identity: identity('pi', 'c9'), seen_at: 1 },
  ],
  clusters: [
    { cluster_id: 'c1aaaaaaaa', connection_ids: ['nas', 'nas2'], suggestions: [], conflicting_backend_ids: [] },
    { cluster_id: 'c9', connection_ids: ['pi'], suggestions: [], conflicting_backend_ids: [] },
  ],
};

describe('ConnectionSwitcher', () => {
  beforeEach(() => {
      window.history.replaceState(null, '', '/b/nas/jobs');
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/connections')) return new Response(JSON.stringify(CONNECTIONS));
      if (url.endsWith('/clusters')) return new Response(JSON.stringify(CLUSTERS));
      return new Response('{}', { status: 404 });
    }));
  });

  afterEach(() => {
      window.history.replaceState(null, '', '/');
    vi.unstubAllGlobals();
  });

  it('lists backends that share a database under their cluster', async () => {
    render(<ConnectionSwitcher />);

    fireEvent.click(await screen.findByRole('button', { name: /NAS/ }));
    const menu = screen.getByRole('menu');
    await within(menu).findByText('Cluster c1aaaaaa');

    const entries = [...menu.querySelectorAll('.connection-switcher-group, a[role="menuitem"]')].map((item) => item.textContent?.trim());
    // Every cluster is listed as one, with a way to open it on a healthy member.
    expect(entries).toEqual([
      'Cluster c1aaaaaa',
      'Open cluster',
      'NAS',
      'NAS2 · unreachable',
      'Cluster c9',
      'Open cluster',
      'PI',
    ]);
    expect(within(menu).getByRole('menuitem', { name: 'NAS' })).toHaveAttribute('aria-current', 'true');
  });
});
