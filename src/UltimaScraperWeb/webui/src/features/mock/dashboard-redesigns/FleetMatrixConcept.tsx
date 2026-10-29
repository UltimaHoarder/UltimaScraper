import type { DashboardMockModel } from './dashboardMockModel';

export function FleetMatrixConcept({ model }: { model: DashboardMockModel }) {
  const { workers, proxies, selectedWorker, setSelectedWorkerId, kpis } = model;

  return (
    <section className="dbm-concept dbm-fleet-matrix" aria-label="Fleet & Proxy Matrix">
      <div className="dbm-fleet-split">
        {/* Left: High-Density Worker Matrix + Proxy Table */}
        <div className="dbm-fleet-main">
          <article className="dbm-panel">
            <header className="dbm-panel-head">
              <div>
                <span className="dbm-eyebrow">WORKER MATRIX // {workers.length} REGISTERED UNITS</span>
                <h3>Cluster Compute &amp; Heartbeat Grid</h3>
              </div>
              <span className="dbm-badge">{kpis.workerUtilization}% Utilization</span>
            </header>
            <div className="dbm-table-wrap">
              <table className="dbm-table" aria-label="Fleet worker matrix">
                <thead>
                  <tr>
                    <th>Unit ID</th>
                    <th>Hostname</th>
                    <th>Region</th>
                    <th>Status</th>
                    <th>CPU</th>
                    <th>Memory</th>
                    <th>I/O Rate</th>
                    <th>Done</th>
                  </tr>
                </thead>
                <tbody>
                  {workers.map((w) => {
                    const selected = w.id === selectedWorker.id;
                    return (
                      <tr
                        key={w.id}
                        className={selected ? 'is-selected' : ''}
                        onClick={() => setSelectedWorkerId(w.id)}
                      >
                        <td>
                          <button
                            type="button"
                            className="dbm-row-select-btn"
                            aria-pressed={selected}
                            onClick={() => setSelectedWorkerId(w.id)}
                          >
                            <code>{w.id}</code>
                          </button>
                        </td>
                        <td><strong>{w.name}</strong></td>
                        <td>{w.region}</td>
                        <td>
                          <span className={`dbm-pill is-${w.state === 'busy' ? 'running' : w.state === 'warning' ? 'failed' : 'queued'}`}>
                            {w.state}
                          </span>
                        </td>
                        <td>{w.cpuPercent}%</td>
                        <td>{w.memPercent}%</td>
                        <td>{w.throughputMb} MB/s</td>
                        <td>{w.tasksCompleted.toLocaleString()}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </article>

          <article className="dbm-panel">
            <header className="dbm-panel-head">
              <div>
                <span className="dbm-eyebrow">GEO-ROUTING // 150 CONFIGURED PROXIES</span>
                <h3>Regional Egress Capacity &amp; Session Health</h3>
              </div>
              <span className="dbm-badge">106 Active Assignments</span>
            </header>
            <div className="dbm-proxy-list">
              {proxies.map((p) => {
                const share = Math.round((p.activeAssignments / p.maxCapacity) * 100);
                return (
                  <div key={p.id} className="dbm-proxy-row">
                    <div className="dbm-proxy-info">
                      <strong>{p.name}</strong>
                      <small>{p.routes} routes · {p.latencyMs}ms RTT · {p.successRate}% SLA</small>
                    </div>
                    <div className="dbm-proxy-bar-wrap">
                      <div className="dbm-progress-bar">
                        <div style={{ width: `${share}%` }} />
                      </div>
                      <small>{share}% saturated ({p.activeAssignments}/{p.maxCapacity})</small>
                    </div>
                    <button
                      type="button"
                      className={`dbm-mini-btn ${p.throttledCount > 0 ? 'is-warning' : ''}`}
                      onClick={() => model.rotateThrottledProxies(p.id)}
                    >
                      {p.throttledCount > 0 ? `Clear ${p.throttledCount} 429s` : 'Rebalance'}
                    </button>
                  </div>
                );
              })}
            </div>
          </article>
        </div>

        {/* Right: Focused Worker Unit Dossier Inspector */}
        <aside className="dbm-panel dbm-worker-dossier" aria-label="Selected worker dossier">
          <header className="dbm-panel-head">
            <div>
              <span className="dbm-eyebrow">WORKER UNIT DOSSIER</span>
              <h3>{selectedWorker.name}</h3>
            </div>
            <span className={`dbm-pill is-${selectedWorker.state === 'busy' ? 'running' : selectedWorker.state === 'warning' ? 'failed' : 'queued'}`}>
              {selectedWorker.state.toUpperCase()}
            </span>
          </header>

          <dl className="dbm-dossier-facts">
            <div>
              <dt>Worker Identifier</dt>
              <dd><code>{selectedWorker.id}</code></dd>
            </div>
            <div>
              <dt>Datacenter Region</dt>
              <dd>{selectedWorker.region}</dd>
            </div>
            <div>
              <dt>Assigned Operation</dt>
              <dd><code>{selectedWorker.activeJobId ?? 'None (Idle Standby)'}</code></dd>
            </div>
            <div>
              <dt>Write Velocity</dt>
              <dd><strong>{selectedWorker.throughputMb} MB/s</strong></dd>
            </div>
            <div>
              <dt>Completed Tasks</dt>
              <dd>{selectedWorker.tasksCompleted.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Broker RTT / Uptime</dt>
              <dd>{selectedWorker.latencyMs}ms · {selectedWorker.uptimeHours}h</dd>
            </div>
          </dl>

          <div className="dbm-dossier-gauges">
            <div>
              <div className="dbm-gauge-label">
                <span>CPU Utilization</span>
                <strong>{selectedWorker.cpuPercent}%</strong>
              </div>
              <div className="dbm-progress-bar">
                <div style={{ width: `${selectedWorker.cpuPercent}%` }} />
              </div>
            </div>
            <div>
              <div className="dbm-gauge-label">
                <span>RSS Memory Pressure</span>
                <strong>{selectedWorker.memPercent}%</strong>
              </div>
              <div className="dbm-progress-bar">
                <div style={{ width: `${selectedWorker.memPercent}%` }} />
              </div>
            </div>
          </div>

          <div className="dbm-dossier-actions">
            <button
              type="button"
              className="dbm-primary-btn"
              onClick={() => model.drainWorker(selectedWorker.id)}
            >
              {selectedWorker.state === 'idle' ? 'Assign Queued Workload' : 'Gracefully Drain Worker'}
            </button>
          </div>
        </aside>
      </div>
    </section>
  );
}
