import type { EligibleAuth } from '../../../api/types/users';

interface UserProfileAuthPickerModalProps {
  isOpen: boolean;
  username: string;
  eligibleAuths: EligibleAuth[];
  isCreatingJob: boolean;
  onClose: () => void;
  onSelectAuth: (authId: number) => void;
}

export function UserProfileAuthPickerModal({
  isOpen,
  username,
  eligibleAuths,
  isCreatingJob,
  onClose,
  onSelectAuth,
}: UserProfileAuthPickerModalProps) {
  if (!isOpen) {
    return null;
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">Select Auth Account</h3>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <p style={{ marginBottom: 'var(--space-4)', color: 'var(--color-text-secondary)' }}>
            Multiple auth accounts have subscription history with <strong>@{username}</strong>.
            Choose which one to use for scraping:
          </p>
          <div className="auth-picker-list">
            {eligibleAuths.map((auth) => (
              <button
                key={auth.auth_id}
                className="auth-picker-option"
                onClick={() => onSelectAuth(auth.auth_id)}
                disabled={isCreatingJob}
              >
                <span className="auth-picker-username">
                  {auth.auth_username || `Auth #${auth.auth_id}`}
                </span>
                <span className="auth-picker-id">
                  ID: {auth.auth_id}{auth.is_active ? '' : ' · expired/inactive subscription'}
                </span>
              </button>
            ))}
          </div>
        </div>
        <div className="modal-footer">
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
