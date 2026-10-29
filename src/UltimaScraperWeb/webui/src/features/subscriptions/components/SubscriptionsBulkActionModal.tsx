import type { SubscriptionInfo } from '../../../api/types/subscriptions';

interface SubscriptionsBulkActionModalProps {
  title: string;
  description: string;
  previewSubscriptions: SubscriptionInfo[];
  overflowCount: number;
  confirmLabel: string;
  confirmButtonClassName?: string;
  confirmDisabled?: boolean;
  onClose: () => void;
  onConfirm: () => void;
}

export function SubscriptionsBulkActionModal({
  title,
  description,
  previewSubscriptions,
  overflowCount,
  confirmLabel,
  confirmButtonClassName,
  confirmDisabled = false,
  onClose,
  onConfirm,
}: SubscriptionsBulkActionModalProps) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog" onClick={(event) => event.stopPropagation()}>
        <h3>{title}</h3>
        <p>{description}</p>
        <div className="selected-users-preview">
          {previewSubscriptions.map((sub) => (
            <span key={`${sub.site}-${sub.id}`} className="selected-user-tag">
              @{sub.username}
            </span>
          ))}
          {overflowCount > 0 && (
            <span className="selected-user-more">+{overflowCount} more</span>
          )}
        </div>
        <div className="modal-actions">
          <button className="btn-cancel" onClick={onClose}>
            Cancel
          </button>
          <button
            className={confirmButtonClassName || 'btn-confirm'}
            onClick={onConfirm}
            disabled={confirmDisabled}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
