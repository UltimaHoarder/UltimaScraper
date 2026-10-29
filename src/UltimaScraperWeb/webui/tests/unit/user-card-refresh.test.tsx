import { act, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UserCardsProvider } from '../../src/features/users/UserCardsProvider';
import { useCachedUserCard, userCardKey } from '../../src/features/users/useCachedUserCard';
import type { UserCardItem } from '../../src/components/users/UserCard';

const mocks = vi.hoisted(() => ({ getCards: vi.fn(), onMessage: undefined as undefined | ((event: Record<string, unknown>) => void) }));
vi.mock('../../src/api/users', () => ({ getUserCards: mocks.getCards }));
vi.mock('../../src/hooks/useWebSocket', () => ({ useWebSocket: (options: {onMessage: typeof mocks.onMessage}) => { mocks.onMessage = options.onMessage; } }));
const cached: UserCardItem = { id: 1, user_id: 1, site: 'onlyfans', username: 'cached', name: 'Cached profile',
  post_count: 1, image_count: 2, video_count: 3, price: 0, is_active: true, last_checked_at: '2026-01-01T00:00:00Z' };
function Card({ item = cached, subscription = false, label = 'card' }: {item?: UserCardItem; subscription?: boolean; label?: string}) {
  const data = useCachedUserCard(item, subscription);
  return <div data-testid={label}>{data.name} · {data.is_active ? 'Active' : 'Inactive'} · {data.id}</div>;
}
function mount(children = <><Card label="users" /><Card label="favourites" /><Card label="subscriptions" subscription item={{...cached, id: 301, is_active: false}} /></>) {
  const client = new QueryClient({ defaultOptions: {queries: {retry: false}} });
  const result = render(<QueryClientProvider client={client}><UserCardsProvider>{children}</UserCardsProvider></QueryClientProvider>);
  return {client, ...result};
}
const event = {type: 'user_profile_updated', site: 'onlyfans', user_id: 1};
beforeEach(() => { mocks.getCards.mockResolvedValue({ users: [{...cached, name:'Fresh profile', last_checked_at:'2026-10-13T00:00:00Z'}] }); });

describe('shared user card background refresh', () => {
  it('renders cached data immediately, then updates all views in one bounded read', async () => {
    mount();
    expect(screen.getByTestId('users')).toHaveTextContent('Cached profile');
    expect(screen.getByTestId('subscriptions')).toHaveTextContent('Inactive · 301');
    expect(mocks.getCards).not.toHaveBeenCalled();
    act(() => { mocks.onMessage?.(event); mocks.onMessage?.(event); });
    await waitFor(() => expect(screen.getByTestId('users')).toHaveTextContent('Fresh profile'));
    expect(screen.getByTestId('favourites')).toHaveTextContent('Fresh profile');
    expect(screen.getByTestId('subscriptions')).toHaveTextContent('Fresh profile · Inactive · 301');
    expect(mocks.getCards).toHaveBeenCalledTimes(1);
    expect(mocks.getCards).toHaveBeenCalledWith([{site:'onlyfans', user_id:1}]);
  });
  it('ignores unrelated hints and cannot roll a newer profile back after a stale response', async () => {
    const {client} = mount();
    act(() => client.setQueryData(userCardKey('onlyfans',1), {...cached, name:'Newest', authoritative:true, last_checked_at:'2026-10-14T00:00:00Z'}));
    act(() => mocks.onMessage?.({...event, site:'fansly'}));
    await new Promise(resolve => setTimeout(resolve, 40));
    expect(mocks.getCards).not.toHaveBeenCalled();
    act(() => mocks.onMessage?.(event));
    await waitFor(() => expect(mocks.getCards).toHaveBeenCalledTimes(1));
    await act(() => new Promise(resolve => setTimeout(resolve, 10)));
    expect(screen.getByTestId('users')).toHaveTextContent('Newest');
  });
  it('recovers missed hints on reconnect and focus, keeping cached data on failure', async () => {
    mount();
    mocks.getCards.mockRejectedValueOnce(new Error('offline'));
    act(() => mocks.onMessage?.({type:'resync'}));
    await waitFor(() => expect(mocks.getCards).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId('users')).toHaveTextContent('Cached profile');
    act(() => window.dispatchEvent(new Event('focus')));
    await waitFor(() => expect(screen.getByTestId('users')).toHaveTextContent('Fresh profile'));
  });
  it('splits more than 200 visible profiles into bounded batches', async () => {
    mocks.getCards.mockResolvedValue({users:[]});
    mount(<>{Array.from({length:201}, (_,i) => <Card key={i} item={{...cached, id:i+1, user_id:i+1}} label={`card${i}`} />)}</>);
    act(() => mocks.onMessage?.({type:'resync'}));
    await waitFor(() => expect(mocks.getCards).toHaveBeenCalledTimes(2));
    expect(mocks.getCards.mock.calls.map(call => call[0].length)).toEqual([200,1]);
  });
});
