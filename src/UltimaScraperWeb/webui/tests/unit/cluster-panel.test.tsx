import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { BackendCluster, BackendClusters } from '../../src/api/webui';
import { ClusterPanel } from '../../src/features/connections/ClusterPanel';
import { JoinClusterForm } from '../../src/features/connections/JoinClusterForm';
import { joinSummary } from '../../src/features/connections/lib/joinSummary';
import { pickClusterMember } from '../../src/features/connections/lib/clusterView';

const CLUSTER: BackendCluster = {
  cluster_id: '1c69d73d-dcc6',
  name: 'Home',
  connection_ids: ['devbox', 'nas'],
  suggestions: [],
  conflicting_backend_ids: [],
};

const identity = (backend_id: string) => ({
  backend_id,
  instance: 'i',
  cluster_id: CLUSTER.cluster_id,
  api_url: null,
  version: '0.1.0',
  api_version: 1,
});

const CLUSTERS: BackendClusters = {
  members: [
    { connection_id: 'devbox', name: 'devbox', reachable: false, identity: identity('devbox-1'), seen_at: 1 },
    { connection_id: 'nas', name: 'nas', reachable: true, identity: identity('nas-1'), seen_at: 1 },
  ],
  clusters: [CLUSTER],
};

const OVERVIEW = {
  cluster_id: CLUSTER.cluster_id,
  name: 'Home',
  backends: [
    { backend_id: 'devbox-1', name: 'devbox', address: 'http://192.168.1.20:21121', version: '0.1.0', status: 'unreachable', last_seen: '', connection_id: 'devbox' },
    { backend_id: 'nas-1', name: 'nas', address: 'http://192.168.1.10:21121', version: '0.1.0', status: 'online', last_seen: '', connection_id: 'nas' },
    { backend_id: 'pc-1', name: 'pc', address: 'https://192.168.1.30:21121', version: '0.1.0', status: 'online', last_seen: '', connection_id: null },
  ],
  worker_hosts: [
    { backend_id: 'alpha-1', name: 'alpha', status: 'online', version: '0.1.0', active_workers: 4, max_workers: 4, pending_jobs: 2, workers: [] },
    { backend_id: 'devbox-1', name: 'devbox', status: 'online', version: '0.1.0', active_workers: 6, max_workers: 12, pending_jobs: 0, workers: [] },
  ],
  answered_by: 'nas',
  error: null,
};

