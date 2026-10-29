import type * as echarts from 'echarts';

export const ATLAS_THEME = {
  bgPrimary: '#1a1f20',
  bgSecondary: '#202526',
  bgTertiary: '#272d2e',
  bgElevated: '#2b3233',
  borderPrimary: '#343a3b',
  borderSecondary: '#303637',
  textPrimary: '#f4f4f2',
  textSecondary: '#bec8c9',
  textTertiary: '#9caeaf',
  accentPrimary: '#24aac3',
  accentSecondary: '#208ca0',
  accentHover: '#62c5d7',
  warning: '#ffd303',
  error: '#ff0037',
  purple: '#a371f7',
  emerald: '#3fb950',
  orange: '#f0883e',
  fontMono: "'IBM Plex Mono', 'SFMono-Regular', Consolas, monospace",
  fontSans: "'Arial', 'Helvetica Neue', system-ui, sans-serif",
};

// Common tooltip format for Atlas styling
const baseTooltip: echarts.TooltipComponentOption = {
  backgroundColor: 'rgba(32, 37, 38, 0.94)',
  borderColor: ATLAS_THEME.borderPrimary,
  borderWidth: 1,
  textStyle: {
    color: ATLAS_THEME.textPrimary,
    fontFamily: ATLAS_THEME.fontMono,
    fontSize: 11,
  },
  padding: [8, 12],
  extraCssText: 'box-shadow: 0 8px 30px rgba(0, 0, 0, 0.55); border-radius: 2px;',
};

// -------------------------------------------------------------
// Chart 1: Live Job Telemetry & Throughput (Dual-Axis Time Series)
// -------------------------------------------------------------
export interface TelemetryPoint {
  time: string;
  throughput: number; // MB/s
  workers: number; // Active inflight concurrency
  memory: number; // MB
}

export function generateInitialTelemetryData(): TelemetryPoint[] {
  const points: TelemetryPoint[] = [];
  const now = Date.now();
  for (let i = 40; i >= 0; i--) {
    const t = new Date(now - i * 3000);
    const timeStr = t.toLocaleTimeString([], { hour12: false });
    const wave = Math.sin(i * 0.28) * 12 + Math.cos(i * 0.15) * 8;
    const throughput = Math.max(8, Number((38 + wave + (Math.random() * 6 - 3)).toFixed(1)));
    const workers = Math.max(12, Math.min(48, Math.round(26 + wave * 0.6 + Math.random() * 4)));
    const memory = Math.round(420 + i * 2.8 + wave * 3.5);
    points.push({ time: timeStr, throughput, workers, memory });
  }
  return points;
}

