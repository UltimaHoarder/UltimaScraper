import { useContext, useEffect, useMemo, useRef, useState } from 'react';
import * as echarts from 'echarts';

import { CHART_COLORS } from './statisticsActivityModel';
import { StatisticsSettings } from './StatisticsSettings';
import { StatisticsChartSettingsContext } from './statisticsChartSettings';

const EMPTY_PARTIAL: boolean[] = [];
// A long bar series opens on its latest buckets, where the bars stay readable; Show all widens it.
const INITIAL_BARS = 36;

export interface ChartSeries {
  label: string;
  color: string;
  pointColors?: string[];
  values: Array<number | null>;
  kind?: 'line' | 'bar' | 'pie';
}

const FALLBACK_VARS: Record<string, string> = {
  '--color-accent-primary': '#24aac3',
  '--color-success': '#82d6b2',
  '--color-warning': '#ffd303',
  '--color-error': '#ff0037',
  '--color-text-primary': '#f4f4f2',
  '--color-text-secondary': '#bec8c9',
  '--color-text-tertiary': '#9caeaf',
  '--atlas-line': '#343a3b',
  '--color-bg-primary': '#1a1f20',
};

function resolveThemeColor(cssVar: string): string {
  if (!cssVar) return CHART_COLORS[0];
  if (!cssVar.startsWith('var(')) return cssVar;
  const varNameMatch = cssVar.match(/var\(\s*(--[^,\s)]+)/);
  const varName = varNameMatch?.[1];
  if (
    varName &&
    typeof document !== 'undefined' &&
    typeof window !== 'undefined' &&
    typeof window.getComputedStyle === 'function'
  ) {
    const computed = window.getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
    if (computed) return computed;
  }
  if (varName && FALLBACK_VARS[varName]) {
    return FALLBACK_VARS[varName];
  }
  const fallbackMatch = cssVar.match(/,\s*([^)]+)\)/);
  if (fallbackMatch) return fallbackMatch[1].trim();
  return CHART_COLORS[0];
}

