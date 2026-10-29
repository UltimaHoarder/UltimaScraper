import { QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { WebhooksPage } from '../../src/themes/ultima-atlas/views/webhooks/WebhooksPage';
import type { WebhookMessage } from '../../src/hooks/useWebhookStream';
import { createTestQueryClient } from './testUtils';

const mocks = vi.hoisted(() => ({ getWebhooks: vi.fn(), saveWebhookConfiguration: vi.fn(), getWatchList: vi.fn(), getWatchStats: vi.fn(), pauseWatches: vi.fn(), resumeWatches: vi.fn(), browseUsers: vi.fn(), addToWatchList: vi.fn(), removeFromWatchList: vi.fn(), clearMessages: vi.fn(), messages: [] as WebhookMessage[] }));
vi.mock('../../src/api/webhooks', () => mocks);
vi.mock('../../src/api/users', () => mocks);
vi.mock('../../src/hooks/useWebhookStream', () => ({ useWebhookStream: () => ({ messages: mocks.messages, isConnected: true, lastActivity: 0, clearMessages: mocks.clearMessages }) }));
const older: WebhookMessage = { id: 'older', event: 'subscription_added', category: 'usapi', receivedAt: '2026-10-11T23:59:00Z', payload: { type: 'subscription_added', site: 'fansly', username: 'ivy', user_id: 3071 } };
const newer: WebhookMessage = { id: 'newer', event: 'chat_message', category: 'usapi', receivedAt: '2026-10-12T03:02:00+02:00', payload: { type: 'chat_message', site: 'onlyfans', message: 'Studio update', user_id: 1042 } };
function renderPage() {
  const client = createTestQueryClient();
  const ui = () => <QueryClientProvider client={client}><WebhooksPage /></QueryClientProvider>;
  const result = render(ui());
  return { ...result, refresh: () => result.rerender(ui()) };
}
function navigate(name: string) { fireEvent.click(within(screen.getByRole('navigation', { name: 'Webhook workspace' })).getByRole('button', { name: new RegExp(`^${name}`, 'i') })); }

beforeEach(() => {
  mocks.messages = [older, newer];
  mocks.getWebhooks.mockResolvedValue({ sites: { onlyfans: { auth: { active: true, url: 'https://example.test/auth', hide_info: ['cookie'] }, download: { active: false, url: null, hide_info: [] } }, fansly: { auth: { active: false, url: null, hide_info: [] }, download: { active: false, url: null, hide_info: [] } } } });
  mocks.getWatchList.mockResolvedValue({ users: [{ id: 3071, username: 'ivy', site: 'fansly', downloaded_at: null }], total: 1 });
  mocks.getWatchStats.mockResolvedValue({ total_watched: 17, by_site: { fansly: 17 }, paused: false });
  mocks.browseUsers.mockResolvedValue({ users: [{ id: 1042, username: 'luna' }] });
  mocks.addToWatchList.mockResolvedValue({});
  mocks.removeFromWatchList.mockResolvedValue({});
  mocks.pauseWatches.mockResolvedValue({ paused: true });
  mocks.resumeWatches.mockResolvedValue({ paused: false });
});

describe('complete Event Journal workspace', () => {
  it('uses real overview metrics, site hook summaries, and shortcuts to every area', async () => {
    const { container } = renderPage();
    expect(screen.getByRole('heading', { name: 'Event journal' })).toBeInTheDocument();
    navigate('Overview');
    await screen.findByRole('heading', { name: 'Recent messages' });
    const metrics = container.querySelector('.wh-metrics')!;
    expect(metrics).toHaveTextContent('Active hooks1 of 4 configured');
    expect(metrics).toHaveTextContent('Retained messages2');
    expect(metrics).toHaveTextContent('Watched users17');
    expect(mocks.getWatchList).toHaveBeenCalledWith(undefined, undefined, 5);
    expect(container.querySelector('.wh-site-overview')).toHaveTextContent('1 of 2 hooks active');
    fireEvent.click(screen.getByRole('button', { name: /Active hooks/ }));
    await screen.findByRole('heading', { name: '1 · Choose a site' });
    expect(screen.getByRole('checkbox', { name: 'Hook: Auth' })).toBeChecked();
    navigate('Overview');
    await screen.findByRole('heading', { name: 'Recent messages' });
    fireEvent.click(screen.getByRole('button', { name: 'Manage watch list →' }));
    await screen.findByRole('heading', { name: 'Watched users' });
  });

  it('imports configured URLs and hidden fields into the site, hook, and destination editor', async () => {
    renderPage();
    navigate('Configuration');
    await screen.findByRole('heading', { name: '1 · Choose a site' });
    expect(screen.getByRole('textbox', { name: 'Destination 1 URL' })).toHaveValue('https://example.test/auth');
    fireEvent.click(screen.getByText('Fields to omit', { selector: 'summary' }));
    expect(screen.getByRole('textbox', { name: 'Fields to omit' })).toHaveValue('cookie');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Hook: Download' }));
    navigate('Messages');
    navigate('Configuration');
    expect(screen.getByRole('checkbox', { name: 'Hook: Download' })).toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Configure Fansly' }));
    expect(screen.getByText('No destinations yet')).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'Hook: Chat messages' })).not.toBeInTheDocument();
  });

  it('keeps the watch roster, search, site filters, pause/resume, add, remove, and undo wired to their APIs', async () => {
    renderPage();
    navigate('Watch list');
    await screen.findByRole('button', { name: 'Unwatch ivy' });
    fireEvent.change(screen.getByRole('textbox', { name: 'Search watched users' }), { target: { value: 'ivy' } });
    await waitFor(() => expect(mocks.getWatchList).toHaveBeenCalledWith(undefined, 'ivy', 50));
    fireEvent.change(screen.getByRole('combobox', { name: 'Filter watched users by site' }), { target: { value: 'fansly' } });
    await waitFor(() => expect(mocks.getWatchList).toHaveBeenCalledWith('fansly', 'ivy', 50));
    fireEvent.click(await screen.findByRole('button', { name: 'Unwatch ivy' }));
    await waitFor(() => expect(mocks.removeFromWatchList).toHaveBeenCalledWith(3071, 'fansly'));
    fireEvent.click(await screen.findByRole('button', { name: 'Undo unwatch' }));
    await waitFor(() => expect(mocks.addToWatchList).toHaveBeenCalledWith(3071, 'fansly'));
    mocks.getWatchStats.mockResolvedValue({ total_watched: 17, paused: true });
    fireEvent.click(await screen.findByRole('button', { name: 'Pause watch list' }));
    await waitFor(() => expect(mocks.pauseWatches).toHaveBeenCalled());
    fireEvent.click(await screen.findByRole('button', { name: 'Resume watch list' }));
    await waitFor(() => expect(mocks.resumeWatches).toHaveBeenCalled());
    fireEvent.click(screen.getByText('＋ Add a user'));
    fireEvent.change(screen.getByRole('combobox', { name: 'Site to search for users' }), { target: { value: 'fansly' } });
    fireEvent.change(screen.getByRole('textbox', { name: 'Search users to watch' }), { target: { value: 'luna' } });
    fireEvent.click(await screen.findByRole('button', { name: 'Watch @luna' }));
    await waitFor(() => expect(mocks.addToWatchList).toHaveBeenCalledWith(1042, 'fansly'));
  });

  it('orders events in UTC and holds the full snapshot during inspection, then resumes live filtering', () => {
    const { container, refresh } = renderPage();
    expect([...container.querySelectorAll('.wh-event-copy strong')].map((node) => node.textContent)).toEqual(['Chat message', 'Subscription added']);
    expect(screen.getByText('01:02')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: 'Search messages' }), { target: { value: '3071' } });
    fireEvent.click(screen.getByRole('button', { name: 'Pause updates' }));
    fireEvent.click(screen.getByRole('button', { name: 'Raw JSON' }));
    expect(container.querySelector('.wh-json')).toHaveTextContent('"user_id": 3071');
    mocks.messages = [{ ...newer, id: 'incoming', event: 'post_update' }];
    refresh();
    expect(screen.getByText('Subscription added')).toBeInTheDocument();
    expect(container.querySelector('.wh-json')).toHaveTextContent('"user_id": 3071');
    fireEvent.click(screen.getByRole('button', { name: 'Resume updates' }));
    expect(screen.getByText('No matching messages')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }));
    expect(screen.getByText('Post update')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    expect(mocks.clearMessages).toHaveBeenCalledOnce();
  });

  it('keeps a large retained journal responsive and pins older pages while new events arrive', () => {
    mocks.messages = Array.from({ length: 205 }, (_, index) => ({ ...newer, id: `event-${index}`, payload: { ...newer.payload, username: `paging-user-${index}` }, receivedAt: new Date(Date.UTC(2026, 9, 12, 0, 0, 205 - index)).toISOString() }));
    const { container, refresh } = renderPage();
    expect(container.querySelectorAll('.wh-event')).toHaveLength(100);
    expect(screen.getByText('1–100 of 205')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Older events' }));
    expect(screen.getByRole('button', { name: 'Resume updates' })).toBeInTheDocument();
    expect(screen.getByText('101–200 of 205')).toBeInTheDocument();
    mocks.messages = [{ ...newer, id: 'new-live-event' }, ...mocks.messages];
    refresh();
    expect(screen.getByText('101–200 of 205')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Older events' }));
    expect(screen.getByText('201–205 of 205')).toBeInTheDocument();
    expect(container.querySelectorAll('.wh-event')).toHaveLength(5);
    expect(screen.getByRole('button', { name: 'Inspect chat_message event-204' })).toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: 'Search messages' }), { target: { value: 'paging-user-0' } });
    expect(screen.getByRole('button', { name: 'Inspect chat_message event-0' })).toBeInTheDocument();
  });

  it('keeps configuration failures scoped to Configuration and never fabricates overview counts', async () => {
    mocks.getWebhooks.mockRejectedValue(new Error('Configuration unavailable'));
    renderPage();
    expect(screen.getByRole('heading', { name: 'Event journal' })).toBeInTheDocument();
    navigate('Configuration');
    await screen.findByText('Failed to load hook configuration');
    navigate('Overview');
    await screen.findByRole('alert');
    expect(screen.queryByRole('button', { name: /Active hooks/ })).not.toBeInTheDocument();
    navigate('Messages');
    expect(screen.getByRole('heading', { name: 'Event journal' })).toBeInTheDocument();
  });

  it('exposes additional watched users rather than silently dropping rows beyond the first page', async () => {
    mocks.getWatchList.mockResolvedValue({ users: [{ id: 3071, username: 'ivy', site: 'fansly' }], total: 60 });
    renderPage();
    navigate('Watch list');
    fireEvent.click(await screen.findByRole('button', { name: 'Load more users' }));
    await waitFor(() => expect(mocks.getWatchList).toHaveBeenCalledWith(undefined, undefined, 100));
  });
});
