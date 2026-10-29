import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { DirectoriesSettingsSection } from '../../src/features/settings/components/DirectoriesSettingsSection';
import type { SettingsResponse } from '../../src/api/types/settings';
import { renderWithProviders } from './testUtils';

const settings = {
  download_setup: {
    drives: [],
    alt_directory_formats: [],
    site_directory_aliases: {},
    staging_directories: [],
    directory_format: '{site_name}/{user_username}',
    filename_format: '{filename}.{ext}',
    text_length: 255,
    date_format: '%Y-%m-%d',
    overwrite_files: true,
  },
} as unknown as SettingsResponse;

describe('DirectoriesSettingsSection', () => {
  it('adds a folder alias under the selected site without comma parsing', () => {
    const onNestedChange = vi.fn();

    renderWithProviders(
      <DirectoriesSettingsSection
        settings={settings}
        getNestedValue={() => undefined}
        onNestedChange={onNestedChange}
      />,
      { withRouter: false },
    );

    fireEvent.change(screen.getByLabelText('New OnlyFans directory alias'), {
      target: { value: 'OnlyFansImages' },
    });
    fireEvent.click(screen.getAllByRole('button', { name: 'Add alias' })[0]);

    expect(onNestedChange).toHaveBeenCalledWith(
      'download_setup',
      'site_directory_aliases',
      { onlyfans: ['OnlyFansImages'] },
    );
  });

  it('lists every backend token under each download format field', () => {
    renderWithProviders(
      <DirectoriesSettingsSection
        settings={settings}
        getNestedValue={() => undefined}
        onNestedChange={vi.fn()}
      />,
      { withRouter: false },
    );

    const lists = screen.getAllByText(/Available tokens:/);
    expect(lists).toHaveLength(3);
    const [directory, filename, alt] = lists.map((list) => list.textContent ?? '');
    for (const token of ['{site_name}', '{user_username}', '{content_type}', '{content_value}', '{media_id}']) {
      expect(directory).toContain(token);
      expect(filename).toContain(token);
    }
    expect(filename).toContain('{media_ext}');
    expect(directory).not.toContain('{media_ext}');
    expect(alt).toContain('{user_id}');
    expect(alt).not.toContain('{content_type}');
    expect(screen.queryByText(/\{site\}|\{username\}|\{id\}/)).toBeNull();
  });

  it('calls out tokens the backend does not know', () => {
    renderWithProviders(
      <DirectoriesSettingsSection
        settings={settings}
        getNestedValue={(section, key) =>
          section === 'download_setup' && key === 'directory_format'
            ? '{site_name}/{user_username}/{user_date}/{value}'
            : undefined}
        onNestedChange={vi.fn()}
      />,
      { withRouter: false },
    );

    expect(screen.getByRole('alert')).toHaveTextContent('{user_date} is not a valid token.');
  });

  it('toggles one staging policy without dropping others and stores free space in bytes', () => {
    const onNestedChange = vi.fn();
    const staging = {
      path: '/dev/shm/UltimaStaging',
      usage: ['downloads', 'merge', 'drm'],
      policy: ['prefer'],
      min_free_bytes: 16 * 1024 ** 3,
    };

    renderWithProviders(
      <DirectoriesSettingsSection
        settings={settings}
        getNestedValue={(section, key) =>
          section === 'download_setup' && key === 'staging_directories' ? [staging] : undefined}
        onNestedChange={onNestedChange}
      />,
      { withRouter: false },
    );

    fireEvent.click(screen.getByLabelText('drm_only'));
    expect(onNestedChange).toHaveBeenLastCalledWith('download_setup', 'staging_directories', [
      { ...staging, policy: ['prefer', 'drm_only'] },
    ]);

    const keepFree = screen.getByLabelText(/Keep free/);
    expect(keepFree).toHaveValue(16);
    fireEvent.change(keepFree, { target: { value: '8' } });
    expect(onNestedChange).toHaveBeenLastCalledWith('download_setup', 'staging_directories', [
      { ...staging, min_free_bytes: 8 * 1024 ** 3 },
    ]);
  });
});
