import { IdentityFields, type IdentityFieldsProps } from '../../user-profile/components/IdentityFields';

interface UsersBulkIdentityModalProps extends IdentityFieldsProps {
  isOpen: boolean;
  selectedCount: number;
  isSaving: boolean;
  onClose: () => void;
  onSave: () => void;
}

export function UsersBulkIdentityModal({
  isOpen,
  selectedCount,
  isSaving,
  onClose,
  onSave,
  ...identity
}: UsersBulkIdentityModalProps) {
  if (!isOpen) {
    return null;
  }

  const label =
    selectedCount === 1
      ? '1 selected user'
      : `${selectedCount.toLocaleString()} selected users`;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">Set Identity for {label}</h3>
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
          <button className="btn-secondary" onClick={onClose} disabled={isSaving}>
            Cancel
          </button>
          <button
            className="btn-primary"
            onClick={onSave}
            disabled={isSaving || selectedCount === 0}
          >
            {isSaving ? 'Saving...' : `Apply to ${selectedCount}`}
          </button>
        </div>
      </div>
    </div>
  );
}
