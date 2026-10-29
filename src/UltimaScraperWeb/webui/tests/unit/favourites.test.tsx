import { fireEvent, render, screen, waitFor, act, cleanup } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider, type InfiniteData } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { FavouriteButton } from '../../src/features/favourites/FavouriteButton';
import { FavouritesProvider } from '../../src/features/favourites/FavouritesProvider';
import { loadFavouriteState } from '../../src/features/favourites/favouritesCache';
import { favouriteKey, type FavouriteKey, type FavouritePage, type FavouriteState } from '../../src/api/favourites';
import { FavouritesPage } from '../../src/themes/ultima-atlas/views/favourites/FavouritesPage';

const mocks = vi.hoisted(() => ({ status: vi.fn(), states: vi.fn(), set: vi.fn(), page: vi.fn(), counts: vi.fn(), event: undefined as undefined | ((event: Record<string,unknown>) => void) }));
vi.mock('../../src/api/favourites', async () => ({ ...(await vi.importActual('../../src/api/favourites')),
  getFavouritesStatus: mocks.status, getFavouriteStates: mocks.states, setFavourite: mocks.set,
  getFavourites: mocks.page, getFavouriteCounts: mocks.counts,
}));
vi.mock('../../src/hooks/useWebSocket', () => ({ useWebSocket: (options: { onMessage: typeof mocks.event }) => { mocks.event = options.onMessage; return {}; } }));

const key: FavouriteKey = { site: 'onlyfans', entity_type: 'user', entity_id: 1 };
const state = (key: FavouriteKey, favourited = false): FavouriteState => ({ ...key, favourited, favourite_id: null, created_at: null, created_at_source: null });
const createClient = () => new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
function wrap(client: QueryClient, element: React.ReactNode) {
  return render(<QueryClientProvider client={client}><MemoryRouter><FavouritesProvider>{element}</FavouritesProvider></MemoryRouter></QueryClientProvider>);
}