function resolveRgba(color: string, alpha: number): string {
  const hex = resolveThemeColor(color);
  if (hex.startsWith('#') && hex.length >= 7) {
    const r = parseInt(hex.slice(1, 3), 16) || 0;
    const g = parseInt(hex.slice(3, 5), 16) || 0;
    const b = parseInt(hex.slice(5, 7), 16) || 0;
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  if (hex.startsWith('rgb(')) {
    return hex.replace('rgb(', 'rgba(').replace(')', `, ${alpha})`);
  }
  return hex;
}

/**
 * Interactive statistics chart powered by Apache ECharts.
 * Supports stacked & grouped bars, line & area overlays, pie/donut charts, partial bucket styling,
 * wheel zoom & drag pan, keyboard arrow inspection, and screen-reader readouts.
 */
export function StatisticsThreeChart({
  labels,
  series,
  label,
  kind = 'bar',
  stacked = false,
  partial = EMPTY_PARTIAL,
  formatAxisValue = (v) => v.toLocaleString(undefined, { notation: 'compact', maximumFractionDigits: 1 }),
  formatValue = (v) => v.toLocaleString(undefined, { maximumFractionDigits: 2 }),
  onSelect,
}: {
  labels: string[];
  series: ChartSeries[];
  label: string;
  kind?: 'line' | 'bar' | 'pie';
  stacked?: boolean;
  partial?: boolean[];
  formatAxisValue?: (value: number) => string;
  formatValue?: (value: number) => string;
  onSelect?: (index: number) => void;
}) {
  const echartContainerRef = useRef<HTMLDivElement>(null);
  const chartInstanceRef = useRef<echarts.EChartsType | null>(null);
  const plotRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ startX: number; startOffset: number; dragged: boolean } | null>(null);
  const settings = useContext(StatisticsChartSettingsContext);
  const [hidden, setHidden] = useState<string[]>([]);
  const selectionScope = `${label}:${labels[0]}:${labels.at(-1)}`;
  const [selection, setSelection] = useState<{ scope: string; value: number }>();
  const selected = selection?.scope === selectionScope ? selection.value : Math.max(0, labels.length - 1);
  const initialView = (length: number) => kind === 'bar' && length > INITIAL_BARS
    ? { zoom: length / INITIAL_BARS, offset: length - INITIAL_BARS }
    : { zoom: 1, offset: 0 };
  const [zoom, setZoom] = useState(() => initialView(labels.length).zoom);
  const [offset, setOffset] = useState(() => initialView(labels.length).offset);
  const [viewScope, setViewScope] = useState(selectionScope);
  if (viewScope !== selectionScope) {
    const next = initialView(labels.length);
    setViewScope(selectionScope);
    setZoom(next.zoom);
    setOffset(next.offset);
  }
  const [depth, setDepth] = useState(false);
  const isPie = kind === 'pie';

  const count = isPie ? Math.max(1, labels.length) : Math.max(1, Math.ceil(labels.length / zoom));
  const start = isPie ? 0 : Math.min(offset, Math.max(0, labels.length - count));
  const end = isPie ? labels.length : Math.min(labels.length, start + count);
  const index = Math.max(start, Math.min(selected, Math.max(start, end - 1)));
  const visible = useMemo(
    () => series.filter((item) => !hidden.includes(item.label)),
    [series, hidden],
  );
  const values = visible.flatMap((item) => item.values.slice(start, end).filter((v): v is number => v !== null));
  const sums = stacked
    ? labels.slice(start, end).map((_, i) =>
        visible
          .filter((s) => (s.kind ?? kind) === 'bar')
          .reduce((sum, s) => sum + (s.values[start + i] ?? 0), 0),
      )
    : [];
  const low = Math.min(0, ...values);
  const high = Math.max(1, ...values, ...sums);
  const selectedBars = visible.filter((item) => (item.kind ?? kind) === 'bar');
  const selectedValues = (selectedBars.length ? selectedBars : visible)
    .map((item) => item.values[index])
    .filter((value): value is number => value != null);
  const selectedAmount = selectedValues.length
    ? stacked && selectedBars.length
      ? selectedValues.reduce((sum, value) => sum + value, 0)
      : Math.max(...selectedValues)
    : null;
  const selectedLeft = 6.14 + ((index - start + 0.5) / Math.max(1, end - start)) * 87.72;
  const selectedHeight =
    selectedAmount === null
      ? 80.6
      : Math.max(0, Math.min(80.6, ((selectedAmount - low) / (high - low)) * 80.6));

  const peakInfo = useMemo(() => {
    if (isPie || start >= end) return null;
    let maxVal = -Infinity;
    let maxIdx = -1;
    for (let i = start; i < end; i++) {
      const val = stacked
        ? visible
            .filter((s) => (s.kind ?? kind) === 'bar')
            .reduce((sum, s) => sum + (s.values[i] ?? 0), 0)
        : Math.max(...visible.map((s) => s.values[i] ?? -Infinity));
      if (val > maxVal) {
        maxVal = val;
        maxIdx = i;
      }
    }
    if (maxIdx === -1 || maxVal <= 0) return null;
    return { index: maxIdx, value: maxVal };
  }, [isPie, start, end, stacked, visible, kind]);

  const echartsOption = useMemo<echarts.EChartsOption>(() => {
    const slicedLabels = labels.slice(start, end);
    const gridColor = resolveThemeColor('var(--atlas-line, #343a3b)');
    const primaryAccent = resolveThemeColor('var(--color-accent-primary, #24aac3)');
    const errorColor = resolveThemeColor('var(--color-error, #ff0037)');
    const surfaceBg = resolveThemeColor('var(--color-bg-primary, #1a1f20)');

    if (isPie) {
      const primarySeries = visible[0];
      const pieSlices = labels.map((sliceLabel, idx) => {
        const rawVal = primarySeries?.values[idx] ?? null;
        const isSliceHidden = !primarySeries || hidden.includes(sliceLabel);
        const val = isSliceHidden || rawVal === null || rawVal < 0 ? 0 : rawVal;
        const rawColor =
          primarySeries?.pointColors?.[idx] ??
          CHART_COLORS[idx % CHART_COLORS.length] ??
          primarySeries?.color ??
          primaryAccent;
        const resolvedColor = resolveThemeColor(rawColor);
        const isSelected = idx === index;
        return {
          name: sliceLabel,
          value: val,
          selected: depth && isSelected,
          itemStyle: {
            color: depth
              ? {
                  type: 'linear' as const,
                  x: 0,
                  y: 0,
                  x2: 1,
                  y2: 1,
                  colorStops: [
                    { offset: 0, color: resolvedColor },
                    { offset: 1, color: resolveRgba(resolvedColor, 0.72) },
                  ],
                }
              : resolvedColor,
            borderColor: isSelected ? '#f4f4f2' : surfaceBg,
            borderWidth: isSelected ? 2 : 2,
            shadowColor: depth || isSelected ? 'rgba(0, 0, 0, 0.55)' : undefined,
            shadowBlur: depth ? 12 : isSelected ? 8 : 0,
            shadowOffsetY: depth ? 4 : 0,
          },
        };
      });

      return {
        backgroundColor: 'transparent',
        animation: false,
        tooltip: {
          trigger: 'item',
          backgroundColor: 'rgba(18, 22, 23, 0.95)',
          borderColor: primaryAccent,
          borderWidth: 1,
          textStyle: {
            color: '#f4f4f2',
            fontSize: 11,
            fontFamily: 'monospace',
          },
          formatter: (params: unknown) => {
            const p = params as { name?: string; value?: number; percent?: number; marker?: string };
            const formatted =
              typeof p.value === 'number' && Number.isFinite(p.value) ? formatValue(p.value) : '—';
            const pct = typeof p.percent === 'number' ? `${p.percent.toFixed(1)}%` : '0.0%';
            return `${p.marker ?? ''} <strong>${p.name ?? ''}</strong><br/>${formatted} (${pct})`;
          },
        },
        series: [
          {
            name: primarySeries?.label ?? label,
            type: 'pie',
            radius: depth ? ['36%', '62%'] : ['40%', '66%'],
            center: ['50%', '52%'],
            selectedMode: 'single',
            selectedOffset: 6,
            avoidLabelOverlap: true,
            minShowLabelAngle: 4,
            padAngle: 1.5,
            itemStyle: {
              borderRadius: 3,
              borderColor: surfaceBg,
              borderWidth: 2,
            },
            label: {
              show: true,
              color: '#bec8c9',
              fontFamily: 'monospace',
              fontSize: 10,
              lineHeight: 14,
              formatter: (params: { name: string; value: unknown; percent?: number }) => {
                const v = typeof params.value === 'number' ? params.value : 0;
                if (v <= 0) return '';
                const pct = typeof params.percent === 'number' ? `${params.percent.toFixed(1)}%` : '';
                return `${params.name}\n${formatValue(v)} (${pct})`;
              },
            },
            labelLine: {
              show: true,
              length: 12,
              length2: 14,
              smooth: 0.15,
              lineStyle: {
                color: '#6a7e80',
                width: 1,
              },
            },
            emphasis: {
              scale: true,
              scaleSize: 5,
              label: {
                color: '#f4f4f2',
                fontWeight: 'bold',
              },
            },
            data: pieSlices,
          },
        ],
      };
    }

    const eSeries: Array<echarts.BarSeriesOption | echarts.LineSeriesOption> = visible.map((item) => {
      const sKind = item.kind ?? kind;
      const baseColor = resolveThemeColor(item.color);
      const slicedValues = item.values.slice(start, end);

      if (sKind === 'line') {
        const isPrimaryLine = kind === 'line';
        return {
          name: item.label,
          type: 'line',
          data: slicedValues,
          connectNulls: false,
          smooth: false,
          showSymbol: slicedLabels.length <= 45,
          symbol: 'circle',
          symbolSize: depth ? 5 : 3.5,
          lineStyle: {
            color: baseColor,
            width: depth ? 2.6 : 2,
            shadowColor: depth ? 'rgba(0, 0, 0, 0.55)' : undefined,
            shadowBlur: depth ? 6 : 0,
            shadowOffsetY: depth ? 3 : 0,
          },
          itemStyle: { color: baseColor },
          areaStyle: isPrimaryLine
            ? {
                color: {
                  type: 'linear',
                  x: 0,
                  y: 0,
                  x2: 0,
                  y2: 1,
                  colorStops: [
                    { offset: 0, color: resolveRgba(baseColor, depth ? 0.28 : 0.18) },
                    { offset: 0.9, color: resolveRgba(baseColor, 0.02) },
                    { offset: 1, color: 'transparent' },
                  ],
                },
              }
            : undefined,
        };
      }

      return {
        name: item.label,
        type: 'bar',
        stack: stacked ? 'total' : undefined,
        barMaxWidth: 38,
        data: slicedValues.map((v, idx) => {
          const isPartial = partial[start + idx];
          const pointRawColor = item.pointColors?.[start + idx];
          const color =
            v !== null && v < 0
              ? errorColor
              : pointRawColor
                ? resolveThemeColor(pointRawColor)
                : baseColor;
          return {
            value: v,
            itemStyle: {
              color: depth
                ? {
                    type: 'linear',
                    x: 0,
                    y: 0,
                    x2: 1,
                    y2: 1,
                    colorStops: [
                      { offset: 0, color },
                      { offset: 1, color: resolveRgba(color, 0.72) },
                    ],
                  }
                : color,
              opacity: isPartial ? 0.45 : 0.92,
              borderColor: depth ? '#f4f4f2' : undefined,
              borderWidth: depth ? 0.5 : 0,
              shadowColor: depth ? 'rgba(0, 0, 0, 0.5)' : undefined,
              shadowBlur: depth ? 6 : 0,
              shadowOffsetX: depth ? 3 : 0,
              shadowOffsetY: depth ? -2 : 0,
            },
          };
        }),
      };
    });

    return {
      backgroundColor: 'transparent',
      animation: false,
      grid: {
        left: '6.14%',
        right: '6.14%',
        top: '11.3%',
        bottom: '8.1%',
        containLabel: false,
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(18, 22, 23, 0.95)',
        borderColor: primaryAccent,
        borderWidth: 1,
        textStyle: {
          color: '#f4f4f2',
          fontSize: 11,
          fontFamily: 'monospace',
        },
        axisPointer: {
          type: 'line',
          lineStyle: { color: primaryAccent, width: 1, opacity: 0.55 },
        },
        valueFormatter: (value) =>
          typeof value === 'number' && Number.isFinite(value) ? formatValue(value) : '—',
      },
      xAxis: {
        type: 'category',
        data: slicedLabels,
        axisLine: { lineStyle: { color: '#6a7e80' } },
        axisTick: { show: false },
        axisLabel: { show: false },
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        min: low,
        max: high,
        interval: (high - low) / 4,
        axisLabel: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: {
          show: true,
          lineStyle: { color: gridColor, width: 1, type: 'solid' },
        },
      },
      series: eSeries,
    };
  }, [depth, end, formatValue, hidden, high, index, isPie, kind, label, labels, low, partial, stacked, start, visible]);

  const onSelectRef = useRef(onSelect);
  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  const selectionScopeRef = useRef(selectionScope);
  useEffect(() => {
    selectionScopeRef.current = selectionScope;
  }, [selectionScope]);

  useEffect(() => {
    const container = echartContainerRef.current;
    const plot = plotRef.current;
    if (!container || !plot) return;

    // Guard for headless test environments (e.g. jsdom) where canvas 2D context is null
    const probeCanvas = document.createElement('canvas');
    let has2DContext = false;
    try {
      has2DContext = Boolean(probeCanvas.getContext('2d'));
    } catch {
      has2DContext = false;
    }
    if (!has2DContext) return;

    const chart = echarts.init(container, undefined, {
      renderer: 'canvas',
      devicePixelRatio: Math.min(window.devicePixelRatio || 1, 1.5),
    });
    chartInstanceRef.current = chart;

    chart.on('mouseover', (params: { dataIndex?: number }) => {
      if (typeof params.dataIndex === 'number') {
        setSelection({ scope: selectionScopeRef.current, value: params.dataIndex });
      }
    });

    chart.on('click', (params: { dataIndex?: number }) => {
      if (typeof params.dataIndex === 'number') {
        setSelection({ scope: selectionScopeRef.current, value: params.dataIndex });
        onSelectRef.current?.(params.dataIndex);
      }
    });

    const resize =
      typeof ResizeObserver !== 'undefined'
        ? new ResizeObserver(() => {
            chart.resize();
          })
        : null;
    resize?.observe(plot);

    return () => {
      resize?.disconnect();
      try {
        chart.dispose();
      } catch {
        // Ignore teardown errors in synthetic DOM environments
      }
      chartInstanceRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartInstanceRef.current;
    if (!chart) return;
    chart.setOption(echartsOption, { notMerge: true, lazyUpdate: true });
    chart.resize();
  }, [echartsOption]);

  const getPickedIndex = (clientX: number) => {
    const plot = plotRef.current;
    if (!plot) return start;
    const rect = plot.getBoundingClientRect();
    const nx = Math.max(0, Math.min(1, (clientX - rect.left) / (rect.width || 1)));
    const length = Math.max(1, end - start);
    return Math.max(start, Math.min(end - 1, start + Math.floor(((nx * 11.4 - 0.7) / 10) * length)));
  };

  const stateRef = useRef({ zoom, offset, labelsLength: labels.length, isPie });
  useEffect(() => {
    stateRef.current = { zoom, offset, labelsLength: labels.length, isPie };
  }, [zoom, offset, labels.length, isPie]);

  useEffect(() => {
    const plot = plotRef.current;
    if (!plot) return;
    const onWheel = (e: WheelEvent) => {
      const { zoom: curZoom, offset: curOffset, labelsLength, isPie: pieMode } = stateRef.current;
      if (pieMode) return;
      e.preventDefault();
      if (labelsLength <= 1) return;
      if (Math.abs(e.deltaY) >= Math.abs(e.deltaX) || e.ctrlKey) {
        const rect = plot.getBoundingClientRect();
        const nx = Math.max(0, Math.min(1, (e.clientX - rect.left) / (rect.width || 1)));
        const factor = e.deltaY < 0 ? 1.25 : 0.8;
        const targetZoom = Math.max(1, Math.min(labelsLength / 3, curZoom * factor));
        if (targetZoom <= 1.05) {
          setZoom(1);
          setOffset(0);
          return;
        }
        const curCount = Math.max(1, Math.ceil(labelsLength / curZoom));
        const nextCount = Math.max(1, Math.ceil(labelsLength / targetZoom));
        const focalIndex = curOffset + nx * curCount;
        const nextOffset = Math.max(0, Math.min(labelsLength - nextCount, Math.round(focalIndex - nx * nextCount)));
        setZoom(targetZoom);
        setOffset(nextOffset);
      } else if (Math.abs(e.deltaX) > 0) {
        const curCount = Math.max(1, Math.ceil(labelsLength / curZoom));
        const delta = Math.round(e.deltaX / 30) || (e.deltaX > 0 ? 1 : -1);
        setOffset(Math.max(0, Math.min(labelsLength - curCount, curOffset + delta)));
      }
    };
    plot.addEventListener('wheel', onWheel, { passive: false });
    return () => plot.removeEventListener('wheel', onWheel);
  }, []);

  const inspect = (value: number) => {
    setSelection({ scope: selectionScope, value });
  };
  const ticks = [...new Set([start, Math.floor((start + end - 1) / 2), Math.max(start, end - 1)])].filter(
    (i) => i >= 0 && i < labels.length,
  );

  return (
    <div className="statistics-three">
      <div className="statistics-three__stage">
        <div className="statistics-three__toolbar" role="toolbar" aria-label={`${label} view controls`}>
          <span>{isPie ? `${labels.length} ${labels.length === 1 ? 'segment' : 'segments'}` : `UTC · ${end - start < labels.length ? `${end - start} of ` : ''}${labels.length} points`}</span>
          <div>
            {!isPie && zoom > 1 && (
              <button
                type="button"
                onClick={() => {
                  setZoom(1);
                  setOffset(0);
                }}
              >
                Show all
              </button>
            )}
            <button type="button" aria-pressed={depth} onClick={() => setDepth(!depth)}>
              Depth
            </button>
            {settings?.settings && <StatisticsSettings label={settings.label}>{settings.settings}</StatisticsSettings>}
          </div>
        </div>
        <div
          className="statistics-three__plot"
          ref={plotRef}
          role="img"
          aria-label={label}
          tabIndex={0}
          style={{ cursor: !isPie && zoom > 1 ? 'grab' : undefined }}
          onPointerDown={(e) => {
            if (isPie) return;
            dragRef.current = { startX: e.clientX, startOffset: offset, dragged: false };
            inspect(getPickedIndex(e.clientX));
          }}
          onPointerMove={(e) => {
            if (isPie) return;
            if (dragRef.current && zoom > 1) {
              const dx = e.clientX - dragRef.current.startX;
              if (Math.abs(dx) > 3) {
                dragRef.current.dragged = true;
                const plot = plotRef.current;
                const width = plot?.clientWidth || 1;
                const delta = Math.round((-dx / width) * count);
                setOffset(Math.max(0, Math.min(labels.length - count, dragRef.current.startOffset + delta)));
                return;
              }
            }
            inspect(getPickedIndex(e.clientX));
          }}
          onPointerUp={() => {
            dragRef.current = null;
          }}
          onClick={(e) => {
            if (isPie) return;
            if (dragRef.current?.dragged) return;
            const picked = getPickedIndex(e.clientX);
            inspect(picked);
            onSelect?.(picked);
          }}
          onKeyDown={(e) => {
            if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
              e.preventDefault();
              inspect(Math.max(start, Math.min(end - 1, index + (e.key === 'ArrowLeft' ? -1 : 1))));
            } else if (e.key === 'Enter') {
              onSelect?.(index);
            }
          }}
        >
          <div
            ref={echartContainerRef}
            className="statistics-three__canvas"
            aria-hidden="true"
            style={{ width: '100%', height: '100%' }}
          />
          {!isPie && labels.length > 0 && (
            <div
              className="statistics-three__cursor"
              style={{ left: `${selectedLeft}%`, top: 'auto', height: `${selectedHeight}%` }}
            />
          )}
          {!isPie && labels.length > 0 && selectedAmount !== null && peakInfo?.index !== index && (
            <>
              <div
                className="statistics-three__peak-marker"
                style={{ left: `${selectedLeft}%`, bottom: `${8.1 + selectedHeight}%` }}
                aria-hidden="true"
              />
              <div
                className="statistics-three__selected-badge"
                style={{
                  left: `${selectedLeft}%`,
                  bottom: `calc(${8.1 + selectedHeight}% + 6px)`,
                  transform: `translateX(-${selectedLeft}%)`,
                }}
                aria-label={`Selected ${selectedBars.length ? 'bar' : 'value'}: ${formatValue(selectedAmount)}`}
              >
                {formatValue(selectedAmount)}
              </div>
            </>
          )}
          {!isPie &&
            peakInfo &&
            (() => {
              const peakIdxRel = peakInfo.index - start;
              const length = Math.max(1, end - start);
              const peakLeft = 6.14 + ((peakIdxRel + 0.5) / length) * 87.72;
              const peakFraction = high > low ? (peakInfo.value - low) / (high - low) : 0;
              const peakBottom = 8.1 + peakFraction * 80.6;
              const markerBottom = Math.min(88.7, Math.max(8.1, peakBottom));
              return (
                <>
                  <div
                    className="statistics-three__peak-marker"
                    style={{ left: `${peakLeft}%`, bottom: `${markerBottom}%` }}
                    aria-hidden="true"
                  />
                  <div
                    className="statistics-three__peak-badge"
                    style={{
                      left: `${peakLeft}%`,
                      bottom: `calc(${markerBottom}% + 6px)`,
                      transform: `translateX(-${peakLeft}%)`,
                    }}
                    aria-label={`Peak: ${formatValue(peakInfo.value)}`}
                  >
                    <span className="statistics-three__peak-tag">PEAK</span>
                    <span className="statistics-three__peak-value">{formatValue(peakInfo.value)}</span>
                  </div>
                </>
              );
            })()}
          {!isPie && (
            <>
              <div className="statistics-three__y" aria-hidden="true">
                {[1, 0.75, 0.5, 0.25, 0].map((v) => (
                  <span key={v}>{formatAxisValue(low + v * (high - low))}</span>
                ))}
              </div>
              <div className="statistics-three__x" aria-hidden="true">
                {ticks.map((i) => (
                  <span key={i}>{labels[i]}</span>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
      <div className="statistics-chart__legend">
        {isPie && label !== 'Site comparison bars'
          ? labels.map((sliceLabel, idx) => {
              const sliceColor =
                series[0]?.pointColors?.[idx] ?? CHART_COLORS[idx % CHART_COLORS.length] ?? series[0]?.color ?? '#24aac3';
              return (
                <button
                  key={sliceLabel}
                  type="button"
                  aria-pressed={!hidden.includes(sliceLabel)}
                  onClick={() =>
                    setHidden((old) =>
                      old.includes(sliceLabel) ? old.filter((v) => v !== sliceLabel) : [...old, sliceLabel],
                    )
                  }
                >
                  <i style={{ background: sliceColor }} />
                  {sliceLabel}
                </button>
              );
            })
          : series.map((item) => (
              <button
                key={item.label}
                type="button"
                aria-pressed={!hidden.includes(item.label)}
                onClick={() =>
                  setHidden((old) => (old.includes(item.label) ? old.filter((v) => v !== item.label) : [...old, item.label]))
                }
              >
                <i style={{ background: item.color }} />
                {item.label}
              </button>
            ))}
      </div>
      <div className="statistics-three__readout sr-only" aria-live="polite">
        <strong>
          {labels[index]}
          {partial[index] ? ' · Partial bucket' : ''}
        </strong>
        {visible.map((item) => (
          <span key={item.label}>
            {item.label} <b>{item.values[index] == null ? '—' : formatValue(item.values[index]!)}</b>
          </span>
        ))}
      </div>
    </div>
  );
}
