import { useState, useMemo } from 'react';
import type { DrivesMockModel } from './drivesMockModel';
import { formatBytes } from '../../../shared/lib/format';

export function StoragePipelineConcept({ model }: { model: DrivesMockModel }) {
  const drive = model.selectedDrive;
  const isAvailable = drive.isAvailable;

  const actualFreeGb = drive.freeBytes / (1024 * 1024 * 1024);
  const [simulatedFreeGb, setSimulatedFreeGb] = useState<number>(Math.round(actualFreeGb));
  const [newStagingPath, setNewStagingPath] = useState(`${drive.path}/staging/custom`);
  const [showStagingAdd, setShowStagingAdd] = useState(false);

  // Run the simulation based on the interactive slider
  const simulation = useMemo(
    () => model.simulateIngestion(simulatedFreeGb),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [model, simulatedFreeGb, drive]
  );

  const primaryDir = drive.directories.find((d) => d.setupType === 'download' && d.store);
  const minSpaceThreshold = primaryDir?.minSpaceGb ?? 50;
  const isThresholdBreached = simulatedFreeGb < minSpaceThreshold;

  const handleAddStaging = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newStagingPath.trim()) return;
    const newEntry = {
      id: `stg-${Date.now()}`,
      path: newStagingPath.trim(),
      usage: ['downloads', 'drm', 'merge'] as ('downloads' | 'drm' | 'merge')[],
      policy: [] as ('drm_only')[],
    };
    model.updateSettings({
      stagingDirectories: [...model.settings.stagingDirectories, newEntry],
    });
    setNewStagingPath(`${drive.path}/staging/buf_${Date.now().toString().slice(-4)}`);
    setShowStagingAdd(false);
  };

  return (
    <div className="sp-pipeline" role="region" aria-label="Storage Pipeline Ingestion Flow">
      {/* Top Banner */}
      <header className="sp-header">
        <div className="sp-header-left">
          <span className="sp-icon-flow">🔀</span>
          <div>
            <div className="sp-title-row">
              <h3>{drive.path}</h3>
              <span className={`sp-badge sp-badge--${drive.health}`}>{drive.health.toUpperCase()}</span>
              <span className="sp-tag">PIPELINE ROUTER</span>
            </div>
            <p className="sp-subtitle">
              Live Ingestion Graph · Gate Threshold: <strong>{minSpaceThreshold} GB</strong> · Backend: <code>{drive.backendId}</code>
            </p>
          </div>
        </div>

        <div className="sp-sim-control">
          <div className="sp-sim-label">
            <span>SIMULATE DISK HEADROOM:</span>
            <strong className={!isAvailable ? 'sp-text-warning' : isThresholdBreached ? 'sp-text-warning' : 'sp-text-accent'}>
              {isAvailable ? `${simulatedFreeGb} GB Free` : 'OFFLINE MOUNT'}
            </strong>
          </div>
          <input
            type="range"
            min={5}
            max={Math.max(500, Math.round(actualFreeGb))}
            step={5}
            value={simulatedFreeGb}
            onChange={(e) => setSimulatedFreeGb(parseInt(e.target.value, 10))}
            className="sp-range"
            disabled={!isAvailable}
            aria-label="Simulate free space headroom"
          />
        </div>
      </header>

      {/* Visual Pipeline Stage Graph */}
      <div className="sp-graph" aria-label="Visual data ingestion pipeline">
        {/* Stage 1: Ingestion API */}
        <div className="sp-stage-node sp-node--source">
          <div className="sp-node-header">
            <span className="sp-node-step">01</span>
            <strong>Worker Ingestion</strong>
          </div>
          <div className="sp-node-body">
            <span className="sp-pill sp-pill--source">OnlyFans / Fansly</span>
            <code className="sp-meta-code">Stream: Chunked TLS</code>
            <small>Media: 1080p Video / Hi-Res Photo</small>
          </div>
        </div>

        <div className="sp-connector">
          <div className="sp-line" />
          <span className="sp-arrow">➔</span>
        </div>

        {/* Stage 2: Staging Queues */}
        <div className="sp-stage-node sp-node--staging">
          <div className="sp-node-header">
            <span className="sp-node-step">02</span>
            <strong>Staging Quarantine</strong>
          </div>
          <div className="sp-node-body">
            {model.settings.stagingDirectories.map((stg) => (
              <div key={stg.id} className="sp-stg-row">
                <code>{stg.path.split('/').pop() || stg.path}</code>
                <div className="sp-stg-tags">
                  {stg.usage.map((u) => (
                    <span key={u} className="sp-tiny-tag">{u}</span>
                  ))}
                  {stg.policy.includes('drm_only') && (
                    <span className="sp-tiny-tag sp-tag--drm">🔒 DRM ONLY</span>
                  )}
                </div>
              </div>
            ))}
            <button
              type="button"
              className="sp-btn-link"
              onClick={() => setShowStagingAdd(true)}
            >
              + Add Staging Buffer
            </button>
          </div>
        </div>

        <div className="sp-connector">
          <div className="sp-line" />
          <span className="sp-arrow">➔</span>
        </div>

        {/* Stage 3: Space Gate Evaluator */}
        <div className={`sp-stage-node sp-node--gate ${isThresholdBreached ? 'is-blocked' : 'is-clear'}`}>
          <div className="sp-node-header">
            <span className="sp-node-step">03</span>
            <strong>Capacity Gate</strong>
          </div>
          <div className="sp-node-body">
            <div className="sp-gate-verdict">
              <span className="sp-gate-icon">{isThresholdBreached ? '⛔' : '✅'}</span>
              <div>
                <strong>{isThresholdBreached ? 'OVERFLOW TRIGGERED' : 'CLEAR TO WRITE'}</strong>
                <p>
                  Free {simulatedFreeGb} GB vs Min {minSpaceThreshold} GB
                </p>
              </div>
            </div>
            <div className="sp-gate-rule">
              <span>Rule: Stop writing if free &lt; {minSpaceThreshold} GB</span>
            </div>
          </div>
        </div>

        <div className="sp-connector">
          <div className="sp-line" />
          <span className="sp-arrow">➔</span>
        </div>

        {/* Stage 4: Destinations (Split into Primary or Spillway) */}
        <div className="sp-stage-split">
          {/* Primary Route */}
          <div className={`sp-dest-card ${!isThresholdBreached ? 'is-active-route' : 'is-disabled-route'}`}>
            <div className="sp-dest-top">
              <span className="sp-dest-badge primary">PRIMARY DESTINATION</span>
              {!isThresholdBreached && <span className="sp-flow-pulse" />}
            </div>
            <code>{primaryDir?.path || `${drive.path}/downloads`}</code>
            <small>{drive.name} · Direct NVMe Commit</small>
          </div>

          {/* Overflow Route */}
          <div className={`sp-dest-card ${isThresholdBreached ? 'is-active-route overflow-route' : 'is-disabled-route'}`}>
            <div className="sp-dest-top">
              <span className="sp-dest-badge overflow">FALLBACK SPILLWAY</span>
              {isThresholdBreached && <span className="sp-flow-pulse warning" />}
            </div>
            <code>{simulation.targetDirectory.path}</code>
            <small>{simulation.targetDrive.name} ({simulation.targetDrive.device})</small>
          </div>
        </div>
      </div>

      {/* Live Ingestion Event Log */}
      <section className="sp-log-section">
        <div className="sp-log-header">
          <span className="sp-log-title">Live Pipeline Event Execution Trace</span>
          <span className="sp-log-tag">SAMPLE PAYLOAD: IMG_4920.jpg</span>
        </div>
        <div className="sp-log-terminal">
          {simulation.stepLog.map((log, index) => (
            <div
              key={index}
              className={`sp-log-entry ${
                log.includes('Threshold') || log.includes('Overflow')
                  ? 'sp-log--alert'
                  : log.includes('Final')
                  ? 'sp-log--success'
                  : ''
              }`}
            >
              <span className="sp-log-time">[00:00:{String(index * 2).padStart(2, '0')}]</span>
              <span>{log}</span>
            </div>
          ))}
        </div>
      </section>

      {/* Directory Routing Table & Overflow Assigners */}
      <section className="sp-dirs-table-wrap">
        <div className="sp-section-head">
          <h4>Configured Mount Targets on {drive.name}</h4>
          <span className="sp-text-muted">{drive.directories.length} Directories</span>
        </div>

        <table className="sp-table">
          <thead>
            <tr>
              <th scope="col">Directory Path</th>
              <th scope="col">Target Role</th>
              <th scope="col">Min Space Barrier</th>
              <th scope="col">Store Ingestion</th>
              <th scope="col">Overflow Spillway</th>
              <th scope="col">Disk Footprint</th>
            </tr>
          </thead>
          <tbody>
            {drive.directories.map((dir) => (
              <tr key={dir.id}>
                <td>
                  <code className="sp-path-code">{dir.path}</code>
                </td>
                <td>
                  <span className={`sp-type-tag sp-type--${dir.setupType}`}>{dir.setupType}</span>
                </td>
                <td>
                  <input
                    type="number"
                    className="sp-input-num"
                    value={dir.minSpaceGb}
                    onChange={(e) =>
                      model.updateDirectoryConfig(drive.id, dir.id, {
                        minSpaceGb: parseInt(e.target.value, 10) || 0,
                      })
                    }
                  />
                  <span>GB</span>
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={dir.store}
                    onChange={(e) =>
                      model.updateDirectoryConfig(drive.id, dir.id, {
                        store: e.target.checked,
                      })
                    }
                  />
                </td>
                <td>
                  <input
                    type="checkbox"
                    checked={dir.overflow}
                    onChange={(e) =>
                      model.updateDirectoryConfig(drive.id, dir.id, {
                        overflow: e.target.checked,
                      })
                    }
                  />
                </td>
                <td>
                  <span>{formatBytes(dir.usedBytes)}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* Staging Add Modal */}
      {showStagingAdd && (
        <div className="sp-modal-overlay" onClick={() => setShowStagingAdd(false)}>
          <div className="sp-modal-card" onClick={(e) => e.stopPropagation()}>
            <h4>Add Staging Directory</h4>
            <p>Temporary disk staging for high-throughput stream reassembly and DRM decrypt.</p>
            <form onSubmit={handleAddStaging}>
              <input
                type="text"
                className="sp-input mono"
                value={newStagingPath}
                onChange={(e) => setNewStagingPath(e.target.value)}
                placeholder="/mnt/storage_fast/staging"
                required
              />
              <div className="sp-modal-btns" style={{ marginTop: '16px' }}>
                <button type="button" className="sp-btn-secondary" onClick={() => setShowStagingAdd(false)}>
                  Cancel
                </button>
                <button type="submit" className="sp-btn-primary">
                  Register Staging Buffer
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
