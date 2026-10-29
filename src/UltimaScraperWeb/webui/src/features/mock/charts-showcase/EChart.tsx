import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';

export interface EChartProps {
  option: echarts.EChartsOption;
  style?: React.CSSProperties;
  className?: string;
  renderer?: 'canvas' | 'svg';
  onChartReady?: (instance: echarts.EChartsType) => void;
  loading?: boolean;
}

/**
 * React wrapper for Apache ECharts.
 * Handles lifecycle, auto-resizing via ResizeObserver, and clean disposal.
 */
export function EChart({
  option,
  style,
  className,
  renderer = 'canvas',
  onChartReady,
  loading = false,
}: EChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.EChartsType | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = echarts.init(container, undefined, {
      renderer,
    });
    chartRef.current = chart;

    if (onChartReady) {
      onChartReady(chart);
    }

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
      chartRef.current = null;
    };
  }, [renderer, onChartReady]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    chart.setOption(option, { notMerge: false, lazyUpdate: true });
  }, [option]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    if (loading) {
      chart.showLoading({
        text: 'Streaming data...',
        color: '#24aac3',
        textColor: '#bec8c9',
        maskColor: 'rgba(26, 31, 32, 0.7)',
      });
    } else {
      chart.hideLoading();
    }
  }, [loading]);

  return (
    <div
      ref={containerRef}
      className={className}
      style={{
        width: '100%',
        height: '100%',
        minHeight: 280,
        ...style,
      }}
    />
  );
}