function stub(routes: Record<string, (init?: RequestInit) => Response>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const match = Object.keys(routes).find((key) => url.endsWith(key));
    return match ? routes[match](init) : new Response('{}', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('pickClusterMember', () => {
  it('keeps the member in use while it is reachable, else takes a reachable one', () => {
    expect(pickClusterMember(CLUSTER, CLUSTERS, 'nas')).toBe('nas');
    expect(pickClusterMember(CLUSTER, CLUSTERS, 'devbox')).toBe('nas');
    expect(pickClusterMember(CLUSTER, null, null)).toBe('devbox');
  });
});

describe('ClusterPanel', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows health, workers per host and other backends, and opens a healthy member', async () => {
    stub({ '/overview': () => new Response(JSON.stringify(OVERVIEW)) });
    const onAdd = vi.fn();
    render(<ClusterPanel cluster={CLUSTER} clusters={CLUSTERS} onAdd={onAdd} />);

    expect(await screen.findByText('3 backends · 10/16 workers busy on 2 hosts · 1 unreachable')).toBeInTheDocument();
    const workers = screen.getByRole('table', { name: 'Workers in Home' });
    expect(within(workers).getByRole('rowheader', { name: 'alpha' }).closest('tr')).toHaveTextContent('alpha4/42');
    // devbox is unreachable, so the cluster opens on nas.
    expect(screen.getByRole('link', { name: 'Open Home' })).toHaveAttribute('href', '/b/nas/');

    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(onAdd).toHaveBeenCalledWith('pc-1', 'https://192.168.1.30:21121');
  });

  it('copies an invite and says which members it left out', async () => {
    const writeText = vi.fn(async () => undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    stub({
      '/overview': () => new Response(JSON.stringify(OVERVIEW)),
      '/invite': () =>
        new Response(
          JSON.stringify({
            invite: 'usr://cluster/abc',
            name: 'Home',
            members: [{ name: 'nas', base_url: 'http://192.168.1.10:21121' }],
            excluded: [{ name: 'devbox', reason: 'http://127.0.0.1:21121 only works from this WebUI’s host.' }],
          }),
        ),
    });
    render(<ClusterPanel cluster={CLUSTER} clusters={CLUSTERS} onAdd={() => undefined} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Invite a WebUI' }));

    expect(await screen.findByText(/Invite for Home copied, with nas/)).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith('usr://cluster/abc');
    expect(screen.getByText(/Left out devbox:/)).toBeInTheDocument();
  });

  it('says a one-time invite works once', async () => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn(async () => undefined) } });
    stub({
      '/overview': () => new Response(JSON.stringify(OVERVIEW)),
      '/invite': () =>
        new Response(
          JSON.stringify({
            invite: 'usr://cluster/usri_x@192.168.1.20:8443#AB:CD',
            name: 'Home',
            members: [{ name: 'devbox', base_url: 'https://192.168.1.20:8443' }],
            excluded: [],
            version: 2,
            expires_at: null,
            warning: null,
          }),
        ),
    });
    render(<ClusterPanel cluster={CLUSTER} clusters={CLUSTERS} onAdd={() => undefined} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Invite a WebUI' }));

    expect(await screen.findByText(/It works once/)).toBeInTheDocument();
    expect(screen.queryByText(/admin tokens/)).not.toBeInTheDocument();
  });

  it('lists the WebUIs that joined and revokes one', async () => {
    const confirm = vi.fn(() => true);
    vi.stubGlobal('confirm', confirm);
    let revoked = false;
    const client = (id: string, name: string, extra = {}) => ({
      id,
      name,
      kind: 'webui',
      created_at: '2026-10-26T10:00:00Z',
      last_seen_at: '2026-10-26T10:05:00Z',
      last_address: '192.168.50.120',
      version: null,
      revoked_at: null,
      is_self: false,
      ...extra,
    });
    const fetchMock = stub({
      '/overview': () => new Response(JSON.stringify(OVERVIEW)),
      '/clients': () =>
        new Response(
          JSON.stringify([
            client('me', 'WebUI on devbox', { is_self: true }),
            client('pi', 'WebUI on alpha', revoked ? { revoked_at: '2026-10-26T11:00:00Z' } : {}),
          ]),
        ),
      '/clients/pi': () => {
        revoked = true;
        return new Response(null, { status: 204 });
      },
    });
    render(<ClusterPanel cluster={CLUSTER} clusters={CLUSTERS} onAdd={() => undefined} />);

    const list = await screen.findByRole('list', { name: 'WebUIs in Home' });
    expect(within(list).getByText('This WebUI')).toBeInTheDocument();
    const alpha = within(list).getByText('WebUI on alpha').closest('li') as HTMLElement;
    fireEvent.click(within(alpha).getByRole('button', { name: 'Revoke' }));

    expect(await within(list).findByText('Revoked')).toBeInTheDocument();
    expect(confirm).toHaveBeenCalledWith('WebUI on alpha will lose access to the cluster. Revoke it?');
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/clients/pi'));
    expect(call?.[1]?.method).toBe('DELETE');
  });

  it('renames the cluster', async () => {
    const fetchMock = stub({
      '/overview': () => new Response(JSON.stringify(OVERVIEW)),
      '/name': (init) => new Response(init?.body as string),
    });
    const onNamed = vi.fn();
    render(<ClusterPanel cluster={CLUSTER} clusters={CLUSTERS} onAdd={() => undefined} onNamed={onNamed} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Rename cluster' }));
    fireEvent.change(screen.getByLabelText('Cluster name'), { target: { value: 'Lab' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByRole('heading', { name: /Lab/ })).toBeInTheDocument();
    expect(onNamed).toHaveBeenLastCalledWith('Lab');
    const rename = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/name'));
    expect(rename?.[1]?.method).toBe('PUT');
  });
});

describe('JoinClusterForm', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('previews an invite, then joins and reports what it added', async () => {
    stub({
      '/clusters/preview-invite': () =>
        new Response(
          JSON.stringify({
            cluster_id: 'c-1',
            name: 'Home',
            members: [
              { name: 'devbox', backend_id: 'devbox-1', base_url: 'http://192.168.1.20:21121', already_connected: true },
              { name: 'nas', backend_id: 'nas-1', base_url: 'http://192.168.1.10:21121', already_connected: false },
            ],
          }),
        ),
      '/clusters/join': () => new Response(JSON.stringify({ cluster_id: 'c-1', name: 'Home', created: ['nas'], skipped: ['devbox'] })),
    });
    const onJoined = vi.fn();
    render(<JoinClusterForm onJoined={onJoined} />);

    fireEvent.change(screen.getByLabelText('Cluster invite'), { target: { value: 'usr://cluster/abc' } });

    expect(await screen.findByText('Already here')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Join' }));

    await waitFor(() => expect(onJoined).toHaveBeenCalledTimes(1));
    expect(joinSummary(onJoined.mock.calls[0][0])).toBe('Joined Home: 1 backend added, 1 already here.');
  });

  it("checks a one-time invite's certificate before joining", async () => {
    stub({
      '/clusters/preview-invite': () =>
        new Response(
          JSON.stringify({
            cluster_id: null,
            name: 'A cluster',
            members: [],
            version: 2,
            entry_url: 'https://192.168.1.20:8443',
            fingerprint: 'AB:CD:EF:01:23:45:67:89:AB:CD',
            verified: true,
            error: null,
          }),
        ),
      '/clusters/join': () =>
        new Response(
          JSON.stringify({
            cluster_id: 'c-1',
            name: 'Home',
            created: ['devbox'],
            skipped: ['alpha'],
            members: [
              { name: 'devbox', base_url: 'https://192.168.1.20:8443', connection_id: 'devbox', note: null },
              { name: 'alpha', base_url: null, connection_id: null, note: 'It serves no HTTPS address for other machines.' },
            ],
          }),
        ),
    });
    const onJoined = vi.fn();
    render(<JoinClusterForm onJoined={onJoined} />);

    fireEvent.change(screen.getByLabelText('Cluster invite'), {
      target: { value: 'usr://cluster/usri_x@192.168.1.20:8443#AB:CD' },
    });

    expect(await screen.findByText(/Certificate verified/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Join' }));

    await waitFor(() => expect(onJoined).toHaveBeenCalledTimes(1));
    expect(joinSummary(onJoined.mock.calls[0][0])).toBe(
      'Joined Home: 1 backend added. alpha: It serves no HTTPS address for other machines.',
    );
  });

  it('will not join when the certificate is not the one the invite names', async () => {
    stub({
      '/clusters/preview-invite': () =>
        new Response(
          JSON.stringify({
            cluster_id: null,
            name: 'A cluster',
            members: [],
            version: 2,
            entry_url: 'https://192.168.1.20:8443',
            fingerprint: 'AB:CD',
            verified: false,
            error: 'https://192.168.1.20:8443 presented a certificate with fingerprint 00:11, not the expected AB:CD.',
          }),
        ),
    });
    render(<JoinClusterForm onJoined={() => undefined} />);

    fireEvent.change(screen.getByLabelText('Cluster invite'), {
      target: { value: 'usr://cluster/usri_x@192.168.1.20:8443#AB:CD' },
    });

    expect(await screen.findByRole('alert')).toHaveTextContent('not the expected AB:CD');
    expect(screen.getByRole('button', { name: 'Join' })).toBeDisabled();
  });

  it('turns away a single-backend ticket', async () => {
    stub({});
    render(<JoinClusterForm onJoined={() => undefined} />);

    fireEvent.change(screen.getByLabelText('Cluster invite'), { target: { value: 'usr://ticket/abc' } });

    expect(await screen.findByRole('alert')).toHaveTextContent('not a cluster invite');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Join' })).toBeDisabled());
  });
});
