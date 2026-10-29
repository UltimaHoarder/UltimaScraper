import { useState } from 'react';
import type { DrivesMockModel, StorageTier } from './drivesMockModel';
import { formatBytes } from '../../../shared/lib/format';

export function CapacityCommanderConcept({ model }: { model: DrivesMockModel }) {
  const drive = model.selectedDrive;
  const isAvailable = drive.isAvailable;

  const [selectedDirIds, setSelectedDirIds] = useState<Set<string>>(new Set());
  const [softWatermark, setSoftWatermark] = useState<number>(75);
  const [hardWatermark, setHardWatermark] = useState<number>(90);
  const [currentTier, setCurrentTier] = useState<StorageTier>(drive.tier);

  // Ingestion burn-rate telemetry (simulated 34.5 GB/day)
  const dailyBurnGb = 34.5;
  const freeGb = drive.freeBytes / (1024 * 1024 * 1024);
  const daysRunway = isAvailable && freeGb > 0 ? Math.floor(freeGb / dailyBurnGb) : 0;

  const toggleSelectDir = (id: string) => {
    setSelectedDirIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    if (selectedDirIds.size === drive.directories.length) {
      setSelectedDirIds(new Set());
    } else {
      setSelectedDirIds(new Set(drive.directories.map((d) => d.id)));
    }
  };

  const batchApply = (patch: { store?: boolean; overflow?: boolean; minSpaceGb?: number }) => {
    selectedDirIds.forEach((dirId) => {
      model.updateDirectoryConfig(drive.id, dirId, patch);
    });
    setSelectedDirIds(new Set());
  };

  return (
    <div className="cc-commander" role="region" aria-label="Capacity Commander Storage Studio">
      {/* Header Banner */}
      <header className="cc-header">
        <div className="cc-header-left">
          <span className="cc-icon-shield">🛡️</span>
          <div>
            <div className="cc-title-row">
              <h3>{drive.path}</h3>
              <span className={`cc-tier-badge cc-tier--${currentTier}`}>
                TIER: {currentTier.toUpperCase()}
              </span>
              <span className={`cc-status-pill cc-status--${drive.health}`}>
                {drive.health.toUpperCase()}
              </span>
            </div>
            <p className="cc-subtitle">
              {drive.device} · Backend: <code>{drive.backendId}</code>
            </p>
          </div>
        </div>

        {/* Tier Selector Buttons */}
        <div className="cc-tier-selector" role="group" aria-label="Storage Tier Selector">
          {(['hot', 'warm', 'cold', 'cloud'] as StorageTier[]).map((tier) => (
            <button
              key={tier}
              type="button"
              className={`cc-tier-btn ${currentTier === tier ? 'is-active' : ''}`}
              onClick={() => setCurrentTier(tier)}
            >
              {tier.toUpperCase()}
            </button>
          ))}
        </div>
      </header>

      {/* Runway & Predictive Velocity Bar */}
      <section className="cc-runway-banner">
        <div className="cc-runway-item">
          <span className="cc-runway-label">ESTIMATED RUNWAY</span>
          <strong className={daysRunway < 14 ? 'cc-text-danger' : daysRunway < 30 ? 'cc-text-warning' : 'cc-text-accent'}>
            {isAvailable ? `~${daysRunway} DAYS` : 'OFFLINE'}
          </strong>
          <small>At {dailyBurnGb} GB/day average ingest rate</small>
        </div>
        <div className="cc-runway-item">
          <span className="cc-runway-label">RESERVED HEADROOM</span>
          <strong>{isAvailable ? formatBytes(drive.freeBytes) : '—'}</strong>
          <small>{((drive.freeBytes / (drive.totalBytes || 1)) * 100).toFixed(1)}% free</small>
        </div>
        <div className="cc-runway-item">
          <span className="cc-runway-label">SOFT WARNING MARK</span>
          <strong className="cc-text-warning">{softWatermark}%</strong>
          <small>Alert triggers in fleet view</small>
        </div>
        <div className="cc-runway-item">
          <span className="cc-runway-label">HARD OVERFLOW CUTOFF</span>
          <strong className="cc-text-danger">{hardWatermark}%</strong>
          <small>Diverts jobs to spillways</small>
        </div>
      </section>

      {/* Storage Watermark Sliders */}
      <section className="cc-watermarks-card">
        <div className="cc-card-title">
          <h4>Dynamic Storage Waterlines &amp; Ingestion Safeguards</h4>
          <span className="cc-text-muted">Autonomous safety boundaries</span>
        </div>

        <div className="cc-sliders-grid">
          <div className="cc-slider-box">
            <div className="cc-slider-label">
              <span>Soft Warning Alert Threshold</span>
              <strong>{softWatermark}% Used</strong>
            </div>
            <input
              type="range"
              min={50}
              max={85}
              value={softWatermark}
              onChange={(e) => setSoftWatermark(parseInt(e.target.value, 10))}
              className="cc-range cc-range--warning"
              aria-label="Soft watermark threshold"
            />
            <small>Triggers notifications and highlights this mount in the Fleet Register.</small>
          </div>

          <div className="cc-slider-box">
            <div className="cc-slider-label">
              <span>Hard Ingestion Spillway Threshold</span>
              <strong>{hardWatermark}% Used</strong>
            </div>
            <input
              type="range"
              min={80}
              max={98}
              value={hardWatermark}
              onChange={(e) => setHardWatermark(parseInt(e.target.value, 10))}
              className="cc-range cc-range--danger"
              aria-label="Hard watermark threshold"
            />
            <small>Immediately ceases write allocation and forces fallback overflow mounts.</small>
          </div>
        </div>
      </section>

      {/* Directory Fleet Table with Batch Checkboxes */}
      <section className="cc-table-section">
        <div className="cc-table-header">
          <div className="cc-table-title">
            <h4>Directories &amp; Quota Partitions ({drive.directories.length})</h4>
            <p className="cc-text-muted">Select multiple directories to execute batch storage policies.</p>
          </div>

          <div className="cc-selection-status">
            <span>{selectedDirIds.size} selected</span>
            <button type="button" className="cc-btn-link" onClick={selectAll}>
              {selectedDirIds.size === drive.directories.length ? 'Deselect All' : 'Select All'}
            </button>
          </div>
        </div>

        <table className="cc-table" aria-label="Capacity Commander directory table">
          <thead>
            <tr>
              <th scope="col" style={{ width: '40px' }}>
                <input
                  type="checkbox"
                  checked={drive.directories.length > 0 && selectedDirIds.size === drive.directories.length}
                  onChange={selectAll}
                  aria-label="Select all directories"
                />
              </th>
              <th scope="col">Directory Target</th>
              <th scope="col">Type</th>
              <th scope="col">Reserve Barrier</th>
              <th scope="col">Store Active</th>
              <th scope="col">Overflow</th>
              <th scope="col">Current Footprint</th>
            </tr>
          </thead>
          <tbody>
            {drive.directories.map((dir) => {
              const isSelected = selectedDirIds.has(dir.id);
              return (
                <tr key={dir.id} className={isSelected ? 'is-selected' : ''}>
                  <td>
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelectDir(dir.id)}
                      aria-label={`Select ${dir.path}`}
                    />
                  </td>
                  <td>
                    <code className="cc-dir-path">{dir.path}</code>
                  </td>
                  <td>
                    <span className={`cc-tag cc-tag--${dir.setupType}`}>{dir.setupType}</span>
                  </td>
                  <td>
                    <span className="cc-quota-badge">{dir.minSpaceGb} GB min</span>
                  </td>
                  <td>
                    <span className={`cc-dot-tag ${dir.store ? 'is-active' : 'is-inactive'}`}>
                      {dir.store ? 'ACTIVE' : 'MUTED'}
                    </span>
                  </td>
                  <td>
                    <span className={`cc-dot-tag ${dir.overflow ? 'is-overflow' : 'is-inactive'}`}>
                      {dir.overflow ? 'ENABLED' : 'OFF'}
                    </span>
                  </td>
                  <td>
                    <strong>{formatBytes(dir.usedBytes)}</strong>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {/* Sticky Batch Command Dock */}
        {selectedDirIds.size > 0 && (
          <div className="cc-batch-dock" role="toolbar" aria-label="Batch operations">
            <span className="cc-dock-title">
              ⚡ Batch Operations on {selectedDirIds.size} directories:
            </span>
            <div className="cc-dock-actions">
              <button
                type="button"
                className="cc-dock-btn"
                onClick={() => batchApply({ store: true })}
              >
                Set Store: Active
              </button>
              <button
                type="button"
                className="cc-dock-btn"
                onClick={() => batchApply({ store: false })}
              >
                Set Store: Muted
              </button>
              <button
                type="button"
                className="cc-dock-btn"
                onClick={() => batchApply({ overflow: true })}
              >
                Enable Overflow
              </button>
              <button
                type="button"
                className="cc-dock-btn"
                onClick={() => batchApply({ minSpaceGb: 50 })}
              >
                Set Min: 50GB
              </button>
              <button
                type="button"
                className="cc-dock-btn cc-dock-btn--cancel"
                onClick={() => setSelectedDirIds(new Set())}
              >
                ✕ Cancel
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
