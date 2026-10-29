import { render } from './renderWithQuery';
import { fireEvent, screen, act } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { PerformerCard, type PerformerCardItem } from '../../src/components/users/PerformerCard';
import { ImageHoverPreview, type HoverPreviewState } from '../../src/shared/ui/ImageHoverPreview';

const mockPerformer: PerformerCardItem = {
  id: 1,
  user_id: 101,
  username: 'candice',
  name: 'Candice Test',
  description: 'Test bio',
  avatar_url: 'https://example.com/avatar.jpg',
  header_url: 'https://example.com/header.jpg',
  post_count: 10,
  image_count: 5,
  video_count: 2,
  price: 9.99,
  site: 'onlyfans',
  is_active: true,
};

describe('ImageHoverPreview component', () => {
  it('renders popover with image and caption when preview state is provided', () => {
    const preview: HoverPreviewState = {
      imageUrl: 'https://example.com/test-img.jpg',
      alt: 'Test performer profile image',
      kind: 'avatar',
      targetRect: new DOMRect(100, 100, 48, 48),
    };
    const onEnter = vi.fn();
    const onLeave = vi.fn();
    const onClick = vi.fn();

    render(
      <ImageHoverPreview
        preview={preview}
        onEnter={onEnter}
        onLeave={onLeave}
        onClick={onClick}
      />
    );

    const tooltip = screen.getByRole('tooltip', { name: 'Test performer profile image preview' });
    expect(tooltip).toBeInTheDocument();

    const img = screen.getByAltText('Test performer profile image');
    expect(img).toHaveAttribute('src', 'https://example.com/test-img.jpg');

    fireEvent.click(tooltip);
    expect(onClick).toHaveBeenCalledWith('https://example.com/test-img.jpg', 'Test performer profile image');

    fireEvent.mouseEnter(tooltip);
    expect(onEnter).toHaveBeenCalled();

    fireEvent.mouseLeave(tooltip);
    expect(onLeave).toHaveBeenCalled();
  });

  it('renders nothing when preview is null', () => {
    const { container } = render(
      <ImageHoverPreview
        preview={null}
        onEnter={vi.fn()}
        onLeave={vi.fn()}
      />
    );
    expect(container.firstChild).toBeNull();
  });
});

describe('PerformerCard 1-second hover preview interactions', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('brings up avatar preview after 1 second of hover, and hides on mouse leave', () => {
    const onOpenLightbox = vi.fn();

    render(
      <PerformerCard
        item={mockPerformer}
        profileUrl="/users/1"
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
        onOpenLightbox={onOpenLightbox}
      />
    );

    const avatar = screen.getByRole('button', { name: 'candice profile image' });

    // Hover begins
    fireEvent.mouseEnter(avatar);

    // After 500ms, preview should NOT be visible yet
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();

    // After 1000ms total, preview appears
    act(() => {
      vi.advanceTimersByTime(500);
    });
    const tooltip = screen.getByRole('tooltip');
    expect(tooltip).toBeInTheDocument();
    expect(screen.getByAltText('candice profile image')).toHaveAttribute('src', 'https://example.com/avatar.jpg');

    // Clicking preview opens full lightbox
    fireEvent.click(tooltip);
    expect(onOpenLightbox).toHaveBeenCalledWith('https://example.com/avatar.jpg', 'candice profile image');
  });

  it('cancels avatar hover preview if mouse leaves before 1 second', () => {
    render(
      <PerformerCard
        item={mockPerformer}
        profileUrl="/users/1"
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
        onOpenLightbox={vi.fn()}
      />
    );

    const avatar = screen.getByRole('button', { name: 'candice profile image' });

    // Hover starts
    fireEvent.mouseEnter(avatar);
    act(() => {
      vi.advanceTimersByTime(600);
    });

    // Mouse leaves before 1s
    fireEvent.mouseLeave(avatar);
    act(() => {
      vi.advanceTimersByTime(600);
    });

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('brings up header preview after 1 second of hover on header', () => {
    const onOpenLightbox = vi.fn();

    render(
      <PerformerCard
        item={mockPerformer}
        profileUrl="/users/1"
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
        onOpenLightbox={onOpenLightbox}
      />
    );

    const header = screen.getByRole('button', { name: 'candice header image' });

    fireEvent.mouseEnter(header);
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    const tooltip = screen.getByRole('tooltip');
    expect(tooltip).toBeInTheDocument();
    expect(screen.getByAltText('candice header')).toHaveAttribute('src', 'https://example.com/header.jpg');

    // Mouse leaves trigger and grace period expires
    fireEvent.mouseLeave(header);
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('does not trigger header preview when hovering over the dropdown button', () => {
    render(
      <PerformerCard
        item={mockPerformer}
        profileUrl="/users/1"
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
        onOpenLightbox={vi.fn()}
      />
    );

    const dropdownBtn = screen.getByTitle('More actions');

    // Hover directly on the dropdown button
    fireEvent.mouseEnter(dropdownBtn);
    act(() => {
      vi.advanceTimersByTime(1500);
    });

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('cancels pending header preview when moving cursor onto dropdown button', () => {
    render(
      <PerformerCard
        item={mockPerformer}
        profileUrl="/users/1"
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
        onOpenLightbox={vi.fn()}
      />
    );

    const header = screen.getByRole('button', { name: 'candice header image' });
    const dropdownBtn = screen.getByTitle('More actions');

    // Hover starts on header
    fireEvent.mouseEnter(header);
    act(() => {
      vi.advanceTimersByTime(500);
    });

    // Cursor moves onto the dropdown button
    fireEvent.mouseEnter(dropdownBtn);
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('does not show hover preview when dropdown menu is open', () => {
    render(
      <PerformerCard
        item={mockPerformer}
        profileUrl="/users/1"
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
        onOpenLightbox={vi.fn()}
      />
    );

    const dropdownBtn = screen.getByTitle('More actions');
    fireEvent.click(dropdownBtn);

    // Dropdown is open, items are visible
    const dropdownItems = screen.getAllByText('Download');
    expect(dropdownItems.length).toBeGreaterThanOrEqual(1);

    const dropdownItem = dropdownItems[0];
    fireEvent.mouseEnter(dropdownItem);
    act(() => {
      vi.advanceTimersByTime(1500);
    });

    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });
});
