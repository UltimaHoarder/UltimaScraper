import type { SearchLoadoutsResponse } from '../../../api/types/loadouts';

interface SubscriptionsLoadoutModalProps {
  loadoutsData: SearchLoadoutsResponse | undefined;
  selectedLoadoutName: string;
  loadoutNameInput: string;
  selectedLoadoutIsDefault: boolean;
  autoNamePlaceholder: string;
  onClose: () => void;
  onLoadoutSelect: (value: string) => void;
  onInputChange: (value: string) => void;
  onAutofill: () => void;
  onDelete: () => void;
  onToggleDefault: () => void;
  onSaveCurrent: () => void;
}

export function SubscriptionsLoadoutModal({
  loadoutsData,
  selectedLoadoutName,
  loadoutNameInput,
  selectedLoadoutIsDefault,
  autoNamePlaceholder,
  onClose,
  onLoadoutSelect,
  onInputChange,
  onAutofill,
  onDelete,
  onToggleDefault,
  onSaveCurrent,
}: SubscriptionsLoadoutModalProps) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog" onClick={(event) => event.stopPropagation()}>
        <h3>Loadouts</h3>
        <p>Save, apply, default, and delete subscription search loadouts.</p>

        <div className="edit-user-form">
          <label className="edit-user-field">
            <span>Saved Loadout</span>
            <select
              value={selectedLoadoutName}
              onChange={(event) => onLoadoutSelect(event.target.value)}
            >
              <option value="">None</option>
              {(loadoutsData?.loadouts || []).map((loadout) => (
                <option key={loadout.name} value={loadout.name}>
                  {loadout.name}
                  {loadout.is_default ? ' (default)' : ''}
                </option>
              ))}
            </select>
          </label>
          <label className="edit-user-field">
            <span>Save As</span>
            <div className="loadout-name-row">
              <input
                type="text"
                value={loadoutNameInput}
                onChange={(event) => onInputChange(event.target.value)}
                placeholder={autoNamePlaceholder}
              />
              <button type="button" className="btn-cancel loadout-inline-btn" onClick={onAutofill}>
                Autofill
              </button>
            </div>
          </label>
        </div>

        <div className="modal-actions">
          <button className="btn-cancel" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-cancel" onClick={onDelete} disabled={!selectedLoadoutName}>
            Delete
          </button>
          <button
            className="btn-cancel"
            onClick={onToggleDefault}
            disabled={!selectedLoadoutName}
          >
            {selectedLoadoutIsDefault ? 'Unset Default' : 'Set Default'}
          </button>
          <button className="btn-confirm" onClick={onSaveCurrent}>
            Save Current
          </button>
        </div>
      </div>
    </div>
  );
}
