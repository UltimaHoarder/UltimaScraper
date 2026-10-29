import { describe, expect, it } from 'vitest';

import { SUBSCRIPTION_SORT_OPTIONS } from '../../src/features/subscriptions/lib/subscriptionsUtils';
import {
  USERS_SORT_OPTIONS,
  applyUsersLoadoutState,
  getUsersSortOptions,
} from '../../src/features/users/lib/usersUtils';

describe('shared sort options', () => {
  it('includes created_at for users', () => {
    expect(USERS_SORT_OPTIONS).toContainEqual({ value: 'created_at', label: 'Created' });
  });

  it('excludes created_at for favourites', () => {
    expect(getUsersSortOptions(true)).not.toContainEqual({
      value: 'created_at',
      label: 'Created',
    });
  });

  it('falls back from created_at in favourite loadouts', () => {
    expect(
      applyUsersLoadoutState(
        {
          name: 'favorites-default',
          type: 'users',
          identifier: '',
          description: '',
          site: 'onlyfans',
          filters: { sort_by: 'created_at', sort_order: 'desc' },
          is_default: false,
          updated_at: null,
        },
        true
      ).sortByValue
    ).toBe('id');
  });

  it('includes created_at for subscriptions', () => {
    expect(SUBSCRIPTION_SORT_OPTIONS).toContainEqual({ value: 'created_at', label: 'Created' });
  });
});