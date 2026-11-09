import { useState } from 'react';

import {
  STAGING_POLICIES,
  STAGING_POLICY_LABELS,
  STAGING_USAGES,
  type StagingDirectory,
  type StagingPolicy,
  type StagingUsage,
} from '../../../api/types/setup';
import type { SettingsResponse } from '../../../api/types/settings';
import { requestErrorMessage } from '../lib/systemUtils';

const BYTES_PER_GB = 1024 * 1024 * 1024;

type SaveNotice = { kind: 'status' | 'alert'; text: string };

interface StagingDirectoriesSectionProps {
  settings: SettingsResponse;
  onSaveSettings: (settings: Partial<SettingsResponse>) => Promise<SettingsResponse>;
}

export function StagingDirectoriesSection({ settings, onSaveSettings }: StagingDirectoriesSectionProps) {
  // Null until edited, so the list follows saved settings until someone changes it.
  const [draft, setDraft] = useState<StagingDirectory[] | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [notice, setNotice] = useState<SaveNotice | null>(null);
  const directories = draft ?? settings.download_setup.staging_directories;

  const edit = (next: StagingDirectory[]) => {
    setDraft(next);
    setNotice(null);
  };

  const updateDirectory = (index: number, changes: Partial<StagingDirectory>) =>
    edit(directories.map((directory, current) => (current === index ? { ...directory, ...changes } : directory)));

  const toggleUsage = (index: number, usage: StagingUsage) => {
    const current = directories[index].usage;
    const usages = current.includes(usage) ? current.filter((value) => value !== usage) : [...current, usage];
    if (usages.length > 0) updateDirectory(index, { usage: usages });
  };

  const togglePolicy = (index: number, policy: StagingPolicy) => {
    const current = directories[index].policy;
    updateDirectory(index, {
      policy: current.includes(policy) ? current.filter((value) => value !== policy) : [...current, policy],
    });
  };

  const save = async () => {
    setIsSaving(true);
    setNotice(null);
    try {
      const response = await onSaveSettings({
        download_setup: {
          ...settings.download_setup,
          staging_directories: directories
            .filter((directory) => directory.path.trim())
            .map((directory) => ({ ...directory, path: directory.path.trim() })),
        },
      });
      setDraft(null);
      const propagation = response.storage_propagation;
      setNotice({
        kind: 'status',
        text: propagation
          ? `Staging directories saved on ${propagation.target_backend_id}; ${propagation.message}`
          : 'Staging directories saved; worker confirmation was not available.',
      });
    } catch (error) {
      setNotice({ kind: 'alert', text: requestErrorMessage(error, 'Failed to save staging directories') });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <section className="fleet-register-panel fleet-staging" aria-labelledby="fleet-staging-title">
      <div className="fleet-register-panel-header">
        <div>
          <h3 id="fleet-staging-title">Staging directories</h3>
          <p>Used for every download, whichever mount it ends up on. A backend skips any path it can't write to.</p>
        </div>
        <button
          type="button"
          className="fleet-register-button"
          onClick={() => edit([...directories, { path: '', usage: ['downloads', 'merge', 'drm'], policy: [] }])}
        >
          + Add staging directory
        </button>
      </div>
      <div className="fleet-staging-body">
        {directories.length === 0 ? (
          <p className="fleet-staging-empty">
            No staging directories configured. Downloads will use their final storage directories as the working path.
          </p>
        ) : (
          <div className="fleet-staging-list">
            {directories.map((directory, index) => (
              <div key={index} className="fleet-staging-card">
                <label className="fleet-staging-field">
                  <span>Path</span>
                  <input
                    type="text"
                    value={directory.path}
                    onChange={(event) => updateDirectory(index, { path: event.target.value })}
                    placeholder="/path/to/staging"
                  />
                </label>
                <div className="fleet-staging-field">
                  <span>Usage</span>
                  <div className="fleet-staging-usage">
                    {STAGING_USAGES.map((usage) => (
                      <label key={usage}>
                        <input
                          type="checkbox"
                          checked={directory.usage.includes(usage)}
                          onChange={() => toggleUsage(index, usage)}
                        />
                        <span>{usage}</span>
                      </label>
                    ))}
                  </div>
                </div>
                {STAGING_POLICIES.map((policy) => (
                  <label key={policy} className="fleet-staging-policy">
                    <input
                      type="checkbox"
                      checked={directory.policy.includes(policy)}
                      onChange={() => togglePolicy(index, policy)}
                    />
                    <span>{STAGING_POLICY_LABELS[policy]}</span>
                  </label>
                ))}
                <label className="fleet-staging-field">
                  <span>Keep free (GB)</span>
                  <input
                    type="number"
                    min={0}
                    value={Math.floor((directory.min_free_bytes ?? 0) / BYTES_PER_GB)}
                    onChange={(event) =>
                      updateDirectory(index, { min_free_bytes: (parseInt(event.target.value, 10) || 0) * BYTES_PER_GB })
                    }
                  />
                </label>
                <div>
                  <button
                    type="button"
                    className="fleet-register-button fleet-register-button--compact"
                    onClick={() => edit(directories.filter((_, current) => current !== index))}
                  >
                    Remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="fleet-staging-actions">
          <button type="button" className="fleet-register-button" onClick={() => void save()} disabled={isSaving || draft === null}>
            {isSaving ? 'Saving...' : 'Save staging directories'}
          </button>
          {notice && <p role={notice.kind}>{notice.text}</p>}
        </div>
      </div>
    </section>
  );
}
