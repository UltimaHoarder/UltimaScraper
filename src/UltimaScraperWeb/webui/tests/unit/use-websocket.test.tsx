import { StrictMode } from 'react';
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { RESYNC_EVENT, useWebSocket } from '../../src/hooks/useWebSocket';
vi.mock('../../src/api/http', () => ({ backendUrl: (url: string) => url }));
class Socket {
  static OPEN = 1;
  static CONNECTING = 0;
  static instances: Socket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => { this.readyState = 3; });
  constructor() { Socket.instances.push(this); }
  open() { this.readyState = 1; this.onopen?.(); }
  message(value: unknown) { this.onmessage?.({ data: JSON.stringify(value) }); }
}
beforeEach(() => { vi.useFakeTimers(); Socket.instances = []; vi.stubGlobal('WebSocket', Socket); });
// The connection lingers this long after the last hook unmounts.
const IDLE_CLOSE_MS = 2000;
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
it('leaves no sockets or timers after unmount, even with a delayed close', () => {
  const { unmount } = renderHook(() => useWebSocket({ url: 'ws://localhost/events' }));
  const socket = Socket.instances[0];
  act(() => { socket.open(); socket.message({ type: 'event' }); });
  const delayedClose = socket.onclose;
  unmount();
  act(() => { delayedClose?.(); vi.advanceTimersByTime(60_000); });
  expect(socket.onmessage).toBeNull();
  expect(Socket.instances).toHaveLength(1);
  expect(vi.getTimerCount()).toBe(0);
});
it('keeps one socket through StrictMode replay', () => {
  const { result, unmount } = renderHook(() => useWebSocket({ url: 'ws://localhost/events' }), { wrapper: StrictMode });
  expect(Socket.instances).toHaveLength(1);
  act(() => Socket.instances[0].open());
  expect(result.current.isConnected).toBe(true);
  unmount();
  act(() => vi.advanceTimersByTime(60_000));
  expect(Socket.instances).toHaveLength(1);
  expect(Socket.instances[0].onmessage).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
});
it('delivers every event while batching rendered snapshots', () => {
  const onMessage = vi.fn();
  const { result, unmount } = renderHook(() => useWebSocket({ url: 'ws://localhost/events', onMessage }));
  act(() => {
    Socket.instances[0].open();
    for (let index = 0; index < 10_000; index++) Socket.instances[0].message({ type: 'event', index });
  });
  expect(onMessage).toHaveBeenCalledTimes(10_000);
  expect(result.current.lastMessage).toBeNull();
  act(() => vi.advanceTimersByTime(1000));
  expect(result.current.lastMessage).toEqual({ type: 'event', index: 9999 });
  unmount();
  act(() => vi.advanceTimersByTime(IDLE_CLOSE_MS));
  expect(vi.getTimerCount()).toBe(0);
});
it('reconnects after a server disconnect while mounted', () => {
  const { unmount } = renderHook(() => useWebSocket({ url: 'ws://localhost/events' }));
  act(() => { Socket.instances[0].open(); Socket.instances[0].onclose?.(); });
  act(() => vi.advanceTimersByTime(3000));
  expect(Socket.instances).toHaveLength(2);
  unmount();
  act(() => vi.advanceTimersByTime(IDLE_CLOSE_MS));
  expect(vi.getTimerCount()).toBe(0);
});

const sentSubscriptions = (socket: Socket) => socket.send.mock.calls
  .map(([raw]) => JSON.parse(raw as string))
  .filter((message) => message.type === 'subscribe')
  .map((message) => message.topics);

it('shares one socket and subscribes to the union of topics', () => {
  const first = renderHook(() => useWebSocket({ url: 'ws://localhost/shared', topics: ['logs'] }));
  const second = renderHook(() => useWebSocket({ url: 'ws://localhost/shared', topics: ['jobs', 'job:abc'] }));
  expect(Socket.instances).toHaveLength(1);
  act(() => Socket.instances[0].open());
  expect(sentSubscriptions(Socket.instances[0]).at(-1)).toEqual(['job:abc', 'jobs', 'logs']);
  second.unmount();
  expect(sentSubscriptions(Socket.instances[0]).at(-1)).toEqual(['logs']);
  first.unmount();
  act(() => vi.advanceTimersByTime(IDLE_CLOSE_MS));
  expect(vi.getTimerCount()).toBe(0);
});

it('resubscribes when a hook changes its topics', () => {
  const { rerender, unmount } = renderHook(
    ({ topics }: { topics: ('jobs' | `job:${string}`)[] }) => useWebSocket({ url: 'ws://localhost/topics', topics }),
    { initialProps: { topics: ['jobs'] } },
  );
  act(() => Socket.instances[0].open());
  rerender({ topics: ['jobs', 'job:selected'] });
  expect(sentSubscriptions(Socket.instances[0]).at(-1)).toEqual(['job:selected', 'jobs']);
  expect(Socket.instances).toHaveLength(1);
  unmount();
  act(() => vi.advanceTimersByTime(IDLE_CLOSE_MS));
});

it('tells hooks to refetch after a reconnect, not after the first connect', () => {
  const onMessage = vi.fn();
  const { unmount } = renderHook(() => useWebSocket({ url: 'ws://localhost/resync', onMessage }));
  act(() => Socket.instances[0].open());
  expect(onMessage).not.toHaveBeenCalled();
  act(() => { Socket.instances[0].onclose?.(); vi.advanceTimersByTime(3000); Socket.instances[1].open(); });
  expect(onMessage).toHaveBeenCalledWith(RESYNC_EVENT);
  unmount();
  act(() => vi.advanceTimersByTime(IDLE_CLOSE_MS));
});
