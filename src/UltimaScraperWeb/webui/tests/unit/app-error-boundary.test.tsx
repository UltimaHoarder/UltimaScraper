import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AppErrorBoundary } from '../../src/app/AppErrorBoundary';

function FailedView(): never {
  throw new Error('Unable to load the operational view');
}

afterEach(() => vi.restoreAllMocks());

describe('AppErrorBoundary', () => {
  it('renders healthy children unchanged', () => {
    render(<AppErrorBoundary><h1>Operations</h1></AppErrorBoundary>);
    expect(screen.getByRole('heading', { name: 'Operations' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('retains diagnostics behind a collapsed incident report without requiring providers', () => {
    const log = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<AppErrorBoundary><FailedView /></AppErrorBoundary>);
    expect(screen.getByRole('alert')).toHaveAccessibleName('Application incident');
    expect(screen.getByRole('heading', { name: 'Application unavailable' })).toBeInTheDocument();
    expect(screen.getByText('Unable to load the operational view', { exact: true })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload application' })).toBeInTheDocument();
    const details = screen.getByText('Error details').closest('details');
    expect(details).not.toHaveAttribute('open');
    expect(details?.querySelector('pre')).toHaveTextContent('Error: Unable to load the operational view');
    expect(log).toHaveBeenCalled();
  });
});
