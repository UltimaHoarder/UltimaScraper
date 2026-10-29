import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { BackendClusters, ClusterHosts } from '../../src/api/webui';
import { pickConnection, rememberConnection } from '../../src/features/connections/lib/lastConnection';
import { ClusterSection } from '../../src/features/system/components/ClusterSection';

const recent = new Date(Date.now() - 20_000).toISOString();

const node = (overrides: Partial<ClusterHosts['hosts'][number]['nodes'][number]>) => ({
  role: 'backend' as const,
  name: 'x',
  state: 'healthy' as const,
  version: '0.1.0',
  detail: null,
  last_seen: recent,
  backend_id: null,
  client_id: null,
  connection_id: null,
  is_self: false,
  installed_only: false,
  ...overrides,
});

const HOSTS: ClusterHosts = {
  cluster_id: 'c-1',
  name: 'Home',
  answered_by: 'default',
  error: null,
  hosts: [
    {
      key: '192.168.50.120',
      name: 'alpha',
      address: '192.168.50.120',
      roles: ['workers', 'webui'],
      state: 'healthy',
      deployment_id: 'd-1',
      nodes: [
        node({ role: 'workers', name: 'alpha-9d4b85', backend_id: 'alpha-9d4b85', detail: '4/4 busy · 0 pending' }),
        node({ role: 'webui', name: 'WebUI on alpha', detail: '192.168.50.120' }),
      ],
    },
    {
      key: '192.168.1.20',
      name: 'hoarder01',
      address: '192.168.1.20',
      roles: ['backend', 'workers', 'webui', 'redis'],
      state: 'healthy',
      deployment_id: null,
      nodes: [
        node({ role: 'backend', name: 'hoarder01', backend_id: 'hoarder01' }),
        node({ role: 'workers', name: 'hoarder01', backend_id: 'hoarder01' }),
        node({ role: 'webui', name: 'WebUI on devbox', is_self: true }),
        node({ role: 'redis', name: 'Redis', detail: 'localhost:6379', last_seen: null, version: null }),
      ],
    },
  ],
};

const CLUSTERS = (main: string | null): BackendClusters => ({
  members: [],
  clusters: [
    { cluster_id: 'c-1', name: 'Home', connection_ids: ['default'], suggestions: [], conflicting_backend_ids: [] },
    { cluster_id: 'c-2', name: 'Lab', connection_ids: ['lab'], suggestions: [], conflicting_backend_ids: [] },
  ],
  main_cluster_id: main,
});

