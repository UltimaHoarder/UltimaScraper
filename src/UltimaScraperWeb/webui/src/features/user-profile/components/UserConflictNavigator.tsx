import './UserConflictNavigator.css';

interface UserConflictNavigatorProps {
  identifier: string;
  page: number;
  total: number;
  loading: boolean;
  onPageChange: (page: number) => void;
}

/** Navigate between saved profiles that share a current username or historical alias. */
export function UserConflictNavigator({
  identifier,
  page,
  total,
  loading,
  onPageChange,
}: UserConflictNavigatorProps) {
  return (
    <nav className="user-conflict-navigator" aria-label="Conflicting user profiles">
      <div className="user-conflict-navigator__copy">
        <span className="user-conflict-navigator__kicker">Shared identifier</span>
        <span className="user-conflict-navigator__summary">
          <strong>@{identifier}</strong> is attached to {total} saved profiles
        </span>
      </div>

      <div className="user-conflict-navigator__controls">
        <button
          type="button"
          aria-label="Previous conflicting profile"
          disabled={loading || page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          <span aria-hidden="true">←</span>
          Previous
        </button>
        <span className="user-conflict-navigator__position" aria-label="Conflicting profile position">
          Record <strong>{page}</strong> of {total}
        </span>
        <button
          type="button"
          aria-label="Next conflicting profile"
          disabled={loading || page >= total}
          onClick={() => onPageChange(page + 1)}
        >
          Next
          <span aria-hidden="true">→</span>
        </button>
      </div>
    </nav>
  );
}
