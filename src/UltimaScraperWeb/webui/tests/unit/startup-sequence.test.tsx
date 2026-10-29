import { StrictMode } from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { StartupMigrationPreviewResponse } from '../../src/api/types/setup';
import { StartupSequence } from '../../src/components/StartupSequence';

const setupApi = vi.hoisted(() => ({
  applyStartupMigration: vi.fn(),
  discardStartupMigration: vi.fn(),
  previewStartupMigration: vi.fn(),
  regenerateStartupMigration: vi.fn(),
}));

vi.mock('../../src/api/setup', () => setupApi);

describe('StartupSequence', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.clearAllMocks();
  });

  it('deduplicates the migration preview across Strict Mode remounts', async () => {
    let resolvePreview!: (value: StartupMigrationPreviewResponse) => void;
    setupApi.previewStartupMigration.mockImplementation(
      () => new Promise<StartupMigrationPreviewResponse>((resolve) => {
        resolvePreview = resolve;
      }),
    );

    render(
      <StrictMode>
        <StartupSequence
          error={null}
          backendStartupId="shared-runtime"
        />
      </StrictMode>,
    );

    await waitFor(() => {
      expect(setupApi.previewStartupMigration).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      resolvePreview({
        status: 'no_changes',
        message: 'No DB schema changes detected.',
        preview_id: null,
        revision: null,
        filename: null,
        diff: '',
        has_changes: false,
        can_apply: false,
        output: [],
      });
    });

    expect(await screen.findByText('Startup complete')).toBeInTheDocument();
  });

  it('keeps backend errors retryable without running migration calls', () => {
    const retry = vi.fn();
    render(<StartupSequence error={new Error('Backend unreachable')} backendStartupId={null} canRunMigrationCheck={false} onRetry={retry} />);
    expect(screen.getByRole('status')).toHaveTextContent('Backend unavailable');
    expect(screen.getByRole('alert')).toHaveTextContent('Backend unreachable');
    fireEvent.click(screen.getByRole('button', { name: 'Retry connection' }));
    expect(retry).toHaveBeenCalledOnce();
    expect(setupApi.previewStartupMigration).not.toHaveBeenCalled();
    expect(setupApi.applyStartupMigration).not.toHaveBeenCalled();
  });

  it('reuses a skip completed by another tab without claiming the schema is current', async () => {
    setupApi.previewStartupMigration.mockResolvedValue({
      status: 'completed', outcome: 'skipped', message: 'Migration skipped for this backend startup.',
      preview_id: null, revision: null, filename: null, diff: null,
      has_changes: false, can_apply: false, output: [],
    } satisfies StartupMigrationPreviewResponse);
    render(<StartupSequence error={null} backendStartupId="skipped-in-another-tab" />);
    expect(await screen.findByText('Startup complete')).toBeInTheDocument();
    expect(screen.queryByText('✓ Database schema is up to date')).not.toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem('usr_last_startup_result')!)).toMatchObject({ outcome: 'skipped' });
    expect(setupApi.applyStartupMigration).not.toHaveBeenCalled();
    expect(localStorage.getItem('usr_migration_done_startup_id')).toBe('skipped-in-another-tab');
  });

  it('waits for explicit migration approval and preserves the reviewed preview ID', async () => {
    setupApi.previewStartupMigration.mockResolvedValue({
      status: 'ready', message: 'Schema review required', preview_id: 'preview-reviewed',
      revision: 'test-revision', filename: 'test-migration.py', diff: '+ add column',
      has_changes: true, can_apply: true, output: [],
    } satisfies StartupMigrationPreviewResponse);
    setupApi.applyStartupMigration.mockResolvedValue({ success: true, message: 'Applied', output: [] });
    render(<StartupSequence error={null} backendStartupId="approval-runtime" />);
    const apply = await screen.findByRole('button', { name: 'Apply migration' });
    expect(apply).toHaveFocus();
    expect(screen.getByRole('status')).toHaveTextContent('Migration approval required');
    expect(setupApi.applyStartupMigration).not.toHaveBeenCalled();
    expect(localStorage.getItem('usr_migration_done_startup_id')).toBeNull();
    fireEvent.click(apply);
    expect(await screen.findByText('Startup complete')).toBeInTheDocument();
    expect(setupApi.applyStartupMigration).toHaveBeenCalledWith({ preview_id: 'preview-reviewed' });
    expect(localStorage.getItem('usr_migration_done_startup_id')).toBe('approval-runtime');
  });
});
