import type { SubscriptionInfo } from '../../../api/types/subscriptions';
import type { EligibleAuth } from '../../../api/types/users';

interface SubscriptionsAuthPickerModalProps {
  target: SubscriptionInfo;
  eligibleAuths: EligibleAuth[];
  isPending: boolean;
  onClose: () => void;
  onSelectAuth: (authId: number) => void;
}

export function SubscriptionsAuthPickerModal({
  target,
  eligibleAuths,
  isPending,
  onClose,
  onSelectAuth,
}: SubscriptionsAuthPickerModalProps) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog" onClick={(event) => event.stopPropagation()}>
        <h3>🔐 Select Auth for @{target.username}</h3>
        <p>
          Multiple auth accounts can access this performer. Choose which auth to use for this
          scrape job.
        </p>
        <div className="auth-picker-list">
          {eligibleAuths.map((auth) => (
            <button
              key={auth.auth_id}
              className="auth-picker-option"
              onClick={() => onSelectAuth(auth.auth_id)}
              disabled={isPending}
            >
              <span className="auth-picker-name">
                {auth.auth_username || `Auth ${auth.auth_id}`}
              </span>
              <span className="auth-picker-id">ID: {auth.auth_id}</span>
            </button>
          ))}
        </div>
        <div className="modal-actions">
          <button className="btn-cancel" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
