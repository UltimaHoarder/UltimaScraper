import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import { RouteFallback } from '../../src/app/RouteFallback';

it('announces workspace loading without pretending to have measured progress', () => {
  render(<RouteFallback />);
  expect(screen.getByRole('status')).toHaveTextContent('Loading workspace...');
  expect(screen.getByRole('status')).toHaveAttribute('aria-busy', 'true');
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
});
