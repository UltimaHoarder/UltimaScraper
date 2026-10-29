import { render } from './renderWithQuery';
import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';

import { PerformerCard, type PerformerCardItem } from '../../src/components/users/PerformerCard';
import { UsersResults } from '../../src/features/users/components/UsersResults';
import { useUsersPageController } from '../../src/features/users/hooks/useUsersPageController';
import type { UserInfo } from '../../src/api/types/users';

const mockUser: PerformerCardItem = {
  id: 1,
  user_id: 101,
  username: 'charlie',
  name: 'Charlie Test',
  description: 'Test performer',
  avatar_url: 'https://example.com/avatar.jpg',
  header_url: 'https://example.com/header.jpg',
  post_count: 50,
  image_count: 30,
  video_count: 20,
  price: 5.99,
  site: 'onlyfans',
  favorite: false,
  is_active: true,
};

describe('PerformerCard header and avatar lightbox interactions', () => {
  it('opens lightbox when clicking header image and does not trigger onSelect', () => {
    const onOpenLightbox = vi.fn();
    const onSelect = vi.fn();

    render(
      <PerformerCard
        item={mockUser}
        profileUrl="/users/1"
        rootClassName="user-card"
        inactiveLabel="Inactive"
        isSelected={false}
        isCreatingJob={false}
        isWatched={false}
        isWatchPending={false}
        isIgnored={false}
        isIgnorePending={false}
        onSelect={onSelect}
        onScrape={vi.fn()}
        onView={vi.fn()}
        onWatchToggle={vi.fn()}
        onIgnoreToggle={vi.fn()}
        formatNumber={(n) => String(n)}
        formatPrice={(p) => `$${p}`}
        onOpenLightbox={onOpenLightbox}
      />
    );

    const headerButton = screen.getByRole('button', { name: 'charlie header image' });
    expect(headerButton).toBeInTheDocument();

    fireEvent.click(headerButton);
    expect(onOpenLightbox).toHaveBeenCalledWith('https://example.com/header.jpg', 'charlie header');
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('opens lightbox when pressing Enter on header image', () => {
    const onOpenLightbox = vi.fn();
    const onSelect = vi.fn();

    render(
      <PerformerCard
        item={mockUser}
        profileUrl="/users/1"
        rootClassName="user-card"
        inactiveLabel="Inactive"
        isSelected={false}
        isCreatingJob={false}
        isWatched={false}
        isWatchPending={false}
        isIgnored={false}
        isIgnorePending={false}
        onSelect={onSelect}
        onScrape={vi.fn()}
        onView={vi.fn()}
        onWatchToggle={vi.fn()}
        onIgnoreToggle={vi.fn()}
        formatNumber={(n) => String(n)}
        formatPrice={(p) => `$${p}`}
        onOpenLightbox={onOpenLightbox}
      />
    );

    const headerButton = screen.getByRole('button', { name: 'charlie header image' });
    fireEvent.keyDown(headerButton, { key: 'Enter' });
    expect(onOpenLightbox).toHaveBeenCalledWith('https://example.com/header.jpg', 'charlie header');
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('opens lightbox when clicking profile avatar and does not trigger onSelect', () => {
    const onOpenLightbox = vi.fn();
    const onSelect = vi.fn();

    render(
      <PerformerCard
        item={mockUser}
        profileUrl="/users/1"
        rootClassName="user-card"
        inactiveLabel="Inactive"
        isSelected={false}
        isCreatingJob={false}
        isWatched={false}
        isWatchPending={false}
        isIgnored={false}
        isIgnorePending={false}
        onSelect={onSelect}
        onScrape={vi.fn()}
        onView={vi.fn()}
        onWatchToggle={vi.fn()}
        onIgnoreToggle={vi.fn()}
        formatNumber={(n) => String(n)}
        formatPrice={(p) => `$${p}`}
        onOpenLightbox={onOpenLightbox}
      />
    );

    const avatarButton = screen.getByRole('button', { name: 'charlie profile image' });
    expect(avatarButton).toBeInTheDocument();

    fireEvent.click(avatarButton);
    expect(onOpenLightbox).toHaveBeenCalledWith('https://example.com/avatar.jpg', 'charlie profile image');
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('opens lightbox when pressing Enter on profile avatar', () => {
    const onOpenLightbox = vi.fn();
    const onSelect = vi.fn();

    render(
      <PerformerCard
        item={mockUser}
        profileUrl="/users/1"
        rootClassName="user-card"
        inactiveLabel="Inactive"
        isSelected={false}
        isCreatingJob={false}
        isWatched={false}
        isWatchPending={false}
        isIgnored={false}
        isIgnorePending={false}
        onSelect={onSelect}
        onScrape={vi.fn()}
        onView={vi.fn()}
        onWatchToggle={vi.fn()}
        onIgnoreToggle={vi.fn()}
        formatNumber={(n) => String(n)}
        formatPrice={(p) => `$${p}`}
        onOpenLightbox={onOpenLightbox}
      />
    );

    const avatarButton = screen.getByRole('button', { name: 'charlie profile image' });
    fireEvent.keyDown(avatarButton, { key: 'Enter' });
    expect(onOpenLightbox).toHaveBeenCalledWith('https://example.com/avatar.jpg', 'charlie profile image');
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('does not make header or avatar button roles when urls are missing', () => {
    const onOpenLightbox = vi.fn();
    const userWithoutMedia: PerformerCardItem = {
      ...mockUser,
      avatar_url: null,
      header_url: null,
    };

    render(
      <PerformerCard
        item={userWithoutMedia}
        profileUrl="/users/1"
        rootClassName="user-card"
        inactiveLabel="Inactive"
        isSelected={false}
        isCreatingJob={false}
        isWatched={false}
        isWatchPending={false}
        isIgnored={false}
        isIgnorePending={false}
        onSelect={vi.fn()}
        onScrape={vi.fn()}
        onView={vi.fn()}
        onWatchToggle={vi.fn()}
        onIgnoreToggle={vi.fn()}
        formatNumber={(n) => String(n)}
        formatPrice={(p) => `$${p}`}
        onOpenLightbox={onOpenLightbox}
      />
    );

    expect(screen.queryByRole('button', { name: 'charlie header image' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'charlie profile image' })).not.toBeInTheDocument();
  });

  it('triggers onSelect when clicking the card body outside buttons and links', () => {
    const onOpenLightbox = vi.fn();
    const onSelect = vi.fn();

    const { container } = render(
      <PerformerCard
        item={mockUser}
        profileUrl="/users/1"
        rootClassName="user-card"
        inactiveLabel="Inactive"
        isSelected={false}
        isCreatingJob={false}
        isWatched={false}
        isWatchPending={false}
        isIgnored={false}
        isIgnorePending={false}
        onSelect={onSelect}
        onScrape={vi.fn()}
        onView={vi.fn()}
        onWatchToggle={vi.fn()}
        onIgnoreToggle={vi.fn()}
        formatNumber={(n) => String(n)}
        formatPrice={(p) => `$${p}`}
        onOpenLightbox={onOpenLightbox}
      />
    );

    const statsArea = container.querySelector('.stats');
    expect(statsArea).not.toBeNull();
    fireEvent.click(statsArea!);
    expect(onSelect).toHaveBeenCalledWith(mockUser);
    expect(onOpenLightbox).not.toHaveBeenCalled();
  });
});

describe('UsersResults passing onOpenLightbox', () => {
  it('passes onOpenLightbox to PerformerCard in grid view mode', () => {
    const onOpenLightbox = vi.fn();
    const user: UserInfo = {
      ...mockUser,
      avatar_url: mockUser.avatar_url ?? null,
      header_url: mockUser.header_url ?? null,
      favorite: mockUser.favorite ?? false,
      username: 'charlie',
      name: 'Charlie Test',
      sex: 0,
      description: 'Bio',
      media_count: 50,
      is_subscribed: false,
      is_pending_order: false,
      downloaded_at: null,
      last_checked_at: null,
    };

    render(
      <MemoryRouter>
        <UsersResults
          favoriteOnly={false}
          error={null}
          allUsers={[user]}
          loadedCount={1}
          totalCount={1}
          searchQuery=""
          viewMode="grid"
          selectedUsers={new Set()}
          watchedKeys={new Set()}
          ignoredKeys={new Set()}
          isCreatingJob={false}
          isAuthPickerLoading={false}
          isSubscribePending={false}
          isWatchPending={false}
          isIgnorePending={false}
          isUpdatePending={false}
          isLoadingInitialPage={false}
          isLoadingNextPage={false}
          hasMore={false}
          pageSize={50}
          loadMoreSentinelRef={{ current: null }}
          navigate={vi.fn()}
          onLoadMore={vi.fn()}
          onSelectUser={vi.fn()}
          onScrapeUser={vi.fn()}
          onSubscribeUser={vi.fn()}
          onWatchToggle={vi.fn()}
          onIgnoreToggle={vi.fn()}
          onEditUser={vi.fn()}
          onOpenLightbox={onOpenLightbox}
        />
      </MemoryRouter>
    );

    const header = screen.getByRole('button', { name: 'charlie header image' });
    fireEvent.click(header);
    expect(onOpenLightbox).toHaveBeenCalledWith('https://example.com/header.jpg', 'charlie header');

    const avatar = screen.getByRole('button', { name: 'charlie profile image' });
    fireEvent.click(avatar);
    expect(onOpenLightbox).toHaveBeenCalledWith('https://example.com/avatar.jpg', 'charlie profile image');
  });
});

describe('useUsersPageController lightbox state', () => {
  it('manages lightbox open and close state correctly', () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );

    const { result } = renderHook(() => useUsersPageController({ favoriteOnly: false }), {
      wrapper,
    });

    expect(result.current.lightboxUrl).toBeNull();

    act(() => {
      result.current.openLightbox('https://example.com/test-header.jpg', 'Test Header');
    });

    expect(result.current.lightboxUrl).toBe('https://example.com/test-header.jpg');
    expect(result.current.lightboxAlt).toBe('Test Header');

    act(() => {
      result.current.closeLightbox();
    });

    expect(result.current.lightboxUrl).toBeNull();
  });
});
