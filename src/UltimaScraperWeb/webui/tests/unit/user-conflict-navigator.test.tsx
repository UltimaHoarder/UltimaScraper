import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import type { UserIdentifierCandidate } from '../../src/api/types/users';
import { UserConflictNavigator } from '../../src/features/user-profile/components/UserConflictNavigator';

const candidates: UserIdentifierCandidate[] = [
  {
    user_id: 91095,
    username: 'missmakaylacox',
    active: true,
    last_checked_at: null,
    matched_by: ['username', 'alias'],
  },
  {
    user_id: 21275519,
    username: 'u21275519',
    active: false,
    last_checked_at: null,
    matched_by: ['alias'],
  },
];

function renderNavigator(currentUserId: number | null) {
  return render(
    <MemoryRouter>
      <UserConflictNavigator
        identifier="missmakaylacox"
        candidates={candidates}
        total={2}
        currentUserId={currentUserId}
        refreshing={false}
        hrefFor={(userId) => `/users/${userId}?conflict=missmakaylacox`}
        chooserHref="/users/missmakaylacox"
      />
    </MemoryRouter>,
  );
}

describe('UserConflictNavigator', () => {
  it('names every claimant and marks the open one', () => {
    renderNavigator(91095);

    const list = screen.getByRole('list');
    const current = within(list).getByRole('link', { current: 'page' });
    expect(current).toHaveTextContent('@missmakaylacox');
    expect(current).toHaveTextContent('91095');
    expect(current).toHaveTextContent('Current name');
    expect(within(list).getByRole('link', { name: /u21275519/ })).toHaveTextContent(
      'Former name · inactive',
    );
  });

  it('links Prev and Next to the neighbouring claimants', () => {
    renderNavigator(91095);

    expect(screen.queryByRole('link', { name: /^Previous/ })).toBeNull();
    expect(screen.getByRole('link', { name: 'Next: @u21275519' })).toHaveAttribute(
      'href',
      '/users/21275519?conflict=missmakaylacox',
    );
    expect(screen.getByRole('link', { name: 'Compare' })).toHaveAttribute(
      'href',
      '/users/missmakaylacox',
    );
  });

  it('says so when the open profile no longer claims the handle', () => {
    renderNavigator(555);

    expect(screen.getByText(/this profile no longer claims it/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { current: 'page' })).toBeNull();
  });
});
