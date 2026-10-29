import { useState } from 'react';
import type { DrivesMockModel } from './drivesMockModel';
import { formatBytes } from '../../../shared/lib/format';

type StudioTab = 'overview' | 'directories' | 'token-studio' | 'sync';

export function DriveStudioProConcept({ model }: { model: DrivesMockModel }) {
  const drive = model.selectedDrive;
  const isAvailable = drive.isAvailable;
  const [activeTab, setActiveTab] = useState<StudioTab>('overview');

  const [activeTokenTarget, setActiveTokenTarget] = useState<'dir' | 'file'>('dir');

  const TOKENS = [
    '{site_name}',
    '{first_username_letter}',
    '{user_username}',
    '{content_type}',
    '{media_type}',
    '{date}',
    '{post_id}',
    '{media_id}',
    '{filename}',
    '{ext}',
  ];

  const insertToken = (token: string) => {
    if (activeTokenTarget === 'dir') {
      const curr = model.settings.downloadDirFormat;
      model.updateSettings({ downloadDirFormat: `${curr}/${token}`.replace(/\/+/g, '/') });
    } else {
      const curr = model.settings.downloadFilenameFormat;
      model.updateSettings({ downloadFilenameFormat: `${curr}_${token}` });
    }
  };

  return (
    <div className="pro-studio" role="region" aria-label="Drive Studio Pro Diagnostics Hub">
      {/* Top Pro Header */}
      <header className="pro-header">
        <div className="pro-header-brand">
          <span className="pro-avatar">⚡</span>
          <div>
            <div className="pro-title-line">
              <h3>{drive.path}</h3>
              <span className={`pro-badge pro-badge--${drive.health}`}>
                {drive.health.toUpperCase()}
              </span>
              <span className="pro-badge-tier">{drive.tier.toUpperCase()} TIER</span>
            </div>
            <p className="pro-subtitle">
              {drive.device} · {drive.fsType} · Worker: <code>{drive.backendId}</code>
            </p>
          </div>
        </div>

        {/* Tab Navigation */}
        <nav className="pro-tab-bar" aria-label="Studio Pro tabs">
          <button
            type="button"
            className={`pro-tab-btn ${activeTab === 'overview' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('overview')}
          >
            📊 Mount &amp; Benchmark
          </button>
          <button
            type="button"
            className={`pro-tab-btn ${activeTab === 'directories' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('directories')}
          >
            📁 Directories ({drive.directories.length})
          </button>
          <button
            type="button"
            className={`pro-tab-btn ${activeTab === 'token-studio' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('token-studio')}
          >
            🧩 Token Studio
          </button>
          <button
            type="button"
            className={`pro-tab-btn ${activeTab === 'sync' ? 'is-active' : ''}`}
            onClick={() => setActiveTab('sync')}
          >
            🔄 Worker Sync
          </button>
        </nav>
      </header>

      {/* Tab 1: Mount & I/O Benchmark */}
      {activeTab === 'overview' && (
        <div className="pro-body">
          <div className="pro-overview-grid">
            {/* Storage Capacity Gauge Card */}
            <div className="pro-card">
              <div className="pro-card-head">
                <h5>Capacity Utilization</h5>
                <strong className={drive.percentUsed > 85 ? 'pro-text-warning' : 'pro-text-accent'}>
                  {isAvailable ? `${drive.percentUsed.toFixed(1)}%` : 'OFFLINE'}
                </strong>
              </div>
              <div className="pro-meter-wrap">
                <div
                  className="pro-meter-bar"
                  style={{ width: `${Math.min(100, drive.percentUsed)}%` }}
                />
              </div>
              <div className="pro-capacity-details">
                <div>
                  <span>USED SPACE</span>
                  <strong>{isAvailable ? formatBytes(drive.usedBytes) : '—'}</strong>
                </div>
                <div>
                  <span>AVAILABLE FREE</span>
                  <strong className="pro-text-accent">
                    {isAvailable ? formatBytes(drive.freeBytes) : '—'}
                  </strong>
                </div>
                <div>
                  <span>TOTAL MOUNT</span>
                  <strong>{isAvailable ? formatBytes(drive.totalBytes) : '—'}</strong>
                </div>
              </div>
            </div>

            {/* Hardware & Filesystem Card */}
            <div className="pro-card">
              <h5>Mountpoint Capabilities &amp; Telemetry</h5>
              <dl className="pro-dl">
                <div>
                  <dt>Filesystem</dt>
                  <dd><code>{drive.fsType}</code></dd>
                </div>
                <div>
                  <dt>Mount Flags</dt>
                  <dd><code className="pro-code-sm">{drive.mountOptions}</code></dd>
                </div>
                <div>
                  <dt>Target Device</dt>
                  <dd><code>{drive.device}</code></dd>
                </div>
                <div>
                  <dt>Direct I/O Support</dt>
                  <dd>O_DIRECT / io_uring (Enabled)</dd>
                </div>
                <div>
                  <dt>Extended Attributes (xattr)</dt>
                  <dd>Supported (user.ultima.* tags)</dd>
                </div>
              </dl>
            </div>
          </div>

          {/* Synthetic I/O Benchmark Studio */}
          <div className="pro-card pro-card--benchmark">
            <div className="pro-benchmark-head">
              <div>
                <h5>Synthetic I/O Performance Profiler</h5>
                <p>Run simulated sequential read/write and random 4K IOPS diagnostics on this mount.</p>
              </div>
              <button
                type="button"
                className="pro-btn pro-btn--primary"
                onClick={model.runBenchmark}
                disabled={model.isBenchmarking || !isAvailable}
              >
                {model.isBenchmarking ? '⏳ Running Benchmark...' : '▶ Run I/O Benchmark'}
              </button>
            </div>

            {model.isBenchmarking && (
              <div className="pro-benchmark-running">
                <span className="pro-spinner" />
                <span>Benchmarking block device write latency and synchronous flush rate...</span>
              </div>
            )}

            {model.benchmarkResult && !model.isBenchmarking && (
              <div className="pro-benchmark-results">
                <div className="pro-result-stat">
                  <span>SEQUENTIAL READ</span>
                  <strong>{model.benchmarkResult.readSpeedMb} MB/s</strong>
                </div>
                <div className="pro-result-stat">
                  <span>SEQUENTIAL WRITE</span>
                  <strong>{model.benchmarkResult.writeSpeedMb} MB/s</strong>
                </div>
                <div className="pro-result-stat">
                  <span>RANDOM 4K IOPS</span>
                  <strong className="pro-text-accent">
                    {model.benchmarkResult.iops.toLocaleString()} IOPS
                  </strong>
                </div>
                <div className="pro-result-stat">
                  <span>AVG FLUSH LATENCY</span>
                  <strong>{model.benchmarkResult.latencyMs} ms</strong>
                </div>
              </div>
            )}

            {!model.benchmarkResult && !model.isBenchmarking && (
              <div className="pro-benchmark-empty">
                No active benchmark recorded for this session. Click &quot;Run I/O Benchmark&quot; to test.
              </div>
            )}
          </div>
        </div>
      )}

      {/* Tab 2: Directories */}
      {activeTab === 'directories' && (
        <div className="pro-body">
          <div className="pro-section-header">
            <h4>Configured Storage Directories on {drive.name}</h4>
            <span className="pro-text-muted">
              {drive.directories.length} Active Targets
            </span>
          </div>

          <div className="pro-dir-grid">
            {drive.directories.map((dir) => (
              <div key={dir.id} className="pro-dir-card">
                <div className="pro-dir-card-head">
                  <span className={`pro-dir-type-pill pro-dir--${dir.setupType}`}>
                    {dir.setupType === 'download' ? '⬇️ Download' : '📋 Metadata'}
                  </span>
                  <div className="pro-dir-pills">
                    {dir.store && <span className="pro-pill-active">STORE</span>}
                    {dir.overflow && <span className="pro-pill-overflow">OVERFLOW</span>}
                  </div>
                </div>

                <code className="pro-dir-path-title">{dir.path}</code>

                <div className="pro-dir-meta-row">
                  <div>
                    <span>RESERVE BARRIER</span>
                    <strong>{dir.minSpaceGb} GB min</strong>
                  </div>
                  <div>
                    <span>EST. FILES</span>
                    <strong>{dir.estimatedFiles.toLocaleString()}</strong>
                  </div>
                  <div>
                    <span>CONSUMED</span>
                    <strong>{formatBytes(dir.usedBytes)}</strong>
                  </div>
                </div>

                <div className="pro-dir-toggles">
                  <label className="pro-check-label">
                    <input
                      type="checkbox"
                      checked={dir.store}
                      onChange={(e) =>
                        model.updateDirectoryConfig(drive.id, dir.id, {
                          store: e.target.checked,
                        })
                      }
                    />
                    <span>Store new files</span>
                  </label>

                  {dir.setupType === 'download' && (
                    <label className="pro-check-label">
                      <input
                        type="checkbox"
                        checked={dir.scanExisting}
                        onChange={(e) =>
                          model.updateDirectoryConfig(drive.id, dir.id, {
                            scanExisting: e.target.checked,
                          })
                        }
                      />
                      <span>Reuse performer folders</span>
                    </label>
                  )}

                  <label className="pro-check-label">
                    <input
                      type="checkbox"
                      checked={dir.overflow}
                      onChange={(e) =>
                        model.updateDirectoryConfig(drive.id, dir.id, {
                          overflow: e.target.checked,
                        })
                      }
                    />
                    <span>Spillway overflow</span>
                  </label>
                </div>

                <div className="pro-dir-actions">
                  <button
                    type="button"
                    className="pro-btn pro-btn--danger-sm"
                    onClick={() => model.removeDirectory(drive.id, dir.id)}
                  >
                    Unlink Directory
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tab 3: Token & Template Studio */}
      {activeTab === 'token-studio' && (
        <div className="pro-body">
          <div className="pro-studio-split">
            {/* Left: Token Palette & Formatter */}
            <div className="pro-card">
              <h5>Clickable Variable Token Palette</h5>
              <p className="pro-text-muted">
                Click any token to append it into the active target template below.
              </p>

              <div className="pro-token-tray">
                {TOKENS.map((token) => (
                  <button
                    key={token}
                    type="button"
                    className="pro-token-pill"
                    onClick={() => insertToken(token)}
                  >
                    + {token}
                  </button>
                ))}
              </div>

              <div className="pro-target-toggle" style={{ marginTop: '16px' }}>
                <span>Active Target:</span>
                <button
                  type="button"
                  className={`pro-toggle-choice ${activeTokenTarget === 'dir' ? 'is-active' : ''}`}
                  onClick={() => setActiveTokenTarget('dir')}
                >
                  Directory Format
                </button>
                <button
                  type="button"
                  className={`pro-toggle-choice ${activeTokenTarget === 'file' ? 'is-active' : ''}`}
                  onClick={() => setActiveTokenTarget('file')}
                >
                  Filename Format
                </button>
              </div>

              <div className="pro-format-inputs" style={{ marginTop: '16px' }}>
                <label className="pro-field">
                  <span>Directory Hierarchy Expression</span>
                  <input
                    type="text"
                    className="pro-input mono"
                    value={model.settings.downloadDirFormat}
                    onChange={(e) => model.updateSettings({ downloadDirFormat: e.target.value })}
                  />
                </label>

                <label className="pro-field" style={{ marginTop: '12px' }}>
                  <span>Filename Expression</span>
                  <input
                    type="text"
                    className="pro-input mono"
                    value={model.settings.downloadFilenameFormat}
                    onChange={(e) => model.updateSettings({ downloadFilenameFormat: e.target.value })}
                  />
                </label>

                <label className="pro-field" style={{ marginTop: '12px' }}>
                  <span>Metadata Format Expression</span>
                  <input
                    type="text"
                    className="pro-input mono"
                    value={model.settings.metadataDirFormat}
                    onChange={(e) => model.updateSettings({ metadataDirFormat: e.target.value })}
                  />
                </label>
              </div>
            </div>

            {/* Right: Live Resolution Sandbox */}
            <div className="pro-card pro-card--sandbox">
              <h5>Real-Time Path Resolution Sandbox</h5>
              <p className="pro-text-muted">
                Evaluated against sample entity: <code>OnlyFans / @belle_delphine</code>
              </p>

              <div className="pro-sandbox-block">
                <span className="pro-sandbox-title">CANONICAL DOWNLOAD DESTINATION:</span>
                <code className="pro-sandbox-code">{model.resolvedSample.downloadFullPath}</code>
              </div>

              <div className="pro-sandbox-block">
                <span className="pro-sandbox-title">CANONICAL METADATA DESTINATION:</span>
                <code className="pro-sandbox-code">{model.resolvedSample.metadataFullPath}</code>
              </div>

              <div className="pro-sandbox-block">
                <span className="pro-sandbox-title">BACKWARD-COMPATIBLE ALT LOOKUPS:</span>
                {model.resolvedSample.altPaths.map((alt, i) => (
                  <code key={i} className="pro-sandbox-code pro-code--alt">
                    {alt}
                  </code>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab 4: Worker Sync & Audit */}
      {activeTab === 'sync' && (
        <div className="pro-body">
          <div className="pro-card">
            <h5>Worker Daemon Topology &amp; Configuration Propagation</h5>
            <p className="pro-text-muted">
              UltimaScraper storage topology is synchronized to worker daemons using revision-versioned RPC events.
            </p>

            <div className="pro-sync-timeline">
              <div className="pro-sync-row">
                <span className="pro-sync-dot is-ack" />
                <div className="pro-sync-details">
                  <strong>Worker: {model.workerPropagation.targetBackendId}</strong>
                  <p>{model.workerPropagation.message}</p>
                  <small>
                    State: <code>{model.workerPropagation.status}</code> · Revision: <code>{model.workerPropagation.revision}</code> · Version: <code>v{model.workerPropagation.configVersion}</code>
                  </small>
                </div>
                <span className="pro-sync-time">{model.workerPropagation.lastSyncTime}</span>
              </div>

              <div className="pro-sync-row">
                <span className="pro-sync-dot is-ack" />
                <div className="pro-sync-details">
                  <strong>Worker: node_worker_frankfurt</strong>
                  <p>Storage mount confirmation received for remote scratch staging queue</p>
                  <small>State: <code>acknowledged</code> · Revision: <code>rev-818</code></small>
                </div>
                <span className="pro-sync-time">3 minutes ago</span>
              </div>
            </div>

            <div className="pro-sync-actions" style={{ marginTop: '20px' }}>
              <button
                type="button"
                className="pro-btn pro-btn--primary"
                onClick={() => model.updateSettings({})}
              >
                🔄 Force Global Worker Sync
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
