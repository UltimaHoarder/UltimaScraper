import { useState } from 'react';
import type { DashboardMockModel } from './dashboardMockModel';

type PipelineNodeId = 'broker' | 'workers' | 'proxies' | 'vault';

const PIPELINE_NODES: Array<{
  id: PipelineNodeId;
  stageCode: string;
  title: string;
  subtitle: string;
}> = [
  { id: 'broker', stageCode: '01 // DISPATCH', title: 'Redis Claim Broker', subtitle: 'Distributed task leases & MPS refills' },
  { id: 'workers', stageCode: '02 // COMPUTE', title: 'Worker Fleet Array', subtitle: 'Multi-region extraction & AV1 transcode' },
  { id: 'proxies', stageCode: '03 // EGRESS', title: 'Proxy Route Fabric', subtitle: 'Geo-assigned residential & DC pools' },
  { id: 'vault', stageCode: '04 // PERSIST', title: 'Tiered Storage Vault', subtitle: 'NVMe staging & ZFS archive spillways' },
];

export function PipelineTopologyConcept({ model }: { model: DashboardMockModel }) {
  const [selectedNode, setSelectedNode] = useState<PipelineNodeId>('vault');
  const [flowAnimated, setFlowAnimated] = useState<boolean>(true);
  const { kpis, mounts, workers, proxies } = model;

  return (
    <section className="dbm-concept dbm-pipeline-topology" aria-label="Acquisition Pipeline Schematic">
      {/* Schematic Header Strip */}
      <header className="dbm-schematic-bar">
        <div>
          <span className="dbm-eyebrow">END-TO-END DATA PATH // INTERACTIVE TOPOLOGY</span>
          <h3>Distributed Acquisition &amp; Storage Flow</h3>
        </div>
        <div className="dbm-schematic-controls">
          <span className="dbm-pill is-running">REDIS BROKER CONNECTED (1.4ms)</span>
          <button
            type="button"
            className="dbm-mini-btn"
            aria-pressed={!flowAnimated}
            onClick={() => setFlowAnimated((v) => !v)}
          >
            {flowAnimated ? 'Pause Flow Pulses' : 'Resume Flow Pulses'}
          </button>
        </div>
      </header>

      {/* 4-Stage Interactive Node Graph */}
      <div className={`dbm-topology-chain ${flowAnimated ? 'is-animated' : ''}`} role="list" aria-label="Pipeline topology stages">
        {PIPELINE_NODES.map((node, index) => {
          const isSelected = selectedNode === node.id;
          const hasWarning =
            (node.id === 'vault' && mounts.some((m) => m.overflowActive)) ||
            (node.id === 'proxies' && proxies.some((p) => p.throttledCount > 0)) ||
            (node.id === 'workers' && workers.some((w) => w.state === 'warning'));

          return (
            <div key={node.id} className="dbm-topology-step" role="listitem">
              <button
                type="button"
                className={`dbm-topology-node ${isSelected ? 'is-selected' : ''} ${hasWarning ? 'has-warning' : ''}`}
                aria-pressed={isSelected}
                onClick={() => setSelectedNode(node.id)}
              >
                <div className="dbm-node-top">
                  <span>{node.stageCode}</span>
                  <i className={`dbm-status-dot ${hasWarning ? 'is-warning' : 'is-info'}`} />
                </div>
                <strong>{node.title}</strong>
                <small>{node.subtitle}</small>
                <div className="dbm-node-metric">
                  {node.id === 'broker' && <span>{kpis.runningJobs} active · {kpis.queuedJobs} queued</span>}
                  {node.id === 'workers' && <span>{kpis.busyWorkers}/{kpis.onlineWorkers} nodes · {kpis.totalItemsPerSec} items/s</span>}
                  {node.id === 'proxies' && <span>150 routes · 99.3% SLA</span>}
                  {node.id === 'vault' && <span>{kpis.totalWriteMb} MB/s write · 3 mounts</span>}
                </div>
              </button>
              {index < PIPELINE_NODES.length - 1 && (
                <div className="dbm-topology-connector" aria-hidden="true">
                  <span className="dbm-connector-line" />
                  <span className="dbm-connector-arrow">→</span>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Stage Deep-Dive Inspector */}
      <div className="dbm-topology-inspector">
        {selectedNode === 'vault' && (
          <article className="dbm-panel">
            <header className="dbm-panel-head">
              <div>
                <span className="dbm-eyebrow">STAGE 04 INSPECTOR // TIERED STORAGE VAULT</span>
                <h3>Mount Capacity, Watermarks &amp; Spillway Governance</h3>
              </div>
              <span className="dbm-badge">{kpis.totalWriteMb} MB/s Aggregate I/O</span>
            </header>
            <div className="dbm-mount-grid">
              {mounts.map((m) => {
                const pct = Math.round((m.usedTb / m.totalTb) * 100);
                return (
                  <div key={m.id} className={`dbm-mount-card ${m.overflowActive ? 'is-overflow' : ''}`}>
                    <div className="dbm-mount-head">
                      <div>
                        <span className="dbm-eyebrow">{m.tier.toUpperCase()} TIER</span>
                        <strong>{m.label}</strong>
                        <code>{m.path}</code>
                      </div>
                      <span className={`dbm-pill ${m.overflowActive ? 'is-failed' : 'is-running'}`}>
                        {m.overflowActive ? 'OVERFLOW ACTIVE' : 'CLEAR TO WRITE'}
                      </span>
                    </div>
                    <div className="dbm-progress-bar">
                      <div style={{ width: `${pct}%` }} />
                    </div>
                    <div className="dbm-mount-stats">
                      <span>Used: <strong>{m.usedTb} / {m.totalTb} TB ({pct}%)</strong></span>
                      <span>Free: <strong>{m.freeSpaceGb} GB</strong> (Min: {m.minWatermarkGb} GB)</span>
                      <span>Write: <strong>{m.writeMbPerSec} MB/s</strong></span>
                    </div>
                    {m.overflowActive && (
                      <div className="dbm-mount-alert">
                        <span>Free space below {m.minWatermarkGb} GB reserve. Spillway routing writes to Cold Archive.</span>
                        <button type="button" className="dbm-mini-btn is-accent" onClick={() => model.rebalanceOverflowMount(m.id)}>
                          Flush Staging to Cold Archive
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </article>
        )}

        {selectedNode === 'workers' && (
          <article className="dbm-panel">
            <header className="dbm-panel-head">
              <div>
                <span className="dbm-eyebrow">STAGE 02 INSPECTOR // WORKER FLEET ARRAY</span>
                <h3>Compute Nodes &amp; Hardware Transcode Telemetry</h3>
              </div>
              <span className="dbm-badge">{kpis.workerUtilization}% Cluster Load</span>
            </header>
            <div className="dbm-table-wrap">
              <table className="dbm-table" aria-label="Compute worker nodes">
                <thead>
                  <tr>
                    <th>Worker Node</th>
                    <th>Region</th>
                    <th>State</th>
                    <th>CPU / Mem</th>
                    <th>Throughput</th>
                    <th>Assigned Job</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {workers.map((w) => (
                    <tr key={w.id}>
                      <td><strong>{w.name}</strong> <code>{w.id}</code></td>
                      <td>{w.region}</td>
                      <td><span className={`dbm-pill is-${w.state === 'busy' ? 'running' : w.state === 'warning' ? 'failed' : 'queued'}`}>{w.state}</span></td>
                      <td>{w.cpuPercent}% / {w.memPercent}%</td>
                      <td>{w.throughputMb} MB/s</td>
                      <td><code>{w.activeJobId ?? 'Standby'}</code></td>
                      <td>
                        <button type="button" className="dbm-mini-btn" onClick={() => model.drainWorker(w.id)}>
                          {w.state === 'idle' ? 'Wake Node' : 'Drain'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>
        )}

        {selectedNode === 'proxies' && (
          <article className="dbm-panel">
            <header className="dbm-panel-head">
              <div>
                <span className="dbm-eyebrow">STAGE 03 INSPECTOR // PROXY ROUTE FABRIC</span>
                <h3>Regional Egress Pools &amp; Rate-Limit Mitigation</h3>
              </div>
              <span className="dbm-badge">5 Geolocation Pools</span>
            </header>
            <div className="dbm-proxy-list">
              {proxies.map((p) => (
                <div key={p.id} className="dbm-proxy-row">
                  <div className="dbm-proxy-info">
                    <strong>{p.name} ({p.countryCode})</strong>
                    <small>{p.routes} dedicated routes · {p.latencyMs}ms avg RTT · {p.successRate}% delivery</small>
                  </div>
                  <div className="dbm-proxy-bar-wrap">
                    <div className="dbm-progress-bar">
                      <div style={{ width: `${Math.round((p.activeAssignments / p.maxCapacity) * 100)}%` }} />
                    </div>
                    <small>{p.activeAssignments} / {p.maxCapacity} session slots</small>
                  </div>
                  <button
                    type="button"
                    className={`dbm-mini-btn ${p.throttledCount > 0 ? 'is-warning' : ''}`}
                    onClick={() => model.rotateThrottledProxies(p.id)}
                  >
                    {p.throttledCount > 0 ? `Rotate ${p.throttledCount} Throttled` : 'Test Route Pool'}
                  </button>
                </div>
              ))}
            </div>
          </article>
        )}

        {selectedNode === 'broker' && (
          <article className="dbm-panel">
            <header className="dbm-panel-head">
              <div>
                <span className="dbm-eyebrow">STAGE 01 INSPECTOR // REDIS CLAIM BROKER</span>
                <h3>Distributed Lease Queue &amp; MPS Refill Engine</h3>
              </div>
              <span className="dbm-badge">Redis 7.4 Cluster</span>
            </header>
            <div className="dbm-broker-stats">
              <div className="dbm-stat-box">
                <span>CLAIM LEASE LATENCY</span>
                <strong>1.4 ms</strong>
                <small>Zero lock contention</small>
              </div>
              <div className="dbm-stat-box">
                <span>MPS REFILL VELOCITY</span>
                <strong>128.4 IDs/s</strong>
                <small>Auto-refilling batch 63</small>
              </div>
              <div className="dbm-stat-box">
                <span>INFLIGHT TASK LEASES</span>
                <strong>{kpis.busyWorkers * 32}</strong>
                <small>30s heartbeat TTL</small>
              </div>
              <div className="dbm-stat-box">
                <span>DEAD-LETTER QUEUE</span>
                <strong>{kpis.totalFailed} tasks</strong>
                <small>Ready for 1-click replay</small>
              </div>
            </div>
          </article>
        )}
      </div>
    </section>
  );
}
