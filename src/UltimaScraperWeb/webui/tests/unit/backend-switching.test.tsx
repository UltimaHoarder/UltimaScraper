import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { connectionScopedKey, getActiveConnectionId, navigateTo } from '../../src/api/http';
import { AppProviders } from '../../src/app/AppProviders';
import { forgetQueryClients, queryClientFor } from '../../src/app/backends/backendQueryClients';
import { BackendScope } from '../../src/app/backends/BackendScope';
import { ConnectionSwitcher } from '../../src/features/connections/ConnectionSwitcher';
import { WebUIServerApp } from '../../src/features/connections/WebUIServerApp';
import { followInApp, sectionOnBackend } from '../../src/features/connections/lib/navigation';
import * as sockets from '../../src/hooks/useWebSocket';

const CONNECTIONS = ['nas', 'pi'].map((id) => ({
  id,
  name: id.toUpperCase(),
  base_url: `http://${id}:21121`,
  tls_verify: true,
  managed: false,
  has_token: true,
  trust_plugins: false,
}));

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  window.history.replaceState(null, '', '/');
  forgetQueryClients();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('backend switching helpers', () => {
  it('keeps one query cache per backend, for the three used last', () => {
    const nas = queryClientFor('nas');
    nas.setQueryData(['users'], ['nas user']);
    expect(queryClientFor('nas')).toBe(nas);
    expect(queryClientFor('pi')).not.toBe(nas);

    queryClientFor('a');
    queryClientFor('b');
    // nas was used longest ago, so it is dropped and its cache cleared.
    expect(nas.getQueryData(['users'])).toBeUndefined();
    expect(queryClientFor('nas')).not.toBe(nas);
  });

  it('keeps the section, not the ids, when switching backends', () => {
    expect(sectionOnBackend('pi', '/b/nas/jobs/123')).toBe('/b/pi/jobs');
    expect(sectionOnBackend('pi', '/b/nas/')).toBe('/b/pi/');
    expect(sectionOnBackend('my pi', '/b/nas%20box/users')).toBe('/b/my%20pi/users');
    expect(sectionOnBackend('pi', '/connections')).toBe('/b/pi/');
  });

  it('stores backend data under the backend it came from', () => {
    window.history.replaceState(null, '', '/b/nas/');
    expect(connectionScopedKey('usr_pulse')).toBe('usr_pulse@nas');
    navigateTo('/b/pi/');
    expect(getActiveConnectionId()).toBe('pi');
    expect(connectionScopedKey('usr_pulse')).toBe('usr_pulse@pi');
  });

  it('leaves new-tab clicks to the browser', () => {
    window.history.replaceState(null, '', '/b/nas/');
    const event = {
      defaultPrevented: false, button: 0, metaKey: true, ctrlKey: false, shiftKey: false, altKey: false,
      preventDefault: vi.fn()
    } as unknown as NonNullable<Parameters<typeof followInApp>[0]>;
    followInApp(event, '/b/pi/');
    expect(event.preventDefault).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe('/b/nas/');
  });
});

describe('leaving a backend', () => {
  it('cancels its queries and closes its unused sockets', async () => {
    vi.useFakeTimers();
    const closeUnused = vi.spyOn(sockets, 'closeUnusedSockets');
    const client = queryClientFor('nas');
    const cancel = vi.spyOn(client, 'cancelQueries');
    const { unmount } = render(<BackendScope connectionId="nas"><span>NAS</span></BackendScope>);

    unmount();
    expect(cancel).toHaveBeenCalled();
    await act(async () => vi.runAllTimers());
    expect(closeUnused).toHaveBeenCalled();
    vi.useRealTimers();
  });
});

