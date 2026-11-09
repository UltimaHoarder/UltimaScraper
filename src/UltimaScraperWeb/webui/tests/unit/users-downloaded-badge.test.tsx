import { render } from './renderWithQuery';
import { screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { UsersResults } from '../../src/features/users/components/UsersResults';
import type { UserInfo } from '../../src/api/types/users';

function user(id: number, username: string, downloadedAt: string | null): UserInfo {
  return {
    id, user_id: id, username, name: null, sex: 0, description: null, avatar_url: null, header_url: null,
    post_count: 1, media_count: 1, image_count: 1, video_count: 0, price: 0, site: 'onlyfans', favorite: false,
    is_active: true, is_subscribed: false, is_pending_order: false, downloaded_at: downloadedAt, last_checked_at: null,
  };
}

const users = [user(1, 'saved', '2026-11-08T19:15:56+00:00'), user(2, 'never', null)];

function renderResults(viewMode: 'table' | 'grid') {
  render(
    <MemoryRouter>
      <UsersResults
        favoriteOnly={false} error={null} allUsers={users} loadedCount={2} totalCount={2} searchQuery=""
        viewMode={viewMode} selectedUsers={new Set()} watchedKeys={new Set()} ignoredKeys={new Set()}
        isCreatingJob={false} isAuthPickerLoading={false} isSubscribePending={false} isWatchPending={false}
        isIgnorePending={false} isUpdatePending={false} isLoadingInitialPage={false} isLoadingNextPage={false}
        hasMore={false} pageSize={50} loadMoreSentinelRef={{ current: null }} navigate={vi.fn()}
        onLoadMore={vi.fn()} onSelectUser={vi.fn()} onScrapeUser={vi.fn()} onSubscribeUser={vi.fn()}
        onWatchToggle={vi.fn()} onIgnoreToggle={vi.fn()} onEditUser={vi.fn()}
      />
    </MemoryRouter>,
  );
}

const lastDownloaded = `Last downloaded ${new Date('2026-11-08T19:15:56+00:00').toLocaleDateString()}`;

describe('Downloaded badge on the users page', () => {
  it('marks only downloaded creators in the table', () => {
    renderResults('table');

    const saved = screen.getByRole('row', { name: /@saved/ });
    expect(within(saved).getByText('Downloaded')).toHaveAttribute('title', lastDownloaded);
    expect(within(screen.getByRole('row', { name: /@never/ })).queryByText('Downloaded')).toBeNull();
  });

  it('marks only downloaded creators in the grid', () => {
    renderResults('grid');

    const badges = document.body.querySelectorAll('.downloaded-badge');
    expect(badges).toHaveLength(1);
    expect(badges[0]).toHaveAttribute('title', lastDownloaded);
    expect(badges[0].closest('.user-card')).toHaveTextContent('@saved');
  });
});
