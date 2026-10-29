import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ConnectionsPage } from '../../src/features/connections/ConnectionsPage';

const CONNECTION = {
  id: 'alpha',
  name: 'alpha',
  base_url: 'http://127.0.0.1:21121',
  has_token: true,
  tls_verify: true,
  plugins_trusted: false,
  is_default: false,
};

const DEPLOYMENT = {
  id: 'dep1',
  name: 'alpha',
  target: 'this machine',
  details: {
    kind: 'local',
    install_dir: '/home/ultima/ultimascraper',
    project: 'usr-alpha',
    version: 'edge',
    image_source: 'registry',
    image_prefix: 'forgejo.example/owner/ultimascraper',
    architecture: 'arm64',
    image_version: '0.1.0-edge.17507c287fe9',
  },
  connection_id: 'alpha',
};

function stubServer({ failFirstList = false } = {}) {
  let lists = 0;
  const calls = { tests: 0, lists: 0 };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith('/connections')) {
      calls.lists += 1;
      lists += 1;
      if (failFirstList && lists === 1) throw new TypeError('Failed to fetch');
      return new Response(JSON.stringify([CONNECTION]), { status: 200 });
    }
    if (url.endsWith('/connections/alpha/test')) {
      calls.tests += 1;
      return new Response(
        JSON.stringify({ reachable: true, authenticated: true, message: 'Connected', latency_ms: 12 }),
        { status: 200 },
      );
    }
    if (url.endsWith('/clusters')) {
      return new Response(
        JSON.stringify({
          members: [
            {
              connection_id: 'alpha',
              name: 'alpha',
              reachable: true,
              identity: { backend_id: 'alpha-1', instance: '', cluster_id: null, api_url: null, version: '0.1.0', api_version: 1 },
              seen_at: 0,
            },
          ],
          clusters: [],
        }),
        { status: 200 },
      );
    }
    if (url.endsWith('/deployments')) return new Response(JSON.stringify([DEPLOYMENT]), { status: 200 });
    if (url.endsWith('/installs/detect')) {
      return new Response(JSON.stringify({ facts: { sudo_mode: 'none' }, needs_sudo_for: [] }), { status: 200 });
    }
    if (url.endsWith('/operations') && init?.method === 'POST') {
      return new Response(JSON.stringify({ id: 'run1' }), { status: 202 });
    }
    if (url.includes('/installs/run1')) {
      return new Response(
        JSON.stringify({
          id: 'run1',
          name: 'alpha',
          target: 'this machine',
          state: 'succeeded',
          connection_id: 'alpha',
          operation: 'repair',
          deployment_id: 'dep1',
          events: [{ seq: 1, at: 0, kind: 'done', message: 'alpha is running.' }],
        }),
        { status: 200 },
      );
    }
    return new Response('{}', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return calls;
}

describe('ConnectionsPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('reloads once after an operation finishes instead of retesting forever', async () => {
    const calls = stubServer();
    render(<ConnectionsPage onClose={() => undefined} />);

    expect(await screen.findByText(/Connected/)).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: 'Repair' }));
    fireEvent.click(screen.getAllByRole('button', { name: 'Repair' }).at(-1)!);
    expect(await screen.findByText('alpha is running.')).toBeInTheDocument();

    await waitFor(() => expect(calls.tests).toBe(2));
    // Give a runaway reload loop time to show itself.
    await act(() => new Promise((resolve) => setTimeout(resolve, 300)));
    expect(calls.tests).toBe(2);
    expect(calls.lists).toBe(2);
    // The retest kept the last result on screen.
    expect(screen.queryByText('Testing…')).not.toBeInTheDocument();
  });

  it('clears a failed load once a later load succeeds', async () => {
    stubServer({ failFirstList: true });
    render(<ConnectionsPage onClose={() => undefined} />);

    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to fetch');
    fireEvent.click(await screen.findByRole('button', { name: 'Repair' }));
    fireEvent.click(screen.getAllByRole('button', { name: 'Repair' }).at(-1)!);

    expect(await screen.findByText(/Connected/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('Failed to fetch')).not.toBeInTheDocument());
  });

  it('shows the version each backend reports and the build a deployment runs', async () => {
    stubServer();
    render(<ConnectionsPage onClose={() => undefined} />);

    expect(await screen.findByTitle('The version this backend reports')).toHaveTextContent('v0.1.0');
    expect(await screen.findByTitle('The image tag this deployment follows')).toHaveTextContent('edge');
    expect(screen.getByText('0.1.0-edge.17507c287fe9')).toBeInTheDocument();
  });
});
