import type {
  BackendInventoryRecord,
  DBSettingRecord,
} from '../../../api/types/settings';
import { isProtectedSettingKey } from '../../../api/settings';

type DbMessage = { type: 'success' | 'error'; text: string } | null;

type DbEditorState = {
  backend: string;
  key: string;
  value: string;
  description: string;
  isSecret: boolean;
};

type InventoryEditorState = {
  backendName: string;
  hostname: string;
  localIp: string;
  settingsId: string;
};

interface SettingsDatabaseSectionProps {
  backendInventory: BackendInventoryRecord[] | undefined;
  dbEditor: DbEditorState;
  dbMessage: DbMessage;
  dbSettings: DBSettingRecord[] | undefined;
  inventoryEditor: InventoryEditorState;
  isFetchingBackendInventory: boolean;
  isFetchingDbSettings: boolean;
  onDbEditorChange: (field: keyof DbEditorState, value: string | boolean) => void;
  onDeleteSelectedDbSetting: () => void;
  onDeleteSelectedInventory: () => void;
  onInventoryEditorChange: (field: keyof InventoryEditorState, value: string) => void;
  onRefreshBackendInventory: () => void;
  onRefreshDbSettings: () => void;
  onResetDbEditor: () => void;
  onResetInventoryEditor: () => void;
  onSaveDbSetting: () => void;
  onSaveInventory: () => void;
  onSelectBackendInventory: (row: BackendInventoryRecord) => void;
  onSelectDbSetting: (row: DBSettingRecord) => void;
  selectedDbSetting: DBSettingRecord | null;
  selectedDbSettingId: number | null;
  selectedInventory: BackendInventoryRecord | null;
  selectedInventoryId: number | null;
}

