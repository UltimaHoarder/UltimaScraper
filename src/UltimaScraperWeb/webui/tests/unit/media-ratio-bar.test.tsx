import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MediaRatioBar } from '../../src/components/users/MediaRatioBar';

describe('MediaRatioBar', () => {
  it('renders track with calculated percentage widths', () => {
    render(<MediaRatioBar imageCount={300} videoCount={100} />);

    const meter = screen.getByRole('meter', { name: /Media asset composition/i });
    expect(meter).toBeInTheDocument();
    expect(meter).toHaveAttribute('aria-valuenow', '75');

    expect(screen.getByText(/300 photos/i)).toBeInTheDocument();
    expect(screen.getByText(/100 videos/i)).toBeInTheDocument();
  });

  it('handles zero media count gracefully', () => {
    render(<MediaRatioBar imageCount={0} videoCount={0} />);

    const meter = screen.getByRole('meter', { name: /Media asset composition/i });
    expect(meter).toBeInTheDocument();
    expect(meter).toHaveAttribute('aria-valuenow', '0');
    expect(screen.getByText(/0 photos/i)).toBeInTheDocument();
    expect(screen.getByText(/0 videos/i)).toBeInTheDocument();
  });

  it('hides counts when showCounts is false', () => {
    render(<MediaRatioBar imageCount={500} videoCount={50} showCounts={false} />);

    expect(screen.getByRole('meter')).toBeInTheDocument();
    expect(screen.queryByText(/500 photos/i)).not.toBeInTheDocument();
  });

  it('uses custom formatNumber prop', () => {
    render(
      <MediaRatioBar
        imageCount={1500}
        videoCount={250}
        formatNumber={(n) => `${n} items`}
      />
    );

    expect(screen.getByText(/1500 items photos/i)).toBeInTheDocument();
    expect(screen.getByText(/250 items videos/i)).toBeInTheDocument();
  });
});
