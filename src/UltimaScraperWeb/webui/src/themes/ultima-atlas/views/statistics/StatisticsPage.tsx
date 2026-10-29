import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getAllStatistics, getStatisticsHistory } from '../../../../api/statistics';
import type {
  SiteStatistics,
  StatisticsHistoryRange,
} from '../../../../api/types/statistics';
import { StatisticsBreakdown } from './StatisticsBreakdown';
import { StatisticsGrowth } from './StatisticsGrowth';
import { StatisticsActivityChart } from './StatisticsActivityChart';
import { StatisticsThreeChart } from './StatisticsThreeChart';
import { StatisticsSeasonality } from './StatisticsSeasonality';
import { StatisticsPanel, StatisticsVisualizationRow } from './StatisticsPanel';
import { StatisticsSiteOrderContext } from './statisticsChartSettings';
import { WorkspacePageHeader } from '../../../../shared/ui/WorkspacePageHeader';
import {
  buildTrendData, formatBytes, formatCount, formatDate, formatPercent,
  formatSiteLabel, getPendingCount, sumMetric, TREND_OPTIONS,
  type MetricTotal, type TrendMetric, type TrendSeries,
} from './statisticsModel';
import './StatisticsPage.css';

function StatisticsTrendChart({ dates, series, metric }: { dates: string[]; series: TrendSeries[]; metric: TrendMetric }) {
  if (!series.some((s) => s.values.some((v) => v !== null))) return <div className="statistics-empty-chart"><strong>No trend points for this selection</strong><span>New inventory metrics begin with the first expanded daily snapshot.</span></div>;
  return <StatisticsThreeChart labels={dates.map(formatDate)} series={series} kind="line" label={`Daily ${TREND_OPTIONS.find((o) => o.value === metric)?.label ?? 'statistics'} trend`} formatValue={metric === 'total_known_bytes' ? formatBytes : formatCount} />;
}

function snapshotState(statistic: SiteStatistics): { label: string; tone: string } {
  if (statistic.availability_error) return { label: 'Unavailable', tone: 'error' };
  if (statistic.build_state === 'failed') return { label: 'Build failed', tone: 'error' };
  if (statistic.is_building) return { label: 'Building', tone: 'warning' };
  if (!statistic.snapshot) return { label: 'No snapshot', tone: 'muted' };
  return statistic.is_current
    ? { label: 'Current', tone: 'success' }
    : { label: 'Latest snapshot', tone: 'muted' };
}

