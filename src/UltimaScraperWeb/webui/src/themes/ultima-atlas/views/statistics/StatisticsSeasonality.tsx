import { useSiteColors } from './statisticsChartSettings';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getStatisticsSeasonality } from '../../../../api/statistics';
import type { SeasonalityCycle, StatisticsActivityMetric } from '../../../../api/types/statistics';
import { StatisticsThreeChart } from './StatisticsThreeChart';
import { StatisticsPanel } from './StatisticsPanel';
import { StatisticsDateRange } from './StatisticsDateRange';
import { formatCount, formatSiteLabel } from './statisticsModel';

const LABELS = {
  hour: Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, '0')}:00`),
  weekday: ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
  monthday: Array.from({ length: 31 }, (_, i) => `Day ${i + 1}`),
  month: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],
};
export function StatisticsSeasonality({ siteScope }: { siteScope: string }) {
  const [metric, setMetric] = useState<StatisticsActivityMetric>('posts');
  const [cycle, setCycle] = useState<SeasonalityCycle>('weekday');
  const dateField = 'join_date';
  const [customStart, setCustomStart] = useState<string>();
  const [range, setRange] = useState('all');
  const [dates, setDates] = useState<{ start: string; end: string }>();
  const [normalized, setNormalized] = useState(true);
  const bounds = range === 'custom' ? dates : undefined;
  const query = useQuery({ queryKey: ['statistics-seasonality', metric, cycle, dateField, siteScope, bounds], queryFn: () => getStatisticsSeasonality(metric, cycle, dateField, siteScope === 'all' ? undefined : siteScope, bounds), enabled: range !== 'custom' || !!bounds, staleTime: 60_000 });
  const data = query.data;
  const siteColors = useSiteColors();
  const sites = data?.sites.filter((s) => s.available) ?? [];
  const labels = LABELS[cycle];
  const series = sites.map((s, i) => ({ label: formatSiteLabel(s.site), color: siteColors.color(s.site, i), values: labels.map((_, bin) => !data?.exposures[bin] ? null : normalized ? s.counts[bin] / data.exposures[bin] : s.counts[bin]) }));
  const rates = labels.map((_, i) => data?.exposures[i] && sites.length ? sites.reduce((sum, s) => sum + s.counts[i], 0) / data.exposures[i] : null);
  const peak = rates.reduce<number>((best, value, i) => value !== null && (rates[best] === null || value > rates[best]!) ? i : best, 0);
  const exposures = data?.exposures ?? [];
  const repetitions = exposures.length ? Math.min(...exposures) : 0;
  const unit = cycle === 'hour' ? 'hour of day' : cycle === 'weekday' ? 'weekday' : cycle === 'monthday' ? 'day of month' : 'calendar month';
  const settings = <>
    <div className="statistics-controls">
      <label><span>Seasonality metric</span><select value={metric} onChange={(e) => setMetric(e.target.value as StatisticsActivityMetric)}><option value="posts">Post publication</option><option value="accounts">Account creation</option></select></label>
      <label><span>Seasonality cycle</span><select value={cycle} onChange={(e) => setCycle(e.target.value as SeasonalityCycle)}><option value="hour">Hour of day</option><option value="weekday">Day of week</option><option value="monthday">Day of month</option><option value="month">Month of year</option></select></label>
      <label><span>Seasonality range</span><select value={range} disabled={query.isLoading} onChange={(e) => { setCustomStart(query.data?.start_date); setRange(e.target.value); }}><option value="all">Start to now</option><option value="custom">Custom dates</option></select></label>

      <label><span>Seasonality values</span><select value={normalized ? 'average' : 'total'} onChange={(e) => setNormalized(e.target.value === 'average')}><option value="average">Average per occurrence</option><option value="total">Total records</option></select></label>
    </div>
    {range === 'custom' && <StatisticsDateRange label="Seasonality" initialStart={dates?.start ?? customStart} onApply={setDates} />}
  </>;
  return <StatisticsPanel className="statistics-seasonality" label="Seasonality" settings={settings}>
    <div className="statistics-panel__header"><div><p className="statistics-eyebrow">03 / Recurring behaviour</p><h2>Seasonality</h2><p>Compare daily, weekly, monthly and annual calendar patterns across completed UTC days.</p></div><span className="statistics-state-chip">{cycle === 'hour' ? 'Daily' : cycle === 'weekday' ? 'Weekly' : cycle === 'monthday' ? 'Monthly' : 'Annual'} cycle</span></div>
    <StatisticsThreeChart label="Seasonality bar graph" labels={labels} series={series} stacked />
    {range === 'custom' && !bounds ? <p className="statistics-coverage-note">Apply dates to compare your own period.</p> : query.isLoading ? <div className="statistics-empty-chart" role="status">Loading calendar patterns</div> : query.error ? <div className="statistics-inline-error" role="alert">Could not load seasonality. Choose a range with completed days.<button type="button" onClick={() => void query.refetch()}>Retry</button></div> : sites.length ? <>
      <div className="statistics-growth-summary">
        <article><span>Busiest {unit}</span><strong>{rates[peak] ? labels[peak] : '—'}</strong><small>{rates[peak]?.toLocaleString(undefined, { maximumFractionDigits: 2 }) ?? '—'} records per occurrence</small></article>
        <article><span>Observed occurrences</span><strong>{repetitions.toLocaleString(undefined, { maximumFractionDigits: 1 })}+</strong><small>Minimum exposure per calendar bin</small></article>
        <article><span>Analysis window</span><strong>{data?.start_date}</strong><small>Through {data?.end_date} · complete UTC days</small></article>
      </div>
      <p className="statistics-footnote">{normalized ? 'Counts divided by observed occurrences: hours, weekdays and month days by occurrence count; months by calendar-month equivalents, including partial months.' : 'Raw counts reflect differing exposure lengths. Use averages to compare fairly.'} {data?.date_field === 'join_date' ? 'Undated accounts are excluded; date-only join timestamps appear at midnight.' : ''}</p>
      {repetitions < 2 && <p className="statistics-coverage-note">Fewer than two occurrences in at least one bin. Extend the range before interpreting this profile as a repeating pattern.</p>}
      <p className="statistics-footnote">Calendar profiles describe archived records, and can reflect collection coverage as well as source behaviour. Calculated {data?.calculated_at ? new Date(data.calculated_at).toLocaleString('en-GB', { timeZone: 'UTC' }) : ''} UTC.</p>
    </> : <div className="statistics-empty-chart">Seasonality counts unavailable</div>}
    <p className="statistics-footnote">{sites.length ? formatCount(sites.reduce((sum, s) => sum + s.counts.reduce((a, b) => a + b, 0), 0)) : '—'} dated records in this analysis window.</p>
  </StatisticsPanel>;
}
