import { useState } from 'react';
import type { DrivesMockModel } from './drivesMockModel';
import { formatBytes } from '../../../shared/lib/format';

export function DualPaneStudioConcept({ model }: { model: DrivesMockModel }) {
  const drive = model.selectedDrive;
  const isAvailable = drive.isAvailable;

  // Selected view on the right pane: either a directory id or 'global-formats'
  const [selectedPaneId, setSelectedPaneId] = useState<string>(
    drive.directories[0]?.id || 'global-formats'
  );
  const [showAddModal, setShowAddModal] = useState(false);
  const [newDirPath, setNewDirPath] = useState(`${drive.path}/new_downloads`);
  const [newDirType, setNewDirType] = useState<'download' | 'metadata'>('download');

  const activeDir = drive.directories.find((d) => d.id === selectedPaneId);
  const isGlobal = selectedPaneId === 'global-formats';

  const handleAddSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newDirPath.trim()) return;
    model.addDirectory(drive.id, {
      path: newDirPath.trim(),
      setupType: newDirType,
      minSpaceGb: 40,
      store: true,
      scanExisting: true,
      overflow: false,
    });
    setShowAddModal(false);
  };

  return (
    <div className="dp-studio" role="region" aria-label="Dual-Pane Storage Architect">
      {/* Top Header */}
      <header className="dp-header">
        <div className="dp-header-left">
          <div className="dp-drive-avatar">💽</div>
          <div>
            <div className="dp-header-title">
              <h3>{drive.path}</h3>
              <span className={`dp-status-badge dp-status--${drive.health}`}>
                {drive.health}
              </span>
              <span className="dp-tag-backend">Backend: {drive.backendId}</span>
            </div>
            <p className="dp-header-sub">
              {drive.device} · {drive.fsType} · {drive.iops}
            </p>
          </div>
        </div>

        <div className="dp-header-metrics">
          <div className="dp-mini-metric">
            <span className="dp-metric-title">USED</span>
            <strong>{isAvailable ? formatBytes(drive.usedBytes) : '—'}</strong>
          </div>
          <div className="dp-mini-metric">
            <span className="dp-metric-title">FREE</span>
            <strong className="dp-text-accent">
              {isAvailable ? formatBytes(drive.freeBytes) : '—'}
            </strong>
          </div>
          <div className="dp-mini-metric">
            <span className="dp-metric-title">CAPACITY</span>
            <strong className={drive.percentUsed > 85 ? 'dp-text-warning' : ''}>
              {isAvailable ? `${drive.percentUsed.toFixed(1)}%` : 'OFFLINE'}
            </strong>
          </div>
        </div>
      </header>

      {/* Main Dual-Pane Body */}
      <div className="dp-panes-layout">
        {/* Left Pane: Hierarchy & Inventory Navigation */}
        <nav className="dp-left-pane" aria-label="Drive directory inventory">
          <div className="dp-pane-title-row">
            <span>DIRECTORIES ON THIS DRIVE</span>
            <button
              type="button"
              className="dp-btn-small"
              onClick={() => setShowAddModal(true)}
              disabled={!isAvailable}
              title="Add directory"
            >
              + Add
            </button>
          </div>

          {/* Group 1: Download Directories */}
          <div className="dp-group">
            <div className="dp-group-label">
              <span>⬇️ Download Directories ({drive.directories.filter((d) => d.setupType === 'download').length})</span>
            </div>
            <div className="dp-item-list">
              {drive.directories
                .filter((d) => d.setupType === 'download')
                .map((dir) => (
                  <button
                    type="button"
                    key={dir.id}
                    className={`dp-nav-item ${selectedPaneId === dir.id ? 'is-selected' : ''}`}
                    onClick={() => setSelectedPaneId(dir.id)}
                  >
                    <div className="dp-nav-item-top">
                      <code className="dp-nav-path">{dir.path.split('/').pop() || dir.path}</code>
                      {dir.store && <span className="dp-pill dp-pill--active">STORE</span>}
                      {dir.overflow && <span className="dp-pill dp-pill--overflow">OVERFLOW</span>}
                    </div>
                    <div className="dp-nav-item-sub">
                      <span>{dir.path}</span>
                      <small>{formatBytes(dir.usedBytes)}</small>
                    </div>
                  </button>
                ))}
            </div>
          </div>

          {/* Group 2: Metadata Directories */}
          <div className="dp-group">
            <div className="dp-group-label">
              <span>📋 Metadata Directories ({drive.directories.filter((d) => d.setupType === 'metadata').length})</span>
            </div>
            <div className="dp-item-list">
              {drive.directories
                .filter((d) => d.setupType === 'metadata')
                .map((dir) => (
                  <button
                    type="button"
                    key={dir.id}
                    className={`dp-nav-item ${selectedPaneId === dir.id ? 'is-selected' : ''}`}
                    onClick={() => setSelectedPaneId(dir.id)}
                  >
                    <div className="dp-nav-item-top">
                      <code className="dp-nav-path">{dir.path.split('/').pop() || dir.path}</code>
                      {dir.store && <span className="dp-pill dp-pill--active">STORE</span>}
                    </div>
                    <div className="dp-nav-item-sub">
                      <span>{dir.path}</span>
                      <small>{formatBytes(dir.usedBytes)}</small>
                    </div>
                  </button>
                ))}
            </div>
          </div>

          {/* Group 3: Global Routing & Token Engine */}
          <div className="dp-group dp-group--special">
            <button
              type="button"
              className={`dp-nav-item dp-nav-item--global ${isGlobal ? 'is-selected' : ''}`}
              onClick={() => setSelectedPaneId('global-formats')}
            >
              <div className="dp-nav-item-top">
                <span className="dp-icon-star">⚡</span>
                <strong>Routing &amp; Token Engine</strong>
              </div>
              <small className="dp-nav-item-sub">Path templates, alt formats &amp; staging</small>
            </button>
          </div>
        </nav>

        {/* Right Pane: Inspector / Detail Studio */}
        <section className="dp-right-pane" aria-label="Selected configuration details">
          {activeDir && !isGlobal && (
            <div className="dp-inspector-content">
              {/* Directory Header */}
              <div className="dp-inspector-header">
                <div>
                  <div className="dp-dir-role-tag">
                    {activeDir.setupType === 'download' ? '⬇️ Download Directory' : '📋 Metadata Directory'}
                  </div>
                  <h4 className="dp-dir-title">
                    <code>{activeDir.path}</code>
                  </h4>
                </div>
                <div className="dp-dir-quick-stats">
                  <div>
                    <span>EST. FILES</span>
                    <strong>{activeDir.estimatedFiles.toLocaleString()}</strong>
                  </div>
                  <div>
                    <span>SPACE CONSUMED</span>
                    <strong>{formatBytes(activeDir.usedBytes)}</strong>
                  </div>
                </div>
              </div>

              {/* Governance & Policy Switches */}
              <div className="dp-card dp-card--switches">
                <h5>Ingestion Policies &amp; Permissions</h5>

                <div className="dp-switch-row">
                  <div className="dp-switch-info">
                    <strong>Active Storage Destination</strong>
                    <p>New files are actively downloaded or written to this mount directory.</p>
                  </div>
                  <label className="dp-switch">
                    <input
                      type="checkbox"
                      checked={activeDir.store}
                      onChange={(e) =>
                        model.updateDirectoryConfig(drive.id, activeDir.id, {
                          store: e.target.checked,
                        })
                      }
                      aria-label="Active store destination"
                    />
                    <span className="dp-slider" />
                  </label>
                </div>

                {activeDir.setupType === 'download' && (
                  <div className="dp-switch-row">
                    <div className="dp-switch-info">
                      <strong>Reuse Performer Folders</strong>
                      <p>
                        Scans and matches existing creator directories on this disk instead of
                        creating duplicates.
                      </p>
                    </div>
                    <label className="dp-switch">
                      <input
                        type="checkbox"
                        checked={activeDir.scanExisting}
                        onChange={(e) =>
                          model.updateDirectoryConfig(drive.id, activeDir.id, {
                            scanExisting: e.target.checked,
                          })
                        }
                        aria-label="Reuse performer folders"
                      />
                      <span className="dp-slider" />
                    </label>
                  </div>
                )}

                <div className="dp-switch-row">
                  <div className="dp-switch-info">
                    <strong>Overflow Fallback Spillway</strong>
                    <p>
                      Receive incoming downloads when primary drives breach their reserve quota.
                    </p>
                  </div>
                  <label className="dp-switch">
                    <input
                      type="checkbox"
                      checked={activeDir.overflow}
                      onChange={(e) =>
                        model.updateDirectoryConfig(drive.id, activeDir.id, {
                          overflow: e.target.checked,
                        })
                      }
                      aria-label="Overflow spillway"
                    />
                    <span className="dp-slider" />
                  </label>
                </div>
              </div>

              {/* Minimum Free Space Watermark */}
              <div className="dp-card">
                <div className="dp-card-head">
                  <h5>Minimum Free Space Watermark</h5>
                  <strong className="dp-accent-value">{activeDir.minSpaceGb} GB</strong>
                </div>
                <p className="dp-card-desc">
                  When free space on this mount drops below this threshold, UltimaScraper will stop
                  writing here and spill over to overflow mounts.
                </p>

                <div className="dp-range-wrapper">
                  <input
                    type="range"
                    min={0}
                    max={1000}
                    step={10}
                    value={activeDir.minSpaceGb}
                    onChange={(e) =>
                      model.updateDirectoryConfig(drive.id, activeDir.id, {
                        minSpaceGb: parseInt(e.target.value, 10),
                      })
                    }
                    className="dp-range"
                    aria-label="Minimum space slider"
                  />
                  <div className="dp-range-ticks">
                    <span>0 GB (No limit)</span>
                    <span>250 GB</span>
                    <span>500 GB</span>
                    <span>1,000 GB</span>
                  </div>
                </div>
              </div>

              {/* Danger Zone: Remove Directory */}
              <div className="dp-card dp-card--danger">
                <h5>Danger Zone: Directory Assignment</h5>
                <p>
                  Removing this path removes it from the UltimaScraper database and worker routing.
                  <strong> No files on the actual drive will be deleted or modified.</strong>
                </p>
                <button
                  type="button"
                  className="dp-btn-danger"
                  onClick={() => model.removeDirectory(drive.id, activeDir.id)}
                >
                  🗑️ Unlink &amp; Remove from Configuration
                </button>
              </div>
            </div>
          )}

          {isGlobal && (
            <div className="dp-inspector-content">
              <div className="dp-inspector-header">
                <div>
                  <div className="dp-dir-role-tag">Global Storage Architecture</div>
                  <h4 className="dp-dir-title">Token Path Resolver &amp; Format Engine</h4>
                </div>
                <span className="dp-badge-live">LIVE SYNCED</span>
              </div>

              {/* Live Preview Banner */}
              <div className="dp-live-preview-box">
                <div className="dp-preview-title">
                  <span>⚡ LIVE RESOLVED SAMPLE PATH</span>
                  <small>OnlyFans / @belle_delphine</small>
                </div>
                <code className="dp-preview-code">{model.resolvedSample.downloadFullPath}</code>
                <div className="dp-preview-meta">
                  <span>Resolved Metadata: <code>{model.resolvedSample.metadataFullPath}</code></span>
                </div>
              </div>

              {/* Format Inputs */}
              <div className="dp-card">
                <h5>Directory Hierarchy Format</h5>
                <input
                  type="text"
                  className="dp-input mono"
                  value={model.settings.downloadDirFormat}
                  onChange={(e) => model.updateSettings({ downloadDirFormat: e.target.value })}
                  aria-label="Download directory format"
                />
                <span className="dp-hint">
                  Tokens: <code>{'{site_name}'}</code>, <code>{'{first_username_letter}'}</code>, <code>{'{user_username}'}</code>, <code>{'{content_type}'}</code>, <code>{'{media_type}'}</code>
                </span>

                <h5 style={{ marginTop: '16px' }}>Filename Formatting Template</h5>
                <input
                  type="text"
                  className="dp-input mono"
                  value={model.settings.downloadFilenameFormat}
                  onChange={(e) => model.updateSettings({ downloadFilenameFormat: e.target.value })}
                  aria-label="Download filename format"
                />
                <span className="dp-hint">
                  Tokens: <code>{'{filename}'}</code>, <code>{'{media_id}'}</code>, <code>{'{post_id}'}</code>, <code>{'{date}'}</code>, <code>{'{ext}'}</code>
                </span>

                <div className="dp-grid-2" style={{ marginTop: '16px' }}>
                  <label className="dp-field">
                    <span>Date Format</span>
                    <input
                      type="text"
                      className="dp-input mono"
                      value={model.settings.downloadDateFormat}
                      onChange={(e) => model.updateSettings({ downloadDateFormat: e.target.value })}
                    />
                  </label>
                  <label className="dp-field">
                    <span>Max Text Length</span>
                    <input
                      type="number"
                      className="dp-input"
                      value={model.settings.downloadTextLength}
                      onChange={(e) =>
                        model.updateSettings({ downloadTextLength: parseInt(e.target.value, 10) || 255 })
                      }
                    />
                  </label>
                </div>

                <label className="dp-checkbox-row" style={{ marginTop: '14px' }}>
                  <input
                    type="checkbox"
                    checked={model.settings.downloadOverwrite}
                    onChange={(e) => model.updateSettings({ downloadOverwrite: e.target.checked })}
                  />
                  <span>Overwrite existing destination files when re-scraped</span>
                </label>
              </div>

              {/* Alternative Legacy Formats */}
              <div className="dp-card">
                <h5>Alternative Detection Formats (Backward Compatibility)</h5>
                <p className="dp-card-desc">
                  UltimaScraper checks these directories when detecting pre-existing archives to prevent duplicate downloads.
                </p>
                <div className="dp-alt-list">
                  {model.settings.downloadAltDirectoryFormats.map((alt, idx) => (
                    <div key={idx} className="dp-alt-item">
                      <code>{alt}</code>
                      <button
                        type="button"
                        className="dp-btn-remove"
                        onClick={() =>
                          model.updateSettings({
                            downloadAltDirectoryFormats: model.settings.downloadAltDirectoryFormats.filter(
                              (_, i) => i !== idx
                            ),
                          })
                        }
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </section>
      </div>

      {/* Modal Dialog for Adding New Directory */}
      {showAddModal && (
        <div className="dp-modal-overlay" onClick={() => setShowAddModal(false)}>
          <div className="dp-modal-dialog" onClick={(e) => e.stopPropagation()}>
            <h4>Add Mount Directory</h4>
            <p>Register a storage target under <code>{drive.path}</code>.</p>
            <form onSubmit={handleAddSubmit}>
              <label className="dp-field">
                <span>Directory Path</span>
                <input
                  type="text"
                  className="dp-input mono"
                  value={newDirPath}
                  onChange={(e) => setNewDirPath(e.target.value)}
                  required
                />
              </label>

              <label className="dp-field" style={{ marginTop: '12px' }}>
                <span>Type</span>
                <select
                  className="dp-input"
                  value={newDirType}
                  onChange={(e) => setNewDirType(e.target.value as 'download' | 'metadata')}
                >
                  <option value="download">Download Directory</option>
                  <option value="metadata">Metadata Directory</option>
                </select>
              </label>

              <div className="dp-modal-actions" style={{ marginTop: '18px' }}>
                <button type="button" className="dp-btn-secondary" onClick={() => setShowAddModal(false)}>
                  Cancel
                </button>
                <button type="submit" className="dp-btn-primary">
                  Add Directory
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