export function StatisticsPage() {
  const range: StatisticsHistoryRange = 'all';
  const [metric, setMetric] = useState<TrendMetric>('total_media_count');
  const [siteScope, setSiteScope] = useState('all');
  const [manualRefreshPending, setManualRefreshPending] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const {
    data: statistics = [],
    isLoading,
    isFetching,
    error,
  } = useQuery({
    queryKey: ['daily-statistics'],
    queryFn: () => getAllStatistics(),
    refetchInterval: (query) => {
      const data = query.state.data as SiteStatistics[] | undefined;
      return data?.some((item) => item.is_building) ? 2500 : false;
    },
  });

  const historyQuery = useQuery({
    queryKey: ['statistics-history', range, statistics.map((site) => site.snapshot?.calculated_at ?? null)],
    queryFn: () => getStatisticsHistory(range),
  });

  const orderedStatistics = useMemo(
    () => [...statistics].sort((left, right) => left.site.localeCompare(right.site)),
    [statistics]
  );
  const siteOrder = useMemo(
    () => [...statistics]
      .sort((left, right) => (right.snapshot?.total_media_count ?? -1) - (left.snapshot?.total_media_count ?? -1) || left.site.localeCompare(right.site))
      .map((item) => item.site),
    [statistics]
  );
  const scopedStatistics = orderedStatistics.filter((item) => siteScope === 'all' || item.site === siteScope);
  const selectedTrendMetric = TREND_OPTIONS.find((option) => option.value === metric)?.label ?? 'Media records';
  const trendData = useMemo(
    () => buildTrendData(historyQuery.data?.sites ?? [], siteScope, metric, historyQuery.data?.start_date, historyQuery.data?.end_date),
    [historyQuery.data, siteScope, metric]
  );

  const userRecords = sumMetric(scopedStatistics, 'user_record_count');
  const performers = sumMetric(scopedStatistics, 'performer_profile_count');
  const contentItems = sumMetric(scopedStatistics, 'archived_content_count');
  const totalMedia = sumMetric(scopedStatistics, 'total_media_count');
  const downloadedMedia = sumMetric(scopedStatistics, 'downloaded_media_count');
  const knownSourceBytes = sumMetric(scopedStatistics, 'total_known_bytes');
  const sizedMedia = sumMetric(scopedStatistics, 'sized_media_count');
  const pendingMedia = totalMedia.value !== null && downloadedMedia.value !== null
    ? {
      value: Math.max(0, totalMedia.value - downloadedMedia.value),
      partial: totalMedia.partial || downloadedMedia.partial,
    }
    : { value: null, partial: totalMedia.partial || downloadedMedia.partial };
  const sizeCoverage = totalMedia.value && sizedMedia.value !== null
    ? sizedMedia.value / totalMedia.value
    : null;
  const buildingSites = orderedStatistics.filter((item) => item.is_building);
  const hasSiteSnapshots = orderedStatistics.some((item) => item.snapshot !== null);
  const initialLoading = isLoading && orderedStatistics.length === 0;
  const refreshBusy = isFetching || manualRefreshPending;

  const handleRefresh = async () => {
    setManualRefreshPending(true);
    setRefreshError(null);
    try {
      const refreshed = await getAllStatistics(true);
      queryClient.setQueryData(['daily-statistics'], refreshed);
      await queryClient.invalidateQueries({ queryKey: ['statistics-history'] });
    } catch (refreshFailure) {
      setRefreshError(
        refreshFailure instanceof Error ? refreshFailure.message : 'Could not refresh statistics.'
      );
    } finally {
      setManualRefreshPending(false);
    }
  };

  const renderTotal = (total: MetricTotal): string =>
    total.value === null ? '—' : formatCount(total.value);

  return (
    <StatisticsSiteOrderContext.Provider value={siteOrder}>
    <main className="statistics-page">
      <WorkspacePageHeader
        eyebrow="Platform / Archive intelligence"
        title="Statistics"
        subtitle="Explore growth, publishing velocity and recurring patterns in your archive."
        icon="▥"
        meta={(
          <button
            type="button"
            className="statistics-refresh"
            onClick={handleRefresh}
            disabled={refreshBusy}
          >
            {refreshBusy ? 'Refreshing…' : 'Refresh snapshot'}
          </button>
        )}
      />

      {(initialLoading || buildingSites.length > 0) && (
        <section className="statistics-notice statistics-notice--info" role="status">
          <strong>{initialLoading ? 'Loading archive snapshot' : 'Daily snapshot building'}</strong>
          <span>
            {initialLoading
              ? 'The first load may take a while while site statistics are calculated.'
              : buildingSites.map((item) => {
                const progress = item.build_progress_ratio === null
                  ? ''
                  : ` (${Math.round(item.build_progress_ratio * 100)}%)`;
                return `${formatSiteLabel(item.site)}${progress}`;
              }).join(' · ')}
          </span>
        </section>
      )}

      {refreshError && (
        <section className="statistics-notice statistics-notice--error" role="alert">
          <strong>Could not refresh statistics</strong>
          <span>{refreshError}</span>
        </section>
      )}

      {error && orderedStatistics.length === 0 ? (
        <section className="statistics-state" role="alert">
          <strong>Could not load statistics</strong>
          <span>{error instanceof Error ? error.message : 'The statistics service is unavailable.'}</span>
          <button type="button" className="statistics-refresh" onClick={handleRefresh}>Retry</button>
        </section>
      ) : initialLoading ? (
        <section className="statistics-state" aria-live="polite">
          <strong>Loading archive totals</strong>
          <span>Waiting for the latest per-site snapshot.</span>
        </section>
      ) : orderedStatistics.length === 0 ? (
        <section className="statistics-state">
          <strong>No archive statistics are available</strong>
          <span>Check that at least one archive site is enabled, then refresh the snapshot.</span>
        </section>
      ) : (
        <>
          {!hasSiteSnapshots && (
            <section className="statistics-state">
              <strong>No completed snapshots yet</strong>
              <span>Site totals will appear after the first daily snapshot finishes building.</span>
            </section>
          )}

          <div className="statistics-visualizations">
            <StatisticsVisualizationRow>
            <StatisticsActivityChart metric="accounts" siteScope={siteScope} />
            <StatisticsActivityChart metric="posts" siteScope={siteScope} />
            </StatisticsVisualizationRow>

          <StatisticsVisualizationRow>
          <StatisticsSeasonality siteScope={siteScope} />

          <StatisticsPanel label="Archive trends" settings={<div className="statistics-controls">
                <label>
                  <span>Metric</span>
                  <select
                    value={metric}
                    onChange={(event) => setMetric(event.target.value as TrendMetric)}
                  >
                    {TREND_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </label>
              </div>}>
            <div className="statistics-panel__header">
              <div>
                <p className="statistics-eyebrow">Daily history</p>
                <h2>Archive trends</h2>
                <p>Compare saved daily totals. Missing dates remain gaps in the chart.</p>
              </div>
            </div>

            {historyQuery.error ? (
              <div className="statistics-inline-error" role="alert">
                Could not load historical snapshots.
                <button type="button" onClick={() => void historyQuery.refetch()}>Retry</button>
              </div>
            ) : historyQuery.isLoading ? (
              <div className="statistics-empty-chart" role="status">
                <strong>Loading daily history</strong>
              </div>
            ) : (
              <>
                <StatisticsTrendChart
                  dates={trendData.dates}
                  series={trendData.series}
                  metric={metric}
                />
                <p className="statistics-chart-caption">
                  {selectedTrendMetric} · {historyQuery.data?.start_date
                    ? `${formatDate(historyQuery.data.start_date)} to ${formatDate(historyQuery.data.end_date)} UTC`
                    : `All available history through ${historyQuery.data?.end_date ?? 'today'} UTC`}
                </p>
              </>
            )}
          </StatisticsPanel>
          </StatisticsVisualizationRow>

          <StatisticsBreakdown statistics={scopedStatistics} onSelectSite={setSiteScope} />

          {!historyQuery.error && !historyQuery.isLoading && <StatisticsVisualizationRow><StatisticsGrowth data={trendData} metric={metric} /></StatisticsVisualizationRow>}
          </div>

          <section className="statistics-kpis" aria-label="Archive totals">
            <article className={`statistics-kpi ${userRecords.partial ? 'is-partial' : ''}`}>
              <span className="statistics-kpi__label">User records</span>
              <strong>{renderTotal(userRecords)}</strong>
              <small>{userRecords.partial ? 'Partial or not yet snapshotted' : 'All tracked user rows'}</small>
            </article>
            <article className={`statistics-kpi ${performers.partial ? 'is-partial' : ''}`}>
              <span className="statistics-kpi__label">Performer profiles</span>
              <strong>{renderTotal(performers)}</strong>
              <small>{performers.partial ? 'Partial or not yet snapshotted' : 'Tracked performer profiles'}</small>
            </article>
            <article className={`statistics-kpi ${contentItems.partial ? 'is-partial' : ''}`}>
              <span className="statistics-kpi__label">Content items</span>
              <strong>{renderTotal(contentItems)}</strong>
              <small>{contentItems.partial ? 'Partial or not yet snapshotted' : 'Posts, messages, stories, and mass messages'}</small>
            </article>
            <article className={`statistics-kpi ${totalMedia.partial ? 'is-partial' : ''}`}>
              <span className="statistics-kpi__label">Media records</span>
              <strong>{renderTotal(totalMedia)}</strong>
              <small>{totalMedia.partial ? 'Partial site total' : 'Images, video, audio, and other'}</small>
            </article>
            <article className={`statistics-kpi ${downloadedMedia.partial ? 'is-partial' : ''}`}>
              <span className="statistics-kpi__label">Downloaded / pending</span>
              <strong>
                {downloadedMedia.value === null || pendingMedia.value === null
                  ? '—'
                  : `${formatCount(downloadedMedia.value)} / ${formatCount(pendingMedia.value)}`}
              </strong>
              <small>
                {downloadedMedia.partial || pendingMedia.partial
                  ? 'Partial or not yet snapshotted'
                  : 'Media download status'}
              </small>
            </article>
            <article className={`statistics-kpi ${knownSourceBytes.partial ? 'is-partial' : ''}`}>
              <span className="statistics-kpi__label">Known source size</span>
              <strong>{knownSourceBytes.value === null ? '—' : formatBytes(knownSourceBytes.value)}</strong>
              <small>
                {sizeCoverage === null
                  ? 'Source size metadata'
                  : `${formatPercent(sizeCoverage)} size coverage · metadata, not disk usage`}
              </small>
            </article>
          </section>

          <section className="statistics-panel">
            <div className="statistics-panel__header">
              <div>
                <p className="statistics-eyebrow">Site comparison</p>
                <h2>Archive by site</h2>
                <p>Select a site to focus the statistics page. Source sizes are recorded metadata values.</p>
              </div>
            </div>
            <div className="statistics-site-cards">
              {orderedStatistics.map((item) => {
                const snapshot = item.availability_error ? null : item.snapshot;
                const state = snapshotState(item);
                const pending = getPendingCount(snapshot);
                return <article key={item.site}>
                  <div className="statistics-site-card__header">
                    <button type="button" className="statistics-site-select" aria-pressed={siteScope === item.site} onClick={() => setSiteScope((current) => current === item.site ? 'all' : item.site)}>{formatSiteLabel(item.site)}</button>
                    <span className={`statistics-state-chip is-${state.tone}`}>{state.label}</span>
                  </div>
                  <dl>
                    <div><dt>Profiles</dt><dd>{snapshot?.user_record_count == null ? '—' : formatCount(snapshot.user_record_count)}<small>{snapshot?.performer_profile_count == null ? 'Performers —' : `${formatCount(snapshot.performer_profile_count)} performers`}</small></dd></div>
                    <div><dt>Content</dt><dd>{snapshot?.archived_content_count == null ? '—' : formatCount(snapshot.archived_content_count)}</dd></div>
                    <div><dt>Media</dt><dd>{snapshot ? formatCount(snapshot.total_media_count) : '—'}<small>{snapshot ? `Image ${formatCount(snapshot.image_media_count)} · Video ${formatCount(snapshot.video_media_count)} · Audio ${formatCount(snapshot.audio_media_count)} · Other ${formatCount(snapshot.other_media_count)}` : 'No completed snapshot'}</small></dd></div>
                    <div><dt>Downloaded / pending</dt><dd>{snapshot?.downloaded_media_count == null || pending === null ? '—' : `${formatCount(snapshot.downloaded_media_count)} / ${formatCount(pending)}`}</dd></div>
                    <div><dt>Known source size</dt><dd>{snapshot ? formatBytes(snapshot.total_known_bytes) : '—'}<small>{snapshot ? `${formatPercent(snapshot.size_coverage_ratio)} media size coverage` : 'Source metadata unavailable'}</small></dd></div>
                  </dl>
                  <small>{snapshot ? formatDate(snapshot.bucket_date) : item.availability_error ?? item.target_bucket_date}</small>
                </article>;
              })}
            </div>
          </section>
        </>
      )}
    </main>
    </StatisticsSiteOrderContext.Provider>
  );
}
