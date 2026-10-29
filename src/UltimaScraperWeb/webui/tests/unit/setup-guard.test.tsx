import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as setupApi from '../../src/api/setup';
import { SetupGuard } from '../../src/components/SetupGuard';
import { SetupPage } from '../../src/features/setup/components/SetupPage';

function createMemoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => Array.from(values.keys())[index] ?? null,
    removeItem: (key) => { values.delete(key); },
    setItem: (key, value) => { values.set(key, String(value)); },
  };
}

Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: createMemoryStorage() });
Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: createMemoryStorage() });

const bootstrapState = vi.hoisted(() => ({
  value: {
    bootstrap: null as null | { setup: { is_configured: boolean; startup_id: string } },
    isLoading: true,
    isFetching: true,
    failureCount: 0,
    error: null as unknown,
    retryBootstrap: vi.fn(),
    statusText: 'Connecting',
  },
}));

vi.mock('../../src/app/bootstrap/AppBootstrapProvider', () => ({
  useAppBootstrap: () => bootstrapState.value,
}));

vi.mock('../../src/components/StartupSequence', () => ({
  StartupSequence: ({ canRunMigrationCheck = true }: { canRunMigrationCheck?: boolean }) => (
    <div data-testid="startup-sequence" data-migration-check={String(canRunMigrationCheck)} />
  ),
}));

function renderGuard() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <SetupGuard>
        <div>Dashboard content</div>
      </SetupGuard>
    </MemoryRouter>,
  );
}

describe('SetupGuard startup flow', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    bootstrapState.value = {
      bootstrap: null,
      isLoading: true,
      isFetching: true,
      failureCount: 0,
      error: null,
      retryBootstrap: vi.fn(),
      statusText: 'Connecting',
    };
  });

  it('keeps the startup screen visible while bootstrap is unresolved', () => {
    renderGuard();

    expect(screen.getByTestId('startup-sequence')).toHaveAttribute('data-migration-check', 'false');
    expect(screen.queryByText('Dashboard content')).not.toBeInTheDocument();
  });

  it('renders a refresh straight away once this browser has passed the gate', () => {
    localStorage.setItem('usr_migration_done_startup_id', 'startup-previous');

    const { rerender } = renderGuard();

    expect(screen.getByText('Dashboard content')).toBeInTheDocument();
    expect(screen.queryByTestId('startup-sequence')).not.toBeInTheDocument();

    // The backend restarted: its new startup id still gets the migration gate.
    bootstrapState.value = {
      ...bootstrapState.value,
      bootstrap: { setup: { is_configured: true, startup_id: 'startup-restarted' } },
      isLoading: false,
      isFetching: false,
    };
    rerender(
      <MemoryRouter initialEntries={['/']}>
        <SetupGuard>
          <div>Dashboard content</div>
        </SetupGuard>
      </MemoryRouter>,
    );

    expect(screen.getByTestId('startup-sequence')).toHaveAttribute('data-migration-check', 'true');
    expect(screen.queryByText('Dashboard content')).not.toBeInTheDocument();
  });

  it('runs the migration gate before showing the dashboard for a new backend startup', () => {
    bootstrapState.value = {
      ...bootstrapState.value,
      bootstrap: { setup: { is_configured: true, startup_id: 'startup-new' } },
      isLoading: false,
      isFetching: false,
    };

    renderGuard();

    expect(screen.getByTestId('startup-sequence')).toHaveAttribute('data-migration-check', 'true');
    expect(screen.queryByText('Dashboard content')).not.toBeInTheDocument();
  });

  it('shows the dashboard once this backend startup has passed migration checks', () => {
    localStorage.setItem('usr_migration_done_startup_id', 'startup-current');
    bootstrapState.value = {
      ...bootstrapState.value,
      bootstrap: { setup: { is_configured: true, startup_id: 'startup-current' } },
      isLoading: false,
      isFetching: false,
    };

    renderGuard();

    expect(screen.getByText('Dashboard content')).toBeInTheDocument();
    expect(screen.queryByTestId('startup-sequence')).not.toBeInTheDocument();
  });

  it('dismisses this startup gate when another tab completes the same startup', () => {
    bootstrapState.value = {
      ...bootstrapState.value,
      bootstrap: { setup: { is_configured: true, startup_id: 'shared-tabs' } },
      isLoading: false, isFetching: false,
    };
    renderGuard();
    expect(screen.getByTestId('startup-sequence')).toBeInTheDocument();
    localStorage.setItem('usr_migration_done_startup_id', 'shared-tabs');
    fireEvent(window, new StorageEvent('storage', { key: 'usr_migration_done_startup_id', newValue: 'shared-tabs' }));
    expect(screen.getByText('Dashboard content')).toBeInTheDocument();
    expect(screen.queryByTestId('startup-sequence')).not.toBeInTheDocument();
  });

  it('retains the migration gate when another tab completes a different startup', () => {
    bootstrapState.value = {
      ...bootstrapState.value,
      bootstrap: { setup: { is_configured: true, startup_id: 'current-tabs' } },
      isLoading: false, isFetching: false,
    };
    renderGuard();
    localStorage.setItem('usr_migration_done_startup_id', 'older-tabs');
    fireEvent(window, new StorageEvent('storage', { key: 'usr_migration_done_startup_id', newValue: 'older-tabs' }));
    expect(screen.getByTestId('startup-sequence')).toBeInTheDocument();
    expect(screen.queryByText('Dashboard content')).not.toBeInTheDocument();
  });

  it('hides Database and Redis steps in SetupPage when has_database and redis_target are already configured', async () => {
    vi.spyOn(setupApi, 'getSetupStatus').mockResolvedValue({
      is_configured: false,
      has_config: true,
      has_database: true,
      redis_target: 'redis:6379',
      data_directory: '/data',
      startup_id: 'startup-1',
      backend_id: 'nas',
    });

    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/setup']}>
          <SetupPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(await screen.findByRole('heading', { name: 'Storage & Network' })).toBeInTheDocument();
    expect(screen.queryByText('Database')).not.toBeInTheDocument();
    expect(screen.queryByText('Redis')).not.toBeInTheDocument();
    expect(screen.getByText('Storage')).toBeInTheDocument();
    expect(screen.getByText('DRM')).toBeInTheDocument();
    expect(screen.getByText('Accounts')).toBeInTheDocument();
    expect(screen.getByText('Review')).toBeInTheDocument();
  });
});
