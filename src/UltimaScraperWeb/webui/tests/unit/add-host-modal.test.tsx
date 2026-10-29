import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AddHostModal } from '../../src/features/system/components/AddHostModal';

function stub(routes: Record<string, (init?: RequestInit) => Response>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input).split('?')[0];
    const match = Object.keys(routes).find((key) => url.endsWith(key));
    return match ? routes[match](init) : new Response('{}', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const renderModal = (overrides: Partial<Parameters<typeof AddHostModal>[0]> = {}) => {
  const props = {
    clusterId: 'c-1',
    clusterName: 'Home',
    connectionId: 'dev',
    onClose: vi.fn(),
    onChanged: vi.fn(),
    ...overrides,
  };
  render(<AddHostModal {...props} />);
  return props;
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('AddHostModal', () => {
  it('offers Install and Connect, and no WebUI', () => {
    stub({});
    renderModal();

    const dialog = screen.getByRole('dialog', { name: 'Add host' });
    expect(dialog).toHaveTextContent('Install');
    expect(screen.getByRole('button', { name: /^Install/ })).toHaveTextContent('(local)');
    expect(screen.getByRole('button', { name: /^Install/ })).toHaveTextContent('(remote)');
    expect(screen.getByRole('button', { name: /^Connect/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /WebUI/ })).not.toBeInTheDocument();
  });

  it('connects a running backend from a connection ticket', async () => {
    const fetchMock = stub({
      '/connections': (init) =>
        new Response(JSON.stringify({ id: 'nas', ...JSON.parse(String(init?.body)), has_token: true }), { status: 201 }),
    });
    const props = renderModal();

    fireEvent.click(screen.getByRole('button', { name: /^Connect/ }));
    const ticket = btoa(JSON.stringify({ v: 1, name: 'nas', base_url: 'https://192.168.50.40:8443', token: 't', tls_verify: true }))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '');
    fireEvent.change(screen.getByLabelText('Connection ticket (optional)'), { target: { value: `usr://ticket/${ticket}` } });
    expect(screen.getByLabelText('Address')).toHaveValue('https://192.168.50.40:8443');
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));

    expect(await screen.findByText(/Connected nas/)).toBeInTheDocument();
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body));
    expect(body).toEqual({ name: 'nas', base_url: 'https://192.168.50.40:8443', token: 't', tls_verify: true });
    expect(props.onChanged).toHaveBeenCalled();
  });

  it('says a cluster invite is for Join, not Connect', () => {
    stub({});
    renderModal();

    fireEvent.click(screen.getByRole('button', { name: /^Connect/ }));
    fireEvent.change(screen.getByLabelText('Connection ticket (optional)'), {
      target: { value: 'usr://cluster/usri_x@192.168.50.60:8443#AB' },
    });
    expect(screen.getByText(/use it in Set up under Join a cluster, not Connect/)).toBeInTheDocument();
  });

  it('goes back to the choices, and closes on Escape', () => {
    stub({});
    const props = renderModal();

    fireEvent.click(screen.getByRole('button', { name: /^Connect/ }));
    fireEvent.click(screen.getByRole('button', { name: /Other ways to add a host/ }));
    expect(screen.getByRole('dialog', { name: 'Add host' })).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(props.onClose).toHaveBeenCalled();
  });

  it('says why it cannot install without a connection to the cluster', () => {
    stub({});
    renderModal({ connectionId: null });

    fireEvent.click(screen.getByRole('button', { name: /^Install/ }));
    expect(screen.getByRole('alert')).toHaveTextContent('no connection to a backend of Home');
  });
});