export function buildTelemetryChartOption(data: TelemetryPoint[]): echarts.EChartsOption {
  const times = data.map((d) => d.time);
  const throughputVals = data.map((d) => d.throughput);
  const workerVals = data.map((d) => d.workers);

  return {
    backgroundColor: 'transparent',
    grid: {
      left: 55,
      right: 55,
      top: 55,
      bottom: 50,
      containLabel: true,
    },
    tooltip: {
      ...baseTooltip,
      trigger: 'axis',
      axisPointer: {
        type: 'cross',
        lineStyle: { color: ATLAS_THEME.borderPrimary, width: 1, type: 'dashed' },
        crossStyle: { color: ATLAS_THEME.accentPrimary },
      },
    },
    legend: {
      data: ['Throughput (MB/s)', 'Active Workers', 'MPS Refill Marker'],
      textStyle: { color: ATLAS_THEME.textSecondary, fontFamily: ATLAS_THEME.fontMono, fontSize: 11 },
      top: 10,
      right: 15,
      icon: 'roundRect',
    },
    xAxis: {
      type: 'category',
      data: times,
      boundaryGap: false,
      axisLine: { lineStyle: { color: ATLAS_THEME.borderPrimary } },
      axisLabel: {
        color: ATLAS_THEME.textTertiary,
        fontFamily: ATLAS_THEME.fontMono,
        fontSize: 10,
        interval: Math.max(1, Math.floor(times.length / 8)),
      },
      splitLine: { show: false },
    },
    yAxis: [
      {
        type: 'value',
        name: 'MB / s',
        nameTextStyle: { color: ATLAS_THEME.accentPrimary, fontFamily: ATLAS_THEME.fontMono, fontSize: 10 },
        position: 'left',
        splitLine: { lineStyle: { color: 'rgba(52, 58, 59, 0.45)', type: 'dashed' } },
        axisLabel: { color: ATLAS_THEME.textTertiary, fontFamily: ATLAS_THEME.fontMono, fontSize: 10 },
      },
      {
        type: 'value',
        name: 'Workers',
        nameTextStyle: { color: ATLAS_THEME.warning, fontFamily: ATLAS_THEME.fontMono, fontSize: 10 },
        position: 'right',
        min: 0,
        max: 64,
        splitLine: { show: false },
        axisLabel: { color: ATLAS_THEME.textTertiary, fontFamily: ATLAS_THEME.fontMono, fontSize: 10 },
      },
    ],
    dataZoom: [
      {
        type: 'inside',
        start: 20,
        end: 100,
      },
      {
        type: 'slider',
        height: 18,
        bottom: 8,
        borderColor: ATLAS_THEME.borderPrimary,
        backgroundColor: ATLAS_THEME.bgTertiary,
        fillerColor: 'rgba(36, 170, 195, 0.18)',
        handleStyle: { color: ATLAS_THEME.accentPrimary, borderColor: ATLAS_THEME.accentHover },
        textStyle: { color: ATLAS_THEME.textTertiary, fontFamily: ATLAS_THEME.fontMono, fontSize: 9 },
      },
    ],
    series: [
      {
        name: 'Throughput (MB/s)',
        type: 'line',
        yAxisIndex: 0,
        data: throughputVals,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 2.2, color: ATLAS_THEME.accentPrimary },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(36, 170, 195, 0.35)' },
              { offset: 0.8, color: 'rgba(36, 170, 195, 0.05)' },
              { offset: 1, color: 'transparent' },
            ],
          },
        },
        markPoint: {
          symbol: 'pin',
          symbolSize: 34,
          data: [
            {
              type: 'max',
              name: 'Peak Throughput',
              itemStyle: { color: ATLAS_THEME.accentHover },
              label: { color: '#0d1117', fontSize: 9, fontFamily: ATLAS_THEME.fontMono, fontWeight: 'bold' },
            },
          ],
        },
      },
      {
        name: 'Active Workers',
        type: 'line',
        yAxisIndex: 1,
        data: workerVals,
        smooth: false,
        showSymbol: true,
        symbolSize: 4,
        lineStyle: { width: 1.8, color: ATLAS_THEME.warning, type: 'solid' },
        itemStyle: { color: ATLAS_THEME.warning },
        markLine: {
          silent: true,
          symbol: 'none',
          data: [
            {
              yAxis: 32,
              name: 'Target Concurrency',
              lineStyle: { color: ATLAS_THEME.warning, type: 'dashed', width: 1.2 },
              label: {
                formatter: 'Target (32)',
                color: ATLAS_THEME.warning,
                fontFamily: ATLAS_THEME.fontMono,
                fontSize: 9,
                position: 'insideEndTop',
              },
            },
          ],
        },
      },
      {
        name: 'MPS Refill Marker',
        type: 'line',
        data: [],
        markLine: {
          symbol: ['none', 'triangle'],
          symbolSize: 6,
          lineStyle: { color: ATLAS_THEME.purple, type: 'dotted', width: 1.5 },
          label: {
            formatter: 'Batch Refill #14',
            color: ATLAS_THEME.purple,
            fontFamily: ATLAS_THEME.fontMono,
            fontSize: 9,
            position: 'insideStartTop',
          },
          data: [{ xAxis: times[Math.floor(times.length * 0.55)] || '' }],
        },
      },
    ],
  };
}

// -------------------------------------------------------------
// Chart 2: Media Vault Storage Composition (Tiered Nested Ring)
// -------------------------------------------------------------
interface PieTooltipParams {
  name: string;
  value: number;
  color: string;
  percent: number;
}

interface HeatmapTooltipParams {
  value: [number, number, number];
}

interface FunnelTooltipParams {
  name: string;
  value: number;
  color: string;
}

