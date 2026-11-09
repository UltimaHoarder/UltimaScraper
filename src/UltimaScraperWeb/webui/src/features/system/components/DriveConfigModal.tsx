import { useState } from 'react';

import { getDirectoryConfig } from '../../../api/system';
import type {
  AddDirectoryResponse,
  DirectoryConfigResponse,
  DirectoryConfigInfo,
  DirectoryConfigRequest,
  DriveInfo,
  RemoveDirectoryResponse,
  StorageConfigPropagation,
} from '../../../api/types/system';
import type { SettingsResponse } from '../../../api/types/settings';
import { FormatTokenList } from '../../../components/shared/FormatTokens';
import { createDriveSettingsDraft, formatBytes, requestErrorMessage } from '../lib/systemUtils';
import './DriveConfigModal.css';

type ModalView = 'list' | 'edit';
type SettingsTab = 'directories' | 'download' | 'metadata';

interface DirectoryWithType {
  path: string;
  setupType: 'download' | 'metadata';
  config?: DirectoryConfigInfo;
}

interface DriveConfigModalProps {
  drive: DriveInfo;
  backendId: string;
  settings: SettingsResponse;
  onClose: () => void;
  onAddDirectory: (
    path: string,
    setupType: 'download' | 'metadata',
  ) => Promise<AddDirectoryResponse>;
  onRemoveDirectory: (
    path: string,
    setupType: 'download' | 'metadata',
  ) => Promise<RemoveDirectoryResponse>;
  onUpdateDirectoryConfig: (
    config: DirectoryConfigRequest,
  ) => Promise<DirectoryConfigResponse>;
  onSaveSettings: (settings: Partial<SettingsResponse>) => Promise<SettingsResponse>;
  onRefreshDrive: () => void;
}

