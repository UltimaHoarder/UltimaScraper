import { render } from './renderWithQuery';
import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { PerformerCard, type PerformerCardItem } from '../../src/components/users/PerformerCard';
import { getUserDescription } from '../../src/features/users/lib/usersUtils';
import { type UserInfo } from '../../src/features/users/lib/usersUtils';

describe('PerformerCard and User Description', () => {
  const sampleLongBio =
    'Hello sweetie thanks for coming to check out my feeties. A bit about me to start: I am a Canadian female content creator and artist sharing exclusive content with all my fans!';

  it('getUserDescription does not truncate text with a hardcoded character limit', () => {
    const mockUser: UserInfo = {
      id: 1,
      user_id: 101,
      username: 'candice',
      name: 'Candice',
      site: 'onlyfans',
      description: sampleLongBio,
      sex: null,
      avatar_url: null,
      header_url: null,
      price: 0,
      post_count: 0,
      media_count: 0,
      image_count: 0,
      video_count: 0,
      favorite: false,
      is_active: true,
      is_subscribed: false,
      is_pending_order: false,
      downloaded_at: null,
      last_checked_at: null,
    };

    const desc = getUserDescription(mockUser);
    expect(desc).toBe(sampleLongBio);
    expect(desc).not.toContain('crea...');
    expect(desc).toContain('creator');
  });

  it('PerformerCard renders full text without character cutoff so CSS line clamp can handle it', () => {
    const mockItem: PerformerCardItem = {
      id: 1,
      user_id: 101,
      username: 'candice',
      name: 'Candice',
      site: 'onlyfans',
      description: sampleLongBio,
      is_active: true,
      post_count: 10,
      image_count: 5,
      video_count: 2,
      price: 9.99,
    };

    render(
      <PerformerCard
        item={mockItem}
        profileUrl="https://onlyfans.com/candice"
        rootClassName="user-card"
        inactiveLabel="Inactive"
        isSelected={false}
        isCreatingJob={false}
        isWatched={false}
        isWatchPending={false}
        isIgnored={false}
        isIgnorePending={false}
        formatNumber={(n) => String(n)}
        formatPrice={(p) => `$${p}`}
        onSelect={vi.fn()}
        onScrape={vi.fn()}
        onView={vi.fn()}
        onWatchToggle={vi.fn()}
        onIgnoreToggle={vi.fn()}
      />
    );

    const descriptionEl = screen.getByTitle(sampleLongBio);
    expect(descriptionEl).toBeInTheDocument();
    expect(descriptionEl.textContent).toBe(sampleLongBio);
    expect(descriptionEl.textContent).not.toContain('crea...');
  });
});
