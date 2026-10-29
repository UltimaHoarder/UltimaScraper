import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SettingsDatabaseSection } from '../../src/features/settings/components/SettingsDatabaseSection';
import { renderWithProviders } from './testUtils';

describe('SettingsDatabaseSection', () => {
  it('disables saving until backend scope and key are provided', () => {
    renderWithProviders(
      <SettingsDatabaseSection
        backendInventory={[]}
        dbEditor={{
          backend: '',
          key: '',
          value: '',
          description: '',
          isSecret: false,
        }}
        dbMessage={null}
        dbSettings={[]}
        inventoryEditor={{
          backendName: '',
          hostname: '',
          localIp: '',
          settingsId: '',
        }}
        isFetchingBackendInventory={false}
        isFetchingDbSettings={false}
        onDbEditorChange={vi.fn()}
        onDeleteSelectedDbSetting={vi.fn()}
        onDeleteSelectedInventory={vi.fn()}
        onInventoryEditorChange={vi.fn()}
        onRefreshBackendInventory={vi.fn()}
        onRefreshDbSettings={vi.fn()}
        onResetDbEditor={vi.fn()}
        onResetInventoryEditor={vi.fn()}
        onSaveDbSetting={vi.fn()}
        onSaveInventory={vi.fn()}
        onSelectBackendInventory={vi.fn()}
        onSelectDbSetting={vi.fn()}
        selectedDbSetting={null}
        selectedDbSettingId={null}
        selectedInventory={null}
        selectedInventoryId={null}
      />,
      { withRouter: false },
    );

    expect(screen.getByRole('button', { name: 'Create Row' })).toBeDisabled();
  });

  it('propagates edits and saves the selected row payload', () => {
    const onDbEditorChange = vi.fn();
    const onSaveDbSetting = vi.fn();

    renderWithProviders(
      <SettingsDatabaseSection
        backendInventory={[]}
        dbEditor={{
          backend: 'backend-main',
          key: 'custom.example',
          value: '127.0.0.1',
          description: 'Redis endpoint',
          isSecret: false,
        }}
        dbMessage={null}
        dbSettings={[]}
        inventoryEditor={{
          backendName: '',
          hostname: '',
          localIp: '',
          settingsId: '',
        }}
        isFetchingBackendInventory={false}
        isFetchingDbSettings={false}
        onDbEditorChange={onDbEditorChange}
        onDeleteSelectedDbSetting={vi.fn()}
        onDeleteSelectedInventory={vi.fn()}
        onInventoryEditorChange={vi.fn()}
        onRefreshBackendInventory={vi.fn()}
        onRefreshDbSettings={vi.fn()}
        onResetDbEditor={vi.fn()}
        onResetInventoryEditor={vi.fn()}
        onSaveDbSetting={onSaveDbSetting}
        onSaveInventory={vi.fn()}
        onSelectBackendInventory={vi.fn()}
        onSelectDbSetting={vi.fn()}
        selectedDbSetting={null}
        selectedDbSettingId={null}
        selectedInventory={null}
        selectedInventoryId={null}
      />,
      { withRouter: false },
    );

    fireEvent.change(screen.getByLabelText('Backend Scope'), {
      target: { value: 'backend-secondary' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Create Row' }));

    expect(onDbEditorChange).toHaveBeenCalledWith('backend', 'backend-secondary');
    expect(onSaveDbSetting).toHaveBeenCalledTimes(1);
  });
});
