import { useState } from 'react';

import { testProxy } from '../../../api/network';
import type { NetworkProxy, ProxyTestStatus } from '../../../api/types/network';
import {
  STAGING_POLICIES,
  STAGING_POLICY_LABELS,
  STAGING_USAGES,
  type NetworkConfig,
  type SetupProxy,
  type StagingDirectory,
  type StagingPolicy,
  type StagingUsage,
} from '../../../api/types/setup';
import { PathField } from '../../../components/shared/PathPicker';
import { ProxyFormModal } from '../../network/components/ProxyFormModal';
import '../../network/components/NetworkWorkspace.css';
import { getSetupErrorMessage } from '../lib/setupUtils';
import { SetupHint } from './SetupHint';

interface SetupStorageNetworkStepProps {
  downloadDirs: string[];
  setDownloadDirs: (dirs: string[]) => void;
  stagingDirectory: StagingDirectory | null;
  setStagingDirectory: (directory: StagingDirectory | null) => void;
  networkConfig: NetworkConfig;
  setNetworkConfig: (cfg: NetworkConfig) => void;
  dataDirectory: string;
  onBack?: () => void;
  onNext: () => void;
}

interface ProxyForm {
  // Index of the proxy being edited, or null when adding one.
  index: number | null;
  url: string;
  username: string;
  password: string;
  group: string;
  maxConnections: number;
}

const EMPTY_PROXY_FORM: ProxyForm = {
  index: null,
  url: '',
  username: '',
  password: '',
  group: '',
  maxConnections: -1,
};

const STAGING_POLICY_HINTS: Record<StagingPolicy, string> = {
  drm_only: 'Everything else is downloaded straight into the download directories.',
  prefer: 'Used before other staging directories while there is room, e.g. a RAM disk with disk overflow.',
};

const STAGING_USAGE_HINTS: Record<StagingUsage, string> = {
  downloads: 'Files are downloaded here first, then moved to a download directory.',
  merge: 'Split media is joined here before it is moved.',
  drm: 'Protected media is decrypted here.',
};

