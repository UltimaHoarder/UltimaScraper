import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { ClusterHost, LocalServices } from '../../src/api/webui';
import { ClusterHostsTable } from '../../src/features/system/components/ClusterHostsTable';
import { LocalServicesModal } from '../../src/features/system/components/LocalServicesModal';

const NAS: ClusterHost = {
  key: '192.0.2.84',
  name: 'nas',
  address: '192.0.2.84',
  roles: ['webui', 'postgres', 'redis'],
  state: 'healthy',
  deployment_id: null,
  local_services: true,
  nodes: [],
};

const OFF: LocalServices = {
  available: true,
  backend: false,
  worker: false,
  cluster_id: null,
  backend_id: null,
  advertise_host: null,
  services: [
    { name: 'backend', state: 'stopped', exit_code: null, log: [] },
    { name: 'worker', state: 'stopped', exit_code: null, log: [] },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('LocalServicesModal', () => {
  it("offers Edit on this WebUI's own host even though nothing was installed there", () => {
    const onEditHost = vi.fn();
    render(
      <ClusterHostsTable
        hosts={[NAS, { ...NAS, key: 'other', name: 'other', local_services: false }]}
        onConfigureBackend={() => undefined}
        onInspectBackend={() => undefined}
        onRenamed={() => undefined}
        onEditHost={onEditHost}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Edit nas' }));
    expect(onEditHost).toHaveBeenCalledWith(expect.objectContaining({ key: '192.0.2.84' }));
    expect(screen.queryByRole('button', { name: 'Edit other' })).not.toBeInTheDocument();
  });

  it('turns the backend and workers on in this container', async () => {
    const saved: unknown[] = [];
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        saved.push(JSON.parse(String(init.body)));
        return new Response(
          JSON.stringify({
            ...OFF,
            backend: true,
            worker: true,
            advertise_host: '192.0.2.84',
            services: [
              { name: 'backend', state: 'running', exit_code: null, log: ['Uvicorn running on http://0.0.0.0:21121'] },
              { name: 'worker', state: 'restarting', exit_code: 1, log: [] },
            ],
          }),
        );
      }
      return new Response(JSON.stringify(OFF));
    });
    vi.stubGlobal('fetch', fetchMock);
    const onChanged = vi.fn();
    render(<LocalServicesModal host={NAS} clusterId="c-1" onClose={() => undefined} onChanged={onChanged} />);

    const apply = await screen.findByRole('button', { name: 'Apply' });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox', { name: /^Backend/ }));
    fireEvent.click(screen.getByRole('checkbox', { name: /^Workers/ }));
    // The host's address from the cluster, which a container cannot see itself.
    expect(screen.getByLabelText("This machine's address on its network")).toHaveValue('192.0.2.84');
    expect(screen.getByText(/mount those folders/)).toBeInTheDocument();
    fireEvent.click(apply);

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(saved).toEqual([{ cluster_id: 'c-1', backend: true, worker: true, advertise_host: '192.0.2.84' }]);
    expect(screen.getByText(/Running/)).toHaveTextContent('Backend: Running');
    expect(screen.getByText(/Restarting/)).toHaveTextContent('(exited with 1)');
  });

  it('explains when this image cannot run them', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ ...OFF, available: false }))));
    render(<LocalServicesModal host={NAS} clusterId="c-1" onClose={() => undefined} onChanged={() => undefined} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('does not run from the full UltimaScraper image');
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled();
  });
});
