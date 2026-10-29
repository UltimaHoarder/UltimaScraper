import type { ComponentProps } from 'react';
import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { UserProfileOverviewTab } from '../../src/features/user-profile/components/UserProfileOverviewTab';
import { renderWithProviders } from './testUtils';

function buildProps(
  overrides: Partial<ComponentProps<typeof UserProfileOverviewTab>> = {},
): ComponentProps<typeof UserProfileOverviewTab> {
  return {
    user: {
      user_id: 123,
      username: 'sample_creator',
      site: 'onlyfans',
      name: 'Sample',
      balance: 0,
      price: 15,
      media_count: 125,
      audio_count: 4,
      stream_count: 2,
      archived_post_count: 9,
      favourited_count: 6,
      subscribers_count: 1200,
      sex: 1,
      gender: 2,
      join_date: '2024-01-01T00:00:00Z',
      downloaded_at: '2024-02-01T00:00:00Z',
      first_downloaded_at: '2024-01-02T00:00:00Z',
      created_at: '2024-01-01T00:00:00Z',
      last_checked_at: '2024-02-02T00:00:00Z',
      location: 'Earth',
      website: 'example.com',
      promotion: false,
      is_subscribed: true,
      subscription_expires_at: '2024-03-01T00:00:00Z',
    } as never,
    activeOverviewVersion: undefined,
    activeOverviewData: null,
    historySnapshotsLength: 0,
    historyLoading: false,
    hasOlderOverviewVersion: false,
    hasNewerOverviewVersion: false,
    onSelectOlderVersion: vi.fn(),
    onSelectNewerVersion: vi.fn(),
    subscriptionCountdown: {
      tone: 'active',
      value: '5 days',
      detail: 'Renews in 5 days',
    },
    onOpenSexModal: vi.fn(),
    updateProfilePending: false,
    estimatedProfileSize: 739_200_000_000,
    showEstimatedProfileSize: true,
    estimatedSizeMeta: 'Confirmed bytes + 2026-06-15 estimate',
    directoryLookup: {
      success: true,
      username: 'sample_creator',
      site: 'onlyfans',
      user_directory_format: '{site}/{model_username}',
      matches: [
        {
          root: '/mnt/storage-a/site',
          path: '/mnt/storage-a/site/S/sample_creator',
        },
        {
          root: '/mnt/storage-b/site',
          path: '/mnt/storage-b/site/S/sample_creator',
        },
      ],
      checked_patterns: [],
      usernames_searched: ['sample_creator'],
      resolved_user_id: 123,
    },
    directoryLookupFetched: true,
    directoryLookupLoading: false,
    directoryLookupError: false,
    onFindDirectory: vi.fn(),
    copiedDirPath: '/mnt/storage-b/site/S/sample_creator',
    onCopyDir: vi.fn(),
    ...overrides,
  };
}

describe('UserProfileOverviewTab', () => {
  it('shows the estimated size inside content stats for the current overview', () => {
    renderWithProviders(<UserProfileOverviewTab {...buildProps()} />, { withRouter: false });

    expect(screen.getByText('Estimated Size')).toBeInTheDocument();
    expect(screen.getByText('688.4 GB')).toBeInTheDocument();
  });

  it('hides the estimated size when browsing a historical snapshot', () => {
    renderWithProviders(
      <UserProfileOverviewTab
        {...buildProps({
          activeOverviewVersion: {
            key: 'history-12',
            label: 'Snapshot 12',
            createdAt: '2024-01-10T00:00:00Z',
            data: {
              description: '',
              price: 15,
              media_count: 100,
              audio_count: 4,
              stream_count: 0,
              archived_post_count: 9,
              favourited_count: 6,
              subscribers_count: 1200,
              location: 'Earth',
              website: 'example.com',
              sex: 1,
              join_date: '2024-01-01T00:00:00Z',
              last_checked_at: '2024-01-10T00:00:00Z',
              downloaded_at: '2024-02-01T00:00:00Z',
              first_downloaded_at: '2024-01-02T00:00:00Z',
              created_at: '2024-01-10T00:00:00Z',
            },
          },
          activeOverviewData: {
            description: '',
            price: 15,
            media_count: 100,
            audio_count: 4,
            stream_count: 0,
            archived_post_count: 9,
            favourited_count: 6,
            subscribers_count: 1200,
            location: 'Earth',
            website: 'example.com',
            sex: 1,
            join_date: '2024-01-01T00:00:00Z',
            last_checked_at: '2024-01-10T00:00:00Z',
            downloaded_at: '2024-02-01T00:00:00Z',
            first_downloaded_at: '2024-01-02T00:00:00Z',
            created_at: '2024-01-10T00:00:00Z',
          },
        })}
      />,
      { withRouter: false },
    );

    expect(screen.queryByText('Estimated Size')).not.toBeInTheDocument();
  });

  it('renders every directory match and copies the selected path', () => {
    const onCopyDir = vi.fn();

    renderWithProviders(
      <UserProfileOverviewTab {...buildProps({ onCopyDir })} />,
      { withRouter: false },
    );

    expect(screen.getByText('Directories')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '/mnt/storage-a/site/S/sample_creator' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: '/mnt/storage-b/site/S/sample_creator' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Copied')).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole('button', { name: '/mnt/storage-a/site/S/sample_creator' }),
    );

    expect(onCopyDir).toHaveBeenCalledWith('/mnt/storage-a/site/S/sample_creator');
  });
});
