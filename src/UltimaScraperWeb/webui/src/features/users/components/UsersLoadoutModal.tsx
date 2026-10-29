import type { SearchLoadoutItem } from '../../../api/types/loadouts';

interface UsersLoadoutModalProps {
  isOpen: boolean;
  loadouts: SearchLoadoutItem[];
  selectedLoadoutName: string;
  selectedLoadoutIsDefault: boolean;
  loadoutNameInput: string;
  placeholderName: string;
  onClose: () => void;
  onSelectedLoadoutChange: (value: string) => void;
  onLoadoutNameInputChange: (value: string) => void;
  onAutofill: () => void;
  onDelete: () => void;
  onToggleDefault: () => void;
  onSave: () => void;
}

export function UsersLoadoutModal({
  isOpen,
  loadouts,
  selectedLoadoutName,
  selectedLoadoutIsDefault,
  loadoutNameInput,
  placeholderName,
  onClose,
  onSelectedLoadoutChange,
  onLoadoutNameInputChange,
  onAutofill,
  onDelete,
  onToggleDefault,
  onSave,
}: UsersLoadoutModalProps) {
  if (!isOpen) {
    return null;
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog" onClick={(event) => event.stopPropagation()}>
        <h3>Loadouts</h3>
        <p>Save, apply, default, and delete user search loadouts.</p>

        <div className="edit-user-form">
          <label className="edit-user-field">
            <span>Saved Loadout</span>
            <select
              value={selectedLoadoutName}
              onChange={(event) => onSelectedLoadoutChange(event.target.value)}
            >
              <option value="">None</option>
              {loadouts.map((loadout) => (
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
                onChange={(event) => onLoadoutNameInputChange(event.target.value)}
                placeholder={placeholderName}
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
          <button
            className="btn-cancel"
            onClick={onDelete}
            disabled={!selectedLoadoutName}
          >
            Delete
          </button>
          <button
            className="btn-cancel"
            onClick={onToggleDefault}
            disabled={!selectedLoadoutName}
          >
            {selectedLoadoutIsDefault ? 'Unset Default' : 'Set Default'}
          </button>
          <button className="btn-confirm" onClick={onSave}>
            Save Current
          </button>
        </div>
      </div>
    </div>
  );
}