export function SetupStorageNetworkStep({
  downloadDirs,
  setDownloadDirs,
  stagingDirectory,
  setStagingDirectory,
  networkConfig,
  setNetworkConfig,
  dataDirectory,
  onBack,
  onNext,
}: SetupStorageNetworkStepProps) {
  const [proxyForm, setProxyForm] = useState<ProxyForm | null>(null);
  const [testStatus, setTestStatus] = useState<ProxyTestStatus>('idle');
  const [testMessage, setTestMessage] = useState<string | null>(null);
  const [testLatencyMs, setTestLatencyMs] = useState<number | null>(null);

  const addDir = () => setDownloadDirs([...downloadDirs, '']);
  const removeDir = (index: number) =>
    setDownloadDirs(downloadDirs.filter((_, currentIndex) => currentIndex !== index));
  const updateDir = (index: number, value: string) =>
    setDownloadDirs(downloadDirs.map((dir, currentIndex) => (currentIndex === index ? value : dir)));

  const updateNetwork = <K extends keyof NetworkConfig>(field: K, value: NetworkConfig[K]) =>
    setNetworkConfig({ ...networkConfig, [field]: value });
  const updateStaging = <K extends keyof StagingDirectory>(
    field: K,
    value: StagingDirectory[K]
  ) => {
    const current =
      stagingDirectory || {
        path: '',
        usage: [...STAGING_USAGES],
        policy: [],
      };
    setStagingDirectory({ ...current, [field]: value });
  };
  const toggleStagingUsage = (usage: StagingUsage) => {
    const current =
      stagingDirectory || {
        path: '',
        usage: [...STAGING_USAGES],
        policy: [],
      };
    const hasUsage = current.usage.includes(usage);
    const nextUsage = hasUsage
      ? current.usage.filter((value) => value !== usage)
      : [...current.usage, usage];
    if (nextUsage.length === 0) return;
    updateStaging('usage', nextUsage);
  };
  const toggleStagingPolicy = (policy: StagingPolicy) => {
    const currentPolicy = stagingDirectory?.policy || [];
    updateStaging(
      'policy',
      currentPolicy.includes(policy)
        ? currentPolicy.filter((value) => value !== policy)
        : [...currentPolicy, policy]
    );
  };

  const openProxyForm = (form: ProxyForm) => {
    setProxyForm(form);
    setTestStatus('idle');
    setTestMessage(null);
    setTestLatencyMs(null);
  };
  const updateProxyForm = (changes: Partial<ProxyForm>) => {
    setProxyForm((current) => (current ? { ...current, ...changes } : current));
    // A changed address or login has not been tested yet.
    if ('url' in changes || 'username' in changes || 'password' in changes) {
      setTestStatus('idle');
      setTestMessage(null);
      setTestLatencyMs(null);
    }
  };
  const runProxyTest = async () => {
    if (!proxyForm) return;
    setTestStatus('testing');
    setTestMessage(null);
    setTestLatencyMs(null);
    try {
      const result = await testProxy({
        url: proxyForm.url.trim(),
        username: proxyForm.username.trim() || undefined,
        password: proxyForm.password || undefined,
      });
      setTestStatus(result.success ? 'success' : 'error');
      setTestMessage(result.message);
      setTestLatencyMs(result.latency_ms ?? null);
    } catch (error: unknown) {
      setTestStatus('error');
      setTestMessage(getSetupErrorMessage(error, 'The proxy test failed'));
    }
  };
  const saveProxy = () => {
    if (!proxyForm) return;
    const proxy: SetupProxy = {
      url: proxyForm.url.trim(),
      username: proxyForm.username.trim() || null,
      password: proxyForm.password || null,
      group: proxyForm.group.trim() || null,
      max_connections: proxyForm.maxConnections,
    };
    const proxies = [...networkConfig.proxies];
    if (proxyForm.index === null) proxies.push(proxy);
    else proxies[proxyForm.index] = proxy;
    updateNetwork('proxies', proxies);
    setProxyForm(null);
  };
  const editingProxy: NetworkProxy | null =
    proxyForm && proxyForm.index !== null
      ? {
          id: proxyForm.url,
          url: proxyForm.url,
          username: proxyForm.username || null,
          max_connections: proxyForm.maxConnections,
          group: proxyForm.group || null,
          assigned_auths: [],
        }
      : null;
  const proxyGroups = [
    ...new Set(networkConfig.proxies.map((proxy) => proxy.group).filter((group): group is string => Boolean(group))),
  ];

  return (
    <>
      <div className="setup-card-header">
        <h2>Storage & Network</h2>
        <p>Choose where downloaded media is stored, and add proxies if you use them.</p>
      </div>

      <div className="setup-card-body">
        {dataDirectory && (
          <div className="setup-data-dir">
            <span>Default data directory:</span>
            <code>{dataDirectory}</code>
          </div>
        )}

        <div className="setup-form-group">
          <label className="setup-form-label">
            Download Directories
            <SetupHint text="Folders on the server where finished media is saved. Leave empty to use the default data directory. On Docker these are paths inside the container, such as a mounted /storage." />
          </label>
          <div className="setup-dir-list">
            {downloadDirs.map((dir, index) => (
              <div key={index} className="setup-dir-row">
                <PathField
                  mode="directory"
                  label="Choose a download directory"
                  value={dir}
                  onChange={(value) => updateDir(index, value)}
                  placeholder="/path/to/downloads"
                />
                {downloadDirs.length > 1 && (
                  <button
                    onClick={() => removeDir(index)}
                    className="setup-dir-remove"
                    title="Remove this directory"
                  >
                    ✕
                  </button>
                )}
              </div>
            ))}
            <button onClick={addDir} className="setup-dir-add" title="Add another download directory">
              + Add directory
            </button>
          </div>
        </div>

        <div className="setup-form-group">
          <label className="setup-form-label">
            Staging Directory
            <SetupHint text="Optional fast scratch space, such as an SSD, used while files are downloaded, merged or decrypted, before they move to a download directory." />
          </label>
          {!stagingDirectory ? (
            <button
              onClick={() =>
                setStagingDirectory({
                  path: '',
                  usage: [...STAGING_USAGES],
                  policy: [],
                })
              }
              className="setup-dir-add"
              title="Add a staging directory"
            >
              + Add staging directory
            </button>
          ) : (
            <div className="setup-dir-list">
              <div className="setup-dir-row">
                <PathField
                  mode="directory"
                  label="Choose a staging directory"
                  value={stagingDirectory.path}
                  onChange={(value) => updateStaging('path', value)}
                  placeholder="/path/to/staging"
                />
                <button
                  onClick={() => setStagingDirectory(null)}
                  className="setup-dir-remove"
                  title="Remove the staging directory"
                >
                  ✕
                </button>
              </div>
              <div className="setup-checkbox-grid">
                {STAGING_USAGES.map((usage) => (
                  <label key={usage} className="setup-skip-toggle">
                    <input
                      type="checkbox"
                      checked={stagingDirectory.usage.includes(usage)}
                      onChange={() => toggleStagingUsage(usage)}
                    />
                    <span>Allow {usage}</span>
                    <SetupHint text={STAGING_USAGE_HINTS[usage]} />
                  </label>
                ))}
              </div>
              {STAGING_POLICIES.map((policy) => (
                <label key={policy} className="setup-skip-toggle">
                  <input
                    type="checkbox"
                    checked={stagingDirectory.policy.includes(policy)}
                    onChange={() => toggleStagingPolicy(policy)}
                  />
                  <span>{STAGING_POLICY_LABELS[policy]}</span>
                  <SetupHint text={STAGING_POLICY_HINTS[policy]} />
                </label>
              ))}
              <label className="setup-skip-toggle">
                <span>Keep free (GB)</span>
                <input
                  type="number"
                  min={0}
                  value={Math.floor((stagingDirectory.min_free_bytes ?? 0) / (1024 * 1024 * 1024))}
                  onChange={(event) =>
                    updateStaging('min_free_bytes', (parseInt(event.target.value, 10) || 0) * 1024 * 1024 * 1024)
                  }
                />
                <SetupHint text="Space left untouched for the system. On a RAM disk this is the memory kept free." />
              </label>
            </div>
          )}
        </div>

        <hr
          style={{
            margin: 'var(--space-4) 0',
            border: 'none',
            borderTop: '1px solid var(--border-color)',
          }}
        />

        <div className="setup-form-group">
          <label className="setup-form-label">
            Proxies
            <SetupHint text="Optional. Accounts can be routed through these, chosen per account in the next steps. You can add more later on the Network page." />
          </label>
          <div className="setup-dir-list">
            {networkConfig.proxies.map((proxy, index) => (
              <div key={`${proxy.url}-${index}`} className="setup-dir-row setup-proxy-row">
                <span className="setup-proxy-url mono">{proxy.url}</span>
                {proxy.group && <span className="setup-proxy-tag">{proxy.group}</span>}
                {proxy.username && <span className="setup-proxy-tag">login</span>}
                <button
                  onClick={() =>
                    openProxyForm({
                      index,
                      url: proxy.url,
                      username: proxy.username ?? '',
                      password: proxy.password ?? '',
                      group: proxy.group ?? '',
                      maxConnections: proxy.max_connections,
                    })
                  }
                  className="setup-dir-remove"
                  title="Edit this proxy"
                >
                  ✎
                </button>
                <button
                  onClick={() =>
                    updateNetwork(
                      'proxies',
                      networkConfig.proxies.filter((_, currentIndex) => currentIndex !== index),
                    )
                  }
                  className="setup-dir-remove"
                  title="Remove this proxy"
                >
                  ✕
                </button>
              </div>
            ))}
            <button
              onClick={() => openProxyForm(EMPTY_PROXY_FORM)}
              className="setup-dir-add"
              title="Add a proxy and test it"
            >
              + Add proxy
            </button>
          </div>
        </div>
      </div>

      <ProxyFormModal
        isOpen={proxyForm !== null}
        editingProxy={editingProxy}
        proxyUrl={proxyForm?.url ?? ''}
        username={proxyForm?.username ?? ''}
        password={proxyForm?.password ?? ''}
        group={proxyForm?.group ?? ''}
        existingGroups={proxyGroups}
        maxConnections={proxyForm?.maxConnections ?? -1}
        formError={null}
        testStatus={testStatus}
        testMessage={testMessage}
        testLatencyMs={testLatencyMs}
        isTesting={testStatus === 'testing'}
        isSaving={false}
        onClose={() => setProxyForm(null)}
        onProxyUrlChange={(url) => updateProxyForm({ url })}
        onUsernameChange={(username) => updateProxyForm({ username })}
        onPasswordChange={(password) => updateProxyForm({ password })}
        onGroupChange={(group) => updateProxyForm({ group })}
        onMaxConnectionsChange={(maxConnections) => updateProxyForm({ maxConnections })}
        onTest={() => void runProxyTest()}
        onSave={saveProxy}
      />

      <div className="setup-card-footer">
        {onBack ? (
          <button onClick={onBack} className="btn-secondary btn-lg">
            Back
          </button>
        ) : (
          <span />
        )}
        <button onClick={onNext} className="btn-primary btn-lg">
          Continue
        </button>
      </div>
    </>
  );
}
