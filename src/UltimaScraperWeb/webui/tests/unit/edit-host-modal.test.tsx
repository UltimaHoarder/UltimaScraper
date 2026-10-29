import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ClusterHost } from '../../src/api/webui';
import { ClusterHostsTable } from '../../src/features/system/components/ClusterHostsTable';
import { EditHostModal } from '../../src/features/system/components/EditHostModal';

const HOST: ClusterHost = {
  key: '192.168.50.120',
  name: 'alpha',
  address: '192.168.50.120',
  roles: ['workers'],
  state: 'healthy',
  deployment_id: 'd-alpha',
  nodes: [],
};

const DEPLOYMENT = {
  id: 'd-alpha',
  name: 'alpha',
  target: 'ultima@192.168.50.120',
  details: {
    kind: 'ssh',
    host: '192.168.50.120',
    username: 'ultima',
    install_dir: '/home/ultima/ultimascraper',
    project: 'usr-alpha',
    version: 'edge',
    image_source: 'registry',
    components: { backend: false, worker: true, postgres: false, redis: false, webui: true },
  },
  connection_id: null,
};

function stub(routes: Record<string, (init?: RequestInit) => Response>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).split('?')[0];
    const match = Object.keys(routes).find((key) => url.endsWith(key));
    return match ? routes[match](init) : new Response('{}', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('EditHostModal', () => {
  it('changes the services of the install on the host', async () => {
    const fetchMock = stub({
      '/deployments': () => new Response(JSON.stringify([DEPLOYMENT])),
      '/deployments/d-alpha/operations': () => new Response(JSON.stringify({ id: 'run-1' }), { status: 202 }),
      '/installs/run-1': () =>
        new Response(JSON.stringify({ id: 'run-1', state: 'running', events: [{ seq: 1, at: 0, kind: 'step', message: 'Changing services: +backend' }] })),
    });
    render(<EditHostModal host={HOST} onClose={() => undefined} onChanged={() => undefined} />);

    const backend = await screen.findByRole('checkbox', { name: /^Backend/ });
    expect(backend).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: /^Workers/ })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /^WebUI/ })).toBeChecked();
    expect(screen.getByText('PostgreSQL: not on this host')).toBeInTheDocument();
    // Nothing changed yet.
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled();

    fireEvent.click(backend);
    fireEvent.change(screen.getByLabelText('Password for ultima@192.168.50.120'), { target: { value: 'pw' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));

    expect(await screen.findByText('Changing services: +backend')).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/deployments/d-alpha/operations'));
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({
      action: 'services',
      services: { backend: true, worker: true, webui: true },
      credentials: { password: 'pw' },
    });
  });

  it('says when this WebUI has no install there', async () => {
    stub({ '/deployments': () => new Response('[]') });
    render(<EditHostModal host={HOST} onClose={() => undefined} onChanged={() => undefined} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('no install on this host');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled());
  });
});

describe('ClusterHostsTable', () => {
  it('offers Edit only on hosts this WebUI installed', () => {
    const onEdit = vi.fn();
    render(
      <ClusterHostsTable
        hosts={[HOST, { ...HOST, key: '192.168.50.40', name: 'nas01', deployment_id: null }]}
        onConfigureBackend={() => undefined}
        onInspectBackend={() => undefined}
        onRenamed={() => undefined}
        onEditHost={onEdit}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Edit alpha' }));
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ name: 'alpha' }));
    expect(screen.queryByRole('button', { name: 'Edit nas01' })).not.toBeInTheDocument();
  });

  it('removes another WebUI, but not this one', () => {
    const onRemove = vi.fn();
    const webui = (name: string, extra = {}) => ({
      role: 'webui' as const,
      name,
      state: 'offline' as const,
      version: null,
      detail: null,
      last_seen: null,
      backend_id: null,
      client_id: `id-${name}`,
      connection_id: null,
      is_self: false,
      installed_only: false,
      ...extra,
    });
    render(
      <ClusterHostsTable
        hosts={[{ ...HOST, roles: ['webui'], nodes: [webui('WebUI on nas01'), webui('WebUI on devbox', { is_self: true })] }]}
        onConfigureBackend={() => undefined}
        onInspectBackend={() => undefined}
        onRenamed={() => undefined}
        onRemoveWebUI={onRemove}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /^alpha/ }));
    expect(screen.getAllByRole('button', { name: 'Remove' })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    expect(onRemove).toHaveBeenCalledWith(expect.objectContaining({ client_id: 'id-WebUI on nas01' }));
    expect(screen.getByText('This WebUI')).toBeInTheDocument();
  });
});
