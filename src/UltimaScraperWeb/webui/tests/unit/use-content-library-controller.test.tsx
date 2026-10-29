import { act, render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ContentLibraryItem } from '../../src/api/types/content';
import { useContentLibraryController } from '../../src/features/content-library/hooks/useContentLibraryController';

const mockBrowseContentLibrary = vi.fn();
const mockGetSearchLoadouts = vi.fn();

vi.mock('../../src/api/content', () => ({
  browseContentLibrary: (...args: unknown[]) => mockBrowseContentLibrary(...args),
}));

vi.mock('../../src/api/loadouts', () => ({
  clearDefaultSearchLoadout: vi.fn(),
  deleteSearchLoadout: vi.fn(),
  getSearchLoadouts: (...args: unknown[]) => mockGetSearchLoadouts(...args),
  saveSearchLoadout: vi.fn(),
  setDefaultSearchLoadout: vi.fn(),
}));

let observerCallback: IntersectionObserverCallback | null = null;

class IntersectionObserverStub implements IntersectionObserver {
  readonly root = null;
  readonly rootMargin = '0px';
  readonly thresholds = [0];

  constructor(callback: IntersectionObserverCallback) {
    observerCallback = callback;
  }

  disconnect() {}
  observe() {}
  takeRecords(): IntersectionObserverEntry[] { return []; }
  unobserve() {}
}

function item(id: number): ContentLibraryItem {
  return {
    id,
    user_id: id,
    username: `user-${id}`,
    content_type: 'post',
    text: null,
    price: 0,
    paid: true,
    deleted: false,
    archived: false,
    media_count: 0,
    media: [],
    expires_at: null,
    created_at: '2026-08-15T00:00:00Z',
    site: 'onlyfans',
  };
}

describe('useContentLibraryController pagination', () => {
  beforeEach(() => {
    observerCallback = null;
    mockBrowseContentLibrary.mockReset();
    mockGetSearchLoadouts.mockReset();
    vi.stubGlobal('IntersectionObserver', IntersectionObserverStub);
    mockGetSearchLoadouts.mockResolvedValue({
      success: true,
      loadouts: [],
      default_name: null,
    });
  });

  it('requests the exact count on the first text-search page', async () => {
    mockBrowseContentLibrary.mockResolvedValue({
      success: true,
      content: Array.from({ length: 30 }, (_, index) => item(index + 1)),
      total: 90,
      total_is_exact: true,
      has_more: true,
    });

    function Harness() {
      const { items, total, totalIsExact } = useContentLibraryController();
      return <div>{`${items.length}:${total}:${String(totalIsExact)}`}</div>;
    }

    const view = render(
      <MemoryRouter initialEntries={['/?identifier=needle']}>
        <Harness />
      </MemoryRouter>,
    );

    await waitFor(() => expect(view.getByText('30:90:true')).toBeInTheDocument());
    expect(mockBrowseContentLibrary).toHaveBeenCalledTimes(1);
    expect(mockBrowseContentLibrary.mock.calls[0]?.[0]).toMatchObject({
      search: 'needle',
      includeTotal: true,
    });
  });

  it('deduplicates repeated sentinel notifications while the next page is pending', async () => {
    let resolveSecondPage: ((value: unknown) => void) | null = null;
    mockBrowseContentLibrary
      .mockResolvedValueOnce({
        success: true,
        content: Array.from({ length: 30 }, (_, index) => item(index + 1)),
        total: 60,
      })
      .mockImplementationOnce(
        () => new Promise((resolve) => { resolveSecondPage = resolve; }),
      );

    function Harness() {
      const { items, sentinelRef } = useContentLibraryController();
      return <div ref={sentinelRef}>{items.length}</div>;
    }

    const view = render(
      <MemoryRouter>
        <Harness />
      </MemoryRouter>,
    );

    await waitFor(() => expect(view.getByText('30')).toBeInTheDocument());
    expect(observerCallback).not.toBeNull();

    act(() => {
      const entry = { isIntersecting: true } as IntersectionObserverEntry;
      observerCallback?.([entry], {} as IntersectionObserver);
      observerCallback?.([entry], {} as IntersectionObserver);
    });

    expect(mockBrowseContentLibrary).toHaveBeenCalledTimes(2);
    expect(mockBrowseContentLibrary.mock.calls[1]?.[0]).toMatchObject({
      page: 2,
      includeTotal: false,
    });

    await act(async () => {
      resolveSecondPage?.({
        success: true,
        content: Array.from({ length: 30 }, (_, index) => item(index + 31)),
        total: 60,
      });
    });

    await waitFor(() => expect(view.getByText('60')).toBeInTheDocument());
  });
});
