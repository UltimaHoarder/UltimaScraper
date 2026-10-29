import { useState, type ReactNode } from 'react';
import type { SiteStatistics } from '../../../../api/types/statistics';
import {
  buildContentBreakdown,
  buildMediaBreakdown,
  buildUserActivityBreakdown,
  buildUserRoleBreakdown,
  formatBytes,
  formatCount,
  formatPercent,
  formatSiteLabel,
  getPendingCount,
  sumMetric,
  type CountField,
} from './statisticsModel';
import { useSiteColors } from './statisticsChartSettings';
import { StatisticsThreeChart } from './StatisticsThreeChart';
import { StatisticsPanel, StatisticsVisualizationRow } from './StatisticsPanel';

function Panel({ title, eyebrow, description, settings, children }: { title: string; eyebrow: string; description: string; settings?: ReactNode; children: ReactNode }) {
  return <StatisticsPanel label={title} settings={settings}><div className="statistics-panel__header"><div><p className="statistics-eyebrow">{eyebrow}</p><h2>{title}</h2><p>{description}</p></div></div>{children}</StatisticsPanel>;
}
const COMPARISON_OPTIONS: Array<{ value: CountField; label: string }> = [
  { value: 'total_media_count', label: 'Media records' }, { value: 'performer_profile_count', label: 'Performer profiles' },
  { value: 'archived_content_count', label: 'Content items' }, { value: 'user_record_count', label: 'User records' }, { value: 'total_known_bytes', label: 'Known source size' },
];
export function StatisticsBreakdown({ statistics, onSelectSite }: { statistics: SiteStatistics[]; onSelectSite: (site: string) => void }) {
  const [comparison, setComparison] = useState<CountField>('total_media_count');
  const siteColors = useSiteColors();
  const types = buildMediaBreakdown(statistics);
  const userRoles = buildUserRoleBreakdown(statistics);
  const userActivity = buildUserActivityBreakdown(statistics);
  const contentTypes = buildContentBreakdown(statistics);
  const total = sumMetric(statistics, 'total_media_count');
  const sized = sumMetric(statistics, 'sized_media_count').value;
  const bytes = sumMetric(statistics, 'total_known_bytes').value;
  const downloads = sumMetric(statistics, 'downloaded_media_count').value;
  const content = sumMetric(statistics, 'archived_content_count').value;
  const performers = sumMetric(statistics, 'performer_profile_count').value;
  const completion = total.value && downloads !== null ? downloads / total.value : null;
  const averageSize = bytes !== null && sized ? bytes / sized : null;
  const coverage = total.value && sized !== null ? sized / total.value : null;
  const performerShare = userRoles.total && performers !== null ? performers / userRoles.total : null;
  const activeShare = userActivity.total && userActivity.active !== null ? userActivity.active / userActivity.total : null;
  const ranked = [...statistics].sort((a, b) => ((b.availability_error ? null : b.snapshot?.[comparison]) ?? -1) - ((a.availability_error ? null : a.snapshot?.[comparison]) ?? -1));
  const snapshot = (site: SiteStatistics) => site.availability_error ? null : site.snapshot;
  return <>
    <section className="statistics-insights" aria-label="Archive ratios">
      {[
        { label: 'Download completion', value: completion === null ? '—' : formatPercent(completion), note: 'Downloaded share of media records' },
        { label: 'Average source size', value: averageSize === null ? '—' : formatBytes(averageSize), note: 'Only media with a recorded size' },
        { label: 'Media per content item', value: content && total.value !== null ? (total.value / content).toFixed(2) : '—', note: 'Media records / content items' },
        { label: 'Content per performer', value: performers && content !== null ? (content / performers).toFixed(1) : '—', note: 'Content items / performer profiles' },
      ].map((item) => <article key={item.label} className="statistics-insight"><span>{item.label}</span><strong>{item.value}</strong><small>{item.note}{total.partial ? ' · Partial sites' : ''}</small></article>)}
    </section>
    <div className="statistics-breakdowns">
      <StatisticsVisualizationRow>
      <Panel title="Users vs performers" eyebrow="04 / User roles" description="Breakdown of regular user accounts and performer profiles in the archive.">
        {userRoles.total === null || userRoles.total === 0 || performers === null ? (
          <div className="statistics-empty-chart"><strong>{userRoles.total === null || performers === null ? 'User role counts unavailable' : 'No user records to compare'}</strong></div>
        ) : (
          <>
            <StatisticsThreeChart
              kind="pie"
              labels={userRoles.slices.map((s) => s.label)}
              series={[{ label: 'User roles', color: '#24aac3', pointColors: userRoles.slices.map((s) => s.color), values: userRoles.slices.map((s) => s.value) }]}
              label="User role distribution"
              formatValue={formatCount}
            />
            <div className="statistics-panel-stat"><strong>{formatCount(userRoles.total)}</strong><span>user records · {performerShare === null ? '—' : formatPercent(performerShare)} performers</span></div>
          </>
        )}
      </Panel>
      <Panel title="Active vs inactive users" eyebrow="05 / Account status" description="Compare active user records against inactive accounts across tracked sites.">
        {userActivity.total === null || userActivity.total === 0 || userActivity.active === null ? (
          <div className="statistics-empty-chart"><strong>{userActivity.total === null || userActivity.active === null ? 'Account activity counts unavailable' : 'No user records to compare'}</strong></div>
        ) : (
          <>
            <StatisticsThreeChart
              kind="pie"
              labels={userActivity.slices.map((s) => s.label)}
              series={[{ label: 'Account activity', color: '#82d6b2', pointColors: userActivity.slices.map((s) => s.color), values: userActivity.slices.map((s) => s.value) }]}
              label="User activity distribution"
              formatValue={formatCount}
            />
            <div className="statistics-panel-stat"><strong>{activeShare === null ? '—' : formatPercent(activeShare)}</strong><span>{formatCount(userActivity.active)} active of {formatCount(userActivity.total)} users</span></div>
          </>
        )}
      </Panel>
      </StatisticsVisualizationRow>
      <StatisticsVisualizationRow>
      <Panel title="Content types" eyebrow="06 / Content mix" description="Breakdown of archived content across posts, messages, stories, and mass messages.">
        {contentTypes.total === null || contentTypes.total === 0 || !contentTypes.hasTypeBreakdown ? (
          <div className="statistics-empty-chart"><strong>{contentTypes.total === 0 ? 'No content items to compare' : 'Content type counts unavailable'}</strong></div>
        ) : (
          <>
            <StatisticsThreeChart
              kind="pie"
              labels={contentTypes.items.map((c) => c.label)}
              series={[{ label: 'Content items', color: '#24aac3', pointColors: contentTypes.items.map((c) => c.color), values: contentTypes.items.map((c) => c.value) }]}
              label="Content type distribution"
              formatValue={formatCount}
            />
            <div className="statistics-panel-stat"><strong>{formatCount(contentTypes.total)}</strong><span>archived content items</span></div>
          </>
        )}
      </Panel>
      <Panel title="Media composition" eyebrow="07 / Catalog mix" description="Inspect and compare media types across the selected archive.">
        {total.value === null || total.value === 0 ? <div className="statistics-empty-chart"><strong>{total.value === null ? 'Media counts unavailable' : 'No media records to compare'}</strong></div> : <>
            <StatisticsThreeChart kind="pie" labels={types.map((t) => t.label)} series={[{ label: 'Media records', color: '#24aac3', pointColors: types.map((t) => t.color), values: types.map((t) => t.value) }]} label="Media type distribution" formatValue={formatCount} />
        <div className="statistics-panel-stat"><strong>{formatCount(total.value)}</strong><span>media records</span></div>
        </>}
      </Panel>
      </StatisticsVisualizationRow>
      <StatisticsVisualizationRow>
      <Panel title="Source size profile" eyebrow="08 / Size metadata" description="Average file size by media type, weighted by sized records.">
        <StatisticsThreeChart kind="pie" labels={types.map((t) => t.label)} series={[{ label: 'Average source size', color: '#9b8fea', pointColors: types.map((t) => t.color), values: types.map((t) => t.average) }]} label="Source size bars" formatAxisValue={formatBytes} formatValue={formatBytes} />
        <div className="statistics-panel-stat"><strong>{coverage === null ? '—' : formatPercent(coverage)}</strong><span>media with known sizes</span></div>
        <p className="statistics-footnote">{sized !== null && total.value !== null ? `${formatCount(Math.max(0, total.value - sized))} media records have no positive size metadata. ` : ''}Source metadata does not measure disk usage. Type averages are approximate.</p>
      </Panel>
      <Panel title="Site distribution" eyebrow="09 / Site comparison" description="Select a site slice or name to focus the page." settings={<label className="statistics-comparison-control"><span>Compare sites by</span><select value={comparison} onChange={(e) => setComparison(e.target.value as CountField)}>{COMPARISON_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}</select></label>}>
        <StatisticsThreeChart kind="pie" labels={ranked.map((s) => formatSiteLabel(s.site))} series={[{ label: COMPARISON_OPTIONS.find((o) => o.value === comparison)!.label, color: '#24aac3', pointColors: ranked.map((s, i) => siteColors.color(s.site, i)), values: ranked.map((s) => snapshot(s)?.[comparison] ?? null) }]} label="Site comparison bars" formatAxisValue={comparison === 'total_known_bytes' ? formatBytes : undefined} formatValue={comparison === 'total_known_bytes' ? formatBytes : formatCount} onSelect={(i) => onSelectSite(ranked[i].site)} />
        <div className="statistics-site-shortcuts">{ranked.map((s) => <button key={s.site} type="button" aria-label={`Focus ${formatSiteLabel(s.site)}`} onClick={() => onSelectSite(s.site)}>{formatSiteLabel(s.site)} ↗</button>)}</div>
      </Panel>
      </StatisticsVisualizationRow>
      <StatisticsVisualizationRow>
      <Panel title="Download coverage" eyebrow="10 / Archive readiness" description="Inspect downloaded and pending media by site.">
        <StatisticsThreeChart labels={statistics.map((s) => formatSiteLabel(s.site))} series={[
          { label: 'Downloaded', color: '#24aac3', values: statistics.map((s) => snapshot(s)?.downloaded_media_count ?? null) },
          { label: 'Pending', color: '#ffd303', values: statistics.map((s) => getPendingCount(snapshot(s))) },
        ]} stacked label="Download coverage bars" formatValue={formatCount} />
        <div className="statistics-panel-stat"><strong>{completion === null ? '—' : formatPercent(completion)}</strong><span>{downloads === null ? 'Download count unavailable' : `${formatCount(downloads)} downloaded`}</span></div>
        {statistics.some((s) => getPendingCount(snapshot(s)) === null) && <p className="statistics-footnote">Download status unavailable for some sites.</p>}
      </Panel>
      </StatisticsVisualizationRow>
    </div>
  </>;
}

