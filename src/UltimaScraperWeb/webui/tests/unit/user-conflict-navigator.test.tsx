import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { UserConflictNavigator } from '../../src/features/user-profile/components/UserConflictNavigator';

describe('UserConflictNavigator', () => {
  it('navigates between conflicting profiles from the profile page', () => {
    const onPageChange = vi.fn();
    render(
      <UserConflictNavigator
        identifier="christinaxiong"
        page={1}
        total={2}
        loading={false}
        onPageChange={onPageChange}
      />,
    );

    expect(screen.getByLabelText('Conflicting profile position')).toHaveTextContent('Record 1 of 2');
    expect(screen.getByRole('button', { name: 'Previous conflicting profile' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Next conflicting profile' }));
    expect(onPageChange).toHaveBeenCalledWith(2);
  });
});
