import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { SettingsResponse } from '../../src/api/types/settings';
import { FindOnlyFoldersSection } from '../../src/features/system/components/FindOnlyFoldersSection';

function settings(findOnly?: Record<string, string[]>, aliases = ['OnlyFansImages', 'OnlyFans (G)']): SettingsResponse {
  return {
    download_setup: {
      drives: [{ directories: ['/mnt/pool/media'] }],
      directory_format: '{site_name}',
      staging_directories: [],
      site_directory_aliases: { onlyfans: aliases },
      find_only_site_directories: findOnly,
    },
  } as unknown as SettingsResponse;
}

describe('FindOnlyFoldersSection', () => {
  it('shows each alias with what is saved and cannot save until changed', () => {
    render(<FindOnlyFoldersSection settings={settings({ onlyfans: ['OnlyFansImages'] })} onSaveSettings={vi.fn()} />);

    expect(screen.getByRole('checkbox', { name: 'OnlyFansImages' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'OnlyFans (G)' })).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Save find-only folders' })).toBeDisabled();
  });

  it('saves the ticked folders without touching the rest of the download setup', async () => {
    const current = settings();
    const onSave = vi.fn().mockResolvedValue({ storage_propagation: { target_backend_id: 'b1', message: 'applied' } });
    render(<FindOnlyFoldersSection settings={current} onSaveSettings={onSave} />);

    fireEvent.click(screen.getByRole('checkbox', { name: 'OnlyFansImages' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save find-only folders' }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0].download_setup).toEqual({
      ...current.download_setup,
      find_only_site_directories: { onlyfans: ['OnlyFansImages'] },
    });
    expect(await screen.findByRole('status')).toHaveTextContent('Find-only folders saved on b1; applied');
  });

  it('can untick a folder', async () => {
    const onSave = vi.fn().mockResolvedValue({});
    render(<FindOnlyFoldersSection settings={settings({ onlyfans: ['OnlyFansImages'] })} onSaveSettings={onSave} />);

    fireEvent.click(screen.getByRole('checkbox', { name: 'OnlyFansImages' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save find-only folders' }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onSave.mock.calls[0][0].download_setup.find_only_site_directories).toEqual({ onlyfans: [] });
  });

  it('keeps the ticks and shows why a save failed', async () => {
    const onSave = vi.fn().mockRejectedValue(new Error('Settings changed since you loaded them'));
    render(<FindOnlyFoldersSection settings={settings()} onSaveSettings={onSave} />);

    fireEvent.click(screen.getByRole('checkbox', { name: 'OnlyFansImages' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save find-only folders' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Settings changed since you loaded them');
    expect(screen.getByRole('checkbox', { name: 'OnlyFansImages' })).toBeChecked();
  });

  it('says so when there are no alternate folders', () => {
    render(<FindOnlyFoldersSection settings={settings(undefined, [])} onSaveSettings={vi.fn()} />);

    expect(screen.getByText('No alternate site folders are configured.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save find-only folders' })).toBeNull();
  });
});
