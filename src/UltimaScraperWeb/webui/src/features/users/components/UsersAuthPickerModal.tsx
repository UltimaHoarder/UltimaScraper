import type { EligibleAuth } from '../../../api/types/users';
import type { UserInfo } from '../lib/usersUtils';

interface UsersAuthPickerModalProps {
  isOpen: boolean;
  targetUser: UserInfo | null;
  eligibleAuths: EligibleAuth[];
  isCreatingJob: boolean;
  onClose: () => void;
  onSelectAuth: (authId: number) => void;
}

export function UsersAuthPickerModal({
  isOpen,
  targetUser,
  eligibleAuths,
  isCreatingJob,
  onClose,
  onSelectAuth,
}: UsersAuthPickerModalProps) {
  if (!isOpen || !targetUser) {
    return null;
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-dialog" onClick={(event) => event.stopPropagation()}>
        <h3>🔐 Select Auth for @{targetUser.username}</h3>
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
              disabled={isCreatingJob}
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
