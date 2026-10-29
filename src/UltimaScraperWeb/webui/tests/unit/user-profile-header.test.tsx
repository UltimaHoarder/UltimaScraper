import type { ComponentProps } from 'react';
import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { UserProfileHeader } from '../../src/features/user-profile/components/UserProfileHeader';
import { renderWithProviders } from './testUtils';

function buildProps(
  overrides: Partial<ComponentProps<typeof UserProfileHeader>> = {},
): ComponentProps<typeof UserProfileHeader> {
  return {
    toast: null,
    onDismissToast: vi.fn(),
    user: {
      user_id: 123,
      username: 'alice',
      site: 'onlyfans',
      name: 'Alice',
      description: 'Creator profile',
      avatar_url: null,
      header_url: null,
      socials: [],
      performer: true,
      favorite: false,
      is_active: true,
      post_count: 12,
      image_count: 40,
      video_count: 8,
      price: 10,
    } as never,
    onBack: vi.fn(),
    profileUrl: 'https://onlyfans.example/alice',
    profileDisplayName: 'Alice',
    profileDescription: 'Creator profile',
    userAliases: [],
    onOpenLightbox: vi.fn(),
    lightboxUrl: null,
    onCloseLightbox: vi.fn(),
    onScrape: vi.fn(),
    onDelegateScrape: vi.fn(),
    createJobPending: false,
    delegateJobPending: false,
    authPickerLoading: false,
    onViewMedia: vi.fn(),
    onSubscribe: vi.fn(),
    subscribePending: false,
    watched: false,
    onToggleWatch: vi.fn(),
    watchPending: false,
    onToggleFavorite: vi.fn(),
    favoritePending: false,
    onOpenEditModal: vi.fn(),
    updateProfilePending: false,
    onOpenChat: vi.fn(),
    paidPreviewLoading: false,
    paidPreviewTotal: 5,
    paidPreviewMediaCount: 12,
    onOpenPaidTab: vi.fn(),
    subscriptionCountdown: {
      tone: 'active',
      value: '5 days',
      detail: 'Renews in 5 days',
    },
    resolvedProfileSize: 2048,
    sizeLabel: 'Profile Size',
    sizeMeta: 'Estimated profile size',
    activeTab: 'overview',
    onTabClick: vi.fn(),
    paidTabLabel: 'Paid',
    hasSubscriptionsTab: true,
    ...overrides,
  };
}

describe('UserProfileHeader', () => {
  it('fires the primary profile actions and tab changes', () => {
    const onBack = vi.fn();
    const onScrape = vi.fn();
    const onDelegateScrape = vi.fn();
    const onViewMedia = vi.fn();
    const onSubscribe = vi.fn();
    const onToggleWatch = vi.fn();
    const onToggleFavorite = vi.fn();
    const onOpenEditModal = vi.fn();
    const onOpenChat = vi.fn();
    const onOpenPaidTab = vi.fn();
    const onTabClick = vi.fn();

    renderWithProviders(
      <UserProfileHeader
        {...buildProps({
          onBack,
          onScrape,
          onDelegateScrape,
          onViewMedia,
          onSubscribe,
          onToggleWatch,
          onToggleFavorite,
          onOpenEditModal,
          onOpenChat,
          onOpenPaidTab,
          onTabClick,
        })}
      />,
      { withRouter: false },
    );

    fireEvent.click(screen.getByRole('button', { name: /back/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Download' }));
    fireEvent.click(screen.getByRole('button', { name: 'More scrape actions' }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Delegate' }));
    fireEvent.click(screen.getByRole('button', { name: 'Browse Files' }));
    fireEvent.click(screen.getByRole('button', { name: 'Subscribe' }));
    fireEvent.click(screen.getByRole('button', { name: 'Watch' }));
    fireEvent.click(screen.getByRole('button', { name: /favorite/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Edit User' }));
    fireEvent.click(screen.getByRole('button', { name: 'Message' }));
    fireEvent.click(screen.getByRole('button', { name: /paid content/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Content' }));
    fireEvent.click(screen.getByRole('button', { name: 'Subscriptions' }));

    expect(onBack).toHaveBeenCalledTimes(1);
    expect(onScrape).toHaveBeenCalledTimes(1);
    expect(onDelegateScrape).toHaveBeenCalledTimes(1);
    expect(onViewMedia).toHaveBeenCalledTimes(1);
    expect(onSubscribe).toHaveBeenCalledTimes(1);
    expect(onToggleWatch).toHaveBeenCalledTimes(1);
    expect(onToggleFavorite).toHaveBeenCalledTimes(1);
    expect(onOpenEditModal).toHaveBeenCalledTimes(1);
    expect(onOpenChat).toHaveBeenCalledTimes(1);
    expect(onOpenPaidTab).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Est. Size')).not.toBeInTheDocument();
    expect(onTabClick).toHaveBeenNthCalledWith(1, 'content');
    expect(onTabClick).toHaveBeenNthCalledWith(2, 'subscriptions');
  });

  it('renders notifications in the shared toast container', () => {
    const onDismissToast = vi.fn();

    renderWithProviders(
      <UserProfileHeader
        {...buildProps({
          toast: { message: 'Updated @alice', type: 'success' },
          onDismissToast,
        })}
      />,
      { withRouter: false },
    );

    expect(document.body.querySelector('.toast-container')).not.toBeNull();
    expect(screen.getByText('Updated @alice')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Close notification' }));

    expect(onDismissToast).toHaveBeenCalledTimes(1);
  });

  it('closes the lightbox when Escape is pressed', () => {
    const onCloseLightbox = vi.fn();

    renderWithProviders(
      <UserProfileHeader
        {...buildProps({
          lightboxUrl: 'https://example.com/header.jpg',
          onCloseLightbox,
        })}
      />,
      { withRouter: false },
    );

    expect(screen.getByRole('dialog', { name: 'Image preview' })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(onCloseLightbox).toHaveBeenCalledTimes(1);
  });
});
