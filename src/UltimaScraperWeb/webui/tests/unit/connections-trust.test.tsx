import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ConnectionsPage } from '../../src/features/connections/ConnectionsPage';

const NAS = {
  id: 'nas',
  name: 'NAS',
  base_url: 'http://nas:21121',
  tls_verify: true,
  managed: false,
  has_token: true,
  trust_plugins: false,
};

function stubServer() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith('/connections')) return new Response(JSON.stringify([NAS]), { status: 200 });
    if (url.endsWith('/deployments')) return new Response('[]', { status: 200 });
    if (url.endsWith('/test')) {
      return new Response(JSON.stringify({ reachable: true, authenticated: true, message: 'Connected', latency_ms: 3 }));
    }
    if (url.endsWith('/plugin-trust') && init?.method === 'PUT') {
      const { trusted } = JSON.parse(String(init.body)) as { trusted: boolean };
      return new Response(JSON.stringify({ ...NAS, trust_plugins: trusted }), { status: 200 });
    }
    return new Response('{}', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const trustCalls = (fetchMock: ReturnType<typeof stubServer>) =>
  fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/plugin-trust'));

describe('Backends page plugin trust', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('trusts native plugins only after the user confirms', async () => {
    const fetchMock = stubServer();
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    render(<ConnectionsPage />);

    const toggle = await screen.findByLabelText('Trust native plugins from this backend');
    expect(toggle).not.toBeChecked();

    fireEvent.click(toggle);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(trustCalls(fetchMock)).toHaveLength(0);
    expect(toggle).not.toBeChecked();

    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).toBeChecked());
    expect(JSON.parse(String(trustCalls(fetchMock)[0][1]?.body))).toEqual({ trusted: true });

    // Withdrawing trust needs no confirmation.
    fireEvent.click(toggle);
    await waitFor(() => expect(toggle).not.toBeChecked());
    expect(confirm).toHaveBeenCalledTimes(2);
  });
});
