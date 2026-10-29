import { screen } from '@testing-library/react';
import { waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { AppBootstrapProvider, useAppBootstrap } from '../../src/app/bootstrap/AppBootstrapProvider';
import { getSystemBootstrap } from '../../src/api/system';
import type { SystemBootstrapResponse } from '../../src/api/types/bootstrap';
import { renderWithProviders } from './testUtils';

vi.mock('../../src/api/system', () => ({
  getSystemBootstrap: vi.fn(),
}));

const bootstrapFixture: SystemBootstrapResponse = {
  backend_id: 'backend-main',
  hostname: 'test-host',
  version: '9.9.9',
  supported_sites: ['onlyfans', 'fansly'],
  setup: {
    is_configured: true,
    has_config: true,
    has_database: true,
    data_directory: '/tmp/usr',
    startup_id: 'startup-123',
  },
  features: {
    webhook_stream: true,
    startup_migrations: true,
    distributed_mode: false,
    remote_backends: false,
    system_bootstrap: true,
  },
  support_matrix: {
    ui_mode: 'webui',
    tui_supported: false,
    runtime_database: 'postgresql',
    postgres_required: true,
    sqlite_runtime_supported: false,
    sqlite_import_supported: true,
  },
};

function BootstrapConsumer() {
  const { statusText, bootstrap } = useAppBootstrap();

  return (
    <div>
      <span>{statusText}</span>
      <span>{bootstrap?.hostname}</span>
    </div>
  );
}

describe('AppBootstrapProvider', () => {
  it('publishes the resolved bootstrap status to consumers', async () => {
    vi.mocked(getSystemBootstrap).mockResolvedValue(bootstrapFixture);

    renderWithProviders(
      <AppBootstrapProvider>
        <BootstrapConsumer />
      </AppBootstrapProvider>,
      { withRouter: false },
    );

    await waitFor(() => {
      expect(screen.getByText('Ready · backend-main · v9.9.9')).toBeInTheDocument();
    });
    expect(screen.getByText('test-host')).toBeInTheDocument();
  });

  it('reports setup required when the backend is not configured yet', async () => {
    vi.mocked(getSystemBootstrap).mockResolvedValue({
      ...bootstrapFixture,
      setup: {
        ...bootstrapFixture.setup,
        is_configured: false,
      },
    });

    renderWithProviders(
      <AppBootstrapProvider>
        <BootstrapConsumer />
      </AppBootstrapProvider>,
      { withRouter: false },
    );

    await waitFor(() => {
      expect(screen.getByText('Setup required · backend-main · v9.9.9')).toBeInTheDocument();
    });
  });
});
