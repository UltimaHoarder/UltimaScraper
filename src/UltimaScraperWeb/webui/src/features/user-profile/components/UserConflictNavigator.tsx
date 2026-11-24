import { Link } from 'react-router-dom';
import type { UserIdentifierCandidate } from '../../../api/types/users';
import './UserConflictNavigator.css';

interface UserConflictNavigatorProps {
  identifier: string;
  candidates: UserIdentifierCandidate[];
  total: number;
  currentUserId: number | null;
  refreshing: boolean;
  hrefFor: (userId: number) => string;
  chooserHref: string;
}

function claimLabel(candidate: UserIdentifierCandidate): string {
  const claim = candidate.matched_by.includes('username') ? 'Current name' : 'Former name';
  return candidate.active ? claim : `${claim} · inactive`;
}

/** Switch between saved profiles that share a current username or historical alias. */
export function UserConflictNavigator({
  identifier,
  candidates,
  total,
  currentUserId,
  refreshing,
  hrefFor,
  chooserHref,
}: UserConflictNavigatorProps) {
  const index = candidates.findIndex((candidate) => candidate.user_id === currentUserId);
  const previous = index > 0 ? candidates[index - 1] : null;
  const next = index >= 0 && index < candidates.length - 1 ? candidates[index + 1] : null;

  return (
    <nav
      className="user-conflict-navigator"
      aria-label="Profiles sharing this identifier"
      aria-busy={refreshing}
    >
      <div className="user-conflict-navigator__head">
        <div className="user-conflict-navigator__copy">
          <span className="user-conflict-navigator__kicker">Shared identifier</span>
          <span className="user-conflict-navigator__summary">
            <strong>@{identifier}</strong> is claimed by {total} saved profiles
            {index < 0 ? ' — this profile no longer claims it' : null}
          </span>
        </div>

        <div className="user-conflict-navigator__controls">
          {previous ? (
            <Link to={hrefFor(previous.user_id)} aria-label={`Previous: @${previous.username}`}>
              <span aria-hidden="true">←</span> Prev
            </Link>
          ) : (
            <span className="is-disabled" aria-disabled="true">
              <span aria-hidden="true">←</span> Prev
            </span>
          )}
          <span className="user-conflict-navigator__position">
            {index >= 0 ? (
              <>
                <strong>{index + 1}</strong> / {total}
              </>
            ) : (
              <>— / {total}</>
            )}
          </span>
          {next ? (
            <Link to={hrefFor(next.user_id)} aria-label={`Next: @${next.username}`}>
              Next <span aria-hidden="true">→</span>
            </Link>
          ) : (
            <span className="is-disabled" aria-disabled="true">
              Next <span aria-hidden="true">→</span>
            </span>
          )}
          <Link className="user-conflict-navigator__compare" to={chooserHref}>
            Compare
          </Link>
        </div>
      </div>

      <ol className="user-conflict-navigator__list">
        {candidates.map((candidate) => {
          const current = candidate.user_id === currentUserId;
          return (
            <li key={candidate.user_id}>
              <Link
                to={hrefFor(candidate.user_id)}
                className={`user-conflict-navigator__claimant${current ? ' is-current' : ''}${candidate.active ? '' : ' is-inactive'}`}
                aria-current={current ? 'page' : undefined}
              >
                <span className="user-conflict-navigator__claimant-name">@{candidate.username}</span>
                <span className="user-conflict-navigator__claimant-meta">
                  <code>{candidate.user_id}</code>
                  <span>{claimLabel(candidate)}</span>
                </span>
              </Link>
            </li>
          );
        })}
      </ol>
      {candidates.length < total ? (
        <p className="user-conflict-navigator__more">
          Showing {candidates.length} of {total}. <Link to={chooserHref}>See all</Link>
        </p>
      ) : null}
    </nav>
  );
}
