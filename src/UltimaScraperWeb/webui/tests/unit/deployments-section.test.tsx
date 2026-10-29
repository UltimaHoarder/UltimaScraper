import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { DeploymentsSection } from '../../src/features/connections/DeploymentsSection';

const DEPLOYMENT = {
  id: 'dep1',
  name: 'NAS',
  target: 'deploy@nas',
  details: {
    kind: 'ssh',
    host: 'nas',
    port: 22,
    username: 'deploy',
    install_dir: '/home/deploy/ultimascraper',
    project: 'usr-nas',
    version: '0.1.0',
    image_source: 'copy',
    image_prefix: '',
    architecture: 'arm64',
  },
  connection_id: 'nas',
};

function stubServer() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith('/deployments')) return new Response(JSON.stringify([DEPLOYMENT]), { status: 200 });
    if (url.endsWith('/operations') && init?.method === 'POST') {
      return new Response(JSON.stringify({ id: 'run1' }), { status: 202 });
    }
    if (url.includes('/installs/run1')) {
      return new Response(
        JSON.stringify({
          id: 'run1',
          name: 'NAS',
          target: 'deploy@nas',
          state: 'succeeded',
          connection_id: null,
          operation: 'uninstall',
          deployment_id: 'dep1',
          events: [{ seq: 1, at: 0, kind: 'done', message: 'NAS is uninstalled.' }],
        }),
        { status: 200 },
      );
    }
    return new Response('{}', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('DeploymentsSection', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders nothing when this WebUI installed nothing', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('[]', { status: 200 })));
    const { container } = render(<DeploymentsSection onChanged={() => undefined} />);

    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('uninstalls with fresh credentials and keeps the data unless asked', async () => {
    const fetchMock = stubServer();
    const onChanged = vi.fn();
    render(<DeploymentsSection onChanged={onChanged} />);

    expect(await screen.findByText('NAS')).toBeInTheDocument();
    expect(screen.getByText('arm64')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Uninstall' }));
    expect(screen.getByLabelText(/delete (its|local container) data/i)).not.toBeChecked();
    fireEvent.change(screen.getByLabelText('Password for deploy@nas'), { target: { value: 'ssh-password' } });
    fireEvent.change(screen.getByLabelText('Your WebUI password, to confirm'), { target: { value: 'site-password' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Uninstall' }).at(-1)!);

    expect(await screen.findByText('NAS is uninstalled.')).toBeInTheDocument();
    const operation = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/operations'));
    expect(JSON.parse(String(operation?.[1]?.body))).toEqual({
      action: 'uninstall',
      credentials: { password: 'ssh-password' },
      delete_data: false,
      remove_files: true,
      webui_password: 'site-password',
    });
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it('only uninstalls after the WebUI password is given, and shows a wrong one', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith('/deployments')) return new Response(JSON.stringify([DEPLOYMENT]), { status: 200 });
        if (url.endsWith('/operations') && init?.method === 'POST') {
          return new Response(JSON.stringify({ detail: 'Wrong WebUI password.' }), { status: 403 });
        }
        return new Response('{}', { status: 404 });
      }),
    );
    render(<DeploymentsSection onChanged={() => undefined} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Uninstall' }));

    const confirm = screen.getByLabelText('Your WebUI password, to confirm');
    expect(confirm).toBeRequired();
    // Repair and upgrade never ask for it.
    fireEvent.click(screen.getByRole('button', { name: 'Repair' }));
    expect(screen.queryByLabelText('Your WebUI password, to confirm')).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByRole('button', { name: 'Uninstall' })[0]);
    fireEvent.change(screen.getByLabelText('Password for deploy@nas'), { target: { value: 'ssh-password' } });
    fireEvent.change(screen.getByLabelText('Your WebUI password, to confirm'), { target: { value: 'wrong' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Uninstall' }).at(-1)!);

    expect(await screen.findByRole('alert')).toHaveTextContent('Wrong WebUI password.');
  });

  it('asks for neither SSH credentials nor sudo password for a local deployment in the docker group', async () => {
    const localDeployment = {
      ...DEPLOYMENT,
      id: 'dep-local',
      name: 'LocalBox',
      target: 'this machine',
      details: {
        ...DEPLOYMENT.details,
        kind: 'local',
        host: '',
        username: '',
      },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/deployments')) return new Response(JSON.stringify([localDeployment]), { status: 200 });
      if (url.endsWith('/installs/detect')) {
        return new Response(
          JSON.stringify({
            facts: { sudo_mode: 'none' },
            needs_sudo_for: [],
          }),
          { status: 200 },
        );
      }
      if (url.endsWith('/operations') && init?.method === 'POST') {
        return new Response(JSON.stringify({ id: 'run-local' }), { status: 202 });
      }
      if (url.includes('/installs/run-local')) {
        return new Response(
          JSON.stringify({
            id: 'run-local',
            name: 'LocalBox',
            target: 'this machine',
            state: 'succeeded',
            connection_id: 'local',
            operation: 'repair',
            deployment_id: 'dep-local',
            events: [{ seq: 1, at: 0, kind: 'done', message: 'LocalBox is repaired.' }],
          }),
          { status: 200 },
        );
      }
      return new Response('{}', { status: 404 });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<DeploymentsSection onChanged={() => undefined} />);
    expect(await screen.findByText('LocalBox')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Repair' }));

    expect(screen.queryByText('SSH password')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/sudo password/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByRole('button', { name: 'Repair' }).at(-1)!);
    expect(await screen.findByText('LocalBox is repaired.')).toBeInTheDocument();
  });

  it('asks only for a sudo password on a local deployment when detection says sudo password is needed', async () => {
    const localDeployment = {
      ...DEPLOYMENT,
      id: 'dep-local-sudo',
      name: 'LocalSudo',
      target: 'this machine',
      details: {
        ...DEPLOYMENT.details,
        kind: 'local',
        host: '',
        username: '',
      },
    };
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.endsWith('/deployments')) return new Response(JSON.stringify([localDeployment]), { status: 200 });
        if (url.endsWith('/installs/detect')) {
          return new Response(
            JSON.stringify({
              facts: { sudo_mode: 'password' },
              needs_sudo_for: ['docker group'],
            }),
            { status: 200 },
          );
        }
        return new Response('{}', { status: 404 });
      }),
    );

    render(<DeploymentsSection onChanged={() => undefined} />);
    expect(await screen.findByText('LocalSudo')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Repair' }));

    expect(screen.queryByText('SSH password')).not.toBeInTheDocument();
    expect(await screen.findByLabelText('sudo password')).toBeInTheDocument();
  });

  it('starts an upgrade on the running version, so re-pulling a tag needs no typing', async () => {
    const fetchMock = stubServer();
    render(<DeploymentsSection onChanged={() => undefined} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Upgrade' }));
    const version = screen.getByLabelText('Version');
    expect(version).toHaveValue('0.1.0');
    expect(screen.getByText(/NAS runs 0\.1\.0\. Upgrading to it again pulls the newest build/)).toBeInTheDocument();

    fireEvent.change(version, { target: { value: '0.2.0' } });
    expect(screen.queryByText(/Upgrading to it again/)).not.toBeInTheDocument();
    fireEvent.change(version, { target: { value: '0.1.0' } });

    fireEvent.change(screen.getByLabelText('Password for deploy@nas'), { target: { value: 'ssh-password' } });
    fireEvent.click(screen.getAllByRole('button', { name: 'Upgrade' }).at(-1)!);

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/operations'))).toBe(true),
    );
    const operation = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/operations'));
    expect(JSON.parse(String(operation?.[1]?.body))).toMatchObject({ action: 'upgrade', version: '0.1.0' });
  });
});