export function buildMediaVaultChartOption(): echarts.EChartsOption {
  const outerData = [
    { value: 6820, name: '4K AV1 Video', itemStyle: { color: '#24aac3' } },
    { value: 4350, name: '1080p H.264', itemStyle: { color: '#208ca0' } },
    { value: 1980, name: '720p Mobile', itemStyle: { color: '#62c5d7' } },
    { value: 2450, name: 'RAW / DNG Photos', itemStyle: { color: '#ffd303' } },
    { value: 1470, name: 'Optimized JPEG', itemStyle: { color: '#f59e0b' } },
    { value: 920, name: 'Lossless FLAC', itemStyle: { color: '#a371f7' } },
    { value: 410, name: 'AAC / Voice', itemStyle: { color: '#8b5cf6' } },
    { value: 380, name: 'Widevine DRM Keys', itemStyle: { color: '#ff0037' } },
    { value: 220, name: 'Sidecar Metadata', itemStyle: { color: '#9caeaf' } },
  ];

  const innerData = [
    { value: 13150, name: 'Video Vault (71.5%)', itemStyle: { color: '#24aac3' } },
    { value: 3920, name: 'Image Gallery (21.3%)', itemStyle: { color: '#ffd303' } },
    { value: 1330, name: 'Audio Archive (7.2%)', itemStyle: { color: '#a371f7' } },
  ];

  return {
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip,
      trigger: 'item',
      formatter: (params: unknown) => {
        const p = params as PieTooltipParams;
        const val = p.value;
        const gb = (val / 1024).toFixed(2);
        return `
          <div style="font-weight:700; color:${p.color}; margin-bottom:4px;">${p.name}</div>
          <div>Size: <span style="color:#f4f4f2">${val.toLocaleString()} GB</span> (${gb} TB)</div>
          <div>Share: <span style="color:#f4f4f2">${p.percent}%</span></div>
        `;
      },
    },
    legend: {
      orient: 'vertical',
      right: 10,
      top: 'middle',
      textStyle: { color: ATLAS_THEME.textSecondary, fontFamily: ATLAS_THEME.fontMono, fontSize: 10 },
      itemWidth: 10,
      itemHeight: 10,
    },
    series: [
      {
        name: 'Category',
        type: 'pie',
        selectedMode: 'single',
        radius: [0, '42%'],
        center: ['40%', '50%'],
        label: {
          position: 'inner',
          fontSize: 9,
          fontFamily: ATLAS_THEME.fontMono,
          color: '#101b1d',
          formatter: '{b}',
        },
        labelLine: { show: false },
        data: innerData,
      },
      {
        name: 'Encoding Format',
        type: 'pie',
        radius: ['52%', '76%'],
        center: ['40%', '50%'],
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 2,
          borderColor: ATLAS_THEME.bgSecondary,
          borderWidth: 2,
        },
        label: {
          show: false,
        },
        emphasis: {
          label: {
            show: true,
            fontSize: 11,
            fontWeight: 'bold',
            fontFamily: ATLAS_THEME.fontMono,
            color: ATLAS_THEME.textPrimary,
          },
        },
        data: outerData,
      },
    ],
  };
}

