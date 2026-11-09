import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { SettingsResponse } from '../../src/api/types/settings';
import { StagingDirectoriesSection } from '../../src/features/system/components/StagingDirectoriesSection';

const GB = 1024 * 1024 * 1024;

function settings(paths: string[]): SettingsResponse {
  return {
    download_setup: {
      drives: [{ directories: ['/mnt/pool/media'] }],
      directory_format: '{site_name}',
      staging_directories: paths.map((path) => ({
        path,
        usage: ['downloads', 'merge', 'drm'],
        policy: [],
        min_free_bytes: 16 * GB,
      })),
    },
  } as unknown as SettingsResponse;
}

function saved(onSave: ReturnType<typeof vi.fn>) {
  return onSave.mock.calls[0][0].download_setup;
}

describe('StagingDirectoriesSection', () => {
  it('says the list applies to every download and cannot save until edited', () => {
    render(<StagingDirectoriesSection settings={settings(['/dev/shm/staging'])} onSaveSettings={vi.fn()} />);

    expect(screen.getByText(/every download, whichever mount/i)).toBeInTheDocument();
    expect(screen.getByLabelText('Path')).toHaveValue('/dev/shm/staging');
    expect(screen.getByLabelText('Keep free (GB)')).toHaveValue(16);
    expect(screen.getByRole('button', { name: 'Save staging directories' })).toBeDisabled();
  });

  it('saves the edited list without touching the rest of the download setup', async () => {
    const current = settings(['/dev/shm/staging']);
    const onSave = vi.fn().mockResolvedValue({ storage_propagation: { target_backend_id: 'b1', message: 'applied' } });
    render(<StagingDirectoriesSection settings={current} onSaveSettings={onSave} />);

    fireEvent.change(screen.getByLabelText('Path'), { target: { value: ' /mnt/fast/staging ' } });
    fireEvent.click(screen.getByRole('checkbox', { name: 'merge' }));
    fireEvent.change(screen.getByLabelText('Keep free (GB)'), { target: { value: '4' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save staging directories' }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(saved(onSave).staging_directories).toEqual([
      { path: '/mnt/fast/staging', usage: ['downloads', 'drm'], policy: [], min_free_bytes: 4 * GB },
    ]);
    expect(saved(onSave).drives).toEqual(current.download_setup.drives);
    expect(await screen.findByRole('status')).toHaveTextContent('saved on b1; applied');
    expect(screen.getByRole('button', { name: 'Save staging directories' })).toBeDisabled();
  });

  it('drops blank rows and can remove every directory', async () => {
    const onSave = vi.fn().mockResolvedValue({});
    render(<StagingDirectoriesSection settings={settings(['/dev/shm/staging'])} onSaveSettings={onSave} />);

    fireEvent.click(screen.getByRole('button', { name: '+ Add staging directory' }));
    fireEvent.click(screen.getAllByRole('button', { name: 'Remove' })[0]);
    fireEvent.click(screen.getByRole('button', { name: 'Save staging directories' }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(saved(onSave).staging_directories).toEqual([]);
  });

  it('keeps at least one usage on a directory', () => {
    render(
      <StagingDirectoriesSection
        settings={{
          download_setup: { staging_directories: [{ path: '/s', usage: ['drm'], policy: [] }] },
        } as unknown as SettingsResponse}
        onSaveSettings={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('checkbox', { name: 'drm' }));

    expect(screen.getByRole('checkbox', { name: 'drm' })).toBeChecked();
  });

  it('keeps edits and shows why when a save fails', async () => {
    const onSave = vi.fn().mockRejectedValue(new Error('Settings changed since you loaded them'));
    render(<StagingDirectoriesSection settings={settings(['/a'])} onSaveSettings={onSave} />);

    fireEvent.change(screen.getByLabelText('Path'), { target: { value: '/b' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save staging directories' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Settings changed since you loaded them');
    expect(screen.getByLabelText('Path')).toHaveValue('/b');
  });

  it('follows saved settings until someone edits the list', () => {
    const { rerender } = render(<StagingDirectoriesSection settings={settings(['/a'])} onSaveSettings={vi.fn()} />);

    rerender(<StagingDirectoriesSection settings={settings(['/b'])} onSaveSettings={vi.fn()} />);

    expect(screen.getByLabelText('Path')).toHaveValue('/b');
  });
});
