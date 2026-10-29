import type { SubscriptionInfo } from '../../../api/types/subscriptions';

interface SubscriptionsEditModalProps {
  target: SubscriptionInfo;
  editName: string;
  editDescription: string;
  editSex: string;
  isPending: boolean;
  onClose: () => void;
  onNameChange: (value: string) => void;
  onDescriptionChange: (value: string) => void;
  onSexChange: (value: string) => void;
  onSave: () => void;
}

export function SubscriptionsEditModal({
  target,
  editName,
  editDescription,
  editSex,
  isPending,
  onClose,
  onNameChange,
  onDescriptionChange,
  onSexChange,
  onSave,
}: SubscriptionsEditModalProps) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog" onClick={(event) => event.stopPropagation()}>
        <h3>Edit User @{target.username || target.user_id}</h3>
        <div className="edit-user-form">
          <label className="edit-user-field">
            <span>Name</span>
            <input
              type="text"
              value={editName}
              onChange={(event) => onNameChange(event.target.value)}
              placeholder="Display name"
            />
          </label>
          <label className="edit-user-field">
            <span>Sex</span>
            <select value={editSex} onChange={(event) => onSexChange(event.target.value)}>
              <option value="">Unset</option>
              <option value="0">Female</option>
              <option value="1">Male</option>
              <option value="2">Other</option>
            </select>
          </label>
          <label className="edit-user-field">
            <span>Description</span>
            <textarea
              value={editDescription}
              onChange={(event) => onDescriptionChange(event.target.value)}
              rows={4}
              placeholder="Bio/description"
            />
          </label>
        </div>
        <div className="modal-actions">
          <button className="btn-cancel" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-confirm" onClick={onSave} disabled={isPending}>
            {isPending ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
