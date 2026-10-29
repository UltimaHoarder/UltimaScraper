import { useEffect, useRef, useState } from 'react';

import {
  getRemoteSettings,
  syncSettingsToAll,
  updateRemoteSettings,
} from '../../../api/settings';
import type { SettingsResponse, SettingsUpdate } from '../../../api/types/settings';
import { FormatTokenList } from '../../../components/shared/FormatTokens';
import './RemoteConfigModal.css';

interface RemoteConfigModalProps {
  backendId: string;
  onClose: () => void;
}

type ConfigTab = 'general' | 'infrastructure' | 'storage';

interface TabMeta {
  id: ConfigTab;
  title: string;
  desc: string;
}

const CONFIG_TABS: readonly TabMeta[] = [
  { id: 'general', title: 'General', desc: 'Identity & worker capacity' },
  { id: 'infrastructure', title: 'Redis & Broker', desc: 'Distributed queue & events' },
  { id: 'storage', title: 'Storage & Formats', desc: 'Download templates & paths' },
];

export function RemoteConfigModal({ backendId, onClose }: RemoteConfigModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [activeTab, setActiveTab] = useState<ConfigTab>('general');
  const [syncToAll, setSyncToAll] = useState(true);

  // General tab state
  const [hostname, setHostname] = useState('');
  const [backendIdConfig, setBackendIdConfig] = useState<string | null>(null);
  const [executionMode, setExecutionMode] = useState<'local' | 'distributed' | 'redis_metrics'>('local');
  const [workerPoolSize, setWorkerPoolSize] = useState(5);
  const [maxClaimedJobs, setMaxClaimedJobs] = useState(5);
  const [workerPoolSites, setWorkerPoolSites] = useState<string[]>(['onlyfans']);

  // Sharing with other machines (General tab)
  const [shareHttps, setShareHttps] = useState(false);
  const [httpsPort, setHttpsPort] = useState(8443);
  const [advertiseHost, setAdvertiseHost] = useState('');

  // Infrastructure tab state
  const [redisEnabled, setRedisEnabled] = useState(true);
  const [redisHost, setRedisHost] = useState('localhost');
  const [redisPort, setRedisPort] = useState(6379);
  const [redisDb, setRedisDb] = useState(0);
  const [redisPassword, setRedisPassword] = useState('');

  // Storage tab state
  const [downloadDirectoryFormat, setDownloadDirectoryFormat] = useState('');
  const [downloadAltDirectoryFormats, setDownloadAltDirectoryFormats] = useState<string[]>([]);
  const [downloadFilenameFormat, setDownloadFilenameFormat] = useState('');
  const [downloadTextLength, setDownloadTextLength] = useState(255);
  const [downloadDateFormat, setDownloadDateFormat] = useState('%Y-%m-%d');
  const [downloadOverwriteFiles, setDownloadOverwriteFiles] = useState(true);
  const [metadataDirectoryFormat, setMetadataDirectoryFormat] = useState('');
  const [previewsDirectory, setPreviewsDirectory] = useState('');
  const [subtitlesDirectory, setSubtitlesDirectory] = useState('');

  // Close on Escape key and lock body scroll
  useEffect(() => {
    const originalOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !saving && !syncing) {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.body.style.overflow = originalOverflow;
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [onClose, saving, syncing]);

  // Load backend settings
  useEffect(() => {
    let cancelled = false;
    const loadSettings = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await getRemoteSettings(backendId);
        if (cancelled) return;
        if (response.error) {
          setError(response.error);
        } else if (response.settings) {
          const s = response.settings;
          setSettings(s);
          setHostname(s.hostname || '');
          setBackendIdConfig(s.backend?.backend_id || null);
          setExecutionMode(s.backend?.execution_mode || 'local');
          setShareHttps(s.backend?.share_https ?? false);
          setHttpsPort(s.backend?.https_port || 8443);
          setAdvertiseHost(s.backend?.advertise_host || '');
          setWorkerPoolSize(s.worker_pool?.size || 5);
          setMaxClaimedJobs(s.worker_pool?.max_claimed_jobs || 5);
          setWorkerPoolSites(s.worker_pool?.sites || ['onlyfans']);

          setRedisEnabled(s.redis?.enabled ?? true);
          setRedisHost(s.redis?.host || 'localhost');
          setRedisPort(s.redis?.port || 6379);
          setRedisDb(s.redis?.db || 0);
          setRedisPassword(s.redis?.password || '');

          setDownloadDirectoryFormat(s.download_setup?.directory_format || '');
          setDownloadAltDirectoryFormats(s.download_setup?.alt_directory_formats || []);
          setDownloadFilenameFormat(s.download_setup?.filename_format || '');
          setDownloadTextLength(s.download_setup?.text_length || 255);
          setDownloadDateFormat(s.download_setup?.date_format || '%Y-%m-%d');
          setDownloadOverwriteFiles(s.download_setup?.overwrite_files ?? true);
          setMetadataDirectoryFormat(s.metadata_setup?.directory_format || '');
          setPreviewsDirectory(s.previews_directory || '');
          setSubtitlesDirectory(s.subtitles_directory || '');
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : 'Failed to load settings');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void loadSettings();
    return () => {
      cancelled = true;
    };
  }, [backendId]);

  const showFeedback = (type: 'success' | 'error', text: string) => {
    setMessage({ type, text });
    setTimeout(() => setMessage(null), 4000);
  };

  const getSharedUpdatesPayload = (): SettingsUpdate => ({
    worker_pool: {
      enabled: true,
      size: workerPoolSize,
      max_claimed_jobs: maxClaimedJobs,
      sites: workerPoolSites,
    },
    download_setup: {
      drives: [],
      alt_directory_formats: downloadAltDirectoryFormats.map((f) => f.trim()).filter(Boolean),
      staging_directories: [],
      directory_format: downloadDirectoryFormat,
      filename_format: downloadFilenameFormat,
      text_length: downloadTextLength,
      date_format: downloadDateFormat,
      overwrite_files: downloadOverwriteFiles,
    },
    metadata_setup: {
      drives: [],
      directory_format: metadataDirectoryFormat,
    },
    previews_directory: previewsDirectory || null,
    subtitles_directory: subtitlesDirectory || null,
  });

  const handleSyncSharedNow = async () => {
    setSyncing(true);
    try {
      const sharedUpdates = getSharedUpdatesPayload();
      const result = await syncSettingsToAll(sharedUpdates);
      if (result.success) {
        const count = result.backends_updated?.length || 0;
        showFeedback(
          'success',
          `Shared options broadcast successfully to ${count} backend${count === 1 ? '' : 's'}.`,
        );
      } else {
        showFeedback('error', result.message || 'Failed to broadcast shared options.');
      }
    } catch (syncErr) {
      showFeedback('error', syncErr instanceof Error ? syncErr.message : 'Sync broadcast failed.');
    } finally {
      setSyncing(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const updates: SettingsUpdate = {
        expected_version: settings?.config_version ?? undefined,
        hostname,
        previews_directory: previewsDirectory || null,
        subtitles_directory: subtitlesDirectory || null,
        worker_pool: {
          enabled: true,
          size: workerPoolSize,
          max_claimed_jobs: maxClaimedJobs,
          sites: workerPoolSites,
        },
        backend: {
          backend_id: backendIdConfig,
          execution_mode: executionMode,
          share_https: shareHttps,
          https_port: httpsPort,
          advertise_host: advertiseHost.trim() || null,
        },
        redis: {
          host: redisHost,
          port: redisPort,
          db: redisDb,
          password: redisPassword || null,
          enabled: redisEnabled,
        },
        download_setup: {
          drives: settings?.download_setup?.drives || [],
          alt_directory_formats: downloadAltDirectoryFormats
            .map((format) => format.trim())
            .filter(Boolean),
          staging_directories: settings?.download_setup?.staging_directories || [],
          directory_format: downloadDirectoryFormat,
          filename_format: downloadFilenameFormat,
          text_length: downloadTextLength,
          date_format: downloadDateFormat,
          overwrite_files: downloadOverwriteFiles,
        },
        metadata_setup: {
          drives: settings?.metadata_setup?.drives || [],
          directory_format: metadataDirectoryFormat,
        },
      };

      const result = await updateRemoteSettings(backendId, updates);
      if (!result.success) {
        showFeedback('error', result.message || 'Failed to save configuration.');
        setSaving(false);
        return;
      }

      // The save bumped config_version; reload it so saving again is not a stale conflict.
      try {
        const refreshed = await getRemoteSettings(backendId);
        if (refreshed.settings) setSettings(refreshed.settings);
      } catch {
        // The save itself succeeded; a later save reports any conflict.
      }

      // If sync to cluster is enabled, broadcast shared options to all nodes
      if (syncToAll) {
        try {
          const sharedUpdates = getSharedUpdatesPayload();
          const syncResult = await syncSettingsToAll(sharedUpdates);
          if (syncResult.success) {
            showFeedback('success', 'Configuration saved and shared options synchronized across cluster.');
          } else {
            showFeedback(
              'success',
              'Configuration saved to node. Note: Cluster broadcast was partially refused.',
            );
          }
        } catch {
          showFeedback('success', 'Configuration saved to node. Note: Redis sync unavailable.');
        }
      } else {
        showFeedback('success', result.message || 'Configuration saved successfully.');
      }
    } catch (saveError) {
      showFeedback('error', saveError instanceof Error ? saveError.message : 'Failed to save configuration.');
    } finally {
      setSaving(false);
    }
  };

  const updateAltFormat = (index: number, val: string) => {
    setDownloadAltDirectoryFormats((prev) =>
      prev.map((item, i) => (i === index ? val : item)),
    );
  };

  const removeAltFormat = (index: number) => {
    setDownloadAltDirectoryFormats((prev) => prev.filter((_, i) => i !== index));
  };

  const addAltFormat = () => {
    setDownloadAltDirectoryFormats((prev) => [...prev, '']);
  };

  return (
    <div className="rc-modal-backdrop" onClick={onClose}>
      <div
        className="rc-modal-dialog"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="rc-modal-heading"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <header className="rc-modal-header">
          <div className="rc-modal-title-group">
            <span className="rc-modal-eyebrow">System Fleet / Backend Configuration</span>
            <div className="rc-modal-title-row">
              <span className="rc-modal-glyph" aria-hidden="true">⬡</span>
              <h2 id="rc-modal-heading" className="rc-modal-title">Node Configuration</h2>
              <span className="rc-modal-pill" title="Target Node Identifier">
                <code>{backendId}</code>
              </span>
              {hostname && (
                <span className="rc-modal-pill rc-modal-pill--host" title="Reported Hostname">
                  {hostname}
                </span>
              )}
            </div>
          </div>
          <button
            type="button"
            className="rc-modal-close-btn"
            onClick={onClose}
            aria-label="Close configuration modal"
          >
            ✕
          </button>
        </header>

        {/* Feedback message */}
        {message && (
          <div className={`rc-feedback-banner rc-feedback-banner--${message.type}`}>
            <span>{message.text}</span>
            <button
              type="button"
              className="rc-modal-close-btn"
              style={{ width: '20px', height: '20px', fontSize: '0.75rem' }}
              onClick={() => setMessage(null)}
            >
              ✕
            </button>
          </div>
        )}

        {/* Modal Body */}
        <div className="rc-modal-body">
          {/* Left Navigation Tabs */}
          <nav className="rc-sidebar-tabs" aria-label="Configuration categories">
            {CONFIG_TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                className={`rc-tab-btn ${activeTab === tab.id ? 'is-active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                <span className="rc-tab-title">{tab.title}</span>
                <span className="rc-tab-desc">{tab.desc}</span>
              </button>
            ))}
          </nav>

          {/* Right Content Panel */}
          <div className="rc-content-panel">
            {loading && (
              <div className="rc-loading-state">
                <span>Reading remote node configuration…</span>
              </div>
            )}

            {error && (
              <div className="rc-error-state">
                <span>Failed to load node configuration: {error}</span>
              </div>
            )}

            {!loading && !error && (
              <>
                {/* Cluster Settings Synchronization Switch Banner */}
                <div className="rc-sync-banner">
                  <div className="rc-sync-banner-info">
                    <div className="rc-sync-banner-title">
                      <span className="rc-sync-icon" aria-hidden="true">⇄</span>
                      <strong>Cluster Settings Synchronization</strong>
                      <span className="rc-sync-badge">Shared Options</span>
                    </div>
                    <p className="rc-sync-banner-desc">
                      Keep formatting patterns, worker sites, and asset paths consistent across all cluster nodes.
                    </p>
                  </div>
                  <div className="rc-sync-banner-controls">
                    <label className="rc-switch" title="Toggle automatic broadcast of shared options to all nodes">
                      <input
                        type="checkbox"
                        checked={syncToAll}
                        onChange={(e) => setSyncToAll(e.target.checked)}
                      />
                      <span className="rc-switch-slider" />
                      <span className="rc-switch-label">{syncToAll ? 'Sync to other backends: ON' : 'Sync to other backends: OFF'}</span>
                    </label>
                    <button
                      type="button"
                      className="rc-btn rc-btn--secondary rc-btn--compact"
                      onClick={handleSyncSharedNow}
                      disabled={syncing || saving}
                      title="Immediately broadcast current shared options to all backends"
                    >
                      {syncing ? 'Broadcasting…' : 'Sync Shared Now ↗'}
                    </button>
                  </div>
                </div>

                {/* Tab: General */}
                {activeTab === 'general' && (
                  <>
                    <div className="rc-setting-section">
                      <div className="rc-section-header">
                        <div className="rc-section-title-wrap">
                          <h3 className="rc-section-title">Node Identity &amp; Execution</h3>
                          <span className="rc-scope-badge rc-scope-badge--local">Node Specific</span>
                        </div>
                        <span className="rc-section-desc">Local identification for {hostname || 'this machine'}</span>
                      </div>

                      <div className="rc-form-grid-2">
                        <div className="rc-setting-item">
                          <label className="rc-setting-label" htmlFor="rc-hostname">Hostname</label>
                          <input
                            id="rc-hostname"
                            type="text"
                            className="rc-setting-input"
                            value={hostname}
                            onChange={(e) => setHostname(e.target.value)}
                            placeholder="e.g. atlas-worker-01"
                          />
                          <span className="rc-setting-hint">Observed hostname for network identification.</span>
                        </div>

                        <div className="rc-setting-item">
                          <label className="rc-setting-label" htmlFor="rc-backendId">Backend Identifier</label>
                          <input
                            id="rc-backendId"
                            type="text"
                            className="rc-setting-input"
                            value={backendIdConfig || ''}
                            onChange={(e) => setBackendIdConfig(e.target.value || null)}
                            placeholder={backendId}
                          />
                          <span className="rc-setting-hint">Unique node UUID or slug within the cluster.</span>
                        </div>
                      </div>

                      <div className="rc-setting-item">
                        <label className="rc-setting-label" htmlFor="rc-execMode">Execution Mode</label>
                        <select
                          id="rc-execMode"
                          className="rc-setting-select"
                          value={executionMode}
                          onChange={(e) => setExecutionMode(e.target.value as typeof executionMode)}
                        >
                          <option value="local">Local execution (Standalone)</option>
                          <option value="distributed">Distributed (Redis broker queue)</option>
                          <option value="redis_metrics">Redis Metrics only</option>
                        </select>
                        <span className="rc-setting-hint">Controls how task queues and job state are coordinated.</span>
                      </div>
                    </div>

                    <div className="rc-setting-section">
                      <div className="rc-section-header">
                        <div className="rc-section-title-wrap">
                          <h3 className="rc-section-title">Worker Pool Concurrency</h3>
                          <span className="rc-scope-badge rc-scope-badge--local">Node Specific</span>
                        </div>
                        <span className="rc-section-desc">Hardware-tailored worker threads on this node</span>
                      </div>

                      <div className="rc-form-grid-2">
                        <div className="rc-setting-item">
                          <label className="rc-setting-label" htmlFor="rc-poolSize">Worker Pool Size</label>
                          <input
                            id="rc-poolSize"
                            type="number"
                            min="1"
                            max="64"
                            className="rc-setting-input"
                            value={workerPoolSize}
                            onChange={(e) => setWorkerPoolSize(parseInt(e.target.value, 10) || 1)}
                          />
                          <span className="rc-setting-hint">Concurrent worker threads allocated on {hostname || 'this host'}.</span>
                        </div>

                        <div className="rc-setting-item">
                          <label className="rc-setting-label" htmlFor="rc-maxClaimed">Max Claimed Jobs</label>
                          <input
                            id="rc-maxClaimed"
                            type="number"
                            min="0"
                            max="100"
                            className="rc-setting-input"
                            value={maxClaimedJobs}
                            onChange={(e) => setMaxClaimedJobs(parseInt(e.target.value, 10) || 0)}
                          />
                          <span className="rc-setting-hint">Prefetch limit for assigned tasks from the Redis queue.</span>
                        </div>
                      </div>
                    </div>

                    <div className="rc-setting-section">
                      <div className="rc-section-header">
                        <div className="rc-section-title-wrap">
                          <h3 className="rc-section-title">Supported Scraper Platforms</h3>
                          <span className="rc-scope-badge rc-scope-badge--shared">Cluster Shared</span>
                        </div>
                        <span className="rc-section-desc">Platforms this fleet participates in downloading</span>
                      </div>

                      <div className="rc-setting-item">
                        <div className="rc-checkbox-group">
                          {['onlyfans', 'fansly', 'loyalfans'].map((site) => {
                            const isChecked = workerPoolSites.includes(site);
                            return (
                              <label key={site} className="rc-checkbox-label">
                                <input
                                  type="checkbox"
                                  checked={isChecked}
                                  onChange={(e) => {
                                    if (e.target.checked) {
                                      setWorkerPoolSites([...workerPoolSites, site]);
                                    } else {
                                      setWorkerPoolSites(workerPoolSites.filter((s) => s !== site));
                                    }
                                  }}
                                />
                                <span style={{ textTransform: 'capitalize' }}>{site}</span>
                              </label>
                            );
                          })}
                        </div>
                        <span className="rc-setting-hint">Nodes will claim jobs belonging to checked platforms.</span>
                      </div>
                    </div>

                    <div className="rc-setting-section">
                      <div className="rc-section-header">
                        <div className="rc-section-title-wrap">
                          <h3 className="rc-section-title">Other machines</h3>
                          <span className="rc-scope-badge rc-scope-badge--local">Node Specific</span>
                        </div>
                        <span className="rc-section-desc">
                          Let WebUIs on other machines join this cluster through this backend
                        </span>
                      </div>

                      <label className="rc-checkbox-label">
                        <input
                          type="checkbox"
                          checked={shareHttps}
                          onChange={(e) => setShareHttps(e.target.checked)}
                        />
                        <span>Serve HTTPS for other machines</span>
                      </label>
                      <span className="rc-setting-hint">
                        Adds an HTTPS listener with a self-signed certificate, which joining WebUIs trust by its
                        fingerprint; cluster invites then become one-time codes. Takes effect when the backend
                        restarts. The backend must be allowed to listen on the network (USR_ALLOW_REMOTE_BIND).
                      </span>

                      {shareHttps && (
                        <div className="rc-form-grid-2">
                          <div className="rc-setting-item">
                            <label className="rc-setting-label" htmlFor="rc-https-port">HTTPS port</label>
                            <input
                              id="rc-https-port"
                              type="number"
                              min={1}
                              max={65535}
                              className="rc-setting-input"
                              value={httpsPort}
                              onChange={(e) => setHttpsPort(Number(e.target.value) || 8443)}
                            />
                          </div>
                          <div className="rc-setting-item">
                            <label className="rc-setting-label" htmlFor="rc-advertise-host">
                              Address for other machines
                            </label>
                            <input
                              id="rc-advertise-host"
                              type="text"
                              className="rc-setting-input"
                              value={advertiseHost}
                              onChange={(e) => setAdvertiseHost(e.target.value)}
                              placeholder={hostname ? `Detected: ${hostname}'s LAN address` : "Detected: this machine's LAN address"}
                              spellCheck={false}
                            />
                            <span className="rc-setting-hint">
                              Only needed when the detected one is wrong, e.g. behind NAT or in a container.
                            </span>
                          </div>
                        </div>
                      )}
                    </div>
                  </>
                )}

                {/* Tab: Infrastructure */}
                {activeTab === 'infrastructure' && (
                  <div className="rc-setting-section">
                    <div className="rc-section-header">
                      <div className="rc-section-title-wrap">
                        <h3 className="rc-section-title">Redis Message Broker &amp; Pub/Sub</h3>
                        <span className="rc-scope-badge rc-scope-badge--shared">Cluster Shared</span>
                      </div>
                      <span className="rc-section-desc">Shared message broker coordinating fleet tasks</span>
                    </div>

                    <div className="rc-setting-item">
                      <label className="rc-checkbox-label">
                        <input
                          type="checkbox"
                          checked={redisEnabled}
                          onChange={(e) => setRedisEnabled(e.target.checked)}
                        />
                        <span>Enable Redis broker connectivity</span>
                      </label>
                      <span className="rc-setting-hint">Required for multi-node task orchestration and live scaling events.</span>
                    </div>

                    <div className="rc-form-grid-2">
                      <div className="rc-setting-item">
                        <label className="rc-setting-label" htmlFor="rc-redisHost">Broker Host</label>
                        <input
                          id="rc-redisHost"
                          type="text"
                          className="rc-setting-input"
                          value={redisHost}
                          onChange={(e) => setRedisHost(e.target.value)}
                          placeholder="e.g. 192.168.50.40"
                        />
                        <span className="rc-setting-hint">Reachable IP address or hostname of Redis server.</span>
                      </div>

                      <div className="rc-setting-item">
                        <label className="rc-setting-label" htmlFor="rc-redisPort">Port</label>
                        <input
                          id="rc-redisPort"
                          type="number"
                          className="rc-setting-input"
                          value={redisPort}
                          onChange={(e) => setRedisPort(parseInt(e.target.value, 10) || 6379)}
                        />
                        <span className="rc-setting-hint">Standard port is 6379.</span>
                      </div>
                    </div>

                    <div className="rc-form-grid-2">
                      <div className="rc-setting-item">
                        <label className="rc-setting-label" htmlFor="rc-redisDb">Database Index</label>
                        <input
                          id="rc-redisDb"
                          type="number"
                          min="0"
                          max="15"
                          className="rc-setting-input"
                          value={redisDb}
                          onChange={(e) => setRedisDb(parseInt(e.target.value, 10) || 0)}
                        />
                        <span className="rc-setting-hint">Logical Redis DB partition (0-15).</span>
                      </div>

                      <div className="rc-setting-item">
                        <label className="rc-setting-label" htmlFor="rc-redisPass">Broker Password</label>
                        <input
                          id="rc-redisPass"
                          type="password"
                          className="rc-setting-input"
                          value={redisPassword}
                          onChange={(e) => setRedisPassword(e.target.value)}
                          placeholder="Leave blank if unauthenticated"
                        />
                        <span className="rc-setting-hint">AUTH password if configured on Redis instance.</span>
                      </div>
                    </div>
                  </div>
                )}

                {/* Tab: Storage & Formats */}
                {activeTab === 'storage' && (
                  <>
                    <div className="rc-setting-section">
                      <div className="rc-section-header">
                        <div className="rc-section-title-wrap">
                          <h3 className="rc-section-title">Directory &amp; Filename Templates</h3>
                          <span className="rc-scope-badge rc-scope-badge--shared">Cluster Shared</span>
                        </div>
                        <span className="rc-section-desc">Unified path formatting across all scrapers</span>
                      </div>

                      <div className="rc-setting-item">
                        <label className="rc-setting-label" htmlFor="rc-dlDirFormat">Download Directory Format</label>
                        <input
                          id="rc-dlDirFormat"
                          type="text"
                          className="rc-setting-input"
                          value={downloadDirectoryFormat}
                          onChange={(e) => setDownloadDirectoryFormat(e.target.value)}
                          placeholder="{site_name}/{user_username}/{content_type}/{content_value}/{media_type}"
                        />
                        <FormatTokenList field="directory" className="rc-setting-hint" value={downloadDirectoryFormat} />
                      </div>

                      <div className="rc-setting-item">
                        <div className="rc-setting-label-row">
                          <label className="rc-setting-label">Alternative Directory Formats</label>
                          <button
                            type="button"
                            className="rc-btn rc-btn--secondary rc-btn--compact"
                            onClick={addAltFormat}
                          >
                            + Add Alternative
                          </button>
                        </div>
                        {downloadAltDirectoryFormats.length === 0 ? (
                          <span className="rc-setting-hint">No alternative formats configured.</span>
                        ) : (
                          <div className="rc-dynamic-list">
                            {downloadAltDirectoryFormats.map((format, idx) => (
                              <div key={idx} className="rc-dynamic-item">
                                <input
                                  type="text"
                                  className="rc-setting-input"
                                  value={format}
                                  onChange={(e) => updateAltFormat(idx, e.target.value)}
                                  placeholder="{site_name}/{user_username}"
                                />
                                <button
                                  type="button"
                                  className="rc-btn rc-btn--danger rc-btn--compact"
                                  onClick={() => removeAltFormat(idx)}
                                >
                                  Remove
                                </button>
                              </div>
                            ))}
                          </div>
                        )}
                        <span className="rc-setting-hint">
                          Legacy or alternative path patterns checked during existing performer lookups. Only the
                          performer folder is matched, and each must include {'{user_username}'} or {'{user_id}'}.
                        </span>
                        <FormatTokenList field="altDirectory" className="rc-setting-hint" value={downloadAltDirectoryFormats} />
                      </div>

                      <div className="rc-form-grid-2">
                        <div className="rc-setting-item">
                          <label className="rc-setting-label" htmlFor="rc-dlFileFormat">Filename Format</label>
                          <input
                            id="rc-dlFileFormat"
                            type="text"
                            className="rc-setting-input"
                            value={downloadFilenameFormat}
                            onChange={(e) => setDownloadFilenameFormat(e.target.value)}
                            placeholder="{media_id}_{media_filename}.{media_ext}"
                          />
                          <span className="rc-setting-hint">Naming pattern for media files written to disk.</span>
                          <FormatTokenList field="filename" className="rc-setting-hint" value={downloadFilenameFormat} />
                        </div>

                        <div className="rc-setting-item">
                          <label className="rc-setting-label" htmlFor="rc-dateFormat">Date Format</label>
                          <input
                            id="rc-dateFormat"
                            type="text"
                            className="rc-setting-input"
                            value={downloadDateFormat}
                            onChange={(e) => setDownloadDateFormat(e.target.value)}
                            placeholder="%Y-%m-%d"
                          />
                          <span className="rc-setting-hint">strftime date pattern (e.g. <code>%Y-%m-%d</code>).</span>
                        </div>
                      </div>

                      <div className="rc-form-grid-2">
                        <div className="rc-setting-item">
                          <label className="rc-setting-label" htmlFor="rc-textLen">Max Text Length</label>
                          <input
                            id="rc-textLen"
                            type="number"
                            min="50"
                            max="500"
                            className="rc-setting-input"
                            value={downloadTextLength}
                            onChange={(e) => setDownloadTextLength(parseInt(e.target.value, 10) || 255)}
                          />
                          <span className="rc-setting-hint">Character cutoff for truncated post caption in filenames.</span>
                        </div>

                        <div className="rc-setting-item" style={{ justifyContent: 'center' }}>
                          <label className="rc-checkbox-label">
                            <input
                              type="checkbox"
                              checked={downloadOverwriteFiles}
                              onChange={(e) => setDownloadOverwriteFiles(e.target.checked)}
                            />
                            <span>Overwrite existing files</span>
                          </label>
                          <span className="rc-setting-hint">If disabled, completed files on disk are preserved.</span>
                        </div>
                      </div>
                    </div>

                    <div className="rc-setting-section">
                      <div className="rc-section-header">
                        <div className="rc-section-title-wrap">
                          <h3 className="rc-section-title">Metadata &amp; Asset Directories</h3>
                          <span className="rc-scope-badge rc-scope-badge--shared">Cluster Shared</span>
                        </div>
                        <span className="rc-section-desc">Shared locations for databases, previews, and subtitles</span>
                      </div>

                      <div className="rc-setting-item">
                        <label className="rc-setting-label" htmlFor="rc-metaDir">Metadata Directory Format</label>
                        <input
                          id="rc-metaDir"
                          type="text"
                          className="rc-setting-input"
                          value={metadataDirectoryFormat}
                          onChange={(e) => setMetadataDirectoryFormat(e.target.value)}
                          placeholder="{site_name}/{username}/.metadata"
                        />
                        <span className="rc-setting-hint">Relative pattern for JSON/sqlite metadata archives.</span>
                      </div>

                      <div className="rc-form-grid-2">
                        <div className="rc-setting-item">
                          <label className="rc-setting-label" htmlFor="rc-prevDir">Previews Directory</label>
                          <input
                            id="rc-prevDir"
                            type="text"
                            className="rc-setting-input"
                            value={previewsDirectory}
                            onChange={(e) => setPreviewsDirectory(e.target.value)}
                            placeholder="Optional custom path"
                          />
                          <span className="rc-setting-hint">Dedicated mount for fast gallery previews.</span>
                        </div>

                        <div className="rc-setting-item">
                          <label className="rc-setting-label" htmlFor="rc-subDir">Subtitles Directory</label>
                          <input
                            id="rc-subDir"
                            type="text"
                            className="rc-setting-input"
                            value={subtitlesDirectory}
                            onChange={(e) => setSubtitlesDirectory(e.target.value)}
                            placeholder="Optional custom path"
                          />
                          <span className="rc-setting-hint">Dedicated mount for extracted VTT/SRT subtitles.</span>
                        </div>
                      </div>
                    </div>
                  </>
                )}
              </>
            )}
          </div>
        </div>

        {/* Modal Footer */}
        <footer className="rc-modal-footer">
          <div className="rc-footer-meta">
            <div className={`rc-footer-sync-indicator ${syncToAll ? 'is-enabled' : 'is-disabled'}`}>
              <span className="rc-footer-dot" />
              <span>{syncToAll ? 'Auto-sync: Cluster broadcast enabled' : 'Auto-sync: Local save only'}</span>
            </div>
            {settings?.config_version && (
              <span style={{ color: 'var(--color-text-tertiary, #9caeaf)' }}>
                Config version: v{settings.config_version}
              </span>
            )}
          </div>

          <div className="rc-footer-actions">
            <button
              type="button"
              className="rc-btn rc-btn--secondary"
              onClick={onClose}
              disabled={saving || syncing}
            >
              Cancel
            </button>
            <button
              type="button"
              className="rc-btn rc-btn--primary"
              onClick={handleSave}
              disabled={saving || loading || !!error}
            >
              {saving ? 'Saving…' : syncToAll ? 'Save & Sync to Cluster' : 'Save Configuration'}
            </button>
          </div>
        </footer>
      </div>
    </div>
  );
}
