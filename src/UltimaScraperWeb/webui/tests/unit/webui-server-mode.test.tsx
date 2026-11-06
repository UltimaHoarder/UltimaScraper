import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { InternalAxiosRequestConfig } from 'axios';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  apiUrl,
  appUrl,
  createHttpClient,
  forgetTokenFromBeforeWebUIServer,
  getActiveConnectionId,
  getApiBaseUrl,
  getWebSocketBaseUrl,
  setScopedConnectionId,
} from '../../src/api/http';
import type { BackendConnection } from '../../src/api/webui';
import { WebUIServerApp } from '../../src/features/connections/WebUIServerApp';
import { WebUISignInGate } from '../../src/features/connections/WebUISignInGate';
import { pickConnection, rememberConnection } from '../../src/features/connections/lib/lastConnection';

function serveFromWebUIServer(path: string) {
  window.history.replaceState(null, '', path);
}

describe('WebUI server mode', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    setScopedConnectionId(null);
  });

  afterEach(() => {
    setScopedConnectionId(null);
    window.history.replaceState(null, '', '/');
    vi.unstubAllGlobals();
  });

  it('sends backend requests to the connection in the page path', () => {
    serveFromWebUIServer('/b/nas/users/1');

    expect(getActiveConnectionId()).toBe('nas');
    expect(getApiBaseUrl()).toBe(`${window.location.origin}/b/nas`);
    expect(getWebSocketBaseUrl()).toBe(`${window.location.origin.replace('http', 'ws')}/b/nas`);
    expect(apiUrl('/api/v1/proxies/x/analyze-stream')).toBe('/b/nas/api/v1/proxies/x/analyze-stream');
    expect(appUrl('/users/2')).toBe('/b/nas/users/2');
  });

  it('uses the scoped connection id when BackendScope is mounted outside /b/{id}/', () => {
    serveFromWebUIServer('/setup');
    setScopedConnectionId('local-1');

    expect(getActiveConnectionId()).toBe('local-1');
    expect(apiUrl('/api/v1/setup/status')).toBe('/b/local-1/api/v1/setup/status');
  });

  it('resolves the backend per request, not when the client was created', async () => {
    serveFromWebUIServer('/b/first/');
    const client = createHttpClient();
    const seen: string[] = [];
    client.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
      seen.push(`${config.baseURL}${config.url}|${config.headers.get('x-usr-admin-token') ?? ''}`);
      return { data: {}, status: 200, statusText: 'OK', headers: {}, config };
    };

    await client.get('/api/v1/a');
    window.history.replaceState(null, '', '/b/second/');
    await client.get('/api/v1/b');

    expect(seen).toEqual([
      `${window.location.origin}/b/first/api/v1/a|`,
      `${window.location.origin}/b/second/api/v1/b|`,
    ]);
  });

  it('drops an admin token an older WebUI saved in the browser', () => {
    localStorage.setItem('usr_admin_token', 'old-token');
    sessionStorage.setItem('usr_admin_token', 'old-token');

    forgetTokenFromBeforeWebUIServer();

    expect(localStorage.getItem('usr_admin_token')).toBeNull();
    expect(sessionStorage.getItem('usr_admin_token')).toBeNull();
  });

  it('has no backend outside a /b/{connection} page', () => {
    serveFromWebUIServer('/connections');

    expect(getActiveConnectionId()).toBeNull();
    expect(apiUrl('/api/v1/x')).toBe('/api/v1/x');
  });

  it('opens the last-used backend, then the default, then the first', () => {
    const connections = ['default', 'nas', 'pi'].map(
      (id) => ({ id, name: id, base_url: `http://${id}`, tls_verify: true, managed: id === 'default', has_token: true }) as BackendConnection,
    );

    expect(pickConnection(connections, 'default')?.id).toBe('default');
    expect(pickConnection(connections.slice(1), null)?.id).toBe('nas');
    rememberConnection('pi');
    expect(pickConnection(connections, 'default')?.id).toBe('pi');
    rememberConnection('removed');
    expect(pickConnection(connections, 'default')?.id).toBe('default');
    expect(pickConnection([], 'default')).toBeNull();
  });

  it('sends users with no connections to /setup and redirects /connections/deploy to /setup', async () => {
    serveFromWebUIServer('/');
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/session')) {
          return new Response(
            JSON.stringify({
              authenticated: true,
              password_set: true,
              can_claim: false,
              default_connection: null,
            }),
            { status: 200 },
          );
        }
        if (url.endsWith('/connections') || url.endsWith('/deployments')) {
          return new Response('[]', { status: 200 });
        }
        if (url.endsWith('/installs/environment')) {
          return new Response(
            JSON.stringify({
              version: '0.1.0',
              in_container: false,
              local_available: true,
              copy_available: false,
              releases: [],
            }),
            { status: 200 },
          );
        }
        if (url.endsWith('/installs/detect')) {
          return new Response(
            JSON.stringify({
              facts: {
                architecture: 'amd64',
                os_name: 'Ubuntu 24.04',
                user: 'deploy',
                home: '/home/deploy',
                hostname: 'devbox',
                docker_version: '27.0.0',
                compose_version: '2.28.0',
                docker_needs_sudo: false,
                sudo_mode: 'none',
                memory_mb: 16000,
                home_free_mb: 102400,
                listening_ports: [],
                existing_projects: [],
                existing_install: null,
                services: {},
                local_images: [],
                warnings: [],
              },
              recommended_components: {
                backend: 'install',
                worker: 'install',
                postgres: 'install',
                redis: 'install',
                webui: 'reuse',
              },
              needs_sudo_for: [],
              recommended_image_source: 'registry',
              recommended_version: '0.1.0',
            }),
            { status: 200 },
          );
        }
        return new Response('{}', { status: 200 });
      }),
    );

    render(<WebUIServerApp renderBackend={() => <div>Backend</div>} />);

    await waitFor(() => expect(window.location.pathname).toBe('/setup'));
    expect(await screen.findByRole('heading', { name: 'Set up UltimaScraper' })).toBeInTheDocument();

    serveFromWebUIServer('/connections/deploy');
    window.dispatchEvent(new PopStateEvent('popstate'));
    await waitFor(() => expect(window.location.pathname).toBe('/setup'));
  });
});

