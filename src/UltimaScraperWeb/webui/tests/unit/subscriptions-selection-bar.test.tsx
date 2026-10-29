import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { SubscriptionsSelectionBar } from '../../src/features/subscriptions/components/SubscriptionsSelectionBar';

describe('SubscriptionsSelectionBar', () => {
  it('renders correctly when 0 items are selected and omits floating toolbar', () => {
    const onSelectAll = vi.fn();
    const onClear = vi.fn();
    const onScrape = vi.fn();
    const onWatch = vi.fn();
    const onIgnore = vi.fn();

    render(
      <SubscriptionsSelectionBar
        selectedCount={0}
        visibleCount={20}
        createJobPending={false}
        onSelectAll={onSelectAll}
        onClear={onClear}
        onScrape={onScrape}
        onWatch={onWatch}
        onIgnore={onIgnore}
      />
    );

    expect(screen.getByText('Click cards to select')).toBeInTheDocument();
    expect(screen.getByText('Ctrl/Cmd+A selects visible · Esc clears')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Select All (20)' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Clear Selection' })).not.toBeInTheDocument();
    expect(screen.queryByRole('toolbar', { name: 'Floating selection actions' })).not.toBeInTheDocument();

    const scrapeBtn = screen.getByRole('button', { name: 'Scrape (0)' });
    const watchBtn = screen.getByRole('button', { name: 'Watch (0)' });
    const ignoreBtn = screen.getByRole('button', { name: 'Ignore (0)' });

    expect(scrapeBtn).toBeDisabled();
    expect(watchBtn).toBeDisabled();
    expect(ignoreBtn).toBeDisabled();
  });

  it('renders floating toolbar when items are selected and responds to actions', () => {
    const onSelectAll = vi.fn();
    const onClear = vi.fn();
    const onScrape = vi.fn();
    const onWatch = vi.fn();
    const onIgnore = vi.fn();

    render(
      <SubscriptionsSelectionBar
        selectedCount={5}
        visibleCount={20}
        createJobPending={false}
        onSelectAll={onSelectAll}
        onClear={onClear}
        onScrape={onScrape}
        onWatch={onWatch}
        onIgnore={onIgnore}
      />
    );

    // Floating toolbar is present
    const floatingToolbar = screen.getByRole('toolbar', { name: 'Floating selection actions' });
    expect(floatingToolbar).toBeInTheDocument();
    expect(floatingToolbar).toHaveClass('selection-bar-floating');

    // Both inline bar and floating bar show selected count and action buttons
    const scrapeButtons = screen.getAllByRole('button', { name: 'Scrape (5)' });
    expect(scrapeButtons).toHaveLength(2);

    const watchButtons = screen.getAllByRole('button', { name: 'Watch (5)' });
    expect(watchButtons).toHaveLength(2);

    const ignoreButtons = screen.getAllByRole('button', { name: 'Ignore (5)' });
    expect(ignoreButtons).toHaveLength(2);

    // Floating bar clear button
    const floatingClearBtn = within(floatingToolbar).getByRole('button', { name: 'Clear' });
    expect(floatingClearBtn).toBeInTheDocument();
    fireEvent.click(floatingClearBtn);
    expect(onClear).toHaveBeenCalledTimes(1);

    // Floating bar action buttons
    const floatingScrapeBtn = within(floatingToolbar).getByRole('button', { name: 'Scrape (5)' });
    fireEvent.click(floatingScrapeBtn);
    expect(onScrape).toHaveBeenCalledTimes(1);

    const floatingWatchBtn = within(floatingToolbar).getByRole('button', { name: 'Watch (5)' });
    fireEvent.click(floatingWatchBtn);
    expect(onWatch).toHaveBeenCalledTimes(1);

    const floatingIgnoreBtn = within(floatingToolbar).getByRole('button', { name: 'Ignore (5)' });
    fireEvent.click(floatingIgnoreBtn);
    expect(onIgnore).toHaveBeenCalledTimes(1);
  });
});
