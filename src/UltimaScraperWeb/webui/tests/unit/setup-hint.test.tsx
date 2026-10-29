import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { SetupHint } from '../../src/features/setup/components/SetupHint';

describe('SetupHint', () => {
  it('shows its explanation outside the clipped setup card', () => {
    const { container } = render(
      <div style={{ overflow: 'hidden' }}>
        <SetupHint text="Folders on the server where finished media is saved." />
      </div>,
    );
    const hint = screen.getByRole('img', { name: 'More information' });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();

    fireEvent.mouseEnter(hint);
    const tooltip = screen.getByRole('tooltip');
    expect(tooltip).toHaveTextContent('Folders on the server where finished media is saved.');
    expect(container).not.toContainElement(tooltip);
    expect(hint).toHaveAttribute('aria-describedby', tooltip.id);

    fireEvent.mouseLeave(hint);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });

  it('opens for keyboard users and closes when the page scrolls', () => {
    render(<SetupHint text="Explained." />);
    const hint = screen.getByRole('img', { name: 'More information' });

    fireEvent.focus(hint);
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
    fireEvent.scroll(window);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });
});
