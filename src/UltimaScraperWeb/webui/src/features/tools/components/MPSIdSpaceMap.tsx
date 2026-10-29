import { useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';
import type { MPSAnalyzeResponse, MPSDensityBucket } from '../../../api/types/mps';

interface Props {
  site: string;
  onSiteChange: (site: string) => void;
  analysis: MPSAnalyzeResponse | null;
  loading: boolean;
  sources?: { missing: boolean; invalid: boolean; existing: boolean };
}

type SegmentSource = 'missing' | 'invalid' | 'existing';

const SEGMENT_COLORS: Record<SegmentSource, string> = {
  missing: '#24aac3',
  invalid: '#f59e0b',
  existing: '#8b5cf6',
};

/** ID-space visualization rendering exact or estimated candidate density buckets via Apache ECharts. */
export function MPSIdSpaceMap({ site, onSiteChange, analysis, loading, sources = { missing: true, invalid: true, existing: true } }: Props) {
  const [hover, setHover] = useState<{ index: number; source: SegmentSource | null } | null>(null);
  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const chartInstanceRef = useRef<echarts.ECharts | null>(null);

  const hasDensityBuckets = Boolean(analysis?.density_buckets && analysis.density_buckets.length > 0);
  const rawDensityBuckets = useMemo(() => analysis?.density_buckets ?? [], [analysis?.density_buckets]);

  const start = analysis
    ? (hasDensityBuckets ? rawDensityBuckets[0].start_id : Math.min(analysis.database_min_id ?? analysis.start_id, analysis.start_id))
    : 0;
  const end = analysis
    ? (hasDensityBuckets ? rawDensityBuckets[rawDensityBuckets.length - 1].end_id : Math.max(analysis.database_max_id ?? analysis.end_id, analysis.end_id))
    : 1;

  const span = Math.max(1, end - start + 1);

  // Preserve ID positions while combining high-resolution API buckets into
  // the mock's readable 72-column plot. Never synthesize variation in estimates.
  const densityBuckets = useMemo(() => {
    if (!hasDensityBuckets) return [];
    const visible = rawDensityBuckets.filter((bucket) => bucket.end_id >= start && bucket.start_id <= end);
    const resolution = Math.min(72, visible.length, span);
    return Array.from({ length: resolution }, (_, index): MPSDensityBucket => {
      const first = start + Math.floor(index * span / resolution);
      const last = start + Math.floor((index + 1) * span / resolution) - 1;
      const result: MPSDensityBucket = {
        start_id: first, end_id: last, missing_count: 0, invalid_count: 0,
        existing_count: 0, candidate_count: 0, is_exact: true,
      };
      for (const bucket of visible) {
        const overlap = Math.max(0, Math.min(last, bucket.end_id) - Math.max(first, bucket.start_id) + 1);
        if (!overlap) continue;
        const fraction = overlap / (bucket.end_id - bucket.start_id + 1);
        for (const key of ['missing_count', 'invalid_count', 'existing_count', 'candidate_count'] as const) {
          result[key] = (result[key] ?? 0) + (bucket[key] ?? 0) * fraction;
        }
        // Redistributing a bucket across display boundaries is also an estimate.
        result.is_exact = result.is_exact && bucket.is_exact && fraction === 1;
      }
      return result;
    });
  }, [hasDensityBuckets, rawDensityBuckets, start, end, span]);

  // Fallback 72 buckets if no density_buckets
  const ranges = useMemo(() => analysis?.candidate_ranges_preview ?? analysis?.missing_ranges ?? [], [analysis?.candidate_ranges_preview, analysis?.missing_ranges]);
  const fallbackBuckets = useMemo(() => {
    if (hasDensityBuckets) return [];
    return Array.from({ length: 72 }, (_, index) => {
      const first = start + (index * span) / 72;
      const last = start + ((index + 1) * span) / 72;
      const count = ranges.reduce(
        (total, range) =>
          total +
          (Math.max(0, Math.min(last, range.end_id + 1) - Math.max(first, range.start_id)) * range.count) /
            Math.max(1, range.end_id - range.start_id + 1),
        0,
      );
      return { first, last, count };
    });
  }, [hasDensityBuckets, start, span, ranges]);

  const peak = useMemo(() => {
    if (hasDensityBuckets) {
      return Math.max(1, ...densityBuckets.map((b) => (b.missing_count ?? 0) + (b.invalid_count ?? 0) + (b.existing_count ?? 0)));
    }
    return Math.max(1, ...fallbackBuckets.map((b) => b.count));
  }, [hasDensityBuckets, densityBuckets, fallbackBuckets]);

  const echartsOption = useMemo<echarts.EChartsOption | null>(() => {
    if (!analysis) return null;

    if (hasDensityBuckets) {
      const categories = densityBuckets.map((_, index) => String(index));
      const slotSeries = [0, 1, 2].map((slotIndex) => ({
        name: `slot-${slotIndex}`,
        type: 'bar' as const,
        stack: 'id-space',
        barWidth: '88%',
        barCategoryGap: '12%',
        silent: true,
        animationDuration: 220,
        animationDurationUpdate: 160,
        data: densityBuckets.map((bucket, bucketIndex) => {
          const ordered = [
            { key: 'missing' as const, count: bucket.missing_count ?? 0 },
            { key: 'invalid' as const, count: bucket.invalid_count ?? 0 },
            { key: 'existing' as const, count: bucket.existing_count ?? 0 },
          ]
            .filter((seg) => seg.count > 0)
            .sort((a, b) => a.count - b.count);

          const segment = ordered[slotIndex];
          if (!segment) {
            return { value: 0, itemStyle: { opacity: 0 } };
          }
          const isActiveSource = sources[segment.key];
          const isHoveredBucket = hover?.index === bucketIndex;
          const isHoveredSegment = isHoveredBucket && hover?.source === segment.key;
          const isEstimated = !bucket.is_exact;
          const baseColor = SEGMENT_COLORS[segment.key];
          const opacity = isActiveSource
            ? isHoveredSegment
              ? 1
              : isHoveredBucket
                ? 0.92
                : isEstimated
                  ? 0.78
                  : 0.9
            : 0.16;

          return {
            value: segment.count,
            itemStyle: {
              color: baseColor,
              opacity,
              borderColor: isHoveredSegment ? '#f4f4f2' : isHoveredBucket ? 'rgba(244, 244, 242, 0.45)' : 'transparent',
              borderWidth: isHoveredSegment ? 1.5 : isHoveredBucket ? 1 : 0,
              borderRadius: slotIndex === ordered.length - 1 ? [2, 2, 0, 0] : [0, 0, 0, 0],
              decal: isEstimated
                ? {
                    symbol: 'rect',
                    dashArrayX: [1, 0],
                    dashArrayY: [2, 2],
                    rotation: -Math.PI / 4,
                    color: 'rgba(15, 20, 22, 0.36)',
                  }
                : undefined,
            },
          };
        }),
      }));

      return {
        animation: true,
        grid: {
          left: 0,
          right: 0,
          top: 0,
          bottom: 0,
          containLabel: false,
        },
        xAxis: {
          type: 'category',
          data: categories,
          show: false,
        },
        yAxis: {
          type: 'value',
          min: 0,
          max: peak,
          interval: peak / 4,
          axisLabel: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
          splitLine: {
            show: true,
            lineStyle: {
              color: '#303637',
              width: 1,
              type: 'solid',
            },
          },
        },
        series: slotSeries,
      };
    }

    const categories = fallbackBuckets.map((_, index) => String(index));
    return {
      animation: true,
      grid: {
        left: 0,
        right: 0,
        top: 0,
        bottom: 0,
        containLabel: false,
      },
      xAxis: {
        type: 'category',
        data: categories,
        show: false,
      },
      yAxis: {
        type: 'value',
        min: 0,
        max: peak,
        interval: peak / 4,
        axisLabel: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: {
          show: true,
          lineStyle: {
            color: '#303637',
            width: 1,
            type: 'solid',
          },
        },
      },
      series: [
        {
          name: 'candidates',
          type: 'bar',
          barWidth: '88%',
          barCategoryGap: '12%',
          silent: true,
          animationDuration: 220,
          animationDurationUpdate: 160,
          data: fallbackBuckets.map((bucket, bucketIndex) => {
            const isHovered = hover?.index === bucketIndex;
            return {
              value: bucket.count,
              itemStyle: {
                color: isHovered
                  ? '#38c7e0'
                  : new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                      { offset: 0, color: '#24aac3' },
                      { offset: 1, color: 'rgba(36, 170, 195, 0.72)' },
                    ]),
                borderColor: isHovered ? '#f4f4f2' : 'transparent',
                borderWidth: isHovered ? 1 : 0,
                borderRadius: [2, 2, 0, 0],
              },
            };
          }),
        },
      ],
    };
  }, [analysis, hasDensityBuckets, densityBuckets, fallbackBuckets, peak, sources, hover]);

  useEffect(() => {
    const container = chartContainerRef.current;
    if (!container || !analysis) return;

    const probeCanvas = document.createElement('canvas');
    let has2dContext = false;
    try {
      has2dContext = Boolean(probeCanvas.getContext('2d'));
    } catch {
      has2dContext = false;
    }
    if (!has2dContext) return;

    const chart = echarts.init(container, undefined, { renderer: 'canvas' });
    chartInstanceRef.current = chart;

    const handleResize = () => {
      chart.resize();
    };
    let observer: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(handleResize);
      observer.observe(container);
    } else {
      window.addEventListener('resize', handleResize);
    }

    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', handleResize);
      try {
        chart.dispose();
      } catch {
        // Ignore dispose errors in headless test environments
      }
      chartInstanceRef.current = null;
    };
  }, [analysis]);

  useEffect(() => {
    const chart = chartInstanceRef.current;
    if (!chart || !echartsOption) return;
    chart.setOption(echartsOption, { notMerge: true });
  }, [echartsOption]);

  const formatTick = (value: number) => new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
  const intervalWidth = Math.ceil(span / (hasDensityBuckets ? Math.max(1, densityBuckets.length) : 72));

  const hoveredBucket = hover ? densityBuckets[hover.index] : undefined;
  const hoveredFallback = hover ? fallbackBuckets[hover.index] : undefined;
  const sourceRows = [
    { key: 'missing' as const, label: 'Missing', count: hoveredBucket?.missing_count ?? 0 },
    { key: 'invalid' as const, label: 'Invalid', count: hoveredBucket?.invalid_count ?? 0 },
    { key: 'existing' as const, label: 'Existing', count: hoveredBucket?.existing_count ?? 0 },
  ];

  return (
    <section className="mps-id-map" aria-label="Provider ID-space map">
      <header>
        <div className="mps-design-sites" role="radiogroup" aria-label="Site">
          {['OnlyFans', 'Fansly', 'LoyalFans'].map((value) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={site === value}
              className={site === value ? 'active' : ''}
              onClick={() => onSiteChange(value)}
            >
              {value}
            </button>
          ))}
        </div>
        <div className="mps-map-actions">
          <span>Viewing {analysis ? `${start.toLocaleString()} – ${end.toLocaleString()}` : 'ID space…'}</span>
        </div>
      </header>

      <div className="mps-design-canvas">
        {analysis && (
          <div className="mps-id-map-legend" aria-label="Profile classifications">
            <span className="legend-item"><span className="legend-color seg-missing" /> Missing</span>
            <span className="legend-item"><span className="legend-color seg-invalid" /> Invalid</span>
            <span className="legend-item"><span className="legend-color seg-existing" /> Existing</span>
            {densityBuckets.some((bucket) => !bucket.is_exact) && (
              <span className="legend-item"><span className="legend-color estimated-hatch" /> Estimated</span>
            )}
          </div>
        )}

        <div className="mps-id-map-y-title">
          <span>{hasDensityBuckets ? 'Profiles per ID interval (stacked)' : 'Candidate IDs per ID interval'}</span>
          {analysis && <span className="mps-id-map-help">
            <button type="button" aria-label="How to read this chart" aria-describedby="mps-chart-help">ⓘ</button>
            <span role="tooltip" id="mps-chart-help">
              Each bar covers about {intervalWidth.toLocaleString()} IDs. Segments are stacked, with the largest count on top. Compare each colour’s thickness. Faded colours are excluded from the run.
              <br /><br />
              Hover a coloured segment to see its profile count.
              {hasDensityBuckets
                ? analysis.density_is_exact
                  ? ' Full Analysis shows exact ID-space candidate density.'
                  : ' Quick analysis shows estimated density; Full Analyze resolves exact counts.'
                : ' Bars show candidate range preview coverage; unshown areas are unknown.'}
            </span>
          </span>}
        </div>
        <div className="mps-id-map-coordinate-system">
          <div className="mps-id-map-y-axis" aria-label="Profile count scale">
            {analysis && [1, 0.75, 0.5, 0.25, 0].map((tick) => (
              <span key={tick} style={{ top: `${(1 - tick) * 100}%` }} title={Math.round(peak * tick).toLocaleString()}>{formatTick(peak * tick)}</span>
            ))}
          </div>
          <div className="mps-id-map-chart">
        <div
          className={`mps-id-map-plot ${hasDensityBuckets ? 'density-mode' : ''} ${analysis ? 'echarts-active' : 'pending'}`}
          role="group"
          aria-label="Profile counts by provider ID interval"
          onPointerLeave={() => setHover(null)}
        >
          {!analysis && (
            <div className="mps-id-map-grid" aria-hidden="true">
              {[0, 0.25, 0.5, 0.75, 1].map((tick) => <span key={tick} style={{ top: `${tick * 100}%` }} />)}
            </div>
          )}
          {analysis && (
            <div
              ref={chartContainerRef}
              className="mps-id-map-echart-surface"
              data-testid="mps-echart-surface"
              aria-hidden="true"
            />
          )}
          {analysis ? (
            <>
              {hasDensityBuckets
                ? densityBuckets.map((bucket, index) => {
                    const candCount = bucket.candidate_count ?? 0;
                    const missing = bucket.missing_count ?? 0;
                    const invalid = bucket.invalid_count ?? 0;
                    const existing = bucket.existing_count ?? 0;
                    const total = missing + invalid + existing;
                    const isEstimated = !bucket.is_exact;

                    const tooltip = [
                      `${bucket.start_id.toLocaleString()} – ${bucket.end_id.toLocaleString()}`,
                      isEstimated ? 'Estimated (uninspected span)' : 'Exact',
                      `Candidates: ${Math.round(candCount).toLocaleString()}`,
                      `Missing: ${Math.round(missing).toLocaleString()} · Invalid: ${Math.round(invalid).toLocaleString()} · Existing: ${Math.round(existing).toLocaleString()}`,
                    ].join('\n');

                    return (
                      <div
                        key={`${bucket.start_id}-${bucket.end_id}-${index}`}
                        aria-label={tooltip}
                        onPointerEnter={() => setHover({ index, source: null })}
                        className={`mps-id-map-bar ${isEstimated ? 'estimated' : ''}`}
                      >
                        <i style={{ height: `${total / peak * 100}%` }}>
                          {[
                            { key: 'missing' as const, label: 'Missing', count: missing },
                            { key: 'invalid' as const, label: 'Invalid', count: invalid },
                            { key: 'existing' as const, label: 'Existing', count: existing },
                          ].filter((segment) => segment.count > 0).sort((a, b) => a.count - b.count).map((segment) => (
                            <span key={segment.key}
                              className={`seg-${segment.key} ${sources[segment.key] ? '' : 'off'}`}
                              style={{ height: `${segment.count / total * 100}%` }}
                              role="img" tabIndex={0}
                              aria-label={`${segment.label}: ${Math.round(segment.count).toLocaleString()} profiles${isEstimated ? ' (estimated)' : ''}`}
                              aria-describedby={hover?.index === index ? 'mps-bar-tooltip' : undefined}
                              onPointerEnter={() => setHover({ index, source: segment.key })}
                              onFocus={() => setHover({ index, source: segment.key })}
                              onBlur={() => setHover(null)}
                            />
                          ))}
                        </i>
                      </div>
                    );
                  })
                : fallbackBuckets.map((bucket, index) => (
                    <div
                      key={index}
                      aria-label={`${Math.ceil(bucket.first).toLocaleString()}–${(Math.ceil(bucket.last) - 1).toLocaleString()}: ${bucket.count ? `about ${Math.round(bucket.count).toLocaleString()} candidate IDs in preview` : 'no preview coverage'}`}
                      className="mps-id-map-bar"
                      onPointerEnter={() => setHover({ index, source: null })}
                    >
                      <i style={{ height: `${(bucket.count / peak) * 100}%` }} role="img" tabIndex={0}
                        aria-label={`Candidates: ${Math.round(bucket.count).toLocaleString()} in preview`}
                        onFocus={() => setHover({ index, source: null })} onBlur={() => setHover(null)} />
                    </div>
                  ))}

            </>
          ) : (
            <p>{loading ? 'Analyzing ID space…' : 'Waiting for quick analysis…'}</p>
          )}
          {hover && (hoveredBucket || hoveredFallback) && (
            <div className="mps-id-map-tooltip" role="tooltip" id="mps-bar-tooltip">
              <div className="mps-id-map-tooltip-range">
                IDs {Math.ceil(hoveredBucket?.start_id ?? hoveredFallback!.first).toLocaleString()} – {Math.floor(hoveredBucket?.end_id ?? (Math.ceil(hoveredFallback!.last) - 1)).toLocaleString()}
              </div>
              {hoveredBucket ? sourceRows.map((row) => (
                <div key={row.key} className={`mps-id-map-tooltip-row ${hover.source === row.key ? 'active' : ''}`}>
                  <span className={`mps-id-map-tooltip-swatch seg-${row.key}`} />
                  <span>{row.label}{sources[row.key] ? '' : ' (excluded)'}</span>
                  <strong>{!hoveredBucket.is_exact && row.count === 0 ? 'Not resolved' : Math.round(row.count).toLocaleString()}</strong>
                </div>
              )) : <div className="mps-id-map-tooltip-row"><span>Candidates in preview</span><strong>{Math.round(hoveredFallback!.count).toLocaleString()}</strong></div>}
              <small>{hoveredBucket?.is_exact ? 'Exact counts' : 'Estimated counts'}</small>
            </div>
          )}
        </div>

        <div className="mps-id-map-axis" aria-hidden="true">
          {analysis &&
            [0, 0.25, 0.5, 0.75, 1].map((tick) => (
              <span key={tick} title={Math.round(start + tick * (end - start)).toLocaleString()}>{formatTick(start + tick * (end - start))}</span>
            ))}
        </div>
        <div className="mps-id-map-x-title">Provider profile ID</div>
          </div>
        </div>
      </div>

    </section>
  );
}
