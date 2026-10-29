import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { WebUIUpdateCard } from '../../src/features/connections/WebUIUpdateCard';

const STATUS = {
  version: '0.1.0.dev20261024000000',
  install_kind: 'uv-tool',
  channel: 'edge',
  index: 'https://forge.example/api/packages/owner/pypi/simple',
  latest: '0.1.0.dev20261025004224',
  update_available: true,
  can_update: true,
  reason: null,
};

function stub(status: object, { sessionFailures = 0 } = {}) {
  let sessions = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith('/self')) return new Response(JSON.stringify(status), { status: 200 });
    if (url.endsWith('/self/update') && init?.method === 'POST') {
      return new Response(JSON.stringify({ version: '0.1.0.dev20261025004224', log: '', restarting: true }), {
        status: 200,
      });
    }
    if (url.endsWith('/session')) {
      sessions += 1;
      if (sessions <= sessionFailures) throw new TypeError('Failed to fetch');
      return new Response(JSON.stringify({ authenticated: true }), { status: 200 });
    }
    return new Response('{}', { status: 404 });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

describe('WebUIUpdateCard', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('updates, waits for the restarted WebUI and reloads onto it', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const fetchMock = stub(STATUS, { sessionFailures: 2 });
    const reload = vi.fn();
    render(<WebUIUpdateCard reload={reload} />);

    expect(await screen.findByTitle('The installed WebUI version')).toHaveTextContent('0.1.0.dev20261024000000');
    expect(screen.getByTitle('Which builds this WebUI updates to')).toHaveTextContent('edge');
    fireEvent.click(screen.getByRole('button', { name: 'Update to 0.1.0.dev20261025004224' }));

    expect(await screen.findByText('Installed 0.1.0.dev20261025004224. Restarting…')).toBeInTheDocument();
    await act(() => vi.advanceTimersByTimeAsync(10_000));

    expect(reload).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/session'))).toHaveLength(3);
  });

  it('explains why there is no update instead of offering one', async () => {
    stub({ ...STATUS, update_available: false, can_update: false, latest: null, reason: 'Set USR_WEBUI_UPDATE_INDEX to the package index CI publishes to.' });
    render(<WebUIUpdateCard reload={() => undefined} />);

    expect(await screen.findByText(/Set USR_WEBUI_UPDATE_INDEX/)).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('says when it is up to date', async () => {
    stub({ ...STATUS, update_available: false, can_update: false, latest: STATUS.version });
    render(<WebUIUpdateCard reload={() => undefined} />);

    expect(await screen.findByText('✓ Up to date')).toBeInTheDocument();
  });

  it('says when nothing is published yet', async () => {
    stub({ ...STATUS, update_available: false, can_update: false, latest: null });
    render(<WebUIUpdateCard reload={() => undefined} />);

    expect(await screen.findByText('Nothing has been published to the package index yet.')).toBeInTheDocument();
  });
});
