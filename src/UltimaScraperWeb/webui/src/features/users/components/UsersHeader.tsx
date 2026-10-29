import type { ReactNode } from 'react';
import { UsersToolbar, type UsersToolbarProps } from './UsersToolbar';
import './UsersHeader.css';

export interface MetricTile {
  label: string;
  value: ReactNode;
  detail?: string;
  accent?: boolean;
  warn?: boolean;
}

export interface UsersHeaderProps extends UsersToolbarProps {
  title?: string;
  subtitle?: string;
  icon?: ReactNode;
  entityLabel?: string;
  metricTiles?: MetricTile[];
  totalRosterCount?: number | null;
  activeRosterCount?: number | null;
  watchedCount?: number;
  unscrapedCount?: number;
  avgPrice?: string | number | null;
  totalsStatus?: 'loading' | 'unavailable' | 'ready';
  onRetryTotals?: () => void;
  viewMode?: 'table' | 'grid';
  onViewModeChange?: (mode: 'table' | 'grid') => void;
  children?: ReactNode;
}

export function UsersHeader({
  title = 'Users',
  subtitle = 'Roster management, creator archives & metadata intelligence',
  icon = '👥',
  entityLabel = 'Creators',
  metricTiles,
  totalRosterCount,
  activeRosterCount,
  watchedCount = 0,
  unscrapedCount = 0,
  avgPrice,
  totalsStatus = 'ready',
  onRetryTotals,
  viewMode,
  onViewModeChange,
  children,
  ...toolbarProps
}: UsersHeaderProps) {
  const formattedAvgPrice =
    typeof avgPrice === 'number' ? avgPrice.toFixed(2) : avgPrice;

  return (
    <section className="users-workspace-stage" aria-label="Roster workspace header">
      {/* ── Tier 1: Workspace Title & Status Header ── */}
      <header className="users-workspace-header">
        <div className="users-workspace-title">
          <span className="users-workspace-symbol" aria-hidden="true">
            {icon}
          </span>
          <div>
            <h1 className="users-workspace-heading">{title}</h1>
            <p className="users-workspace-subtitle">{subtitle}</p>
          </div>
        </div>

        <div className="users-workspace-meta">
          <div className="users-header-status">
            <span className="users-dot users-dot--live" />
            <span>{totalRosterCount ?? '—'} {entityLabel} in Roster</span>
            <span className="users-header-divider" />
            <span>{activeRosterCount ?? '—'} Active</span>
            {totalsStatus !== 'ready' && <span role="status">{totalsStatus === 'loading' ? 'Loading totals…' : <>Totals unavailable <button type="button" onClick={onRetryTotals}>Retry</button></>}</span>}
          </div>

          {onViewModeChange && viewMode && (
            <div className="view-toggle">
              <button
                type="button"
                className={`view-btn ${viewMode === 'table' ? 'active' : ''}`}
                onClick={() => onViewModeChange('table')}
                title="Table view"
                aria-label="Table view"
              >
                ☰
              </button>
              <button
                type="button"
                className={`view-btn ${viewMode === 'grid' ? 'active' : ''}`}
                onClick={() => onViewModeChange('grid')}
                title="Grid view"
                aria-label="Grid view"
              >
                ⊞
              </button>
            </div>
          )}
        </div>
      </header>

      {/* ── Tier 2: 4-Tile Global Metrics Strip ── */}
      <div className="users-metrics">
        {metricTiles ? (
          metricTiles.map((tile, i) => (
            <div key={tile.label || i} className="users-metric-tile">
              <span>{tile.label}</span>
              <strong className={tile.accent ? 'users-metric-accent' : tile.warn ? 'users-metric-warn' : ''}>
                {tile.value}
              </strong>
              {tile.detail && <small>{tile.detail}</small>}
            </div>
          ))
        ) : (
          <>
            <div className="users-metric-tile">
              <span>Total {entityLabel}</span>
              <strong>{totalRosterCount == null ? '—' : String(totalRosterCount).padStart(2, '0')}</strong>
              <small>Across all platforms</small>
            </div>
            <div className="users-metric-tile">
              <span>Live Watched</span>
              <strong className="users-metric-accent">
                {String(watchedCount).padStart(2, '0')}
              </strong>
              <small>Webhook listeners</small>
            </div>
            <div className="users-metric-tile">
              <span>Overdue / Unscraped</span>
              <strong className={unscrapedCount > 0 ? 'users-metric-warn' : ''}>
                {String(unscrapedCount).padStart(2, '0')}
              </strong>
              <small>Needs archive sync</small>
            </div>
            <div className="users-metric-tile">
              <span>Average Rate</span>
              <strong>{formattedAvgPrice == null ? '—' : `$${formattedAvgPrice}`}</strong>
              <small>Paid subscriptions</small>
            </div>
          </>
        )}
      </div>

      {/* ── Tier 3: Universal Search & Filter Toolbar ── */}
      <UsersToolbar {...toolbarProps} />

      {/* ── Workspace Body (together inside the same stage) ── */}
      {children && <div className="users-workspace-body">{children}</div>}
    </section>
  );
}
