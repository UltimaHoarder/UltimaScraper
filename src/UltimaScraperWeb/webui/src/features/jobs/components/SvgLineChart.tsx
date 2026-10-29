import { memo, useMemo, useState, useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import {
  MAX_CHART_LINE_GAP_MS,
  formatChartClock,
  type ChartMarker,
  type ChartSeries,
} from '../lib/diagnosticsChartUtils';

interface SvgLineChartProps {
  title: string;
  subtitle?: string;
  series: ChartSeries[];
  chartId: string;
  chartGroup: string;
  expandedChartId: string | null;
  expandedChartGroup: string | null;
  onToggleExpand: (chartId: string, chartGroup: string) => void;
  referenceLine?: {
    value: number;
    label: string;
    color: string;
  };
  referenceLines?: Array<{
    value: number;
    label: string;
    color: string;
  }>;
  unit?: string;
  yAxisFormatter?: (val: number) => string;
  timestamps: number[];
  sampleIntervalMs?: number[];
  /** Longest gap between points still drawn as a connected line. */
  maxLineGapMs?: number;
  timeDomain: [number, number];
  timeMarkers?: ChartMarker[];
  timeScaleMode?: 'live' | 'full';
  totalDurationFormatted?: string;
  emptyMessage?: string;
}

const FALLBACK_VARS: Record<string, string> = {
  '--jdr-chart-primary': '#24aac3',
  '--jdr-chart-secondary': '#f4f4f2',
  '--jdr-chart-latency': '#24aac3',
  '--jdr-chart-tail': '#f4f4f2',
  '--jdr-chart-success': '#24aac3',
  '--jdr-chart-warning': '#ffd303',
  '--jdr-chart-error': '#ff0037',
  '--jdr-chart-not-found': '#bec8c9',
  '--jdr-chart-timeout': '#ffd303',
  '--jdr-chart-capacity': '#f4f4f2',
  '--jdr-chart-axis': '#9caeaf',
  '--jdr-chart-grid': '#343a3b',
  '--jdr-chart-bg': '#1a1f20',
};

function resolveColor(cssVar: string): string {
  if (!cssVar) return '#24aac3';
  if (!cssVar.startsWith('var(')) return cssVar;
  const varNameMatch = cssVar.match(/var\(\s*(--[^,\s)]+)/);
  const varName = varNameMatch?.[1];
  if (
    varName &&
    typeof document !== 'undefined' &&
    typeof window !== 'undefined' &&
    typeof window.getComputedStyle === 'function'
  ) {
    const container = document.querySelector<HTMLElement>('.jdr-container') ?? document.documentElement;
    const computed = window.getComputedStyle(container).getPropertyValue(varName).trim();
    if (computed) return computed;
  }
  if (varName && FALLBACK_VARS[varName]) {
    return FALLBACK_VARS[varName];
  }
  const match = cssVar.match(/,\s*([^)]+)\)/);
  if (match) return match[1].trim();
  return '#24aac3';
}