function ActiveBackend() {
  const client = useQueryClient();
  const connectionId = getActiveConnectionId() ?? '';
  const { data } = useQuery({ queryKey: ['who'], queryFn: async () => `data from ${connectionId}` });
  return (
    <div>
      <p>Open: {connectionId}</p>
      <p>{data ?? 'loading'}</p>
      <p>Cache: {String(client.getQueryData(['who']) ?? 'empty')}</p>
      <button type="button" onClick={() => navigateTo(sectionOnBackend(connectionId === 'nas' ? 'pi' : 'nas'))}>
        Switch
      </button>
    </div>
  );
}

describe('WebUIServerApp', () => {
  function stubServer() {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith('/session')) {
        return new Response(JSON.stringify({ authenticated: true, password_set: true, can_claim: false, default_connection: null }));
      }
      if (url.endsWith('/connections')) return new Response(JSON.stringify(CONNECTIONS));
      return new Response('{}', { status: 404 });
    });
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('switches backends without reloading and keeps each one’s cache', async () => {
    const fetchMock = stubServer();
    window.history.replaceState(null, '', '/b/nas/jobs');
    render(
      <WebUIServerApp
        renderBackend={(connectionId) => (
          <BackendScope key={connectionId} connectionId={connectionId}>
            <ActiveBackend />
          </BackendScope>
        )}
      />,
    );

    expect(await screen.findByText('data from nas')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Switch' }));
    expect(await screen.findByText('data from pi')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/b/pi/jobs');
    // The connection list was fetched once: switching does not ask again.
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/connections'))).toHaveLength(1);

    // Back to nas, as the browser's back button does: its cache is still there.
    act(() => {
      window.history.replaceState(null, '', '/b/nas/jobs');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    expect(await screen.findByText('Open: nas')).toBeInTheDocument();
    expect(screen.getByText('Cache: data from nas')).toBeInTheDocument();
  });

  it('opens an old bookmark on the chosen backend', async () => {
    stubServer();
    localStorage.setItem('usr_webui_last_connection', 'pi');
    window.history.replaceState(null, '', '/jobs?status=failed');
    // StrictMode runs the opening step twice, as development builds do.
    render(<StrictMode><WebUIServerApp renderBackend={(connectionId) => <p>App for {connectionId}</p>} /></StrictMode>);

    expect(await screen.findByText('App for pi')).toBeInTheDocument();
    expect(`${window.location.pathname}${window.location.search}`).toBe('/b/pi/jobs?status=failed');
  });

  it('shows the Clusters page and an unknown backend in-app', async () => {
    stubServer();
    window.history.replaceState(null, '', '/b/gone/');
    render(<WebUIServerApp renderBackend={() => <p>App</p>} />);

    expect(await screen.findByText('Unknown backend')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: 'Choose a backend' }));
    expect(await screen.findByRole('heading', { name: 'Clusters' })).toBeInTheDocument();
    expect(window.location.pathname).toBe('/connections');
  });

  it('opens the manage clusters modal from the switcher and switches backend', async () => {
    stubServer();
    window.history.replaceState(null, '', '/b/nas/jobs');
    render(<ConnectionSwitcher />);

    fireEvent.click(screen.getByTitle('Switch backend'));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Manage clusters' }));

    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Manage clusters' })).toBeInTheDocument();

    const cluster = screen.getByRole('region', { name: 'Independent backends' });
    const piRow = within(cluster).getByText('PI').closest('li')!;
    fireEvent.click(within(piRow).getByRole('link', { name: 'Open' }));

    expect(window.location.pathname).toBe('/b/pi/jobs');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});

describe('AppProviders', () => {
  it('uses the backend’s own cache behind the WebUI server', () => {
    window.history.replaceState(null, '', '/b/nas/');
    const nas = queryClientFor('nas');
    function Probe() {
      return <p>{useQueryClient() === nas ? 'Own cache' : 'Other cache'}</p>;
    }
    render(<AppProviders connectionId="nas"><Probe /></AppProviders>);
    expect(screen.getByText('Own cache')).toBeInTheDocument();
  });
});
