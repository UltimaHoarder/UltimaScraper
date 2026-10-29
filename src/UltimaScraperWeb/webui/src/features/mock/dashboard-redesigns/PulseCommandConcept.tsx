import type { DashboardMockModel } from './dashboardMockModel';

function buildSparklinePoints(values: number[], width = 100, height = 24): string {
  if (values.length === 0) return `0,${height} ${width},${height}`;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 1);
  return values
    .map((v, i) => {
      const x = (i / Math.max(values.length - 1, 1)) * width;
      const y = height - 3 - ((v - min) / span) * (height - 6);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
}

export function PulseCommandConcept({ model }: { model: DashboardMockModel }) {
  const { kpis, samples, jobs, workers, proxies, filteredEvents, eventFilter, setEventFilter } = model;

  const itemRates = samples.map((s) => s.itemsPerSec);
  const writeRates = samples.map((s) => s.writeMbPerSec);
  const failRates = samples.map((s) => s.failureRate);
  const workerLoads = samples.map((s) => s.workerLoad);
  const queueDepths = samples.map((s) => s.queueDepth);

  const maxThroughput = Math.max(...itemRates, 220);
  const chartPoints = samples
    .map((s, idx) => {
      const x = (idx / Math.max(samples.length - 1, 1)) * 600;
      const y = 155 - (s.itemsPerSec / maxThroughput) * 130;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  const writePoints = samples
    .map((s, idx) => {
      const x = (idx / Math.max(samples.length - 1, 1)) * 600;
      const y = 155 - (s.writeMbPerSec / 450) * 130;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');

  return (
    <section className="dbm-concept dbm-pulse-command" aria-label="Pulse Command Deck">
      {/* 6 KPI Strip with Sparklines */}
      <div className="dbm-kpi-grid">
        <article className="dbm-kpi-card is-info">
          <header>
            <span>ACTIVE JOBS</span>
            <small>{kpis.queuedJobs} queued</small>
          </header>
          <strong>{kpis.runningJobs}</strong>
          <svg viewBox="0 0 100 24" className="dbm-sparkline" aria-hidden="true">
            <polyline points={buildSparklinePoints([2, 3, 3, 4, 3, 3, kpis.runningJobs])} />
          </svg>
        </article>

        <article className="dbm-kpi-card is-warning">
          <header>
            <span>QUEUE DEPTH</span>
            <small>Redis stream</small>
          </header>
          <strong>{queueDepths[queueDepths.length - 1]?.toLocaleString()}</strong>
          <svg viewBox="0 0 100 24" className="dbm-sparkline" aria-hidden="true">
            <polyline points={buildSparklinePoints(queueDepths)} />
          </svg>
        </article>

        <article className="dbm-kpi-card is-accent">
          <header>
            <span>ITEMS / SEC</span>
            <small>Aggregate velocity</small>
          </header>
          <strong>{kpis.totalItemsPerSec}</strong>
          <svg viewBox="0 0 100 24" className="dbm-sparkline" aria-hidden="true">
            <polyline points={buildSparklinePoints(itemRates)} />
          </svg>
        </article>

        <article className={`dbm-kpi-card ${kpis.successRate < 98 ? 'is-danger' : 'is-accent'}`}>
          <header>
            <span>SUCCESS RATE</span>
            <small>{kpis.totalFailed} failed tasks</small>
          </header>
          <strong>{kpis.successRate}%</strong>
          <svg viewBox="0 0 100 24" className="dbm-sparkline" aria-hidden="true">
            <polyline points={buildSparklinePoints(failRates.map((f) => 100 - f))} />
          </svg>
        </article>

        <article className="dbm-kpi-card is-info">
          <header>
            <span>WORKER LOAD</span>
            <small>{kpis.busyWorkers}/{kpis.onlineWorkers} active</small>
          </header>
          <strong>{kpis.workerUtilization}%</strong>
          <svg viewBox="0 0 100 24" className="dbm-sparkline" aria-hidden="true">
            <polyline points={buildSparklinePoints(workerLoads)} />
          </svg>
        </article>

        <article className="dbm-kpi-card is-accent">
          <header>
            <span>WRITE THROUGHPUT</span>
            <small>3 mounts active</small>
          </header>
          <strong>{kpis.totalWriteMb} MB/s</strong>
          <svg viewBox="0 0 100 24" className="dbm-sparkline" aria-hidden="true">
            <polyline points={buildSparklinePoints(writeRates)} />
          </svg>
        </article>
      </div>

      {/* Main Command Grid */}
      <div className="dbm-command-grid">
        {/* Dual-Series Telemetry Chart */}
        <article className="dbm-panel dbm-panel--wide">
          <header className="dbm-panel-head">
            <div>
              <span className="dbm-eyebrow">TELEMETRY // {model.range.toUpperCase()} WINDOW</span>
              <h3>Scraping &amp; Disk Write Velocity</h3>
            </div>
            <div className="dbm-legend">
              <span className="is-cyan">● Items/sec ({kpis.totalItemsPerSec}/s)</span>
              <span className="is-gold">● Disk I/O ({kpis.totalWriteMb} MB/s)</span>
            </div>
          </header>
          <div className="dbm-chart-box">
            <svg viewBox="0 0 600 165" className="dbm-main-svg" role="img" aria-label="Scraping and disk write telemetry">
              <defs>
                <linearGradient id="dbm-cyan-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#24aac3" stopOpacity="0.28" />
                  <stop offset="100%" stopColor="#24aac3" stopOpacity="0.0" />
                </linearGradient>
              </defs>
              <g className="dbm-svg-grid">
                <line x1="0" y1="30" x2="600" y2="30" />
                <line x1="0" y1="70" x2="600" y2="70" />
                <line x1="0" y1="110" x2="600" y2="110" />
                <line x1="0" y1="150" x2="600" y2="150" />
              </g>
              <polygon points={`0,155 ${chartPoints} 600,155`} fill="url(#dbm-cyan-grad)" />
              <polyline points={chartPoints} fill="none" stroke="#24aac3" strokeWidth="2.2" />
              <polyline points={writePoints} fill="none" stroke="#ffd303" strokeWidth="1.6" strokeDasharray="5 3" />
            </svg>
            <div className="dbm-chart-x">
              {samples.map((s) => (
                <span key={s.timeLabel}>{s.timeLabel}</span>
              ))}
            </div>
          </div>
        </article>

        {/* Active Jobs Execution Queue */}
        <article className="dbm-panel">
          <header className="dbm-panel-head">
            <div>
              <span className="dbm-eyebrow">EXECUTION QUEUE</span>
              <h3>Active &amp; Stalled Workloads</h3>
            </div>
            <span className="dbm-badge">{jobs.length} total</span>
          </header>
          <div className="dbm-job-cards">
            {jobs.map((job) => {
              const pct = Math.round(((job.completedTasks + job.failedTasks) / Math.max(job.totalTasks, 1)) * 100);
              return (
                <div key={job.id} className={`dbm-job-row is-${job.status}`}>
                  <div className="dbm-job-row-top">
                    <span className={`dbm-pill is-${job.status}`}>{job.status}</span>
                    <code>{job.id}</code>
                    <small>{job.site} · {job.currentStage}</small>
                    <div className="dbm-job-actions">
                      {job.status === 'failed' ? (
                        <button type="button" className="dbm-mini-btn is-accent" onClick={() => model.retryFailedJob(job.id)}>
                          Retry ({job.failedTasks})
                        </button>
                      ) : (
                        <button type="button" className="dbm-mini-btn" onClick={() => model.toggleJobPause(job.id)}>
                          {job.status === 'running' ? 'Pause' : 'Resume'}
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="dbm-job-row-title">
                    <strong>{job.name}</strong>
                    <span>{job.itemsPerSec > 0 ? `${job.itemsPerSec}/s` : '—'}</span>
                  </div>
                  <div className="dbm-progress-bar" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                    <div style={{ width: `${pct}%` }} />
                  </div>
                  <div className="dbm-job-row-meta">
                    <span>{job.completedTasks.toLocaleString()} / {job.totalTasks.toLocaleString()} tasks</span>
                    <span>Worker: {job.workerId}</span>
                    <span>ETA: {job.etaMinutes > 0 ? `${job.etaMinutes}m` : '—'}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </article>

        {/* Worker Unit Array */}
        <article className="dbm-panel">
          <header className="dbm-panel-head">
            <div>
              <span className="dbm-eyebrow">COMPUTE CLUSTER</span>
              <h3>Worker Unit Array</h3>
            </div>
            <span className="dbm-badge">{kpis.busyWorkers}/{kpis.totalWorkers} Busy</span>
          </header>
          <div className="dbm-worker-matrix">
            {workers.map((w, idx) => (
              <button
                type="button"
                key={w.id}
                className={`dbm-worker-cell is-${w.state} ${model.selectedWorkerId === w.id ? 'is-selected' : ''}`}
                onClick={() => model.setSelectedWorkerId(w.id)}
                aria-pressed={model.selectedWorkerId === w.id}
              >
                <div className="dbm-worker-cell-head">
                  <span>UNIT 0{idx + 1}</span>
                  <i className={`dbm-status-dot is-${w.state}`} />
                </div>
                <strong>{w.name}</strong>
                <small>{w.region}</small>
                <div className="dbm-worker-bars">
                  <span>CPU {w.cpuPercent}%</span>
                  <span>MEM {w.memPercent}%</span>
                </div>
              </button>
            ))}
          </div>
          {model.selectedWorker && (
            <div className="dbm-worker-strip">
              <div>
                <strong>{model.selectedWorker.name}</strong>
                <span>{model.selectedWorker.activeJobId ? `Assigned: ${model.selectedWorker.activeJobId}` : 'Standby / Idle'} · {model.selectedWorker.throughputMb} MB/s</span>
              </div>
              <button type="button" className="dbm-mini-btn" onClick={() => model.drainWorker(model.selectedWorker.id)}>
                {model.selectedWorker.state === 'idle' ? 'Assign Workload' : 'Drain Node'}
              </button>
            </div>
          )}
        </article>

        {/* Proxy Route Fabric */}
        <article className="dbm-panel">
          <header className="dbm-panel-head">
            <div>
              <span className="dbm-eyebrow">EGRESS ROUTING</span>
              <h3>Regional Proxy Fabric</h3>
            </div>
            <span className="dbm-badge">150 routes</span>
          </header>
          <div className="dbm-proxy-list">
            {proxies.map((p) => {
              const util = Math.round((p.activeAssignments / p.maxCapacity) * 100);
              return (
                <div key={p.id} className="dbm-proxy-row">
                  <div className="dbm-proxy-info">
                    <strong>{p.name}</strong>
                    <small>{p.routes} routes · {p.latencyMs}ms · {p.successRate}% ok</small>
                  </div>
                  <div className="dbm-proxy-bar-wrap">
                    <div className="dbm-progress-bar">
                      <div style={{ width: `${util}%` }} />
                    </div>
                    <small>{p.activeAssignments}/{p.maxCapacity} slots</small>
                  </div>
                  {p.throttledCount > 0 ? (
                    <button type="button" className="dbm-mini-btn is-warning" onClick={() => model.rotateThrottledProxies(p.id)}>
                      Rotate ({p.throttledCount} 429s)
                    </button>
                  ) : (
                    <span className="dbm-pill is-running">Healthy</span>
                  )}
                </div>
              );
            })}
          </div>
        </article>

        {/* Correlated Event Stream */}
        <article className="dbm-panel">
          <header className="dbm-panel-head">
            <div>
              <span className="dbm-eyebrow">SYSTEM LOGS</span>
              <h3>Correlated Event Stream</h3>
            </div>
            <div className="dbm-filter-pills" role="group" aria-label="Filter events by severity">
              {(['all', 'critical', 'warning', 'info'] as const).map((sev) => (
                <button
                  type="button"
                  key={sev}
                  className={eventFilter === sev ? 'is-active' : ''}
                  onClick={() => setEventFilter(sev)}
                >
                  {sev}
                </button>
              ))}
            </div>
          </header>
          <div className="dbm-event-stream">
            {filteredEvents.map((ev) => (
              <div key={ev.id} className={`dbm-event-item is-${ev.severity}`}>
                <time>{ev.timestamp}</time>
                <i className={`dbm-status-dot is-${ev.severity}`} />
                <div>
                  <strong>{ev.title}</strong>
                  <small>{ev.source} · {ev.detail}</small>
                </div>
              </div>
            ))}
          </div>
        </article>
      </div>
    </section>
  );
}