// -------------------------------------------------------------
// Chart 3: 24/7 Download Activity & Network Heatmap
// -------------------------------------------------------------
export function buildActivityHeatmapChartOption(): echarts.EChartsOption {
  const hours = [
    '00', '01', '02', '03', '04', '05', '06', '07', '08', '09', '10', '11',
    '12', '13', '14', '15', '16', '17', '18', '19', '20', '21', '22', '23',
  ];
  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  const data: Array<[number, number, number]> = [];
  for (let d = 0; d < 7; d++) {
    for (let h = 0; h < 24; h++) {
      // simulate realistic batch job peaks at night and weekend catchups
      const isNight = h >= 1 && h <= 5;
      const isWeekend = d >= 5;
      const base = isNight ? 65 : 22;
      const multiplier = isWeekend ? 1.4 : 1.0;
      const noise = Math.sin(h * 0.4 + d) * 18 + (Math.random() * 14 - 7);
      const val = Math.max(5, Math.min(100, Math.round((base + noise) * multiplier)));
      data.push([h, d, val]);
    }
  }

  return {
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip,
      position: 'top',
      formatter: (params: unknown) => {
        const p = params as HeatmapTooltipParams;
        const [hourIdx, dayIdx, value] = p.value;
        const day = days[dayIdx];
        const hour = hours[hourIdx];
        return `
          <div style="color:${ATLAS_THEME.accentPrimary}; font-weight:700;">${day} at ${hour}:00</div>
          <div>Bandwidth Load: <span style="color:#f4f4f2">${value}%</span></div>
          <div>Ingestion Volume: <span style="color:#f4f4f2">${(value * 1.45).toFixed(1)} GB/hr</span></div>
        `;
      },
    },
    grid: {
      left: 45,
      right: 25,
      top: 25,
      bottom: 50,
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      data: hours,
      splitArea: { show: true, areaStyle: { color: ['rgba(32, 37, 38, 0.4)', 'rgba(39, 45, 46, 0.4)'] } },
      axisLine: { lineStyle: { color: ATLAS_THEME.borderPrimary } },
      axisLabel: { color: ATLAS_THEME.textTertiary, fontFamily: ATLAS_THEME.fontMono, fontSize: 10 },
    },
    yAxis: {
      type: 'category',
      data: days,
      splitArea: { show: true },
      axisLine: { lineStyle: { color: ATLAS_THEME.borderPrimary } },
      axisLabel: { color: ATLAS_THEME.textSecondary, fontFamily: ATLAS_THEME.fontMono, fontSize: 10 },
    },
    visualMap: {
      min: 0,
      max: 100,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 5,
      inRange: {
        color: ['#202526', '#208ca0', '#24aac3', '#ffd303'],
      },
      textStyle: { color: ATLAS_THEME.textTertiary, fontFamily: ATLAS_THEME.fontMono, fontSize: 10 },
    },
    series: [
      {
        name: 'Download Bandwidth',
        type: 'heatmap',
        data,
        label: { show: false },
        emphasis: {
          itemStyle: {
            shadowBlur: 10,
            shadowColor: 'rgba(0, 0, 0, 0.8)',
            borderColor: ATLAS_THEME.accentHover,
            borderWidth: 1.5,
          },
        },
      },
    ],
  };
}

// -------------------------------------------------------------
// Chart 4: Creator Archival & Sync Health (Radar / Spider)
// -------------------------------------------------------------
export function buildRosterRadarChartOption(): echarts.EChartsOption {
  return {
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip,
      trigger: 'item',
    },
    legend: {
      data: ['VIP Creators (Tier A)', 'Fleet Average', 'Target SLA Baseline'],
      top: 10,
      right: 15,
      textStyle: { color: ATLAS_THEME.textSecondary, fontFamily: ATLAS_THEME.fontMono, fontSize: 10 },
      icon: 'circle',
    },
    radar: {
      center: ['50%', '55%'],
      radius: '68%',
      indicator: [
        { name: 'Post Archival %', max: 100 },
        { name: 'Media Retention', max: 100 },
        { name: 'Stories & Highlights', max: 100 },
        { name: 'Direct Messages & Vault', max: 100 },
        { name: 'Metadata & Tags', max: 100 },
        { name: 'DRM Decryption', max: 100 },
      ],
      axisName: {
        color: ATLAS_THEME.textSecondary,
        fontFamily: ATLAS_THEME.fontMono,
        fontSize: 10,
      },
      splitLine: {
        lineStyle: {
          color: [
            'rgba(52, 58, 59, 0.25)',
            'rgba(52, 58, 59, 0.4)',
            'rgba(52, 58, 59, 0.55)',
            'rgba(52, 58, 59, 0.7)',
            ATLAS_THEME.borderPrimary,
          ],
        },
      },
      splitArea: {
        show: true,
        areaStyle: {
          color: ['rgba(32, 37, 38, 0.6)', 'rgba(39, 45, 46, 0.3)'],
        },
      },
      axisLine: {
        lineStyle: { color: ATLAS_THEME.borderPrimary },
      },
    },
    series: [
      {
        name: 'Creator Health Benchmark',
        type: 'radar',
        data: [
          {
            value: [98.5, 96.2, 94.0, 91.5, 99.0, 97.8],
            name: 'VIP Creators (Tier A)',
            symbol: 'circle',
            symbolSize: 4,
            lineStyle: { color: ATLAS_THEME.warning, width: 2 },
            areaStyle: { color: 'rgba(255, 211, 3, 0.2)' },
            itemStyle: { color: ATLAS_THEME.warning },
          },
          {
            value: [88.2, 84.5, 76.0, 68.4, 85.0, 92.1],
            name: 'Fleet Average',
            symbol: 'circle',
            symbolSize: 4,
            lineStyle: { color: ATLAS_THEME.accentPrimary, width: 2 },
            areaStyle: { color: 'rgba(36, 170, 195, 0.22)' },
            itemStyle: { color: ATLAS_THEME.accentPrimary },
          },
          {
            value: [75.0, 75.0, 70.0, 60.0, 70.0, 80.0],
            name: 'Target SLA Baseline',
            symbol: 'none',
            lineStyle: { color: ATLAS_THEME.error, width: 1.5, type: 'dashed' },
            itemStyle: { color: ATLAS_THEME.error },
          },
        ],
      },
    ],
  };
}

