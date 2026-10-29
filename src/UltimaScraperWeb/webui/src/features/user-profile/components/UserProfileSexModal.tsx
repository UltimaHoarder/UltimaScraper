import { IdentityFields, type IdentityFieldsProps } from './IdentityFields';

interface UserProfileSexModalProps extends IdentityFieldsProps {
  isOpen: boolean;
  username: string;
  isSaving: boolean;
  onClose: () => void;
  onSave: () => void;
}

export function UserProfileSexModal({
  isOpen,
  username,
  isSaving,
  onClose,
  onSave,
  ...identity
}: UserProfileSexModalProps) {
  if (!isOpen) {
    return null;
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">Set Identity for @{username}</h3>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <div className="edit-user-form">
            <IdentityFields {...identity} />
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
