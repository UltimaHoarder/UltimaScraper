import { dailyChanges, formatDate, formatMetric, formatPercent, summarizeTrend, type TrendData, type TrendMetric } from './statisticsModel';

import { StatisticsThreeChart } from './StatisticsThreeChart';
import { StatisticsPanel } from './StatisticsPanel';

export function StatisticsGrowth({ data, metric }: { data: TrendData; metric: TrendMetric }) {
  const primary = data.series[0];
  const summary = summarizeTrend(data.dates, primary?.values ?? []);
  const changes = data.series.map((series) => ({ ...series, values: dailyChanges(series.values) }));
  const known = changes.flatMap((series) => series.values.filter((value): value is number => value !== null));
  const signed = (value: number | null) => value === null ? '—' : `${value > 0 ? '+' : ''}${formatMetric(value, metric)}`;

  return <StatisticsPanel label="Daily net change">
    <div className="statistics-panel__header"><div>
      <p className="statistics-eyebrow">Growth / Change</p><h2>Daily net change</h2>
      <p>Changes between consecutive UTC daily snapshots. Decreases include removals and corrections.</p>
    </div></div>
    {known.length === 0 ? <div className="statistics-empty-chart"><strong>Not enough consecutive snapshots</strong><span>Daily changes need two adjacent days with known values.</span></div> : <>
      <StatisticsThreeChart labels={data.dates.map(formatDate)} series={changes} label="Daily net change bars" formatValue={(v) => signed(v)} />
    </>}
    <div className="statistics-growth-summary">
      <article><span>{primary?.label ?? 'Selected metric'} net change</span><strong>{signed(summary.net)}</strong><small>{summary.percent === null ? 'Percentage unavailable' : `${summary.percent > 0 ? '+' : ''}${formatPercent(summary.percent)} from first recorded value`}</small></article>
      <article><span>Average daily net change</span><strong>{summary.averageDaily === null ? '—' : signed(Math.round(summary.averageDaily))}</strong><small>{summary.comparedDays} consecutive daily comparisons</small></article>
      <article><span>Recorded days</span><strong>{summary.recordedDays} / {data.dates.length}</strong><small>{summary.first && summary.last ? `${formatDate(summary.first.date)} – ${formatDate(summary.last.date)}` : 'No recorded values'}</small></article>
    </div>
    <p className="statistics-footnote">Net changes describe inventory counts, rather than job throughput. Gaps and unknown values are excluded from daily averages.</p>
  </StatisticsPanel>;
}
