import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { UsersSelectionBar } from '../../src/features/users/components/UsersSelectionBar';

describe('UsersSelectionBar', () => {
  it('renders correctly when 0 items are selected and omits floating toolbar', () => {
    const onSelectAll = vi.fn();
    const onClearSelection = vi.fn();
    const onScrapeSelected = vi.fn();
    const onWatchSelected = vi.fn();
    const onIgnoreSelected = vi.fn();
    const onSetIdentitySelected = vi.fn();

    render(
      <UsersSelectionBar
        selectedCount={0}
        totalUsers={36}
        isCreatingJob={false}
        isAuthPickerLoading={false}
        isWatching={false}
        isIgnoring={false}
        isSettingIdentity={false}
        onSelectAll={onSelectAll}
        onClearSelection={onClearSelection}
        onScrapeSelected={onScrapeSelected}
        onWatchSelected={onWatchSelected}
        onIgnoreSelected={onIgnoreSelected}
        onSetIdentitySelected={onSetIdentitySelected}
      />
    );

    expect(screen.getByText('Click cards to select')).toBeInTheDocument();
    expect(screen.getByText('Ctrl/Cmd+A selects visible · Esc clears')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Select All (36)' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Clear Selection' })).not.toBeInTheDocument();
    expect(screen.queryByRole('toolbar', { name: 'Floating selection actions' })).not.toBeInTheDocument();

    const scrapeBtn = screen.getByRole('button', { name: 'Scrape (0)' });
    const watchBtn = screen.getByRole('button', { name: 'Watch (0)' });
    const ignoreBtn = screen.getByRole('button', { name: 'Ignore (0)' });
    const identityBtn = screen.getByRole('button', { name: 'Set Identity (0)' });

    expect(scrapeBtn).toBeDisabled();
    expect(watchBtn).toBeDisabled();
    expect(ignoreBtn).toBeDisabled();
    expect(identityBtn).toBeDisabled();

    // Verify actions container exists
    const actionsContainer = scrapeBtn.parentElement;
    expect(actionsContainer).toHaveClass('selection-bar-actions');
    expect(actionsContainer?.children).toHaveLength(4);
  });

  it('renders floating toolbar when items are selected and responds to actions', () => {
    const onSelectAll = vi.fn();
    const onClearSelection = vi.fn();
    const onScrapeSelected = vi.fn();
    const onWatchSelected = vi.fn();
    const onIgnoreSelected = vi.fn();
    const onSetIdentitySelected = vi.fn();

    render(
      <UsersSelectionBar
        selectedCount={3}
        totalUsers={36}
        isCreatingJob={false}
        isAuthPickerLoading={false}
        isWatching={false}
        isIgnoring={false}
        isSettingIdentity={false}
        onSelectAll={onSelectAll}
        onClearSelection={onClearSelection}
        onScrapeSelected={onScrapeSelected}
        onWatchSelected={onWatchSelected}
        onIgnoreSelected={onIgnoreSelected}
        onSetIdentitySelected={onSetIdentitySelected}
      />
    );

    // Floating toolbar is present
    const floatingToolbar = screen.getByRole('toolbar', { name: 'Floating selection actions' });
    expect(floatingToolbar).toBeInTheDocument();
    expect(floatingToolbar).toHaveClass('selection-bar-floating');

    // Both inline bar and floating bar show selected count and action buttons
    const scrapeButtons = screen.getAllByRole('button', { name: 'Scrape (3)' });
    expect(scrapeButtons).toHaveLength(2);

    const watchButtons = screen.getAllByRole('button', { name: 'Watch (3)' });
    expect(watchButtons).toHaveLength(2);

    const ignoreButtons = screen.getAllByRole('button', { name: 'Ignore (3)' });
    expect(ignoreButtons).toHaveLength(2);

    const identityButtons = screen.getAllByRole('button', { name: 'Set Identity (3)' });
    expect(identityButtons).toHaveLength(2);

    // Floating bar has clear button
    const floatingClearBtn = within(floatingToolbar).getByRole('button', { name: 'Clear' });
    expect(floatingClearBtn).toBeInTheDocument();
    fireEvent.click(floatingClearBtn);
    expect(onClearSelection).toHaveBeenCalledTimes(1);

    // Floating bar buttons trigger callbacks
    const floatingScrapeBtn = within(floatingToolbar).getByRole('button', { name: 'Scrape (3)' });
    fireEvent.click(floatingScrapeBtn);
    expect(onScrapeSelected).toHaveBeenCalledTimes(1);

    const floatingWatchBtn = within(floatingToolbar).getByRole('button', { name: 'Watch (3)' });
    fireEvent.click(floatingWatchBtn);
    expect(onWatchSelected).toHaveBeenCalledTimes(1);

    const floatingIgnoreBtn = within(floatingToolbar).getByRole('button', { name: 'Ignore (3)' });
    fireEvent.click(floatingIgnoreBtn);
    expect(onIgnoreSelected).toHaveBeenCalledTimes(1);

    const floatingIdentityBtn = within(floatingToolbar).getByRole('button', { name: 'Set Identity (3)' });
    fireEvent.click(floatingIdentityBtn);
    expect(onSetIdentitySelected).toHaveBeenCalledTimes(1);
  });
});