export function SettingsDatabaseSection({
  backendInventory,
  dbEditor,
  dbMessage,
  dbSettings,
  inventoryEditor,
  isFetchingBackendInventory,
  isFetchingDbSettings,
  onDbEditorChange,
  onDeleteSelectedDbSetting,
  onDeleteSelectedInventory,
  onInventoryEditorChange,
  onRefreshBackendInventory,
  onRefreshDbSettings,
  onResetDbEditor,
  onResetInventoryEditor,
  onSaveDbSetting,
  onSaveInventory,
  onSelectBackendInventory,
  onSelectDbSetting,
  selectedDbSetting,
  selectedDbSettingId,
  selectedInventory,
  selectedInventoryId,
}: SettingsDatabaseSectionProps) {
  const selectedReadOnly = Boolean(selectedDbSetting && isProtectedSettingKey(selectedDbSetting.key));
  const protectedKey = selectedReadOnly || isProtectedSettingKey(dbEditor.key.trim());
  return (
    <div className="settings-section">
      <h2>Raw Settings Rows</h2>
      <p className="section-description">
        Edit custom settings here. Application settings and deployment values have dedicated controls.
      </p>

      {dbMessage && (
        <div className={`test-result ${dbMessage.type === 'success' ? 'success' : 'error'}`}>
          {dbMessage.text}
        </div>
      )}

      <div className="db-grid">
        <div className="db-list-panel">
          <div className="db-toolbar">
            <button
              className="btn-reset"
              onClick={onRefreshDbSettings}
              disabled={isFetchingDbSettings}
            >
              Refresh
            </button>
            <button className="btn-reset" onClick={onResetDbEditor}>
              New Row
            </button>
          </div>
          <div className="db-table-wrap">
            <table className="db-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Backend</th>
                  <th>Key</th>
                  <th>Version</th>
                </tr>
              </thead>
              <tbody>
                {(dbSettings || []).map((row) => (
                  <tr
                    key={row.id}
                    className={selectedDbSettingId === row.id ? 'selected' : ''}
                    onClick={() => onSelectDbSetting(row)}
                  >
                    <td data-label="ID">{row.id}</td>
                    <td data-label="Backend">{row.backend}</td>
                    <td data-label="Key">{row.key}</td>
                    <td data-label="Version">{row.version}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(!dbSettings || dbSettings.length === 0) && (
              <div className="db-empty">No settings rows found.</div>
            )}
          </div>
        </div>

        <div className="db-editor-panel">
          <h3>{selectedDbSetting ? `Edit Row #${selectedDbSetting.id}` : 'Create Settings Row'}</h3>
          {protectedKey && <p className="section-description">This key is read-only here. Use the application settings controls or deployment configuration.</p>}

          <div className="setting-item">
            <label htmlFor="db-backend">Backend Scope</label>
            <input
              id="db-backend"
              disabled={selectedReadOnly}
              type="text"
              value={dbEditor.backend}
              onChange={(event) => onDbEditorChange('backend', event.target.value)}
            />
          </div>

          <div className="setting-item">
            <label htmlFor="db-key">Key</label>
            <input
              id="db-key"
              disabled={selectedReadOnly}
              type="text"
              value={dbEditor.key}
              onChange={(event) => onDbEditorChange('key', event.target.value)}
            />
          </div>

          <div className="setting-item">
            <label htmlFor="db-value">Value</label>
            <textarea
              id="db-value"
              disabled={selectedReadOnly}
              value={dbEditor.value}
              onChange={(event) => onDbEditorChange('value', event.target.value)}
              rows={7}
            />
          </div>

          <div className="setting-item">
            <label htmlFor="db-description">Description</label>
            <input
              id="db-description"
              disabled={selectedReadOnly}
              type="text"
              value={dbEditor.description}
              onChange={(event) => onDbEditorChange('description', event.target.value)}
            />
          </div>

          <div className="setting-item checkbox">
            <label>
              <input
                type="checkbox"
                checked={dbEditor.isSecret}
                disabled={selectedReadOnly}
                onChange={(event) => onDbEditorChange('isSecret', event.target.checked)}
              />
              Secret Value
            </label>
          </div>

          <div className="db-editor-actions">
            <button
              className="btn-save"
              onClick={onSaveDbSetting}
              disabled={protectedKey || !dbEditor.backend.trim() || !dbEditor.key.trim()}
            >
              {selectedDbSetting ? 'Save Row' : 'Create Row'}
            </button>
            <button className="btn-reset" onClick={onResetDbEditor}>
              Clear
            </button>
            {selectedDbSetting && (
              <button className="btn-delete" onClick={onDeleteSelectedDbSetting} disabled={selectedReadOnly}>
                Delete
              </button>
            )}
          </div>
        </div>
      </div>

      <h2>Backend Inventory Mapping</h2>
      <p className="section-description">
        Map many backend hostnames to one shared settings row via `settings_id`.
      </p>

      <div className="db-grid">
        <div className="db-list-panel">
          <div className="db-toolbar">
            <button
              className="btn-reset"
              onClick={onRefreshBackendInventory}
              disabled={isFetchingBackendInventory}
            >
              Refresh
            </button>
            <button className="btn-reset" onClick={onResetInventoryEditor}>
              New Mapping
            </button>
          </div>
          <div className="db-table-wrap">
            <table className="db-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Backend Name</th>
                  <th>Hostname</th>
                  <th>Settings ID</th>
                </tr>
              </thead>
              <tbody>
                {(backendInventory || []).map((row) => (
                  <tr
                    key={row.id}
                    className={selectedInventoryId === row.id ? 'selected' : ''}
                    onClick={() => onSelectBackendInventory(row)}
                  >
                    <td data-label="ID">{row.id}</td>
                    <td data-label="Backend">{row.backend_name}</td>
                    <td data-label="Hostname">{row.hostname}</td>
                    <td data-label="Settings">{row.settings_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(!backendInventory || backendInventory.length === 0) && (
              <div className="db-empty">No backend mappings found.</div>
            )}
          </div>
        </div>

        <div className="db-editor-panel">
          <h3>{selectedInventory ? `Edit Mapping #${selectedInventory.id}` : 'Create Backend Mapping'}</h3>

          <div className="setting-item">
            <label htmlFor="map-backend-name">Backend Name</label>
            <input
              id="map-backend-name"
              type="text"
              value={inventoryEditor.backendName}
              onChange={(event) => onInventoryEditorChange('backendName', event.target.value)}
            />
          </div>

          <div className="setting-item">
            <label htmlFor="map-hostname">Hostname</label>
            <input
              id="map-hostname"
              type="text"
              value={inventoryEditor.hostname}
              onChange={(event) => onInventoryEditorChange('hostname', event.target.value)}
            />
          </div>

          <div className="setting-item">
            <label htmlFor="map-local-ip">Local IP</label>
            <input
              id="map-local-ip"
              type="text"
              value={inventoryEditor.localIp}
              onChange={(event) => onInventoryEditorChange('localIp', event.target.value)}
              placeholder="Optional"
            />
          </div>

          <div className="setting-item">
            <label htmlFor="map-settings-id">Settings ID</label>
            <input
              id="map-settings-id"
              type="number"
              min={1}
              value={inventoryEditor.settingsId}
              onChange={(event) => onInventoryEditorChange('settingsId', event.target.value)}
            />
            <span className="setting-description">
              Existing IDs: {(dbSettings || []).slice(0, 8).map((row) => row.id).join(', ') || 'none'}
            </span>
          </div>

          <div className="db-editor-actions">
            <button
              className="btn-save"
              onClick={onSaveInventory}
              disabled={
                !inventoryEditor.backendName.trim() ||
                !inventoryEditor.hostname.trim() ||
                !inventoryEditor.settingsId.trim()
              }
            >
              {selectedInventory ? 'Save Mapping' : 'Create Mapping'}
            </button>
            <button className="btn-reset" onClick={onResetInventoryEditor}>
              Clear
            </button>
            {selectedInventory && (
              <button className="btn-delete" onClick={onDeleteSelectedInventory}>
                Delete
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