describe('unified favourites', () => {
  beforeEach(() => {
    mocks.status.mockResolvedValue({ enabled: true });
    mocks.states.mockImplementation(async (keys: FavouriteKey[]) => keys.map(key => state(key)));
    mocks.set.mockImplementation(async (key: FavouriteKey, desired: boolean) => state(key,desired));
    mocks.page.mockResolvedValue({ items: [], has_more: false, next_cursor: null });
    mocks.counts.mockResolvedValue({ total: 0, by_type: { user:0,post:0,story:0,message:0 } });
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals(); });

  it('batches 201 checks into requests of at most 200', async () => {
    const client = createClient();
    const values = await Promise.all(Array.from({length:201},(_,i) => loadFavouriteState(client,{...key,entity_id:i+1})));
    expect(values).toHaveLength(201);
    expect(mocks.states.mock.calls.map(call => call[0].length)).toEqual([200,1]);
  });

  it('shares state and blocks duplicate submissions across controls', async () => {
    const client = createClient();
    let finish!: (state: FavouriteState) => void;
    mocks.set.mockReturnValue(new Promise<FavouriteState>(resolve => { finish = resolve; }));
    wrap(client,<><FavouriteButton entity={key} initialFavorite={false}/><FavouriteButton entity={key} initialFavorite={false}/></>);
    const buttons = await screen.findAllByRole('button',{name:'Add favourite user 1'});
    fireEvent.click(buttons[0]); fireEvent.click(buttons[1]);
    await waitFor(() => expect(mocks.set).toHaveBeenCalledTimes(1));
    expect(buttons[0]).toHaveAttribute('aria-pressed','true');
    mocks.states.mockImplementation(async (keys: FavouriteKey[]) => keys.map(key => state(key,true)));
    await act(async () => finish(state(key,true)));
    expect(buttons[1]).toHaveAttribute('aria-pressed','true');
  });

  it.each([false, true])('rolls back a failed removal without restoring another record (infinite=%s)', async infinite => {
    const client = createClient();
    const other = {...key,entity_id:2};
    const item = (entity: FavouriteKey) => ({ ...entity,id:entity.entity_id,created_at:'2025-01-01Z',created_at_source:'added',availability:'available' as const,entity:null });
    const page = {items:[item(key),item(other)],has_more:false,next_cursor:null} satisfies FavouritePage;
    client.setQueryData(['favourites-list','test'], infinite ? {pages:[{...page,items:[]},page],pageParams:[null,'next']} : page);
    let reject!: (error: Error) => void;
    mocks.set.mockReturnValue(new Promise((_resolve, fail) => { reject = fail; }));
    wrap(client,<FavouriteButton entity={key} initialFavorite/>);
    fireEvent.click(await screen.findByRole('button',{name:'Remove favourite user 1'}));
    await waitFor(() => expect(mocks.set).toHaveBeenCalledOnce());
    if (infinite) client.setQueryData<InfiniteData<FavouritePage>>(['favourites-list','test'],data => ({...data!,pages:data!.pages.map(page => ({...page,items:[]}))}));
    else client.setQueryData<FavouritePage>(['favourites-list','test'],page => ({...page!,items:[]}));
    await act(async () => reject(new Error('Save failed')));
    expect(await screen.findByRole('alert')).toHaveTextContent('Save failed');
    const restored = client.getQueryData<FavouritePage | InfiniteData<FavouritePage>>(['favourites-list','test'])!;
    expect(('pages' in restored ? restored.pages.flatMap(page => page.items) : restored.items).map(item => item.entity_id)).toEqual([1]);
    if ('pages' in restored) expect(restored.pageParams).toEqual([null, 'next']);
    expect(client.getQueryData<FavouriteState>(favouriteKey(key))?.pending).toBeFalsy();
  });

  it('opens on Users and filters types without loading unbounded results', async () => {
    const client = createClient();
    wrap(client,<FavouritesPage/>);
    expect(await screen.findByRole('tab',{name:'Users (0)'})).toHaveAttribute('aria-selected','true');
    await waitFor(() => expect(mocks.page).toHaveBeenCalled());
    expect(mocks.page.mock.calls.at(-1)?.[0].entity_type).toBe('user');
    fireEvent.click(screen.getByRole('tab',{name:'Stories (0)'}));
    await waitFor(() => expect(mocks.page.mock.calls.at(-1)?.[0].entity_type).toBe('story'));
    expect(screen.queryByRole('button',{name:'Next'})).not.toBeInTheDocument();
    expect(screen.queryByRole('button',{name:'Load More (50)'})).not.toBeInTheDocument();
  });

  it('sources the page from the favourites API even when legacy controls are enabled', async () => {
    mocks.status.mockResolvedValue({ enabled: false });
    wrap(createClient(), <FavouritesPage/>);
    expect(await screen.findByRole('tab', { name: 'Users (0)' })).toHaveAttribute('aria-selected', 'true');
    await waitFor(() => expect(mocks.page).toHaveBeenCalled());
    expect(mocks.page.mock.calls.at(-1)?.[0].entity_type).toBe('user');
    expect(screen.queryByText('Browse favourited creators from your database')).not.toBeInTheDocument();
  });

  it('shows canonical API errors instead of falling back to legacy user favourites', async () => {
    mocks.status.mockResolvedValue({ enabled: false });
    mocks.page.mockRejectedValue(new Error('Favourites backfill/cutover is incomplete'));
    wrap(createClient(), <FavouritesPage/>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Favourites backfill/cutover is incomplete');
    expect(screen.getByRole('tab', { name: 'Users (0)' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByText('No favourites found.')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeVisible();
  });

  it('appends cursor batches on intersection, deduplicates and suppresses concurrent loading', async () => {
    let intersect!: IntersectionObserverCallback;
    vi.stubGlobal('IntersectionObserver', class {
      constructor(callback: IntersectionObserverCallback) { intersect = callback; }
      observe() {} disconnect() {}
    });
    const item = (id: number) => ({...key,id,entity_id:id,created_at:'2025-01-01Z',created_at_source:'added',availability:'available',entity:null});
    let complete!: (value: unknown) => void;
    mocks.page.mockImplementation((_filters, cursor) => cursor === null
      ? Promise.resolve({items:[item(1)],has_more:true,next_cursor:'next'})
      : new Promise(resolve => { complete = resolve; }));
    wrap(createClient(), <FavouritesPage/>);
    await screen.findByText('1 visible');
    await waitFor(() => expect(intersect).toBeTypeOf('function'));
    act(() => { intersect([{isIntersecting:true}] as IntersectionObserverEntry[], {} as IntersectionObserver); intersect([{isIntersecting:true}] as IntersectionObserverEntry[], {} as IntersectionObserver); });
    await waitFor(() => expect(mocks.page).toHaveBeenCalledTimes(2));
    expect(mocks.page.mock.calls[1][1]).toBe('next');
    expect(screen.getByText('1 visible')).toBeInTheDocument();
    await act(async () => complete({items:[item(1),item(2)],has_more:false,next_cursor:null}));
    expect(await screen.findByText('2 visible')).toBeInTheDocument();
    expect(screen.getByText('All favourites loaded')).toBeInTheDocument();
    expect(screen.queryByRole('button',{name:'Next'})).not.toBeInTheDocument();
  });

  it('keeps loaded cards when the next batch fails and retries the same cursor', async () => {
    const item = {...key,id:1,created_at:'2025-01-01Z',created_at_source:'added',availability:'available',entity:null};
    mocks.page.mockResolvedValueOnce({items:[item],has_more:true,next_cursor:'cursor'});
    mocks.page.mockRejectedValueOnce(new Error('Offline'));
    mocks.page.mockResolvedValue({items:[],has_more:false,next_cursor:null});
    wrap(createClient(), <FavouritesPage/>);
    fireEvent.click(await screen.findByRole('button',{name:'Load More (50)'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('loaded favourites are still visible');
    expect(screen.getByText('1 visible')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'Retry loading more'}));
    await screen.findByText('All favourites loaded');
    expect(mocks.page.mock.calls.slice(1).map(call => call[1])).toEqual(['cursor','cursor']);
  });

  it('applies creator filters to pages and grouped counts, validates and clears them', async () => {
    const client = createClient();
    wrap(client, <FavouritesPage/>);
    fireEvent.click(await screen.findByRole('button',{name:'Filters'}));
    expect(screen.getByRole('dialog',{name:'Favourite filters'})).toBeVisible();
    fireEvent.change(screen.getByRole('spinbutton',{name:'Minimum price'}),{target:{value:'10'}});
    fireEvent.change(screen.getByRole('spinbutton',{name:'Maximum price'}),{target:{value:'2'}});
    fireEvent.click(screen.getByRole('button',{name:'Apply'}));
    expect(screen.getByRole('alert')).toHaveTextContent('Minimum values');
    fireEvent.change(screen.getByRole('spinbutton',{name:'Maximum price'}),{target:{value:'20'}});
    fireEvent.change(screen.getByRole('combobox',{name:'Favourite availability'}),{target:{value:'available'}});
    fireEvent.click(screen.getAllByRole('checkbox',{name:'Female'})[0]);
    fireEvent.click(screen.getByRole('button',{name:'Apply'}));
    await waitFor(() => expect(mocks.page.mock.calls.at(-1)?.[0]).toMatchObject({entity_type:'user',availability:'available',min_price:10,max_price:20,sex:[0]}));
    expect(mocks.page.mock.calls.at(-1)?.[1]).toBeNull();
    await waitFor(() => expect(mocks.counts.mock.calls.at(-1)?.[0]).toMatchObject({availability:'available',min_price:10,max_price:20,sex:[0]}));
    expect(mocks.counts.mock.calls.at(-1)?.[0]).not.toHaveProperty('entity_type');
    fireEvent.click(screen.getByRole('button',{name:'Filters (4)'}));
    fireEvent.click(screen.getByRole('button',{name:'Clear'}));
    fireEvent.click(screen.getByRole('button',{name:'Apply'}));
    await waitFor(() => expect(screen.getByRole('button',{name:'Filters'})).toBeVisible());
    expect(client.getQueryCache().findAll({type:'active',queryKey:['favourites-list']})[0].queryKey[1]).not.toHaveProperty('min_price');
  });

  it('resets accumulated results when filters change and ignores a stale next batch', async () => {
    const item = (id: number) => ({...key,id,entity_id:id,created_at:'2025-01-01Z',created_at_source:'added',availability:'available',entity:null});
    let complete!: (value: unknown) => void;
    mocks.page.mockImplementation((filters, cursor) => filters.site === 'fansly'
      ? Promise.resolve({items:[],has_more:false,next_cursor:null})
      : cursor === null ? Promise.resolve({items:[item(1)],has_more:true,next_cursor:'old'})
      : new Promise(resolve => { complete = resolve; }));
    wrap(createClient(), <FavouritesPage/>);
    fireEvent.click(await screen.findByRole('button',{name:'Load More (50)'}));
    await waitFor(() => expect(complete).toBeTypeOf('function'));
    fireEvent.change(screen.getByRole('combobox',{name:'Favourite site'}),{target:{value:'fansly'}});
    await screen.findByText('No favourites found.');
    await act(async () => complete({items:[item(2)],has_more:false,next_cursor:null}));
    expect(screen.getByText('0 visible')).toBeInTheDocument();
    expect(mocks.page.mock.calls.at(-1)?.[1]).toBeNull();
  });

  it('rechecks server state for stale event hints and reconnects', async () => {
    const client = createClient();
    wrap(client,<FavouriteButton entity={key}/>);
    await screen.findByRole('button',{name:'Add favourite user 1'});
    mocks.states.mockImplementation(async (keys: FavouriteKey[]) => keys.map(key => state(key,true)));
    act(() => mocks.event?.({type:'favourite_changed',...key,favourited:false}));
    await screen.findByRole('button',{name:'Remove favourite user 1'});
    const before = mocks.states.mock.calls.length;
    act(() => mocks.event?.({type:'resync'}));
    await waitFor(() => expect(mocks.states.mock.calls.length).toBeGreaterThan(before));
  });
});
