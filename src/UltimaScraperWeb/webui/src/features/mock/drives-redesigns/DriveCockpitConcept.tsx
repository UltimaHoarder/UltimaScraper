import { useState } from 'react';
import type { DrivesMockModel } from './drivesMockModel';
import { formatBytes } from '../../../shared/lib/format';

export function DriveCockpitConcept({ model }: { model: DrivesMockModel }) {
  const drive = model.selectedDrive;
  const isAvailable = drive.isAvailable;

  const [newPath, setNewPath] = useState(`${drive.path}/new_folder`);
  const [newType, setNewType] = useState<'download' | 'metadata'>('download');
  const [newMinSpace, setNewMinSpace] = useState<number>(50);
  const [isAdding, setIsAdding] = useState(false);

  // Compute storage segments for visual allocation bar
  const total = drive.totalBytes || 1;
  const used = drive.usedBytes;
  const free = drive.freeBytes;

  const dlBytes = drive.directories
    .filter((d) => d.setupType === 'download')
    .reduce((acc, d) => acc + d.usedBytes, 0);
  const metaBytes = drive.directories
    .filter((d) => d.setupType === 'metadata')
    .reduce((acc, d) => acc + d.usedBytes, 0);
  const sysBytes = Math.max(0, used - (dlBytes + metaBytes));

  const pctDl = ((dlBytes / total) * 100).toFixed(1);
  const pctMeta = ((metaBytes / total) * 100).toFixed(1);
  const pctSys = ((sysBytes / total) * 100).toFixed(1);
  const pctFree = ((free / total) * 100).toFixed(1);

  const handleAddSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPath.trim()) return;
    model.addDirectory(drive.id, {
      path: newPath.trim(),
      setupType: newType,
      minSpaceGb: newMinSpace,
      store: true,
      scanExisting: true,
      overflow: false,
    });
    setNewPath(`${drive.path}/data_${Date.now().toString().slice(-4)}`);
    setIsAdding(false);
  };

  return (
    <div className="dc-cockpit" role="region" aria-label="Drive Cockpit Console">
      {/* Modal / Dialog Header */}
      <header className="dc-header">
        <div className="dc-header-brand">
          <span className="dc-icon-mount">💾</span>
          <div>
            <div className="dc-title-row">
              <h3>{drive.path}</h3>
              <span className={`dc-badge dc-badge--${drive.health}`}>
                <span className="dc-dot" />
                {drive.health.toUpperCase()}
              </span>
              <span className="dc-tier-tag">TIER: {drive.tier.toUpperCase()}</span>
            </div>
            <p className="dc-subtitle">
              {drive.device} · Backend: <code>{drive.backendId}</code>
            </p>
          </div>
        </div>

        <div className="dc-header-stats">
          <div className="dc-stat-metric">
            <span className="dc-metric-label">Capacity</span>
            <strong>{isAvailable ? `${drive.percentUsed.toFixed(1)}%` : 'OFFLINE'}</strong>
          </div>
          <div className="dc-stat-metric">
            <span className="dc-metric-label">Free Headroom</span>
            <strong>{isAvailable ? formatBytes(drive.freeBytes) : '—'}</strong>
          </div>
          <div className="dc-stat-metric">
            <span className="dc-metric-label">Total Pool</span>
            <strong>{isAvailable ? formatBytes(drive.totalBytes) : '—'}</strong>
          </div>
        </div>
      </header>

      {/* Visual Multi-Segment Storage Strip */}
      <section className="dc-strip-section" aria-label="Disk Partition Allocation Strip">
        <div className="dc-strip-header">
          <span className="dc-strip-title">Storage Partitioning & Allocation Breakdown</span>
          <span className="dc-strip-legend">
            <span className="dc-legend-pill dc-legend--dl">Downloads ({pctDl}%)</span>
            <span className="dc-legend-pill dc-legend--meta">Metadata ({pctMeta}%)</span>
            <span className="dc-legend-pill dc-legend--sys">System/Other ({pctSys}%)</span>
            <span className="dc-legend-pill dc-legend--free">Free ({pctFree}%)</span>
          </span>
        </div>

        <div className="dc-partition-bar" role="meter" aria-valuenow={drive.percentUsed} aria-valuemin={0} aria-valuemax={100}>
          {isAvailable ? (
            <>
              <div className="dc-bar-seg dc-bar--dl" style={{ width: `${pctDl}%` }} title={`Downloads: ${formatBytes(dlBytes)}`} />
              <div className="dc-bar-seg dc-bar--meta" style={{ width: `${pctMeta}%` }} title={`Metadata: ${formatBytes(metaBytes)}`} />
              <div className="dc-bar-seg dc-bar--sys" style={{ width: `${pctSys}%` }} title={`System/Other: ${formatBytes(sysBytes)}`} />
              <div className="dc-bar-seg dc-bar--free" style={{ width: `${pctFree}%` }} title={`Free: ${formatBytes(free)}`} />
            </>
          ) : (
            <div className="dc-bar-seg dc-bar--offline" style={{ width: '100%' }}>Mount Offline</div>
          )}
        </div>

        {/* Hardware & Mount Telemetry Grid */}
        <div className="dc-telemetry-row">
          <div className="dc-telemetry-item">
            <span>Filesystem:</span>
            <code>{drive.fsType}</code>
          </div>
          <div className="dc-telemetry-item">
            <span>Mount Flags:</span>
            <code>{drive.mountOptions}</code>
          </div>
          <div className="dc-telemetry-item">
            <span>Peak IOPS:</span>
            <strong>{drive.iops}</strong>
          </div>
          <div className="dc-telemetry-item">
            <span>Avg Latency:</span>
            <strong>{drive.latencyMs} ms</strong>
          </div>
          {drive.temperatureC !== undefined && (
            <div className="dc-telemetry-item">
              <span>Drive Temp:</span>
              <strong className={drive.temperatureC > 45 ? 'dc-temp--hot' : ''}>{drive.temperatureC}°C</strong>
            </div>
          )}
        </div>
      </section>

      {/* Main Content: Directory Rules & Toggles */}
      <section className="dc-dirs-section">
        <div className="dc-dirs-header">
          <div>
            <h4>Mount Directories & Ingestion Governance</h4>
            <p className="dc-text-muted">
              Configure download destinations, reserve thresholds, and overflow routing flags.
            </p>
          </div>
          <button
            type="button"
            className="dc-btn dc-btn--primary"
            onClick={() => setIsAdding(!isAdding)}
            disabled={!isAvailable}
            title={isAvailable ? 'Add new directory to this mount' : 'Mount unavailable'}
          >
            {isAdding ? '✕ Cancel' : '+ Add Mount Directory'}
          </button>
        </div>

        {/* Add Directory Inline Tray */}
        {isAdding && (
          <form className="dc-add-tray" onSubmit={handleAddSubmit}>
            <h5>Create Directory Assignment</h5>
            <div className="dc-add-grid">
              <label className="dc-field">
                <span>Directory Path (Absolute)</span>
                <input
                  type="text"
                  className="dc-input mono"
                  value={newPath}
                  onChange={(e) => setNewPath(e.target.value)}
                  placeholder="/mnt/storage_fast/downloads/folder"
                  required
                />
              </label>

              <label className="dc-field">
                <span>Setup Type</span>
                <select
                  className="dc-input"
                  value={newType}
                  onChange={(e) => setNewType(e.target.value as 'download' | 'metadata')}
                >
                  <option value="download">⬇️ Download (Media Files)</option>
                  <option value="metadata">📋 Metadata (JSON & Logs)</option>
                </select>
              </label>

              <label className="dc-field">
                <span>Min Free Space (GB Threshold)</span>
                <input
                  type="number"
                  min={0}
                  max={20000}
                  className="dc-input"
                  value={newMinSpace}
                  onChange={(e) => setNewMinSpace(parseInt(e.target.value, 10) || 0)}
                />
              </label>
            </div>

            <div className="dc-add-actions">
              <span className="dc-tip">
                Storage changes require worker confirmation before active tasks adopt them.
              </span>
              <div className="dc-btn-group">
                <button type="button" className="dc-btn dc-btn--ghost" onClick={() => setIsAdding(false)}>
                  Cancel
                </button>
                <button type="submit" className="dc-btn dc-btn--primary">
                  Confirm & Register Directory
                </button>
              </div>
            </div>
          </form>
        )}

        {/* Directory Rows Table */}
        <div className="dc-table-wrap">
          <table className="dc-table">
            <thead>
              <tr>
                <th scope="col">Configured Directory</th>
                <th scope="col">Role</th>
                <th scope="col">Min Free Reserve</th>
                <th scope="col">Active Store</th>
                <th scope="col">Reuse Folders</th>
                <th scope="col">Overflow Dest</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {drive.directories.length === 0 ? (
                <tr>
                  <td colSpan={7} className="dc-empty">
                    No directories configured on this drive. Click &quot;Add Mount Directory&quot; above.
                  </td>
                </tr>
              ) : (
                drive.directories.map((dir) => (
                  <tr key={dir.id} className={!dir.store ? 'dc-row--inactive' : ''}>
                    {/* Path & stats */}
                    <td className="dc-cell-path">
                      <div className="dc-dir-path-wrap">
                        <code>{dir.path}</code>
                        <small className="dc-dir-meta">
                          {dir.estimatedFiles.toLocaleString()} files · {formatBytes(dir.usedBytes)} used
                        </small>
                      </div>
                    </td>

                    {/* Role badge */}
                    <td>
                      <span className={`dc-type-pill dc-type--${dir.setupType}`}>
                        {dir.setupType === 'download' ? '⬇️ Download' : '📋 Metadata'}
                      </span>
                    </td>

                    {/* Min Space Slider / Presets */}
                    <td>
                      <div className="dc-min-space-control">
                        <input
                          type="number"
                          className="dc-min-input"
                          min={0}
                          max={5000}
                          value={dir.minSpaceGb}
                          onChange={(e) =>
                            model.updateDirectoryConfig(drive.id, dir.id, {
                              minSpaceGb: parseInt(e.target.value, 10) || 0,
                            })
                          }
                          aria-label={`Minimum space for ${dir.path}`}
                        />
                        <span className="dc-unit">GB</span>
                        <div className="dc-quick-presets">
                          {[0, 20, 50, 100].map((preset) => (
                            <button
                              key={preset}
                              type="button"
                              className={`dc-preset-pill ${dir.minSpaceGb === preset ? 'is-active' : ''}`}
                              onClick={() =>
                                model.updateDirectoryConfig(drive.id, dir.id, {
                                  minSpaceGb: preset,
                                })
                              }
                            >
                              {preset}G
                            </button>
                          ))}
                        </div>
                      </div>
                    </td>

                    {/* Active Store toggle */}
                    <td>
                      <label className="dc-switch" title="Active - Store new downloaded files here">
                        <input
                          type="checkbox"
                          checked={dir.store}
                          onChange={(e) =>
                            model.updateDirectoryConfig(drive.id, dir.id, {
                              store: e.target.checked,
                            })
                          }
                          aria-label={`Store files in ${dir.path}`}
                        />
                        <span className="dc-slider" />
                      </label>
                    </td>

                    {/* Reuse performer folders */}
                    <td>
                      {dir.setupType === 'download' ? (
                        <label
                          className="dc-switch"
                          title="Reuse performer folders already discovered on this drive"
                        >
                          <input
                            type="checkbox"
                            checked={dir.scanExisting}
                            onChange={(e) =>
                              model.updateDirectoryConfig(drive.id, dir.id, {
                                scanExisting: e.target.checked,
                              })
                            }
                            aria-label={`Reuse existing folders for ${dir.path}`}
                          />
                          <span className="dc-slider" />
                        </label>
                      ) : (
                        <span className="dc-text-muted">—</span>
                      )}
                    </td>

                    {/* Overflow toggle */}
                    <td>
                      <label
                        className="dc-switch"
                        title="Use as overflow fallback destination when other drives are full"
                      >
                        <input
                          type="checkbox"
                          checked={dir.overflow}
                          onChange={(e) =>
                            model.updateDirectoryConfig(drive.id, dir.id, {
                              overflow: e.target.checked,
                            })
                          }
                          aria-label={`Overflow destination for ${dir.path}`}
                        />
                        <span className="dc-slider" />
                      </label>
                    </td>

                    {/* Delete action */}
                    <td>
                      <button
                        type="button"
                        className="dc-btn dc-btn--danger-ghost"
                        onClick={() => model.removeDirectory(drive.id, dir.id)}
                        title="Remove directory assignment from UltimaScraper configuration"
                        aria-label={`Remove directory ${dir.path}`}
                      >
                        🗑️
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Footer: Worker Sync Status & Save Action */}
      <footer className="dc-footer">
        <div className="dc-worker-status">
          <span className="dc-dot dc-dot--acknowledged" />
          <span>
            Worker: <strong>{model.workerPropagation.targetBackendId}</strong> · State:{' '}
            <strong className="dc-text-accent">
              {model.workerPropagation.status.toUpperCase()}
            </strong>{' '}
            (Rev {model.workerPropagation.revision})
          </span>
          <small className="dc-text-muted">· {model.workerPropagation.message}</small>
        </div>

        <div className="dc-footer-actions">
          <button
            type="button"
            className="dc-btn dc-btn--secondary"
            onClick={() => model.reset()}
          >
            Revert Changes
          </button>
          <button
            type="button"
            className="dc-btn dc-btn--primary"
            onClick={() =>
              model.updateDirectoryConfig(drive.id, drive.directories[0]?.id || '', {})
            }
          >
            ✓ Save & Propagate to Worker
          </button>
        </div>
      </footer>
    </div>
  );
}
