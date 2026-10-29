import type { SearchLoadoutItem } from '../../../api/types/loadouts';

interface ContentLibraryLoadoutModalProps {
  loadoutNameInput: string;
  loadouts: SearchLoadoutItem[];
  onAutofill: () => void;
  onClose: () => void;
  onDelete: () => void;
  onInputChange: (value: string) => void;
  onLoadoutSelect: (value: string) => void;
  onSaveCurrent: () => void;
  onToggleDefault: () => void;
  selectedLoadoutIsDefault: boolean;
  selectedLoadoutName: string;
  suggestedName: string;
}

export function ContentLibraryLoadoutModal({
  loadoutNameInput,
  loadouts,
  onAutofill,
  onClose,
  onDelete,
  onInputChange,
  onLoadoutSelect,
  onSaveCurrent,
  onToggleDefault,
  selectedLoadoutIsDefault,
  selectedLoadoutName,
  suggestedName,
}: ContentLibraryLoadoutModalProps) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content content-library-filter-modal" onClick={(event) => event.stopPropagation()}>
        <div className="content-library-filter-modal-header">
          <h3>Loadouts</h3>
          <button className="content-library-filter-close" onClick={onClose}>
            ×
          </button>
        </div>
        <p className="content-library-filter-help">
          Save, apply, default, and delete content search loadouts.
        </p>
        <div className="content-library-loadout-form">
          <label className="content-library-loadout-field">
            <span className="content-library-filter-name">Saved Loadout</span>
            <select
              className="content-library-loadout-control"
              value={selectedLoadoutName}
              onChange={(event) => onLoadoutSelect(event.target.value)}
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
          <label className="content-library-loadout-field">
            <span className="content-library-filter-name">Save As</span>
            <div className="content-library-loadout-name-row">
              <input
                type="text"
                className="content-library-loadout-control"
                value={loadoutNameInput}
                onChange={(event) => onInputChange(event.target.value)}
                placeholder={suggestedName}
              />
              <button type="button" className="btn-secondary" onClick={onAutofill}>
                Autofill
              </button>
            </div>
          </label>
        </div>
        <div className="content-library-filter-footer">
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-secondary" onClick={onDelete} disabled={!selectedLoadoutName}>
            Delete
          </button>
          <button
            className="btn-secondary"
            onClick={onToggleDefault}
            disabled={!selectedLoadoutName}
          >
            {selectedLoadoutIsDefault ? 'Unset Default' : 'Set Default'}
          </button>
          <button className="btn-primary" onClick={onSaveCurrent}>
            Save Current
          </button>
        </div>
      </div>
    </div>
  );
}