// -------------------------------------------------------------
// Chart 5: Scraper Pipeline Funnel & Stage Bottleneck
// -------------------------------------------------------------
export function buildPipelineFunnelChartOption(): echarts.EChartsOption {
  const funnelData = [
    { value: 150000, name: '01 · Profiles Discovered', itemStyle: { color: '#24aac3' } },
    { value: 146800, name: '02 · Post Feeds Indexed', itemStyle: { color: '#208ca0' } },
    { value: 138500, name: '03 · Media URLs Extracted', itemStyle: { color: '#62c5d7' } },
    { value: 132100, name: '04 · DRM License Handshake', itemStyle: { color: '#ffd303' } },
    { value: 129400, name: '05 · Binary Payload Downloaded', itemStyle: { color: '#3fb950' } },
    { value: 128750, name: '06 · Checksum Stamped & Verified', itemStyle: { color: '#a371f7' } },
  ];

  return {
    backgroundColor: 'transparent',
    tooltip: {
      ...baseTooltip,
      trigger: 'item',
      formatter: (params: unknown) => {
        const p = params as FunnelTooltipParams;
        const val = p.value;
        const total = 150000;
        const pct = ((val / total) * 100).toFixed(1);
        return `
          <div style="font-weight:700; color:${p.color}; margin-bottom:4px;">${p.name}</div>
          <div>Items Processed: <span style="color:#f4f4f2">${val.toLocaleString()}</span></div>
          <div>End-to-End Retention: <span style="color:#f4f4f2">${pct}%</span></div>
          <div style="color:${ATLAS_THEME.textTertiary}; font-size:10px; margin-top:4px;">
            Dropouts: ${(total - val).toLocaleString()} candidates
          </div>
        `;
      },
    },
    legend: {
      data: funnelData.map((d) => d.name),
      top: 10,
      textStyle: { color: ATLAS_THEME.textSecondary, fontFamily: ATLAS_THEME.fontMono, fontSize: 10 },
      icon: 'square',
    },
    series: [
      {
        name: 'Ingestion Funnel',
        type: 'funnel',
        left: '12%',
        top: 60,
        bottom: 20,
        width: '76%',
        min: 100000,
        max: 150000,
        minSize: '30%',
        maxSize: '100%',
        sort: 'descending',
        gap: 3,
        label: {
          show: true,
          position: 'inside',
          formatter: '{b}: {c}',
          fontFamily: ATLAS_THEME.fontMono,
          fontSize: 10,
          color: '#101b1d',
          fontWeight: 'bold',
        },
        labelLine: {
          length: 10,
          lineStyle: {
            width: 1,
            type: 'solid',
          },
        },
        itemStyle: {
          borderColor: ATLAS_THEME.bgSecondary,
          borderWidth: 1.5,
        },
        emphasis: {
          label: {
            fontSize: 11,
          },
        },
        data: funnelData,
      },
    ],
  };
}
