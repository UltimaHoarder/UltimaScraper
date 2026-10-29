import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ConfirmDialog } from '../../src/themes/ultima-atlas/patterns/ConfirmDialog';

describe('Atlas confirmation dialog', () => {
  it('focuses cancellation, traps focus, and restores the opener and scroll state', () => {
    const opener = document.createElement('button');
    document.body.append(opener);
    opener.focus();
    const onClose = vi.fn();
    const { unmount } = render(<ConfirmDialog isOpen title="Delete operation?" description="Cannot be undone." onClose={onClose} onConfirm={vi.fn()} />);
    const cancel = screen.getByRole('button', { name: 'Cancel' });
    const confirm = screen.getByRole('button', { name: 'Confirm' });
    expect(cancel).toHaveFocus();
    expect(document.body.style.overflow).toBe('hidden');
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(confirm).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(cancel).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledOnce();
    unmount();
    expect(opener).toHaveFocus();
    expect(document.body.style.overflow).toBe('');
    opener.remove();
  });

  it('guards pending work from keyboard, backdrop, and repeat submission', () => {
    const onClose = vi.fn();
    const onConfirm = vi.fn();
    render(<ConfirmDialog isOpen isPending title="Apply configuration?" description="Updating." onClose={onClose} onConfirm={onConfirm} />);
    expect(screen.getByRole('dialog')).toHaveAttribute('aria-busy', 'true');
    fireEvent.keyDown(document, { key: 'Escape' });
    fireEvent.click(document.querySelector('.atlas-confirm-overlay')!);
    fireEvent.click(screen.getByRole('button', { name: 'Working...' }));
    expect(onClose).not.toHaveBeenCalled();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('provides unique names and descriptions and calls the existing confirm handler', () => {
    const onConfirm = vi.fn();
    render(<ConfirmDialog isOpen tone="neutral" title="Apply configuration?" description="Update this backend." onClose={vi.fn()} onConfirm={onConfirm} />);
    expect(screen.getByRole('dialog', { name: 'Apply configuration?' })).toHaveAccessibleDescription('Update this backend.');
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});