describe('WebUISignInGate', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function stubServer(session: Record<string, unknown>) {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/session/claim') && init?.method === 'POST') {
        session.authenticated = true;
        session.password_set = true;
        return new Response(null, { status: 204 });
      }
      return new Response(JSON.stringify(session), { status: 200 });
    });
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('lets the first visitor on the network create the password', async () => {
    const fetchMock = stubServer({ authenticated: false, password_set: false, can_claim: true, default_connection: 'default' });
    render(<WebUISignInGate><div>Application</div></WebUISignInGate>);

    fireEvent.change(await screen.findByLabelText('Password'), { target: { value: 'short-p' } });
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'short-p' } });
    expect(screen.queryByLabelText('Setup code')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Create password' }));
    expect(await screen.findByText('Use at least 8 characters.')).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/session/claim'))).toBe(false);

    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'a-long-password' } });
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'a-long-password' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create password' }));

    await screen.findByText('Application');
    const claim = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/session/claim'));
    expect(claim?.[1]?.body).toBe(JSON.stringify({ password: 'a-long-password', code: null }));
  });

  it('asks a remote first visitor for the setup code', async () => {
    stubServer({ authenticated: false, password_set: false, can_claim: false, default_connection: null });
    render(<WebUISignInGate><div>Application</div></WebUISignInGate>);

    expect(await screen.findByLabelText('Setup code')).toBeInTheDocument();
    expect(screen.getByText('docker compose logs webui')).toBeInTheDocument();
  });

  it('gives password managers a sign-up form they can generate a password for', async () => {
    stubServer({ authenticated: false, password_set: false, can_claim: false, default_connection: null });
    const { container } = render(<WebUISignInGate><div>Application</div></WebUISignInGate>);

    // Only the new password and its confirmation are password fields; the setup
    // code is not, or a manager would take the form for a password change.
    const code = await screen.findByLabelText('Setup code');
    expect(code).toHaveAttribute('type', 'text');
    expect(code).toHaveAttribute('autocomplete', 'one-time-code');
    const passwords = [...container.querySelectorAll('input[type="password"]')];
    expect(passwords.map((input) => input.getAttribute('autocomplete'))).toEqual(['new-password', 'new-password']);
    // The username the saved login is filed under.
    expect(container.querySelector('input[autocomplete="username"]')).toHaveValue('UltimaScraper');
  });

  it('refuses mismatched passwords before sending them', async () => {
    const fetchMock = stubServer({ authenticated: false, password_set: false, can_claim: true, default_connection: null });
    render(<WebUISignInGate><div>Application</div></WebUISignInGate>);

    fireEvent.change(await screen.findByLabelText('Password'), { target: { value: 'a-long-password' } });
    fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'different-password' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create password' }));

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('do not match'));
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/session/claim'))).toBe(false);
  });

  it('signs in an existing user', async () => {
    stubServer({ authenticated: false, password_set: true, can_claim: false, default_connection: null });
    render(<WebUISignInGate><div>Application</div></WebUISignInGate>);

    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Confirm password')).not.toBeInTheDocument();
  });
});