function stub(routes: Record<string, (init?: RequestInit) => Response>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).split('?')[0];
    const match = Object.keys(routes).find((key) => url.endsWith(key));
    return match ? routes[match](init) : new Response('{}', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function renderSection(clustersData: BackendClusters, onInspectBackend = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ClusterSection
          backends={[]}
          clusterId="c-1"
          availableClusters={[
            { clusterId: 'c-1', nodeCount: 2, label: 'Home', isCurrent: true },
            { clusterId: 'c-2', nodeCount: 1, label: 'Lab', connectionId: 'lab' },
          ]}
          clustersData={clustersData}
          databases={[]}
          settingsData={undefined}
          onConfigureBackend={() => undefined}
          onInspectBackend={onInspectBackend}
          onInspectWorker={() => undefined}
          onNavigateToTab={() => undefined}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onInspectBackend;
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe('Cluster hosts', () => {
  it('lists hosts with their roles, and their nodes when expanded', async () => {
    stub({ '/clusters/c-1/hosts': () => new Response(JSON.stringify(HOSTS)) });
    const onInspect = renderSection(CLUSTERS('c-1'));

    const table = await screen.findByRole('table', { name: 'Hosts' });
    expect(screen.getByRole('heading', { name: 'Hosts (2)' })).toBeInTheDocument();
    expect(within(table).getByRole('columnheader', { name: 'Config' })).toBeInTheDocument();
    expect(within(table).getByRole('columnheader', { name: 'Inspect' })).toBeInTheDocument();
    const alpha = within(table).getByRole('button', { name: /^alpha/ }).closest('tr') as HTMLElement;
    expect(within(alpha).getByText('Workers')).toBeInTheDocument();
    expect(within(alpha).getByText('WebUI')).toBeInTheDocument();
    expect(within(alpha).queryByText('Backend')).not.toBeInTheDocument();

    fireEvent.click(within(table).getByRole('button', { name: /^hoarder01/ }));
    const nodes = screen.getByRole('table', { name: 'Nodes on hoarder01' });
    expect(within(nodes).getByText('This WebUI')).toBeInTheDocument();
    expect(within(nodes).getByText('localhost:6379')).toBeInTheDocument();
    // Host has single Edit config and Inspect action; child nodes do not duplicate them
    expect(within(nodes).queryByRole('button', { name: 'Edit config ↗' })).not.toBeInTheDocument();
    expect(within(nodes).queryByRole('button', { name: 'Inspect hoarder01' })).not.toBeInTheDocument();
    fireEvent.click(within(table).getByRole('button', { name: 'Inspect hoarder01' }));
    expect(onInspect).toHaveBeenCalledWith('hoarder01');
    expect(screen.getByText('Main cluster')).toBeInTheDocument();
    // Named, with each fact once: PostgreSQL and Redis are nodes, not separate cards.
    expect(screen.getByRole('heading', { name: 'Home' })).toBeInTheDocument();
    expect(screen.getByText('2 / 2 hosts healthy')).toBeInTheDocument();
    expect(screen.queryByText(/PostgreSQL Archive Database/)).not.toBeInTheDocument();
    expect(screen.queryByText('Cluster Nodes')).not.toBeInTheDocument();
  });

  it('upgrades the cluster in a dialog', async () => {
    stub({
      '/clusters/c-1/hosts': () => new Response(JSON.stringify(HOSTS)),
      '/clusters/c-1/deployments': () => new Response('[]'),
    });
    renderSection(CLUSTERS('c-1'));

    const home = await screen.findByRole('region', { name: 'Cluster Home' });
    fireEvent.click(within(home).getByRole('button', { name: 'Manage cluster' }));
    fireEvent.click(screen.getByRole('button', { name: /^Upgrade cluster/ }));

    const dialog = await screen.findByRole('dialog', { name: 'Upgrade cluster' });
    expect(await within(dialog).findByText(/installed none of this cluster/)).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('copies an invite for another WebUI', async () => {
    const writeText = vi.fn(async () => undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    stub({
      '/clusters/c-1/hosts': () => new Response(JSON.stringify(HOSTS)),
      '/clusters/c-1/invite': () =>
        new Response(
          JSON.stringify({
            invite: 'usr://cluster/usri_x@192.168.1.20:8443#AB:CD',
            name: 'Home',
            members: [{ name: 'hoarder01', base_url: 'https://192.168.1.20:8443' }],
            excluded: [],
            version: 2,
            expires_at: null,
            warning: null,
          }),
        ),
    });
    renderSection(CLUSTERS('c-1'));

    const home = await screen.findByRole('region', { name: 'Cluster Home' });
    fireEvent.click(within(home).getByRole('button', { name: 'Manage cluster' }));
    fireEvent.click(screen.getByRole('button', { name: /^Invite a WebUI/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Copy invite' }));

    expect(await screen.findByText(/Invite for Home copied, with hoarder01/)).toBeInTheDocument();
    expect(screen.getByText(/It works once/)).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith('usr://cluster/usri_x@192.168.1.20:8443#AB:CD');
  });

  it('opens the architecture of the whole system', async () => {
    stub({
      '/clusters/c-1/hosts': () => new Response(JSON.stringify(HOSTS)),
      '/clusters/c-2/hosts': () => new Response(JSON.stringify({ ...HOSTS, cluster_id: 'c-2', name: 'Lab', hosts: [] })),
      '/clusters': () => new Response(JSON.stringify(CLUSTERS('c-1'))),
    });
    renderSection(CLUSTERS('c-1'));

    fireEvent.click(await screen.findByRole('button', { name: 'Architecture' }));

    const dialog = await screen.findByRole('dialog', { name: 'Architecture' });
    const figure = within(dialog).getByRole('figure', { name: 'The system' });
    expect(within(figure).getByText(/^2 clusters · /)).toBeInTheDocument();
    // WebUIs on top, then each cluster in its own frame.
    const regions = within(figure).getAllByRole('region').map((region) => region.getAttribute('aria-label'));
    expect(regions[0]).toBe('WebUIs');
    const home = within(figure).getByRole('region', { name: 'Cluster Home' });
    expect(await within(home).findAllByText('hoarder01')).not.toHaveLength(0);
    // Nothing is being installed: nothing is highlighted.
    expect(within(figure).queryByText('This install')).not.toBeInTheDocument();

    // Clicking a box opens its details beside it; clicking it again closes them.
    const box = within(home).getAllByRole('button', { name: /hoarder01/ })[0];
    fireEvent.click(box);
    const details = within(figure).getByRole('dialog', { name: /hoarder01/ });
    expect(details).toHaveTextContent('Home');
    fireEvent.click(within(details).getByRole('button', { name: 'Close details' }));
    expect(within(figure).queryByRole('dialog', { name: /hoarder01/ })).not.toBeInTheDocument();

    // A flow plays across the diagram and the flowchart, step by step.
    fireEvent.click(within(figure).getByRole('button', { name: 'DRM video' }));
    expect(within(figure).getByText(/DRM video · step 1 of 6/)).toBeInTheDocument();
    const webuis = within(figure).getByRole('region', { name: 'WebUIs' });
    expect(webuis.querySelector('[data-flow-active="true"]')).not.toBeNull();
    // While it plays, a footer carries the controls and its route through the flowchart.
    const footer = within(figure).getByRole('region', { name: 'Flow progress' });
    expect(footer.querySelector('[data-chart-node="queued"]')).toHaveClass('is-active');
    expect(footer.querySelector('[data-chart-node="decrypt"]')).toHaveClass('is-ahead');
    expect(footer.querySelector('[data-chart-node="isDrm"]')).toHaveTextContent('yes');
    fireEvent.click(within(footer).getByRole('button', { name: 'Next step' }));
    expect(within(footer).getByText(/DRM video · step 2 of 6/)).toBeInTheDocument();
    expect(within(footer).getByRole('button', { name: 'Play' })).toBeInTheDocument();
    fireEvent.click(within(footer).getByRole('button', { name: 'Stop' }));
    expect(within(figure).queryByRole('region', { name: 'Flow progress' })).not.toBeInTheDocument();
    fireEvent.click(within(figure).getByRole('button', { name: 'Zoom in' }));
    expect(within(figure).getByRole('button', { name: 'Fit to view' })).toHaveTextContent('125%');
    expect(within(figure).queryByRole('complementary')).not.toBeInTheDocument();
  });

  it('renames a host', async () => {
    const fetchMock = stub({
      '/clusters/c-1/hosts': () => new Response(JSON.stringify(HOSTS)),
      '/hosts/name': (init) => new Response(init?.body as string),
    });
    renderSection(CLUSTERS('c-1'));

    fireEvent.click(await screen.findByRole('button', { name: 'Rename alpha' }));
    fireEvent.change(screen.getByLabelText('Name for 192.168.50.120'), { target: { value: 'pi' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/hosts/name'));
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ key: '192.168.50.120', name: 'pi' });
    });
  });

  it('lists every cluster, opens the main one, and makes another main', async () => {
    const fetchMock = stub({
      '/clusters/c-1/hosts': () => new Response(JSON.stringify(HOSTS)),
      '/clusters/main': (init) => new Response(init?.body as string),
    });
    renderSection(CLUSTERS('c-2'));

    // The main cluster (Lab) is open; the one this page shows (Home) is listed too.
    const lab = await screen.findByRole('region', { name: 'Cluster Lab' });
    const home = screen.getByRole('region', { name: 'Cluster Home' });
    expect(within(lab).getByText('Main cluster')).toBeInTheDocument();
    expect(within(lab).getByRole('button', { name: /Lab/, expanded: true })).toBeInTheDocument();
    expect(within(home).getByRole('button', { name: /Home/, expanded: false })).toBeInTheDocument();
    // Another cluster opens on one of its own backends.
    expect(within(lab).getByRole('button', { name: 'Open' })).toBeInTheDocument();

    fireEvent.click(within(home).getByRole('button', { name: 'Make main' }));
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/clusters/main'));
      expect(call?.[1]?.method).toBe('PUT');
      expect(JSON.parse(String(call?.[1]?.body))).toEqual({ cluster_id: 'c-1' });
    });
  });
});

describe('pickConnection', () => {
  const connections = ['default', 'lab', 'nas'].map((id) => ({ id }) as never);

  it('reopens the last backend only when it is in the main cluster', () => {
    rememberConnection('nas');
    expect(pickConnection(connections, 'default')).toMatchObject({ id: 'nas' });
    expect(pickConnection(connections, 'lab', ['lab'])).toMatchObject({ id: 'lab' });
    rememberConnection('lab');
    expect(pickConnection(connections, 'lab', ['lab'])).toMatchObject({ id: 'lab' });
  });
});
