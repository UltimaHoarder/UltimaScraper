interface UserProfileEditModalProps {
  isOpen: boolean;
  username: string;
  editName: string;
  editAlias: string;
  editDescription: string;
  editSex: string;
  editGender: string;
  isSaving: boolean;
  onClose: () => void;
  onEditNameChange: (value: string) => void;
  onEditAliasChange: (value: string) => void;
  onEditDescriptionChange: (value: string) => void;
  onEditSexChange: (value: string) => void;
  onEditGenderChange: (value: string) => void;
  onSave: () => void;
}

export function UserProfileEditModal({
  isOpen,
  username,
  editName,
  editAlias,
  editDescription,
  editSex,
  editGender,
  isSaving,
  onClose,
  onEditNameChange,
  onEditAliasChange,
  onEditDescriptionChange,
  onEditSexChange,
  onEditGenderChange,
  onSave,
}: UserProfileEditModalProps) {
  if (!isOpen) {
    return null;
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">Edit User @{username}</h3>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <div className="edit-user-form">
            <label className="edit-user-field">
              <span>Name</span>
              <input
                type="text"
                value={editName}
                onChange={(event) => onEditNameChange(event.target.value)}
                placeholder="Display name"
              />
            </label>
            <label className="edit-user-field">
              <span>Alias</span>
              <input
                type="text"
                value={editAlias}
                onChange={(event) => onEditAliasChange(event.target.value)}
                placeholder="Add alias username"
              />
            </label>
            <label className="edit-user-field">
              <span>Sex</span>
              <select value={editSex} onChange={(event) => onEditSexChange(event.target.value)}>
                <option value="">Unset</option>
                <option value="0">Female</option>
                <option value="1">Male</option>
                <option value="2">Other</option>
              </select>
            </label>
            <label className="edit-user-field">
              <span>Gender</span>
              <select
                value={editGender}
                onChange={(event) => onEditGenderChange(event.target.value)}
              >
                <option value="">Unset</option>
                <option value="0">Woman</option>
                <option value="1">Man</option>
                <option value="2">Other</option>
              </select>
            </label>
            <label className="edit-user-field">
              <span>Description</span>
              <textarea
                value={editDescription}
                onChange={(event) => onEditDescriptionChange(event.target.value)}
                rows={5}
                placeholder="Bio/description"
              />
            </label>
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={onSave} disabled={isSaving}>
            {isSaving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
