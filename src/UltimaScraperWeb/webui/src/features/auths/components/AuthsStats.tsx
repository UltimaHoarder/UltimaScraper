interface AuthsStatsProps {
  showing: number;
  total: number;
  accounts: number;
  loadedEnabledCount: number;
  loadedDisabledCount: number;
  spenderCount: number;
}

export function AuthsStats({
  showing,
  total,
  accounts,
  loadedEnabledCount,
  loadedDisabledCount,
  spenderCount,
}: AuthsStatsProps) {
  return (
    <dl className="auths-stats">
      <div>
        <dt>Accounts</dt>
        <dd>{accounts}</dd>
      </div>
      <div>
        <dt>Auths</dt>
        <dd>
          {showing}
          {showing !== total && <small> of {total}</small>}
        </dd>
      </div>
      <div>
        <dt>Active</dt>
        <dd>
          {loadedEnabledCount}
          {loadedDisabledCount > 0 && <small> · {loadedDisabledCount} disabled</small>}
        </dd>
      </div>
      <div className="auths-stats-warn" title="Accounts that may purchase subscriptions">
        <dt>Can spend</dt>
        <dd>{spenderCount}</dd>
      </div>
      <div title="Accounts that cannot purchase subscriptions">
        <dt>Locked</dt>
        <dd>{accounts - spenderCount}</dd>
      </div>
    </dl>
  );
}
