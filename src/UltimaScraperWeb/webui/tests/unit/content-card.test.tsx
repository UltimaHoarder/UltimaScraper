import { fireEvent, waitFor } from '@testing-library/react';
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest';

import { ContentCard } from '../../src/components/content/ContentCard';
import type { ContentLibraryItem } from '../../src/api/types/content';
import { renderWithProviders } from './testUtils';

const resizeObserverStub = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;

const baseItem: ContentLibraryItem = {
  id: 101,
  user_id: 202,
  username: 'alice',
  content_type: 'post',
  text: 'preview image',
  price: 15,
  paid: true,
  deleted: false,
  archived: false,
  media_count: 1,
  media: [
    {
      id: 303,
      category: 'image',
      preview: true,
      local_url: null,
      thumb_url: null,
    },
  ],
  expires_at: null,
  created_at: '2026-03-28T12:00:00Z',
  site: 'onlyfans',
};

describe('ContentCard', () => {
  beforeAll(() => {
    Object.defineProperty(globalThis, 'ResizeObserver', {
      configurable: true,
      writable: true,
      value: resizeObserverStub,
    });
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: vi.fn(() => 'blob:remote-thumbnail'),
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });
  });

  afterAll(() => {
    delete (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: originalCreateObjectURL,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: originalRevokeObjectURL,
    });
  });

  it('opens preview media in the lightbox when the item is already accessible', () => {
    const { container } = renderWithProviders(<ContentCard item={baseItem} />);

    const mediaButton = container.querySelector('.content-card-media-item');
    expect(mediaButton).not.toBeNull();

    fireEvent.click(mediaButton as Element);

    expect(container.querySelector('.cc-lightbox-overlay')).toBeInTheDocument();
    expect(container.querySelector('.cc-lightbox-image')).toBeInTheDocument();
  });

  it('opens video media in the lightbox instead of navigating to a video page', async () => {
    const videoItem: ContentLibraryItem = {
      ...baseItem,
      media: [{
        ...baseItem.media[0],
        category: 'video',
        duration: 42.75,
      }],
    };
    const { container } = renderWithProviders(<ContentCard item={videoItem} />);

    fireEvent.click(container.querySelector('.content-card-media-item') as Element);

    expect(container.querySelector('.cc-lightbox-overlay')).toBeInTheDocument();
    expect(container.querySelector('.cc-lightbox-media')).toHaveAttribute(
      'data-media-category',
      'video',
    );
    // The player is loaded on demand, so wait for it to mount.
    await waitFor(() => expect(container.querySelector('.vjs-lightbox')).toBeInTheDocument());
    expect(container.querySelector('.content-card-media-duration')).toHaveTextContent('0:42');
  });

  it('navigates between lightbox images with the left and right arrow keys', () => {
    const item: ContentLibraryItem = {
      ...baseItem,
      media_count: 2,
      media: [
        baseItem.media[0],
        {
          ...baseItem.media[0],
          id: 304,
        },
      ],
    };
    const { container } = renderWithProviders(<ContentCard item={item} />);

    fireEvent.click(container.querySelector('.content-card-media-item') as Element);
    expect(container.querySelector('.cc-lightbox-counter')).toHaveTextContent('1 / 2');

    fireEvent.keyDown(document, { key: 'ArrowRight' });
    expect(container.querySelector('.cc-lightbox-counter')).toHaveTextContent('2 / 2');

    fireEvent.keyDown(document, { key: 'ArrowLeft' });
    expect(container.querySelector('.cc-lightbox-counter')).toHaveTextContent('1 / 2');
  });

  it('keeps locked preview-only media out of the lightbox', () => {
    const lockedItem: ContentLibraryItem = {
      ...baseItem,
      paid: false,
    };
    const { container } = renderWithProviders(<ContentCard item={lockedItem} />);

    const mediaButton = container.querySelector('.content-card-media-item');
    expect(mediaButton).not.toBeNull();

    fireEvent.click(mediaButton as Element);

    expect(container.querySelector('.cc-lightbox-overlay')).not.toBeInTheDocument();
  });

  it('triggers onHideUser when clicking the 3-dotted menu and selecting hide user from results', () => {
    let hiddenUserId: number | null = null;
    let hiddenUsername: string | null | undefined = null;

    const { container } = renderWithProviders(
      <ContentCard
        item={baseItem}
        onHideUser={(userId, username) => {
          hiddenUserId = userId;
          hiddenUsername = username;
        }}
      />
    );

    const menuButton = container.querySelector('.content-card-menu-btn');
    expect(menuButton).not.toBeNull();
    fireEvent.click(menuButton as Element);

    const hideButton = Array.from(
      container.querySelectorAll('.content-card-dropdown-item')
    ).find((el) => el.textContent?.includes('Hide user from results'));

    expect(hideButton).toBeDefined();
    fireEvent.click(hideButton as Element);

    expect(hiddenUserId).toBe(202);
    expect(hiddenUsername).toBe('alice');
    expect(container.querySelector('.content-card-dropdown')).not.toBeInTheDocument();
  });

  it('tries the guarded remote thumbnail only after the local-only thumbnail fails', async () => {
    const item: ContentLibraryItem = {
      ...baseItem,
      media: [{
        ...baseItem.media[0],
        thumb_url: '/api/v1/media/thumbnail/onlyfans/303?local_only=true',
        fallback_thumb_url: '/api/v1/media/thumbnail/onlyfans/303?remote_only=true',
      }],
    };
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce({
        ok: true,
        status: 202,
        headers: new Headers({ 'Retry-After': '0' }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers(),
        blob: async () => new Blob(['thumbnail'], { type: 'image/png' }),
      } as Response);
    const { container } = renderWithProviders(<ContentCard item={item} />);
    const image = container.querySelector('.content-card-media-item img');

    expect(image).not.toBeNull();
    expect(image).toHaveAttribute(
      'src',
      '/api/v1/media/thumbnail/onlyfans/303?local_only=true',
    );
    fireEvent.error(image as Element);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        '/api/v1/media/thumbnail/onlyfans/303?remote_only=true',
        expect.objectContaining({ cache: 'no-store' }),
      );
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(container.querySelector('.content-card-media-item img')).toHaveAttribute(
        'src',
        'blob:remote-thumbnail',
      );
    });
    fetchMock.mockRestore();
  });

  it('highlights every case-insensitive occurrence of the active search text', () => {
    const item: ContentLibraryItem = {
      ...baseItem,
      text: 'Preview IMAGE and another image.',
      media: [],
    };
    const { container } = renderWithProviders(
      <ContentCard item={item} highlightText="image" />
    );

    const highlights = container.querySelectorAll('.content-card-search-highlight');
    expect(highlights).toHaveLength(2);
    expect(Array.from(highlights).map((element) => element.textContent)).toEqual([
      'IMAGE',
      'image',
    ]);
  });

  it('highlights rich text without changing safe links or treating the query as HTML', () => {
    const item: ContentLibraryItem = {
      ...baseItem,
      text: '<a href="https://example.com/search">Search link</a> and search text',
      media: [],
    };
    const { container } = renderWithProviders(
      <ContentCard item={item} highlightText="search" />
    );

    expect(container.querySelectorAll('.content-card-search-highlight')).toHaveLength(2);
    expect(container.querySelector('.content-card-text a')).toHaveAttribute(
      'href',
      'https://example.com/search',
    );
  });
});