function resolveRgba(color: string, alpha: number): string {
  const resolved = resolveColor(color);
  if (resolved.startsWith('#') && resolved.length >= 7) {
    const r = parseInt(resolved.slice(1, 3), 16) || 0;
    const g = parseInt(resolved.slice(3, 5), 16) || 0;
    const b = parseInt(resolved.slice(5, 7), 16) || 0;
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  if (resolved.startsWith('rgb(')) {
    return resolved.replace('rgb(', 'rgba(').replace(')', `, ${alpha})`);
  }
  return resolved;
}

/**
 * High-performance line chart component powered by Apache ECharts.
 * Supports dual-axis scaling, gap-tolerant time series, responsive dataZoom,
 * and reference markers for route ceilings and MPS refills.
 */
export const SvgLineChart = memo(function SvgLineChart({
  title,
  subtitle,
  series,
  chartId,
  chartGroup,
  expandedChartId,
  expandedChartGroup,
  onToggleExpand,
  referenceLine,
  referenceLines: suppliedReferenceLines,
  unit = '',
  yAxisFormatter,
  timestamps,
  sampleIntervalMs,
  maxLineGapMs = MAX_CHART_LINE_GAP_MS,
  timeDomain,
  timeMarkers = [],
  timeScaleMode = 'live',
  totalDurationFormatted,
  emptyMessage = 'Waiting for a second timestamped observation...',
}: SvgLineChartProps) {
  const isExpanded = expandedChartId === chartId;
  const isHidden = expandedChartGroup === chartGroup && !isExpanded;
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartInstanceRef = useRef<echarts.EChartsType | null>(null);

  const referenceLines = useMemo(
    () => suppliedReferenceLines ?? (referenceLine ? [referenceLine] : []),
    [referenceLine, suppliedReferenceLines],
  );

  const chartWidth = 480;
  const chartHeight = isExpanded ? 400 : 148;
  const padLeft = 52;
  const padBottom = 26;
  const padTop = 16;
  const padRight = 16;

  const plotWidth = chartWidth - padLeft - padRight;
  const plotHeight = chartHeight - padTop - padBottom;
  const [domainStart, domainEnd] = timeDomain;
  const domainSpan = Math.max(1, domainEnd - domainStart);
  const xForTime = (timestamp: number) =>
    padLeft + ((timestamp - domainStart) / domainSpan) * plotWidth;

  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  // Compute overall min and max across all series and reference lines
  const { minVal, maxVal, maxDataLength } = useMemo(() => {
    let min = 0;
    let max = 1;
    let hasData = false;
    let maxLen = 0;

    for (const s of series) {
      maxLen = Math.max(maxLen, s.values.length);
      s.values.forEach((v, idx) => {
        const timestamp = timestamps[idx];
        if (
          v !== null && !isNaN(v) && isFinite(v) && Number.isFinite(timestamp) &&
          timestamp >= domainStart && timestamp <= domainEnd
        ) {
          min = Math.min(min, v);
          max = Math.max(max, v);
          hasData = true;
        }
      });
    }

    referenceLines.forEach((line) => {
      max = Math.max(max, line.value);
    });

    if (!hasData) {
      max = 10;
    } else if (max === min) {
      max = min + 10;
    } else {
      const rawMax = max * 1.12;
      const magnitude = Math.pow(10, Math.floor(Math.log10(Math.max(1, rawMax))));
      const step = magnitude / 2;
      max = Math.ceil(rawMax / step) * step;
    }

    return { minVal: min, maxVal: max, maxDataLength: maxLen };
  }, [domainEnd, domainStart, referenceLines, series, timestamps]);

  const ySpan = maxVal - minVal || 1;

  const referenceLineLabelYs = useMemo(() => {
    const labelGap = 10;
    const topLimit = padTop + 8;
    const bottomLimit = padTop + plotHeight - 2;
    const sortedLines = referenceLines
      .map((line, index) => ({
        index,
        y: padTop + plotHeight - ((line.value - minVal) / ySpan) * plotHeight,
      }))
      .sort((left, right) => left.y - right.y);
    const labelYs = new Array<number>(referenceLines.length);

    sortedLines.forEach((line, index) => {
      labelYs[line.index] = Math.max(
        line.y - 4,
        index === 0 ? topLimit : labelYs[sortedLines[index - 1].index] + labelGap,
      );
    });

    const lastLabelY = sortedLines.length > 0
      ? labelYs[sortedLines[sortedLines.length - 1].index]
      : bottomLimit;
    const overflow = Math.max(0, lastLabelY - bottomLimit);
    if (overflow > 0) {
      labelYs.forEach((labelY, index) => {
        labelYs[index] = labelY - overflow;
      });
    }

    const topOverflow = Math.max(0, topLimit - (labelYs[sortedLines[0]?.index] ?? topLimit));
    if (topOverflow > 0) {
      labelYs.forEach((labelY, index) => {
        labelYs[index] = labelY + topOverflow;
      });
    }
    return labelYs;
  }, [minVal, padTop, plotHeight, referenceLines, ySpan]);

  const hasAnyData = series.some((s) =>
    s.values.some((value, idx) =>
      value !== null && Number.isFinite(value) && Number.isFinite(timestamps[idx]) &&
      timestamps[idx] >= domainStart && timestamps[idx] <= domainEnd,
    ),
  );

  // Build ECharts option
  const echartsOption = useMemo<echarts.EChartsOption | null>(() => {
    if (!hasAnyData) return null;

    const axisColor = resolveColor('var(--jdr-chart-axis, #9caeaf)');
    const gridColor = resolveColor('var(--jdr-chart-grid, #343a3b)');
    const primaryAccent = resolveColor('var(--jdr-chart-primary, #24aac3)');

    const formatY = (v: number) => {
      if (yAxisFormatter) return yAxisFormatter(v);
      if (v >= 1000) return `${(v / 1000).toFixed(1)}k`;
      return `${Math.round(v)}${unit}`;
    };

    // Build series data with gap tolerance
    const eSeries: echarts.LineSeriesOption[] = series.map((s) => {
      const data: Array<[number, number | null]> = [];
      let previousTimestamp: number | null = null;

      s.values.forEach((value, idx) => {
        const timestamp = timestamps[idx];
        if (
          !Number.isFinite(timestamp) ||
          timestamp < domainStart ||
          timestamp > domainEnd
        ) {
          return;
        }

        // Connect only close observations; leave long intervals blank
        if (previousTimestamp !== null && timestamp - previousTimestamp > maxLineGapMs) {
          data.push([timestamp - 1, null]);
        }

        const validVal = value !== null && Number.isFinite(value) ? value : null;
        data.push([timestamp, validVal]);
        previousTimestamp = timestamp;
      });

      const color = resolveColor(s.color);
      const isPrimaryArea =
        !s.isDashed &&
        (s.name.includes('Throughput') ||
          s.name.includes('Tasks/sec') ||
          s.name.includes('Items/sec') ||
          s.name.includes('Inflight') ||
          s.name.includes('Errors'));

      return {
        name: s.name,
        type: 'line',
        data,
        connectNulls: false,
        smooth: false,
        showSymbol: data.length <= 45,
        symbol: 'circle',
        symbolSize: isExpanded ? 4 : 3,
        lineStyle: {
          color,
          width: s.strokeWidth ?? 1.8,
          type: s.isDashed ? 'dashed' : 'solid',
        },
        itemStyle: { color },
        areaStyle: isPrimaryArea
          ? {
              color: {
                type: 'linear',
                x: 0,
                y: 0,
                x2: 0,
                y2: 1,
                colorStops: [
                  { offset: 0, color: resolveRgba(color, 0.2) },
                  { offset: 0.9, color: resolveRgba(color, 0.02) },
                  { offset: 1, color: 'transparent' },
                ],
              },
            }
          : undefined,
      };
    });

    // Reference lines & refill markers on first series
    const markLineData: Array<{
      yAxis?: number;
      xAxis?: number;
      name?: string;
      lineStyle?: { color: string; type: 'dashed' | 'dotted' | 'solid'; width: number };
      label?: {
        formatter: string;
        color: string;
        fontSize: number;
        fontFamily: string;
        position: string;
        backgroundColor?: string;
        padding?: [number, number];
      };
    }> = [];

    referenceLines.forEach((line) => {
      const lineColor = resolveColor(line.color);
      markLineData.push({
        yAxis: line.value,
        name: line.label,
        lineStyle: { color: lineColor, type: 'dashed', width: 1.2 },
        label: {
          formatter: `${line.label} (${line.value})`,
          color: lineColor,
          fontSize: 9,
          fontFamily: 'monospace',
          position: 'insideEndTop',
          backgroundColor: 'rgba(26, 31, 32, 0.85)',
          padding: [2, 4],
        },
      });
    });

    timeMarkers.forEach((marker) => {
      if (marker.timestamp >= domainStart && marker.timestamp <= domainEnd) {
        const markerColor = resolveColor(marker.color);
        markLineData.push({
          xAxis: marker.timestamp,
          name: marker.label,
          lineStyle: { color: markerColor, type: 'dotted', width: 1.2 },
          label: {
            formatter: isExpanded ? `${marker.label} · ${formatChartClock(marker.timestamp)}` : marker.label,
            color: markerColor,
            fontSize: 8,
            fontFamily: 'monospace',
            position: 'insideStartTop',
          },
        });
      }
    });

    if (eSeries[0] && markLineData.length > 0) {
      (eSeries[0] as unknown as { markLine: unknown }).markLine = {
        silent: true,
        symbol: ['none', 'none'],
        data: markLineData,
      };
    }

    return {
      backgroundColor: 'transparent',
      animation: false,
      grid: {
        left: padLeft,
        right: padRight,
        top: padTop,
        bottom: isExpanded ? 54 : 26,
        containLabel: false,
      },
      xAxis: {
        type: 'time',
        min: domainStart,
        max: domainEnd,
        splitNumber: isExpanded ? 6 : 3,
        axisLine: { lineStyle: { color: gridColor } },
        axisTick: { show: true, lineStyle: { color: gridColor } },
        splitLine: { show: false },
        axisLabel: {
          color: axisColor,
          fontSize: 9,
          fontFamily: 'monospace',
          hideOverlap: true,
          showMinLabel: true,
          showMaxLabel: true,
          alignMinLabel: 'left',
          alignMaxLabel: 'right',
          formatter: (val: number) => {
            if (timeScaleMode === 'full') {
              if (Math.abs(val - domainStart) <= Math.max(1500, domainSpan * 0.03)) {
                return `T₀ ${formatChartClock(domainStart)}`;
              }
              if (Math.abs(domainEnd - val) <= Math.max(1500, domainSpan * 0.03)) {
                return `T_complete (${totalDurationFormatted || formatChartClock(domainEnd)})`;
              }
              return formatChartClock(val);
            } else {
              const nowDiffSec = Math.round((domainEnd - val) / 1000);
              if (nowDiffSec <= 5) return 'Now';
              if (Math.abs(nowDiffSec - 90) <= 10) return '-90s';
              if (Math.abs(nowDiffSec - 180) <= 10) return '-3m';
              return formatChartClock(val);
            }
          },
        },
      },
      yAxis: {
        type: 'value',
        min: minVal,
        max: maxVal,
        splitNumber: isExpanded ? 5 : 3,
        splitLine: { lineStyle: { color: gridColor, type: 'dashed', opacity: 0.55 } },
        axisLine: { show: false },
        axisLabel: {
          color: axisColor,
          fontSize: 9,
          fontFamily: 'monospace',
          hideOverlap: true,
          formatter: (val: number) => formatY(val),
        },
      },
      dataZoom: isExpanded
        ? [
            { type: 'inside' },
            {
              type: 'slider',
              height: 18,
              bottom: 6,
              borderColor: gridColor,
              backgroundColor: '#202526',
              fillerColor: resolveRgba(primaryAccent, 0.16),
              dataBackground: {
                lineStyle: { color: axisColor, opacity: 0.45 },
                areaStyle: { color: gridColor, opacity: 0.35 },
              },
              selectedDataBackground: {
                lineStyle: { color: primaryAccent },
                areaStyle: { color: primaryAccent, opacity: 0.2 },
              },
              handleStyle: { color: primaryAccent, borderColor: primaryAccent },
              moveHandleStyle: { color: primaryAccent },
              textStyle: { color: axisColor, fontSize: 9, fontFamily: 'monospace' },
            },
          ]
        : [],
      series: eSeries,
    };
  }, [
    domainEnd,
    domainSpan,
    domainStart,
    hasAnyData,
    isExpanded,
    maxLineGapMs,
    maxVal,
    minVal,
    padLeft,
    padRight,
    padTop,
    referenceLines,
    series,
    timeMarkers,
    timeScaleMode,
    timestamps,
    totalDurationFormatted,
    unit,
    yAxisFormatter,
  ]);

  // ECharts lifecycle management
  useEffect(() => {
    const container = chartContainerRef.current;
    if (!container || !hasAnyData) return;

    const chart = echarts.init(container, undefined, {
      renderer: 'canvas',
    });
    chartInstanceRef.current = chart;

    const resizeObserver =
      typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(() => {
            chart.resize();
          })
        : null;

    if (resizeObserver) {
      resizeObserver.observe(container);
    }

    return () => {
      resizeObserver?.disconnect();
      chart.dispose();
      chartInstanceRef.current = null;
    };
  }, [hasAnyData]);

  useEffect(() => {
    const chart = chartInstanceRef.current;
    if (!chart || !echartsOption) return;
    chart.setOption(echartsOption, { notMerge: true, lazyUpdate: true });
    chart.resize();
  }, [echartsOption, isExpanded]);

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (maxDataLength === 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = e.clientX - rect.left;
    const svgX = (relX / rect.width) * chartWidth;
    if (svgX < padLeft || svgX > chartWidth - padRight) {
      setHoverIdx(null);
      return;
    }
    const targetTime = domainStart + ((svgX - padLeft) / plotWidth) * domainSpan;
    let nearestIdx = -1;
    let nearestDistance = Number.POSITIVE_INFINITY;
    timestamps.forEach((timestamp, idx) => {
      if (timestamp < domainStart || timestamp > domainEnd) return;
      const distance = Math.abs(timestamp - targetTime);
      if (distance < nearestDistance) {
        nearestIdx = idx;
        nearestDistance = distance;
      }
    });
    setHoverIdx(nearestIdx >= 0 ? nearestIdx : null);
  };

  const handleMouseLeave = () => {
    setHoverIdx(null);
  };

  const hoverTimestamp = hoverIdx === null ? null : timestamps[hoverIdx];
  const hoverX =
    hoverTimestamp !== null && Number.isFinite(hoverTimestamp)
      ? xForTime(hoverTimestamp)
      : null;

  return (
    <div
      className={`jdr-chart-card${isExpanded ? ' is-expanded' : ''}`}
      hidden={isHidden}
    >
      <div className="jdr-chart-header">
        <div className="jdr-chart-title-area">
          <h3>{title}</h3>
          {subtitle && <p>{subtitle}</p>}
        </div>
        <div className="jdr-chart-legend">
          {series.map((s) => (
            <span key={s.name} className="jdr-legend-item">
              <i
                className="jdr-legend-dot"
                style={{ backgroundColor: s.color }}
              />
              {s.name}
            </span>
          ))}
          {timeMarkers.length > 0 && (
            <span className="jdr-legend-item">
              <i
                className="jdr-legend-dot"
                style={{ backgroundColor: 'var(--jdr-chart-warning, #d29922)' }}
              />
              MPS refill events
            </span>
          )}
          {referenceLines.map((line) => (
            <span key={`${line.label}-${line.value}`} className="jdr-legend-item">
              <i
                className="jdr-legend-dot"
                style={{ backgroundColor: line.color, borderRadius: 0 }}
              />
              {line.label}
            </span>
          ))}
        </div>
      </div>
      <button
        type="button"
        className="jdr-chart-expand"
        aria-label={`${isExpanded ? 'Collapse' : 'Expand'} ${title}`}
        aria-expanded={isExpanded}
        aria-controls={`${chartId}-plot`}
        title={`${isExpanded ? 'Collapse' : 'Expand'} ${title}`}
        onClick={() => onToggleExpand(chartId, chartGroup)}
      >
        <span aria-hidden="true">{isExpanded ? '↙' : '↗'}</span>
        {isExpanded ? 'Collapse' : 'Expand'}
      </button>

      <div className="jdr-chart-body" id={`${chartId}-plot`}>
        {!hasAnyData ? (
          <div className="jdr-chart-empty">{emptyMessage}</div>
        ) : (
          <>
            {/* Apache ECharts Container */}
            <div
              ref={chartContainerRef}
              className="jdr-echart-canvas"
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: '100%',
              }}
            />

            {/* Transparent Interactive Hover Layer & Accessible/Test Labels */}
            <svg
              className="jdr-svg-chart"
              viewBox={`0 0 ${chartWidth} ${chartHeight}`}
              preserveAspectRatio="none"
              onMouseMove={handleMouseMove}
              onMouseLeave={handleMouseLeave}
              data-testid="chart-svg"
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: isExpanded ? 'calc(100% - 28px)' : '100%',
                background: 'transparent',
              }}
            >
              {/* Visually hidden DOM labels for accessibility & unit test assertions */}
              <g style={{ opacity: 0, pointerEvents: 'none' }}>
                {referenceLines.map((line, index) => {
                  const normalized = (line.value - minVal) / ySpan;
                  const y = padTop + plotHeight - normalized * plotHeight;
                  return (
                    <text
                      key={`reference-${line.label}-${line.value}`}
                      x={chartWidth - padRight}
                      y={referenceLineLabelYs[index] ?? y - 4}
                      textAnchor="end"
                    >
                      {line.label} ({line.value})
                    </text>
                  );
                })}

                {timeScaleMode === 'full' ? (
                  <g className="jdr-x-axis-group">
                    <text x={padLeft} y={padTop + plotHeight + 15}>
                      T₀ {formatChartClock(domainStart)}
                    </text>
                    <text x={padLeft + plotWidth / 2} y={padTop + plotHeight + 15}>
                      50% · {formatChartClock(domainStart + domainSpan / 2)}
                    </text>
                    <text x={padLeft + plotWidth} y={padTop + plotHeight + 15}>
                      T_complete ({totalDurationFormatted || formatChartClock(domainEnd)})
                    </text>
                  </g>
                ) : (
                  <g className="jdr-x-axis-group">
                    <text x={padLeft} y={padTop + plotHeight + 15}>
                      -3m
                    </text>
                    <text x={padLeft + plotWidth / 2} y={padTop + plotHeight + 15}>
                      -90s
                    </text>
                    <text x={padLeft + plotWidth} y={padTop + plotHeight + 15}>
                      Now
                    </text>
                  </g>
                )}
              </g>

              {/* Reference Crosshair Line on Hover */}
              {hoverX !== null && (
                <line
                  x1={hoverX}
                  y1={padTop}
                  x2={hoverX}
                  y2={padTop + plotHeight}
                  className="jdr-crosshair-line"
                />
              )}
            </svg>

            {hoverX !== null && hoverIdx !== null && (
              <div
                className={`jdr-chart-tooltip ${
                  hoverX > chartWidth * 0.65 ? 'is-right' : 'is-left'
                }`}
                style={{
                  left: `${(hoverX / chartWidth) * 100}%`,
                }}
              >
                <div className="jdr-tooltip-header">
                  {hoverTimestamp !== null
                    ? formatChartClock(hoverTimestamp)
                    : `Sample #${hoverIdx + 1}`}
                  {timeScaleMode === 'full' && hoverTimestamp !== null && (
                    <span style={{ marginLeft: 6, opacity: 0.8 }}>
                      · {Math.round(((hoverTimestamp - domainStart) / domainSpan) * 100)}% progress
                    </span>
                  )}
                  {sampleIntervalMs?.[hoverIdx] != null && (
                    <span style={{ marginLeft: 6, opacity: 0.8 }}>
                      · rate over {(sampleIntervalMs[hoverIdx] / 1000).toFixed(1)}s
                    </span>
                  )}
                </div>
                {series.map((s) => {
                  const val = s.values[hoverIdx];
                  return (
                    <div key={s.name} className="jdr-tooltip-row">
                      <span
                        className="jdr-tooltip-dot"
                        style={{ backgroundColor: s.color }}
                      />
                      <span className="jdr-tooltip-name">{s.name}:</span>
                      <span className="jdr-tooltip-val">
                        {val !== undefined && val !== null ? `${val}${unit}` : '—'}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
});