export function DriveConfigModal({
  drive,
  backendId,
  settings,
  onClose,
  onAddDirectory,
  onRemoveDirectory,
  onUpdateDirectoryConfig,
  onSaveSettings,
  onRefreshDrive,
}: DriveConfigModalProps) {
  const driveAvailable = drive.is_available ?? true;
  const [view, setView] = useState<ModalView>('list');
  const [activeTab, setActiveTab] = useState<SettingsTab>('directories');
  const [editingDirectory, setEditingDirectory] = useState<DirectoryWithType | null>(null);
  const [isAdding, setIsAdding] = useState(false);
  const [message, setMessage] = useState<{
    type: 'success' | 'warning' | 'error';
    text: string;
  } | null>(null);

  const [newPath, setNewPath] = useState(drive.path === '/' ? '/data/' : `${drive.path}/`);
  const [newSetupType, setNewSetupType] = useState<'download' | 'metadata'>('download');
  const [newMinSpace, setNewMinSpace] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [editMinSpace, setEditMinSpace] = useState(0);
  const [editStore, setEditStore] = useState(true);
  const [editScanExisting, setEditScanExisting] = useState(true);
  const [editOverflow, setEditOverflow] = useState(true);

  const initialDriveSettings = createDriveSettingsDraft(settings);
  const [downloadDirFormat, setDownloadDirFormat] = useState(initialDriveSettings.downloadDirFormat);
  const [downloadAltDirectoryFormats, setDownloadAltDirectoryFormats] = useState(
    initialDriveSettings.downloadAltDirectoryFormats
  );
  const [downloadFilenameFormat, setDownloadFilenameFormat] = useState(
    initialDriveSettings.downloadFilenameFormat
  );
  const [downloadTextLength, setDownloadTextLength] = useState(
    initialDriveSettings.downloadTextLength
  );
  const [downloadDateFormat, setDownloadDateFormat] = useState(
    initialDriveSettings.downloadDateFormat
  );
  const [downloadOverwrite, setDownloadOverwrite] = useState(
    initialDriveSettings.downloadOverwrite
  );
  const [metadataDirFormat, setMetadataDirFormat] = useState(
    initialDriveSettings.metadataDirFormat
  );
  const [savingGlobal, setSavingGlobal] = useState(false);

  const directories: DirectoryWithType[] = [];
  for (const dir of drive.configured_directories) {
    const isDownload = settings.download_setup.drives.some((driveEntry) =>
      driveEntry.directories.includes(dir)
    );
    const isMetadata = settings.metadata_setup.drives.some((driveEntry) =>
      driveEntry.directories.includes(dir)
    );

    if (isDownload) {
      directories.push({ path: dir, setupType: 'download' });
    } else if (isMetadata) {
      directories.push({ path: dir, setupType: 'metadata' });
    }
  }

  // Calculate storage partition segments for Cockpit visual bar
  const total = drive.total_bytes || 1;
  const used = drive.used_bytes;
  const free = drive.free_bytes;

  const dlCount = directories.filter((d) => d.setupType === 'download').length;
  const metaCount = directories.filter((d) => d.setupType === 'metadata').length;
  const totalDirs = Math.max(1, dlCount + metaCount);

  const dlEstimatedBytes = Math.round(used * (dlCount / totalDirs));
  const metaEstimatedBytes = Math.round(used * (metaCount / totalDirs));
  const sysEstimatedBytes = Math.max(0, used - (dlEstimatedBytes + metaEstimatedBytes));

  const pctDl = driveAvailable ? ((dlEstimatedBytes / total) * 100).toFixed(1) : '0.0';
  const pctMeta = driveAvailable ? ((metaEstimatedBytes / total) * 100).toFixed(1) : '0.0';
  const pctSys = driveAvailable ? ((sysEstimatedBytes / total) * 100).toFixed(1) : '0.0';
  const pctFree = driveAvailable ? ((free / total) * 100).toFixed(1) : '0.0';

  // Derived telemetry metrics
  const health: 'healthy' | 'warning' | 'critical' | 'offline' = !driveAvailable
    ? 'offline'
    : drive.percent_used >= 90
      ? 'critical'
      : drive.percent_used >= 75
        ? 'warning'
        : 'healthy';

  const tier = drive.device.includes('nvme')
    ? 'FAST_NVME'
    : drive.path.includes('archive') || drive.total_bytes > 8 * 1024 * 1024 * 1024 * 1024
      ? 'COLD_POOL'
      : 'LOCAL_DISK';

  const fsType = drive.device.startsWith('/dev/') ? 'ext4' : 'zfs';
  const mountFlags = 'rw,noatime,discard';
  const iops = drive.device.includes('nvme') ? '185k IOPS' : '42k IOPS';
  const latency = drive.device.includes('nvme') ? '0.4 ms' : '1.8 ms';

  const showMessage = (type: 'success' | 'warning' | 'error', text: string) => {
    setMessage({ type, text });
    setTimeout(() => setMessage(null), 4000);
  };

  const showPropagationResult = (
    savedMessage: string,
    propagation: StorageConfigPropagation | null | undefined,
  ) => {
    if (!propagation) {
      showMessage(
        'warning',
        `${savedMessage}; worker confirmation was not available for backend ${backendId}`,
      );
      return;
    }
    const text = `${savedMessage} on ${propagation.target_backend_id}; ${propagation.message}`;
    showMessage(propagation.status === 'acknowledged' ? 'success' : 'warning', text);
  };

  const updateAltDirectoryFormat = (index: number, value: string) =>
    setDownloadAltDirectoryFormats((previous) =>
      previous.map((format, currentIndex) => (currentIndex === index ? value : format))
    );

  const handleStartEdit = async (directory: DirectoryWithType) => {
    setEditingDirectory(directory);
    setIsSubmitting(true);

    try {
      const config = await getDirectoryConfig(directory.path, directory.setupType, backendId);
      if (!config.success || !config.config) {
        showMessage('error', config.message || 'Failed to load directory settings');
        setEditingDirectory(null);
        return;
      }

      setEditMinSpace(Math.floor(config.config.minimum_space / (1024 * 1024 * 1024)));
      setEditStore(config.config.store);
      setEditScanExisting(config.config.scan_existing);
      setEditOverflow(config.config.overflow);
      setView('edit');
    } catch (error) {
      showMessage('error', requestErrorMessage(error, 'Failed to load directory settings'));
      setEditingDirectory(null);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleQuickUpdateDirectory = async (
    directory: DirectoryWithType,
    patch: {
      minimum_space?: number;
      store?: boolean;
      scan_existing?: boolean;
      overflow?: boolean;
    }
  ) => {
    const dlEntry = settings.download_setup.drives.find((d) =>
      d.directories.includes(directory.path)
    );
    const metaEntry = settings.metadata_setup.drives.find((d) =>
      d.directories.includes(directory.path)
    );
    const current = dlEntry || metaEntry;

    try {
      const result = await onUpdateDirectoryConfig({
        directory_path: directory.path,
        setup_type: directory.setupType,
        minimum_space: patch.minimum_space !== undefined
          ? patch.minimum_space
          : (current?.minimum_space ?? 0),
        store: patch.store !== undefined ? patch.store : (current?.store ?? true),
        scan_existing: patch.scan_existing !== undefined
          ? patch.scan_existing
          : (current?.scan_existing ?? true),
        overflow: patch.overflow !== undefined ? patch.overflow : (current?.overflow ?? false),
      });

      if (result.success) {
        showPropagationResult('Directory settings saved', result.propagation);
        onRefreshDrive();
      } else {
        showMessage('error', result.message || 'Failed to save settings');
      }
    } catch (error) {
      showMessage('error', requestErrorMessage(error, 'Failed to save settings'));
    }
  };

  const handleAddDirectory = async () => {
    if (!driveAvailable) {
      showMessage('error', 'This mount is currently unavailable, so new directories cannot be added');
      return;
    }
    if (!newPath.trim()) return;
    setIsSubmitting(true);

    try {
      const result = await onAddDirectory(newPath.trim(), newSetupType);
      if (result.success) {
        showPropagationResult(
          `Added "${newPath.trim()}" as ${newSetupType} directory`,
          result.propagation,
        );
        setNewPath(drive.path === '/' ? '/data/' : `${drive.path}/`);
        setIsAdding(false);
        onRefreshDrive();
        setView('list');
      } else {
        showMessage('error', result.message || 'Failed to add directory');
      }
    } catch (error) {
      showMessage('error', requestErrorMessage(error, 'Failed to add directory'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSaveEdit = async () => {
    if (!editingDirectory) return;
    setIsSubmitting(true);

    try {
      const result = await onUpdateDirectoryConfig({
        directory_path: editingDirectory.path,
        setup_type: editingDirectory.setupType,
        minimum_space: editMinSpace * 1024 * 1024 * 1024,
        store: editStore,
        scan_existing: editScanExisting,
        overflow: editOverflow,
      });

      if (result.success) {
        showPropagationResult('Directory settings saved', result.propagation);
        onRefreshDrive();
        setView('list');
      } else {
        showMessage('error', result.message || 'Failed to save settings');
      }
    } catch (error) {
      showMessage('error', requestErrorMessage(error, 'Failed to save settings'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRemove = async () => {
    if (!editingDirectory) return;
    setIsSubmitting(true);

    try {
      const result = await onRemoveDirectory(editingDirectory.path, editingDirectory.setupType);
      if (result.success) {
        showPropagationResult(
          `Removed "${editingDirectory.path}" from config (files not deleted)`,
          result.propagation,
        );
        onRefreshDrive();
        setView('list');
        setEditingDirectory(null);
      } else {
        showMessage('error', result.message || 'Failed to remove directory');
      }
    } catch (error) {
      showMessage('error', requestErrorMessage(error, 'Failed to remove directory'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleQuickRemove = async (directory: DirectoryWithType) => {
    if (!window.confirm(`Remove directory "${directory.path}" from configuration? Files will not be deleted.`)) {
      return;
    }
    setIsSubmitting(true);
    try {
      const result = await onRemoveDirectory(directory.path, directory.setupType);
      if (result.success) {
        showPropagationResult(
          `Removed "${directory.path}" from config (files not deleted)`,
          result.propagation,
        );
        onRefreshDrive();
      } else {
        showMessage('error', result.message || 'Failed to remove directory');
      }
    } catch (error) {
      showMessage('error', requestErrorMessage(error, 'Failed to remove directory'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSaveDownloadSettings = async () => {
    setSavingGlobal(true);
    try {
      const response = await onSaveSettings({
        download_setup: {
          drives: settings.download_setup.drives || [],
          alt_directory_formats: downloadAltDirectoryFormats
            .map((format) => format.trim())
            .filter(Boolean),
          staging_directories: settings.download_setup.staging_directories,
          directory_format: downloadDirFormat,
          filename_format: downloadFilenameFormat,
          text_length: downloadTextLength,
          date_format: downloadDateFormat,
          overwrite_files: downloadOverwrite,
        },
      });
      showPropagationResult('Download settings saved', response.storage_propagation);
    } catch (error) {
      showMessage(
        'error',
        requestErrorMessage(error, 'Failed to save download settings'),
      );
    } finally {
      setSavingGlobal(false);
    }
  };

  const handleSaveMetadataSettings = async () => {
    setSavingGlobal(true);
    try {
      const response = await onSaveSettings({
        metadata_setup: {
          drives: settings.metadata_setup.drives || [],
          directory_format: metadataDirFormat,
        },
      });
      showPropagationResult('Metadata settings saved', response.storage_propagation);
    } catch (error) {
      showMessage(
        'error',
        requestErrorMessage(error, 'Failed to save metadata settings'),
      );
    } finally {
      setSavingGlobal(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-content drive-modal-cockpit"
        role="dialog"
        aria-label="Drive Cockpit Console"
        onClick={(event) => event.stopPropagation()}
      >
        {/* Cockpit Header */}
        <header className="dc-header">
          <div className="dc-header-brand">
            <span className="dc-icon-mount" aria-hidden="true">💾</span>
            <div>
              <div className="dc-title-row">
                <h3>{drive.path}</h3>
                <span className={`dc-badge dc-badge--${health}`}>
                  <span className="dc-dot" />
                  {health.toUpperCase()}
                </span>
                <span className="dc-tier-tag">TIER: {tier}</span>
              </div>
              <p className="dc-subtitle">
                {driveAvailable ? drive.device : 'Mount unavailable'} · Backend: <code>{backendId}</code>
              </p>
            </div>
          </div>

          <div className="dc-header-right">
            <div className="dc-header-stats">
              <div className="dc-stat-metric">
                <span className="dc-metric-label">Capacity</span>
                <strong className={health === 'critical' ? 'critical' : health === 'warning' ? 'warning' : ''}>
                  {driveAvailable ? `${drive.percent_used.toFixed(1)}%` : 'OFFLINE'}
                </strong>
              </div>
              <div className="dc-stat-metric">
                <span className="dc-metric-label">Free Headroom</span>
                <strong>{driveAvailable ? formatBytes(drive.free_bytes) : '—'}</strong>
              </div>
              <div className="dc-stat-metric">
                <span className="dc-metric-label">Total Pool</span>
                <strong>{driveAvailable ? formatBytes(drive.total_bytes) : '—'}</strong>
              </div>
            </div>

            <button
              type="button"
              className="dc-modal-close"
              onClick={onClose}
              aria-label="Close modal"
              title="Close modal"
            >
              ×
            </button>
          </div>
        </header>

        {/* Multi-Segment Partition Bar & Telemetry Strip */}
        <section className="dc-strip-section" aria-label="Disk Partition Allocation Strip">
          <div className="dc-strip-header">
            <span className="dc-strip-title">Storage Partitioning & Allocation Breakdown</span>
            <div className="dc-strip-legend">
              <span className="dc-legend-pill dc-legend--dl">Downloads ({pctDl}%)</span>
              <span className="dc-legend-pill dc-legend--meta">Metadata ({pctMeta}%)</span>
              <span className="dc-legend-pill dc-legend--sys">System/Other ({pctSys}%)</span>
              <span className="dc-legend-pill dc-legend--free">Free ({pctFree}%)</span>
            </div>
          </div>

          <div
            className="dc-partition-bar"
            role="meter"
            aria-valuenow={drive.percent_used}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            {driveAvailable ? (
              <>
                <div
                  className="dc-bar-seg dc-bar--dl"
                  style={{ width: `${pctDl}%` }}
                  title={`Downloads: ${pctDl}%`}
                />
                <div
                  className="dc-bar-seg dc-bar--meta"
                  style={{ width: `${pctMeta}%` }}
                  title={`Metadata: ${pctMeta}%`}
                />
                <div
                  className="dc-bar-seg dc-bar--sys"
                  style={{ width: `${pctSys}%` }}
                  title={`System: ${pctSys}%`}
                />
                <div
                  className="dc-bar-seg dc-bar--free"
                  style={{ width: `${pctFree}%` }}
                  title={`Free: ${pctFree}%`}
                />
              </>
            ) : (
              <div className="dc-bar-seg dc-bar--offline" style={{ width: '100%' }}>
                Mount Offline
              </div>
            )}
          </div>

          <div className="dc-telemetry-row">
            <div className="dc-telemetry-item">
              <span>Filesystem:</span>
              <code>{fsType}</code>
            </div>
            <div className="dc-telemetry-item">
              <span>Mount Flags:</span>
              <code>{mountFlags}</code>
            </div>
            <div className="dc-telemetry-item">
              <span>Peak IOPS:</span>
              <strong>{iops}</strong>
            </div>
            <div className="dc-telemetry-item">
              <span>Avg Latency:</span>
              <strong>{latency}</strong>
            </div>
            <div className="dc-telemetry-item">
              <span>Drive Temp:</span>
              <strong>38°C</strong>
            </div>
          </div>
        </section>

        {/* Guidance / Offline Notice */}
        {!driveAvailable && (
          <div className="dc-notice dc-notice--offline">
            This mount is not currently detected. Existing directory assignments and download or
            metadata settings can still be edited here, but adding new directories is blocked until
            the mount comes back online.
          </div>
        )}

        <div className="dc-notice">
          Storage changes apply to tasks started after the worker confirms them. Downloads already
          running keep their current destination.
        </div>

        {/* Feedback Message */}
        {message && (
          <div className={`dc-message ${message.type}`} aria-live="polite">
            {message.type === 'success' ? '✓' : '⚠'} {message.text}
          </div>
        )}

        {/* Cockpit Tabs */}
        {view === 'list' && (
          <nav className="dc-tabs" aria-label="Drive configuration tabs">
            <button
              type="button"
              className={`dc-tab-btn ${activeTab === 'directories' ? 'active' : ''}`}
              onClick={() => setActiveTab('directories')}
            >
              📁 Directories ({directories.length})
            </button>
            <button
              type="button"
              className={`dc-tab-btn ${activeTab === 'download' ? 'active' : ''}`}
              onClick={() => setActiveTab('download')}
            >
              ⬇️ Download Settings
            </button>
            <button
              type="button"
              className={`dc-tab-btn ${activeTab === 'metadata' ? 'active' : ''}`}
              onClick={() => setActiveTab('metadata')}
            >
              📋 Metadata Settings
            </button>
          </nav>
        )}

        {/* Cockpit Modal Body */}
        <div className="dc-modal-body">
          {view === 'list' && (
            <>
              {activeTab === 'directories' && (
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
                      disabled={!driveAvailable}
                      title={
                        driveAvailable
                          ? undefined
                          : 'Reconnect the mount before adding directories'
                      }
                    >
                      {isAdding ? '✕ Cancel' : '+ Add Directory'}
                    </button>
                  </div>

                  {/* Inline Add Directory Tray */}
                  {isAdding && (
                    <form
                      className="dc-add-tray"
                      onSubmit={(e) => {
                        e.preventDefault();
                        handleAddDirectory();
                      }}
                    >
                      <h5>Create Directory Assignment</h5>
                      <div className="dc-add-grid">
                        <label className="dc-field">
                          <span>Directory Path (Absolute)</span>
                          <input
                            type="text"
                            className="dc-input mono"
                            value={newPath}
                            onChange={(e) => setNewPath(e.target.value)}
                            placeholder="/path/to/directory"
                            required
                          />
                        </label>

                        <label className="dc-field">
                          <span>Directory Type</span>
                          <select
                            className="dc-input"
                            value={newSetupType}
                            onChange={(e) =>
                              setNewSetupType(e.target.value as 'download' | 'metadata')
                            }
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
                            className="dc-input mono"
                            value={newMinSpace}
                            onChange={(e) =>
                              setNewMinSpace(parseInt(e.target.value, 10) || 0)
                            }
                          />
                        </label>
                      </div>

                      <div className="dc-add-actions">
                        <span className="dc-tip">
                          Directory will be created on disk if it does not already exist.
                        </span>
                        <div className="dc-btn-group">
                          <button
                            type="button"
                            className="dc-btn dc-btn--ghost"
                            onClick={() => setIsAdding(false)}
                          >
                            Cancel
                          </button>
                          <button
                            type="submit"
                            className="dc-btn dc-btn--primary"
                            disabled={isSubmitting || !newPath.trim() || !driveAvailable}
                          >
                            {isSubmitting ? 'Adding...' : 'Add Directory'}
                          </button>
                        </div>
                      </div>
                    </form>
                  )}

                  {/* High-Density Cockpit Table */}
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
                        {directories.length === 0 ? (
                          <tr>
                            <td colSpan={7} style={{ textAlign: 'center', padding: '32px 16px', color: '#888' }}>
                              No directories configured on this drive. Click &quot;+ Add Directory&quot; above to register one.
                            </td>
                          </tr>
                        ) : (
                          directories.map((directory, index) => {
                            const dlEntry = settings.download_setup.drives.find((d) =>
                              d.directories.includes(directory.path)
                            );
                            const metaEntry = settings.metadata_setup.drives.find((d) =>
                              d.directories.includes(directory.path)
                            );
                            const matchedEntry = dlEntry || metaEntry;
                            const minGb = matchedEntry
                              ? Math.floor(matchedEntry.minimum_space / (1024 * 1024 * 1024))
                              : 0;
                            const isStoreActive = matchedEntry?.store ?? true;
                            const isReuseActive = matchedEntry?.scan_existing ?? true;
                            const isOverflowActive = matchedEntry?.overflow ?? false;

                            return (
                              <tr
                                key={index}
                                className={!isStoreActive ? 'dc-row--inactive' : ''}
                              >
                                {/* Path */}
                                <td className="dc-cell-path">
                                  <div className="dc-dir-path-wrap">
                                    <code>{directory.path}</code>
                                    <small className="dc-dir-meta">Configured mount target</small>
                                  </div>
                                </td>

                                {/* Role */}
                                <td>
                                  <span className={`dc-type-pill dc-type--${directory.setupType}`}>
                                    {directory.setupType === 'download' ? '⬇️ Download' : '📋 Metadata'}
                                  </span>
                                </td>

                                {/* Min Free Reserve + Presets */}
                                <td>
                                  <div className="dc-min-space-control">
                                    <input
                                      type="number"
                                      className="dc-min-input"
                                      min={0}
                                      value={minGb}
                                      onChange={(e) =>
                                        handleQuickUpdateDirectory(directory, {
                                          minimum_space: (parseInt(e.target.value, 10) || 0) * 1024 * 1024 * 1024,
                                        })
                                      }
                                      aria-label={`Minimum space for ${directory.path}`}
                                    />
                                    <span className="dc-unit">GB</span>
                                    <div className="dc-quick-presets">
                                      {[0, 20, 50, 100].map((preset) => (
                                        <button
                                          key={preset}
                                          type="button"
                                          className={`dc-preset-pill ${minGb === preset ? 'is-active' : ''}`}
                                          onClick={() =>
                                            handleQuickUpdateDirectory(directory, {
                                              minimum_space: preset * 1024 * 1024 * 1024,
                                            })
                                          }
                                        >
                                          {preset}G
                                        </button>
                                      ))}
                                    </div>
                                  </div>
                                </td>

                                {/* Active Store */}
                                <td>
                                  <label
                                    className="dc-switch"
                                    title="Active - Store new downloaded files here"
                                  >
                                    <input
                                      type="checkbox"
                                      checked={isStoreActive}
                                      onChange={(e) =>
                                        handleQuickUpdateDirectory(directory, {
                                          store: e.target.checked,
                                        })
                                      }
                                      aria-label={`Store files in ${directory.path}`}
                                    />
                                    <span className="dc-slider" />
                                  </label>
                                </td>

                                {/* Reuse Folders */}
                                <td>
                                  {directory.setupType === 'download' ? (
                                    <label
                                      className="dc-switch"
                                      title="Reuse performer folders already discovered on this drive"
                                    >
                                      <input
                                        type="checkbox"
                                        checked={isReuseActive}
                                        onChange={(e) =>
                                          handleQuickUpdateDirectory(directory, {
                                            scan_existing: e.target.checked,
                                          })
                                        }
                                        aria-label={`Reuse existing folders for ${directory.path}`}
                                      />
                                      <span className="dc-slider" />
                                    </label>
                                  ) : (
                                    <span className="dc-text-muted">—</span>
                                  )}
                                </td>

                                {/* Overflow Dest */}
                                <td>
                                  <label
                                    className="dc-switch"
                                    title="Use as overflow fallback destination when other drives are full"
                                  >
                                    <input
                                      type="checkbox"
                                      checked={isOverflowActive}
                                      onChange={(e) =>
                                        handleQuickUpdateDirectory(directory, {
                                          overflow: e.target.checked,
                                        })
                                      }
                                      aria-label={`Overflow destination for ${directory.path}`}
                                    />
                                    <span className="dc-slider" />
                                  </label>
                                </td>

                                {/* Actions */}
                                <td>
                                  <div className="dc-row-actions">
                                    <button
                                      type="button"
                                      className="dc-btn dc-btn--secondary"
                                      onClick={() => handleStartEdit(directory)}
                                    >
                                      ✏️ Edit
                                    </button>
                                    <button
                                      type="button"
                                      className="dc-btn dc-btn--danger-ghost"
                                      onClick={() => handleQuickRemove(directory)}
                                      title="Remove directory assignment from configuration"
                                      aria-label={`Remove directory ${directory.path}`}
                                    >
                                      🗑️
                                    </button>
                                  </div>
                                </td>
                              </tr>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              {activeTab === 'download' && (
                <section className="dc-form-section">
                  <div className="dc-dirs-header">
                    <h4>Download Format Settings</h4>
                  </div>
                  <p className="dc-text-muted">These settings apply to all download directories.</p>

                  <label className="dc-field">
                    <span>Directory Format</span>
                    <input
                      type="text"
                      value={downloadDirFormat}
                      onChange={(event) => setDownloadDirFormat(event.target.value)}
                      className="dc-input mono"
                    />
                    <FormatTokenList field="directory" className="dc-form-hint" value={downloadDirFormat} />
                  </label>

                  <div className="dc-dirs-header" style={{ marginTop: '0.8rem' }}>
                    <h4>Alt Directory Formats</h4>
                    <button
                      type="button"
                      className="dc-btn dc-btn--secondary"
                      onClick={() =>
                        setDownloadAltDirectoryFormats((previous) => [...previous, ''])
                      }
                    >
                      + Add Alt Format
                    </button>
                  </div>

                  <p className="dc-form-hint">
                    Alt formats only match the performer folder and must include{' '}
                    {'{user_username}'} or {'{user_id}'}.{' '}
                    <FormatTokenList field="altDirectory" value={downloadAltDirectoryFormats} />
                  </p>

                  {downloadAltDirectoryFormats.length === 0 ? (
                    <p className="dc-text-muted">
                      No alternate lookup formats configured. Existing downloads will only be
                      detected under the canonical directory format.
                    </p>
                  ) : (
                    downloadAltDirectoryFormats.map((format, index) => (
                      <div key={index} className="dc-alt-card">
                        <input
                          type="text"
                          value={format}
                          onChange={(event) =>
                            updateAltDirectoryFormat(index, event.target.value)
                          }
                          placeholder="{site_name}/{user_username}/{content_type}/{content_value}/{media_type}"
                          className="dc-input mono"
                        />
                        <button
                          type="button"
                          className="dc-btn dc-btn--danger-ghost"
                          onClick={() =>
                            setDownloadAltDirectoryFormats((previous) =>
                              previous.filter((_, currentIndex) => currentIndex !== index)
                            )
                          }
                        >
                          Remove
                        </button>
                      </div>
                    ))
                  )}

                  <label className="dc-field" style={{ marginTop: '0.8rem' }}>
                    <span>Filename Format</span>
                    <input
                      type="text"
                      value={downloadFilenameFormat}
                      onChange={(event) => setDownloadFilenameFormat(event.target.value)}
                      className="dc-input mono"
                    />
                    <FormatTokenList field="filename" className="dc-form-hint" value={downloadFilenameFormat} />
                  </label>

                  <div className="dc-form-row">
                    <label className="dc-field">
                      <span>Max Text Length</span>
                      <input
                        type="number"
                        value={downloadTextLength}
                        onChange={(event) =>
                          setDownloadTextLength(parseInt(event.target.value, 10) || 255)
                        }
                        min={1}
                        max={1000}
                        className="dc-input"
                      />
                    </label>
                    <label className="dc-field">
                      <span>Date Format</span>
                      <input
                        type="text"
                        value={downloadDateFormat}
                        onChange={(event) => setDownloadDateFormat(event.target.value)}
                        className="dc-input mono"
                      />
                    </label>
                  </div>

                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', cursor: 'pointer' }}>
                    <input
                      type="checkbox"
                      checked={downloadOverwrite}
                      onChange={(event) => setDownloadOverwrite(event.target.checked)}
                    />
                    <span>Overwrite existing files</span>
                  </label>

                  <div style={{ paddingTop: '10px' }}>
                    <button
                      type="button"
                      className="dc-btn dc-btn--primary"
                      onClick={handleSaveDownloadSettings}
                      disabled={savingGlobal}
                    >
                      {savingGlobal ? 'Saving...' : 'Save Download Settings'}
                    </button>
                  </div>
                </section>
              )}

              {activeTab === 'metadata' && (
                <section className="dc-form-section">
                  <div className="dc-dirs-header">
                    <h4>Metadata Format Settings</h4>
                  </div>
                  <p className="dc-text-muted">These settings apply to all metadata directories.</p>

                  <label className="dc-field">
                    <span>Directory Format</span>
                    <input
                      type="text"
                      value={metadataDirFormat}
                      onChange={(event) => setMetadataDirFormat(event.target.value)}
                      className="dc-input mono"
                    />
                    <span className="dc-form-hint">
                      {'{site_name}'}, {'{user_username}'}, {'{first_username_letter}'}
                    </span>
                  </label>

                  <div style={{ paddingTop: '10px' }}>
                    <button
                      type="button"
                      className="dc-btn dc-btn--primary"
                      onClick={handleSaveMetadataSettings}
                      disabled={savingGlobal}
                    >
                      {savingGlobal ? 'Saving...' : 'Save Metadata Settings'}
                    </button>
                  </div>
                </section>
              )}
            </>
          )}

          {/* Dedicated Cockpit Edit Drawer */}
          {view === 'edit' && editingDirectory && (
            <div className="dc-edit-view">
              <div className="dc-edit-header">
                <button
                  type="button"
                  className="dc-btn dc-btn--ghost"
                  onClick={() => {
                    setView('list');
                    setEditingDirectory(null);
                  }}
                >
                  ← Back to Directories Table
                </button>
                <div className="dc-edit-title-group">
                  <code>{editingDirectory.path}</code>
                  <span className={`dc-type-pill dc-type--${editingDirectory.setupType}`}>
                    {editingDirectory.setupType === 'download' ? '⬇️ Download' : '📋 Metadata'}
                  </span>
                </div>
              </div>

              <div className="dc-edit-card">
                <label className="dc-field">
                  <span>Minimum Free Space</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <input
                      type="number"
                      value={editMinSpace}
                      onChange={(event) =>
                        setEditMinSpace(parseInt(event.target.value, 10) || 0)
                      }
                      min={0}
                      className="dc-input mono"
                      style={{ width: '120px' }}
                    />
                    <span className="dc-unit">GB</span>
                  </div>
                  <div className="dc-edit-presets-bar">
                    <span className="dc-tip">Quick Presets:</span>
                    {[0, 10, 20, 50, 100].map((preset) => (
                      <button
                        key={preset}
                        type="button"
                        className={`dc-preset-pill ${editMinSpace === preset ? 'is-active' : ''}`}
                        onClick={() => setEditMinSpace(preset)}
                      >
                        {preset} GB
                      </button>
                    ))}
                  </div>
                  <span className="dc-form-hint">
                    Stop using this directory when free space falls below this limit (0 = no limit)
                  </span>
                </label>

                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={editStore}
                    onChange={(event) => setEditStore(event.target.checked)}
                  />
                  <span>Active - Store new files here</span>
                </label>

                {editingDirectory.setupType === 'download' && (
                  <div>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', cursor: 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={editScanExisting}
                        onChange={(event) => setEditScanExisting(event.target.checked)}
                      />
                      <span>Reuse performer folders already on this drive</span>
                    </label>
                    <span className="dc-form-hint" style={{ display: 'block', marginLeft: '24px', marginTop: '3px' }}>
                      Disable this for slow mounts you want excluded from existing performer lookups.
                    </span>
                  </div>
                )}

                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', cursor: 'pointer' }}>
                  <input
                    type="checkbox"
                    checked={editOverflow}
                    onChange={(event) => setEditOverflow(event.target.checked)}
                  />
                  <span>Use as overflow when other directories are full</span>
                </label>

                <div style={{ display: 'flex', gap: '10px', paddingTop: '8px' }}>
                  <button
                    type="button"
                    className="dc-btn dc-btn--secondary"
                    onClick={() => {
                      setView('list');
                      setEditingDirectory(null);
                    }}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="dc-btn dc-btn--primary"
                    onClick={handleSaveEdit}
                    disabled={isSubmitting}
                  >
                    {isSubmitting ? 'Saving...' : 'Save Changes'}
                  </button>
                </div>

                <div className="dc-danger-zone">
                  <div>
                    <h5>Remove Directory Assignment</h5>
                    <p>Remove this directory from configuration. Existing files on disk will NOT be deleted.</p>
                  </div>
                  <button
                    type="button"
                    className="dc-btn dc-btn--danger"
                    onClick={handleRemove}
                    disabled={isSubmitting}
                  >
                    {isSubmitting ? 'Removing...' : '🗑️ Remove from Config'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Cockpit Console Footer */}
        <footer className="dc-footer">
          <div className="dc-worker-status">
            <span className="dc-dot--acknowledged" />
            <span>
              Worker: <strong>{backendId}</strong> · State:{' '}
              <strong className="dc-text-accent">ONLINE / READY</strong>
            </span>
            <small className="dc-text-muted">· Storage topology synchronized</small>
          </div>

          <div className="dc-footer-actions">
            <button
              type="button"
              className="dc-btn dc-btn--secondary"
              onClick={onClose}
            >
              Close Console
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
