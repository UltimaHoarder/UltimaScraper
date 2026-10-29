import { useState, useEffect, useMemo, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { EChart } from './EChart';
import {
  generateInitialTelemetryData,
  buildTelemetryChartOption,
  buildMediaVaultChartOption,
  buildActivityHeatmapChartOption,
  buildRosterRadarChartOption,
  buildPipelineFunnelChartOption,
  type TelemetryPoint,
} from './chartsData';
import './ChartsShowcase.css';

const CONCEPTS = [
  { id: 'overview', name: '00 · Unified Dashboard', note: 'All 5 ECharts concepts orchestrated into a high-density operations center.' },
  { id: 'telemetry', name: '01 · Ingestion Telemetry', note: 'Dual-axis real-time throughput & worker concurrency with interactive dataZoom scrubber.' },
  { id: 'storage', name: '02 · Media Vault Storage', note: 'Nested sunburst doughnut showing video codecs, image types, audio, and DRM keys across 18.4 TB.' },
  { id: 'heatmap', name: '03 · 24/7 Activity Matrix', note: 'Temporal day-of-week vs hour-of-day download density and bandwidth saturation heatmap.' },
  { id: 'radar', name: '04 · Roster Health Radar', note: 'Multi-dimensional synchronization maturity comparing VIP creators against fleet average and SLA.' },
  { id: 'funnel', name: '05 · Pipeline Funnel', note: 'End-to-end ingestion pipeline throughput and stage dropout analysis from discovery to checksum.' },
] as const;

type ConceptId = typeof CONCEPTS[number]['id'];

export function ChartsShowcaseMock() {
  const [params, setParams] = useSearchParams();
  const activeId = (params.get('concept') as ConceptId) || 'overview';
  const activeConcept = CONCEPTS.find((c) => c.id === activeId) ?? CONCEPTS[0];

  // State for interactive features
  const [renderer, setRenderer] = useState<'canvas' | 'svg'>('canvas');
  const [isLiveSimulating, setIsLiveSimulating] = useState(false);
  const [timeRange, setTimeRange] = useState<'15m' | '1h' | '24h' | '7d'>('1h');
  const [telemetryData, setTelemetryData] = useState<TelemetryPoint[]>(generateInitialTelemetryData);

  // Live simulation tick: appends new points to telemetry data
  useEffect(() => {
    if (!isLiveSimulating) return;

    const interval = setInterval(() => {
      setTelemetryData((prev) => {
        const last = prev[prev.length - 1];
        const now = new Date();
        const timeStr = now.toLocaleTimeString([], { hour12: false });
        const delta = (Math.random() - 0.48) * 7;
        const throughput = Math.max(12, Math.min(85, Number((last.throughput + delta).toFixed(1))));
        const workerDelta = Math.round((Math.random() - 0.5) * 4);
        const workers = Math.max(16, Math.min(60, last.workers + workerDelta));
        const memory = Math.round(last.memory + (Math.random() * 4 - 2));

        return [...prev.slice(1), { time: timeStr, throughput, workers, memory }];
      });
    }, 1500);

    return () => clearInterval(interval);
  }, [isLiveSimulating]);

  const selectConcept = useCallback((id: ConceptId) => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set('category', 'charts');
      next.set('concept', id);
      return next;
    });
  }, [setParams]);

  // Memoized chart options
  const telemetryOption = useMemo(() => buildTelemetryChartOption(telemetryData), [telemetryData]);
  const mediaVaultOption = useMemo(() => buildMediaVaultChartOption(), []);
  const heatmapOption = useMemo(() => buildActivityHeatmapChartOption(), []);
  const radarOption = useMemo(() => buildRosterRadarChartOption(), []);
  const funnelOption = useMemo(() => buildPipelineFunnelChartOption(), []);

  // Live stats derived from current data
  const currentThroughput = telemetryData[telemetryData.length - 1]?.throughput ?? 38.4;
  const currentWorkers = telemetryData[telemetryData.length - 1]?.workers ?? 28;

  return (
    <div className="cs-lab" data-testid="charts-showcase-mock">
      {/* Concept Switcher Navigation */}
      <div className="cs-lab-controls">
        <nav className="cs-concepts" aria-label="ECharts concepts">
          {CONCEPTS.map((c) => (
            <button
              key={c.id}
              type="button"
              aria-pressed={activeId === c.id}
              onClick={() => selectConcept(c.id)}
            >
              <span>{c.name.split('·')[0].trim()}</span>
              {c.name.split('·')[1].trim()}
            </button>
          ))}
        </nav>
      </div>

      <div className="cs-stage">
        {/* Workspace Header */}
        <header className="cs-workspace-header">
          <div>
            <div className="cs-workspace-symbol" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M3 3v18h18" />
                <path d="m19 9-5 5-4-4-3 3" />
              </svg>
            </div>
            <div>
              <div className="cs-eyebrow">Interactive Telemetry & Analytics · Apache ECharts</div>
              <h2>{activeConcept.name}</h2>
              <div className="cs-header-status">
                <span className={`cs-dot ${isLiveSimulating ? 'cs-dot--live' : ''}`} />
                <span>{isLiveSimulating ? 'Live Streaming Active' : 'Static Snapshot'}</span>
                <span className="cs-header-divider" />
                <span>Renderer: {renderer.toUpperCase()}</span>
                <span className="cs-header-divider" />
                <span>Timeframe: {timeRange}</span>
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              type="button"
              className={`cs-btn ${isLiveSimulating ? 'cs-btn--active' : ''}`}
              onClick={() => setIsLiveSimulating((v) => !v)}
              aria-pressed={isLiveSimulating}
            >
              <span className={`cs-dot ${isLiveSimulating ? 'cs-dot--live' : ''}`} />
              {isLiveSimulating ? 'Pause Stream' : 'Simulate Stream'}
            </button>
            <button
              type="button"
              className="cs-btn"
              onClick={() => setRenderer((r) => (r === 'canvas' ? 'svg' : 'canvas'))}
            >
              Switch to {renderer === 'canvas' ? 'SVG' : 'Canvas'}
            </button>
          </div>
        </header>

        {/* Global Key Metrics Bar */}
        <div className="cs-metrics">
          <div>
            <span>Total Vault Size</span>
            <strong>18.4<small style={{ fontSize: '14px', marginLeft: '4px' }}>TB</small></strong>
            <small className="cs-accent">248,910 media assets</small>
          </div>
          <div>
            <span>Live Throughput</span>
            <strong className="cs-accent">{currentThroughput}<small style={{ fontSize: '14px', marginLeft: '4px' }}>MB/s</small></strong>
            <small>Peak: 68.2 MB/s</small>
          </div>
          <div>
            <span>Active Workers</span>
            <strong className="cs-warning">{currentWorkers}<small style={{ fontSize: '14px', marginLeft: '4px' }}>/ 64</small></strong>
            <small>Optimal concurrency</small>
          </div>
          <div>
            <span>Pipeline Verified</span>
            <strong className="cs-success">98.6%</strong>
            <small>128,750 verified runs</small>
          </div>
        </div>

        {/* Secondary Toolbar */}
        <div className="cs-toolbar">
          <div className="cs-pill-group" role="group" aria-label="Timeframe selection">
            {(['15m', '1h', '24h', '7d'] as const).map((range) => (
              <button
                key={range}
                type="button"
                className="cs-pill-btn"
                aria-pressed={timeRange === range}
                onClick={() => setTimeRange(range)}
              >
                {range}
              </button>
            ))}
          </div>

          <span className="cs-mono cs-muted" style={{ fontSize: '11px', marginLeft: '8px' }}>
            {activeConcept.note}
          </span>

          <div className="cs-toolbar-right">
            <button
              type="button"
              className="cs-btn cs-btn--primary"
              onClick={() => {
                setTelemetryData(generateInitialTelemetryData());
              }}
            >
              Regenerate Sample Data
            </button>
          </div>
        </div>

        {/* Charts Render Grid */}
        <div className={`cs-charts-grid ${activeId !== 'overview' ? 'cs-charts-grid--single' : ''}`}>
          {/* Chart 1: Live Telemetry */}
          {(activeId === 'overview' || activeId === 'telemetry') && (
            <article className={`cs-chart-card ${activeId === 'overview' ? 'cs-chart-card--wide' : ''}`}>
              <header className="cs-card-header">
                <div className="cs-card-title-group">
                  <h3>01 · Live Ingestion Telemetry & Concurrency</h3>
                  <p>Dual-axis time series with throughput (MB/s), inflight worker allocation, and MPS refill spikes</p>
                </div>
                <span className="cs-card-badge">Streaming EChart</span>
              </header>
              <div className="cs-card-body cs-card-body--tall">
                <EChart option={telemetryOption} renderer={renderer} />
              </div>
              <footer className="cs-card-footer">
                <div className="cs-card-footer-stats">
                  <span>Current: <strong>{currentThroughput} MB/s</strong></span>
                  <span>Inflight: <strong>{currentWorkers} Workers</strong></span>
                  <span>Zoom: <strong>Interactive Slider & Scrub</strong></span>
                </div>
                <span>Chart 1 of 5</span>
              </footer>
            </article>
          )}

          {/* Chart 2: Media Vault Storage */}
          {(activeId === 'overview' || activeId === 'storage') && (
            <article className="cs-chart-card">
              <header className="cs-card-header">
                <div className="cs-card-title-group">
                  <h3>02 · Media Vault Storage Breakdown</h3>
                  <p>Tiered nested ring: categories (Video, Photo, Audio) and encoding codecs (AV1, H.264, RAW)</p>
                </div>
                <span className="cs-card-badge">Nested Ring</span>
              </header>
              <div className="cs-card-body">
                <EChart option={mediaVaultOption} renderer={renderer} />
              </div>
              <footer className="cs-card-footer">
                <div className="cs-card-footer-stats">
                  <span>Video: <strong>71.5%</strong></span>
                  <span>Photos: <strong>21.3%</strong></span>
                  <span>Audio: <strong>7.2%</strong></span>
                </div>
                <span>Chart 2 of 5</span>
              </footer>
            </article>
          )}

          {/* Chart 3: 24/7 Activity Heatmap */}
          {(activeId === 'overview' || activeId === 'heatmap') && (
            <article className="cs-chart-card">
              <header className="cs-card-header">
                <div className="cs-card-title-group">
                  <h3>03 · 24/7 Download Bandwidth Heatmap</h3>
                  <p>Hour-of-day vs Day-of-week network saturation to pinpoint off-peak scheduled scrape windows</p>
                </div>
                <span className="cs-card-badge">VisualMap Matrix</span>
              </header>
              <div className="cs-card-body">
                <EChart option={heatmapOption} renderer={renderer} />
              </div>
              <footer className="cs-card-footer">
                <div className="cs-card-footer-stats">
                  <span>Peak Window: <strong>02:00 - 05:00 UTC</strong></span>
                  <span>Max Density: <strong>118 GB/hr</strong></span>
                </div>
                <span>Chart 3 of 5</span>
              </footer>
            </article>
          )}

          {/* Chart 4: Roster Health Radar */}
          {(activeId === 'overview' || activeId === 'radar') && (
            <article className="cs-chart-card">
              <header className="cs-card-header">
                <div className="cs-card-title-group">
                  <h3>04 · Creator Archival Health & Completeness</h3>
                  <p>Multi-dimensional radar comparing VIP creators against overall fleet average and minimum SLA</p>
                </div>
                <span className="cs-card-badge">Radar Polygons</span>
              </header>
              <div className="cs-card-body">
                <EChart option={radarOption} renderer={renderer} />
              </div>
              <footer className="cs-card-footer">
                <div className="cs-card-footer-stats">
                  <span>VIP Score: <strong>96.8 / 100</strong></span>
                  <span>Fleet Avg: <strong>82.4 / 100</strong></span>
                  <span>SLA Floor: <strong>70.0</strong></span>
                </div>
                <span>Chart 4 of 5</span>
              </footer>
            </article>
          )}

          {/* Chart 5: Pipeline Funnel */}
          {(activeId === 'overview' || activeId === 'funnel') && (
            <article className="cs-chart-card">
              <header className="cs-card-header">
                <div className="cs-card-title-group">
                  <h3>05 · Scraper Ingestion Pipeline Funnel</h3>
                  <p>Step-by-step conversion from profile discovery to verified checksum across 150k candidates</p>
                </div>
                <span className="cs-card-badge">Conversion Funnel</span>
              </header>
              <div className="cs-card-body">
                <EChart option={funnelOption} renderer={renderer} />
              </div>
              <footer className="cs-card-footer">
                <div className="cs-card-footer-stats">
                  <span>Discovered: <strong>150,000</strong></span>
                  <span>Checksummed: <strong>128,750</strong></span>
                  <span>Retention: <strong>85.8%</strong></span>
                </div>
                <span>Chart 5 of 5</span>
              </footer>
            </article>
          )}
        </div>
      </div>
    </div>
  );
}
