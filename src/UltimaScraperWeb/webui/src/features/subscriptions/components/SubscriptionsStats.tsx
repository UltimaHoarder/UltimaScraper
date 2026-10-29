import type { SubscriptionStats } from '../../../api/types/subscriptions';

interface SubscriptionsStatsProps {
  stats: SubscriptionStats[] | undefined;
  statsLoading: boolean;
}

export function SubscriptionsStats({ stats, statsLoading }: SubscriptionsStatsProps) {
  return (
    <div className="stats-grid">
      {statsLoading ? (
        <div className="loading-stats">Loading stats...</div>
      ) : stats && stats.length > 0 ? (
        stats.map((stat) => (
          <div key={stat.site} className="stat-card">
            <div className="stat-site">{stat.site}</div>
            <div className="stat-numbers">
              <div className="stat-item">
                <span className="stat-value">{stat.total}</span>
                <span className="stat-label">Total</span>
              </div>
              <div className="stat-item">
                <span className="stat-value active">{stat.active}</span>
                <span className="stat-label">Active</span>
              </div>
              <div className="stat-item">
                <span className="stat-value expired">{stat.expired}</span>
                <span className="stat-label">Expired</span>
              </div>
            </div>
          </div>
        ))
      ) : (
        <div className="no-stats">No subscription data available</div>
      )}
    </div>
  );
}
