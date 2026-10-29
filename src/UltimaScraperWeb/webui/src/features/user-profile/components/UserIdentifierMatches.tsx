import type { UserIdentifierResolutionResponse } from '../../../api/types/users';
import './UserIdentifierMatches.css';

interface UserIdentifierMatchesProps {
  identifier: string;
  resolution: UserIdentifierResolutionResponse;
  onBack: () => void;
  onSelect: (userId: number) => void;
}

type Candidate = UserIdentifierResolutionResponse['candidates'][number];

function matchDetails(candidate: Candidate, identifier: string) {
  if (candidate.matched_by.includes('user_id')) {
    return {
      label: 'Numeric ID match',
      detail: 'This account was matched directly by its stable site ID.',
    };
  }
  if (
    candidate.matched_by.includes('username') &&
    candidate.matched_by.includes('alias')
  ) {
    return {
      label: 'Current name + alias',
      detail: 'Both the current username and historical alias point to this account.',
    };
  }
  if (candidate.matched_by.includes('username')) {
    return {
      label: 'Current username',
      detail: `@${identifier} is this account’s current username.`,
    };
  }
  return {
    label: 'Historical alias',
    detail: `@${identifier} appeared on this account previously.`,
  };
}

function lastCheckedLabel(value?: string | null) {
  if (!value) return 'Never verified';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return 'Verification time unavailable';
  return `Checked ${new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(parsed)}`;
}

/** Choose deliberately when historical data maps one handle to several accounts. */
export function UserIdentifierMatches({
  identifier,
  resolution,
  onBack,
  onSelect,
}: UserIdentifierMatchesProps) {
  return (
    <div className="user-profile-page user-identifier-shell">
      <section
        className="user-identifier-panel"
        aria-labelledby="user-identifier-matches-title"
      >
        <header className="user-identifier-header">
          <div className="user-identifier-header__mark" aria-hidden="true">
            <span />
            <span />
          </div>
          <div className="user-identifier-header__copy">
            <p className="user-identifier-kicker">Identity conflict</p>
            <h1 id="user-identifier-matches-title">Which account did you mean?</h1>
            <p>
              The handle <strong>@{identifier}</strong> belongs to {resolution.total} saved account records. Compare the
              stable numeric IDs and account state before opening one.
            </p>
          </div>
          <div className="user-identifier-count" aria-label={`${resolution.total} possible accounts`}>
            <strong>{resolution.total}</strong>
            <span>possible accounts</span>
          </div>
        </header>

        <div className="user-identifier-guidance">
          <span aria-hidden="true">i</span>
          <p>
            Prefer an <strong>active current-username match</strong>. Historical aliases remain
            available so old links still resolve safely.
          </p>
        </div>

        <div className="user-identifier-card-grid">
          {resolution.candidates.map((candidate) => {
            const match = matchDetails(candidate, identifier);
            const isCurrentUsername = candidate.matched_by.includes('username');
            const isRecommended = candidate.active && isCurrentUsername;

            return (
              <button
                className={`user-identifier-card${isRecommended ? ' is-recommended' : ''}${candidate.active ? '' : ' is-inactive'}`}
                key={candidate.user_id}
                type="button"
                onClick={() => onSelect(candidate.user_id)}
              >
                <span className="user-identifier-card__topline">
                  <span className={`user-identifier-state ${candidate.active ? 'is-active' : 'is-inactive'}`}>
                    <i />
                    {candidate.active ? 'Active account' : 'Inactive record'}
                  </span>
                  {isRecommended ? <span className="user-identifier-recommended">Best match</span> : null}
                </span>

                <span className="user-identifier-card__identity">
                  <span className="user-identifier-card__avatar" aria-hidden="true">
                    {candidate.username.slice(0, 1).toUpperCase() || '?'}
                  </span>
                  <span>
                    <strong>@{candidate.username}</strong>
                    <small>OnlyFans account</small>
                  </span>
                </span>

                <span className="user-identifier-card__id">
                  <small>Stable numeric ID</small>
                  <code>{candidate.user_id}</code>
                </span>

                <span className="user-identifier-card__match">
                  <strong>{match.label}</strong>
                  <small>{match.detail}</small>
                </span>

                <span className="user-identifier-card__footer">
                  <small>{lastCheckedLabel(candidate.last_checked_at)}</small>
                  <strong>Open account <span aria-hidden="true">→</span></strong>
                </span>
              </button>
            );
          })}
        </div>

        <footer className="user-identifier-footer">
          <button className="user-identifier-back" type="button" onClick={onBack}>
            <span aria-hidden="true">←</span> Back to users
          </button>
        </footer>
      </section>
    </div>
  );
}
