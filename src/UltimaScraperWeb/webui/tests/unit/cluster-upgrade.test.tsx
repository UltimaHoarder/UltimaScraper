import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { RegisterBackend } from '../../src/features/system/systemFleetRegisterData';
import { ClusterSection } from '../../src/features/system/components/ClusterSection';
import { ClusterUpgradeModal } from '../../src/features/system/components/ClusterUpgradeModal';

const deployment = (id: string, name: string, kind: 'local' | 'ssh', host?: string) => ({
  id,
  name,
  target: host ?? 'local',
  details: {
    kind,
    host: host ?? null,
    username: kind === 'ssh' ? 'ultima' : null,
    install_dir: '~/ultimascraper',
    project: `usr-${name}`,
    version: 'edge',
    image_source: 'registry',
    image_prefix: 'forgejo.example/org/ultimascraper',
    components: { backend: kind === 'local', worker: true, postgres: false, redis: false, webui: false },
  },
  connection_id: null,
});

function stub(routes: Record<string, (init?: RequestInit) => Response>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const match = Object.keys(routes).find((key) => url.split('?')[0].endsWith(key));
    return match ? routes[match](init) : new Response('{}', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('ClusterUpgradeModal', () => {
  it('upgrades every node to one version with the same SSH credentials', async () => {
    const fetchMock = stub({
      '/clusters/c-1/deployments': () =>
        new Response(
          JSON.stringify([
            deployment('dev', 'devbox', 'local'),
            deployment('alpha', 'alpha', 'ssh', '192.168.50.120'),
            deployment('nas', 'nas01', 'ssh', '192.168.50.40'),
          ]),
        ),
      '/clusters/c-1/upgrade': () => new Response(JSON.stringify({ id: 'run-1' }), { status: 202 }),
      '/installs/run-1': () =>
        new Response(JSON.stringify({ id: 'run-1', state: 'running', events: [{ seq: 1, at: 0, kind: 'step', message: 'Upgrading devbox (1 of 3)' }] })),
    });
    render(<ClusterUpgradeModal clusterId="c-1" onClose={() => undefined} />);

    expect(await screen.findByText('alpha')).toBeInTheDocument();
    expect(screen.getByLabelText('Version')).toHaveValue('edge');
    fireEvent.change(screen.getByLabelText('Version'), { target: { value: '0.2.0' } });
    // One password for both hosts.
    fireEvent.change(screen.getByLabelText(/Password for ultima@192.168.50.120, ultima@192.168.50.40/), {
      target: { value: 'secret' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Upgrade 3 nodes' }));

    expect(await screen.findByText(/Upgrading devbox \(1 of 3\)/)).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/clusters/c-1/upgrade'));
    const body = JSON.parse(String(call?.[1]?.body));
    expect(body.version).toBe('0.2.0');
    expect(body.deployment_ids).toEqual(['dev', 'alpha', 'nas']);
    expect(body.credentials).toEqual({ dev: {}, alpha: { password: 'secret' }, nas: { password: 'secret' } });
  });

  it('asks per host when the credentials differ, and leaves out unticked nodes', async () => {
    const fetchMock = stub({
      '/clusters/c-1/deployments': () =>
        new Response(
          JSON.stringify([
            deployment('alpha', 'alpha', 'ssh', '192.168.50.120'),
            deployment('nas', 'nas01', 'ssh', '192.168.50.40'),
            deployment('pc', 'pc', 'ssh', '192.168.1.30'),
          ]),
        ),
      '/clusters/c-1/upgrade': () => new Response(JSON.stringify({ id: 'run-2' }), { status: 202 }),
      '/installs/run-2': () => new Response(JSON.stringify({ id: 'run-2', state: 'running', events: [] })),
    });
    render(<ClusterUpgradeModal clusterId="c-1" onClose={() => undefined} />);

    fireEvent.click(await screen.findByRole('checkbox', { name: /pc/ }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Use the same SSH credentials for every host' }));
    fireEvent.change(screen.getByLabelText('Password for ultima@192.168.50.120'), { target: { value: 'a' } });
    fireEvent.change(screen.getByLabelText('Password for ultima@192.168.50.40'), { target: { value: 'b' } });
    fireEvent.click(screen.getByRole('button', { name: 'Upgrade 2 nodes' }));

    await screen.findByLabelText('Cluster upgrade');
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/clusters/c-1/upgrade'));
    const body = JSON.parse(String(call?.[1]?.body));
    expect(body.deployment_ids).toEqual(['alpha', 'nas']);
    expect(body.credentials).toEqual({ alpha: { password: 'a' }, nas: { password: 'b' } });
  });

  it('says when this WebUI manages none of the nodes', async () => {
    stub({ '/clusters/c-1/deployments': () => new Response('[]') });
    render(<ClusterUpgradeModal clusterId="c-1" onClose={() => undefined} />);

    expect(await screen.findByText(/installed none of this cluster/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Upgrade 0 nodes' })).toBeDisabled();
  });
});

describe('ClusterSection', () => {
  it('lists the WebUIs connected to the cluster next to its nodes', async () => {
    const recent = new Date(Date.now() - 20_000).toISOString();
    stub({
      '/clusters/c-1/clients': () =>
        new Response(
          JSON.stringify([
            { id: 'a', name: 'WebUI on alpha', kind: 'webui', created_at: recent, last_seen_at: recent, last_address: '192.168.50.120', version: '0.1.0', revoked_at: null, is_self: false },
            { id: 'b', name: 'WebUI on devbox', kind: 'webui', created_at: recent, last_seen_at: recent, last_address: null, version: null, revoked_at: null, is_self: true },
            { id: 'c', name: 'Old WebUI', kind: 'webui', created_at: recent, last_seen_at: recent, last_address: null, version: null, revoked_at: recent, is_self: false },
          ]),
        ),
    });
    const backend: RegisterBackend = {
      backendId: 'hoarder01',
      label: 'hoarder01',
      hostname: 'hoarder01',
      status: 'online',
      version: '0.1.0',
      maxWorkers: 8,
      activeWorkers: 0,
      pendingJobs: 0,
      lastSeen: recent,
      heartbeatAge: 2,
      health: 'healthy',
      isLocal: true,
      clusterId: 'c-1',
      workers: [],
      mounts: [],
    };
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <ClusterSection
            backends={[backend]}
            clusterId="c-1"
            clustersData={undefined}
            databases={[]}
            settingsData={undefined}
            onConfigureBackend={() => undefined}
            onInspectBackend={() => undefined}
            onInspectWorker={() => undefined}
            onNavigateToTab={() => undefined}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const alpha = (await screen.findByText('WebUI on alpha')).closest('tr') as HTMLElement;
    expect(within(alpha).getByText('WebUI · client')).toBeInTheDocument();
    expect(within(alpha).getByText(/192.168.50.120/)).toBeInTheDocument();
    expect(within(alpha).getByText('Healthy')).toBeInTheDocument();
    expect(screen.getByText(/THIS WEBUI/)).toBeInTheDocument();
    expect(screen.queryByText('Old WebUI')).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Cluster Fleet Nodes \(1\) · WebUIs \(2\)/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Manage cluster' })).toBeInTheDocument();
  });
});
