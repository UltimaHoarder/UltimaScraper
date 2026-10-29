import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getStatisticsActivity } from '../../../../api/statistics';
import type { StatisticsActivityInterval, StatisticsActivityMetric, StatisticsActivityRange } from '../../../../api/types/statistics';
import { ACTIVITY_RANGES, ACTIVITY_RANGE_LABELS, analyzeActivity, buildActivityBuckets, formatActivityDate } from './statisticsActivityModel';
import { formatCount, formatPercent, formatSiteLabel } from './statisticsModel';
import { StatisticsThreeChart, type ChartSeries } from './StatisticsThreeChart';
import { StatisticsDateRange } from './StatisticsDateRange';
import { StatisticsPanel } from './StatisticsPanel';
import { useSiteColors } from './statisticsChartSettings';

export function StatisticsActivityChart({ metric, siteScope }: { metric: StatisticsActivityMetric; siteScope: string }) {
  const [interval, setActivityInterval] = useState<StatisticsActivityInterval>('month');
  const [range, setRange] = useState<StatisticsActivityRange>('all');
  const [dates, setDates] = useState<{ start: string; end: string }>();
  const accountDate = 'join_date';
  const [customStart, setCustomStart] = useState<string>();
  const [view, setView] = useState('rate');
  const [trend, setTrend] = useState('rolling');
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const siteColors = useSiteColors();
  const site = siteScope === 'all' ? undefined : siteScope;
  const bounds = range === 'custom' ? dates : undefined;
  const queryKey = ['statistics-activity', metric, interval, range, accountDate, siteScope, bounds];
  const fetchActivity = (refresh = false) => bounds ? getStatisticsActivity(metric, interval, range, accountDate, site, refresh, bounds) : refresh ? getStatisticsActivity(metric, interval, range, accountDate, site, true) : getStatisticsActivity(metric, interval, range, accountDate, site);
  const query = useQuery({ queryKey, queryFn: () => fetchActivity(), enabled: range !== 'custom' || !!bounds, staleTime: 60_000 });
  const title = metric === 'accounts' ? 'Account creation' : 'Post publication';
  const noun = metric === 'accounts' ? 'Accounts' : 'Posts';
  const allowedIntervals: StatisticsActivityInterval[] = metric === 'accounts' ? ['day', 'month', 'year'] : ['minute', 'hour', 'day', 'month', 'year'];
  const activity = query.data ? buildActivityBuckets(query.data) : null;
  const effective = query.data?.interval ?? interval;
  const analysis = analyzeActivity(activity?.buckets.map((b) => b.partial ? null : b.count) ?? [], effective === 'month' || effective === 'year' ? 3 : 7);
  // The largest site stacks at the bottom and leads the legend.
  const siteIndexes = activity?.sites.map((_, index) => index).sort((a, b) => siteColors.rank(activity.sites[a].site, a) - siteColors.rank(activity.sites[b].site, b)) ?? [];
  const chartSeries: ChartSeries[] = siteIndexes.map((index) => {
    const s = activity!.sites[index];
    let running = s.before_window_count ?? 0;
    return { label: formatSiteLabel(s.site), color: siteColors.color(s.site, index), values: activity!.buckets.map((b) => view === 'cumulative' ? (running += b.counts[index]) : b.counts[index]) };
  });
  const fitted = trend === 'linear' ? analysis.linear : trend === 'exponential' ? analysis.exponential : null;
  if (view === 'rate' && trend !== 'none') {
    const values = trend === 'rolling' ? analysis.rolling : fitted?.values;
    if (values) chartSeries.push({ label: trend === 'rolling' ? `${analysis.n < 7 && (effective === 'month' || effective === 'year') ? 3 : 7}-bucket average` : `${trend === 'linear' ? 'Linear' : 'Exponential'} fit`, color: '#f4f4f2', values, kind: 'line' });
  }
  const changeInterval = (value: StatisticsActivityInterval) => {
    setActivityInterval(value);
    if (range !== 'custom' && !ACTIVITY_RANGES[value].includes(range)) setRange(ACTIVITY_RANGES[value][0]);
    setRefreshError(null);
  };
  const refresh = async () => {
    setRefreshing(true); setRefreshError(null);
    try { queryClient.setQueryData(queryKey, await fetchActivity(true)); }
    catch { setRefreshError('Could not refresh these activity counts.'); }
    finally { setRefreshing(false); }
  };
  const settings = <>
    <div className="statistics-controls statistics-activity__controls">
      <label><span>Group {noun.toLowerCase()} by</span><select value={interval} onChange={(e) => changeInterval(e.target.value as StatisticsActivityInterval)}>{allowedIntervals.map((v) => <option key={v} value={v}>Per {v}</option>)}</select></label>
      <label><span>{noun} time range</span><select value={range} disabled={query.isLoading} onChange={(e) => { setCustomStart(query.data?.start_at.slice(0, 10)); setRange(e.target.value as StatisticsActivityRange); setRefreshError(null); }}>{[...ACTIVITY_RANGES[interval], 'custom' as const].map((v) => <option key={v} value={v}>{ACTIVITY_RANGE_LABELS[v]}</option>)}</select></label>

      <label><span>{noun} view</span><select value={view} onChange={(e) => setView(e.target.value)}><option value="rate">Activity rate</option><option value="cumulative">Cumulative in period</option></select></label>
      <label><span>{noun} trendline</span><select value={trend} onChange={(e) => setTrend(e.target.value)} disabled={view === 'cumulative'}><option value="rolling">Moving average</option><option value="linear">Linear fit</option><option value="exponential">Exponential fit</option><option value="none">None</option></select></label>
    </div>
    {range === 'custom' && <StatisticsDateRange label={noun} initialStart={dates?.start ?? customStart} onApply={setDates} />}
  </>;
  return <StatisticsPanel className="statistics-activity" label={title} settings={settings}>
    <div className="statistics-panel__header"><div><p className="statistics-eyebrow">{metric === 'accounts' ? '01 / Growth & adoption' : '02 / Publishing velocity'}</p><h2>{title}</h2>
      <p>{metric === 'accounts' ? 'Account creation uses the platform join_date, from the first dated record through now.' : 'Explore original publication times for posts currently in your archive.'}</p></div></div>
    <StatisticsThreeChart labels={activity?.buckets.map((b) => `${formatActivityDate(b.start, effective)} UTC`) ?? []} series={chartSeries} stacked={view === 'rate'} kind={view === 'cumulative' ? 'line' : 'bar'} partial={activity?.buckets.map((b) => b.partial) ?? []} label={view === 'cumulative' ? `Cumulative ${noun.toLowerCase()} in period` : `${noun} per ${effective} bar graph`} />
    {range === 'custom' && !dates ? <p className="statistics-coverage-note">Apply your dates to explore this period.</p>
      : query.error ? <div className="statistics-inline-error" role="alert">Could not load {noun.toLowerCase()} activity.<button type="button" onClick={() => void query.refetch()}>Retry</button></div>
        : query.isLoading ? <div className="statistics-empty-chart" role="status"><strong>Loading {noun.toLowerCase()} activity</strong></div>
          : activity && activity.total !== null ? <>
            <div className="statistics-growth-summary statistics-activity__summary">
              <article><span>{noun} in this period</span><strong>{formatCount(activity.total)}</strong></article>
              <article><span>Average per {effective}</span><strong>{activity.average === null ? '—' : activity.average.toLocaleString(undefined, { maximumFractionDigits: 1 })}</strong></article>
              <article><span>Rate change in view</span><strong>{analysis.change === null ? '—' : `${analysis.change > 0 ? '+' : ''}${formatPercent(analysis.change)}`}</strong></article>
            </div>
            {view === 'rate' && fitted && <p className="statistics-footnote">{trend === 'exponential' ? `Fitted rate: ${formatPercent(fitted.rate)} per ${effective}. ` : ''}Fit R²: {fitted.r2.toFixed(2)}{trend === 'exponential' ? ' in log space' : ''}. Describes the selected records; no forecast.</p>}
            {view === 'rate' && ['exponential', 'linear'].includes(trend) && !fitted && <p className="statistics-coverage-note">This fit needs at least six completed buckets{trend === 'exponential' ? ', all with positive counts' : ''}.</p>}
            <p className="statistics-footnote">{metric === 'accounts' ? 'Growth describes the archived sample. Platform-wide adoption or saturation needs the total eligible population. ' : ''}{formatCount(activity.undated ?? 0)} {metric} have no usable {metric === 'accounts' ? 'join date' : 'publication date'} and are excluded.</p>
          </> : <div className="statistics-empty-chart"><strong>Activity counts unavailable</strong><span>None of the selected sites could return counts.</span></div>}
    {refreshError && <p className="statistics-inline-error" role="alert">{refreshError}</p>}
    <div className="statistics-activity__footer"><small>{query.data ? `Calculated ${new Date(query.data.calculated_at).toLocaleString('en-GB', { timeZone: 'UTC' })} UTC` : 'UTC calendar buckets'} · Current archive records</small><button type="button" className="statistics-refresh" onClick={() => void refresh()} disabled={refreshing || query.isFetching || (range === 'custom' && !dates)}>{refreshing ? 'Refreshing…' : `Refresh ${noun.toLowerCase()}`}</button></div>
  </StatisticsPanel>;
}
