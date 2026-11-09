import { useState } from 'react';

import type { SettingsResponse } from '../../../api/types/settings';
import { requestErrorMessage } from '../lib/systemUtils';

type FindOnlyFolders = Record<string, string[]>;
type SaveNotice = { kind: 'status' | 'alert'; text: string };

interface FindOnlyFoldersSectionProps {
  settings: SettingsResponse;
  onSaveSettings: (settings: Partial<SettingsResponse>) => Promise<SettingsResponse>;
}

export function FindOnlyFoldersSection({ settings, onSaveSettings }: FindOnlyFoldersSectionProps) {
  // Null until edited, so the ticks follow saved settings until someone changes one.
  const [draft, setDraft] = useState<FindOnlyFolders | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [notice, setNotice] = useState<SaveNotice | null>(null);
  const aliases = Object.entries(settings.download_setup.site_directory_aliases ?? {}).filter(
    ([, folders]) => folders.length > 0,
  );
  const findOnly = draft ?? settings.download_setup.find_only_site_directories ?? {};

  const toggle = (site: string, folder: string) => {
    const current = findOnly[site] ?? [];
    setDraft({
      ...findOnly,
      [site]: current.includes(folder) ? current.filter((value) => value !== folder) : [...current, folder],
    });
    setNotice(null);
  };

  const save = async () => {
    setIsSaving(true);
    setNotice(null);
    try {
      const response = await onSaveSettings({
        download_setup: { ...settings.download_setup, find_only_site_directories: findOnly },
      });
      setDraft(null);
      const propagation = response.storage_propagation;
      setNotice({
        kind: 'status',
        text: propagation
          ? `Find-only folders saved on ${propagation.target_backend_id}; ${propagation.message}`
          : 'Find-only folders saved; worker confirmation was not available.',
      });
    } catch (error) {
      setNotice({ kind: 'alert', text: requestErrorMessage(error, 'Failed to save find-only folders') });
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <section className="fleet-register-panel fleet-staging" aria-labelledby="fleet-find-only-title">
      <div className="fleet-register-panel-header">
        <div>
          <h3 id="fleet-find-only-title">Find-only site folders</h3>
          <p>
            Applies to every mount. Files already in a ticked folder aren't downloaded again, but anything new for those
            creators goes in the main site folder.
          </p>
        </div>
      </div>
      <div className="fleet-staging-body">
        {aliases.length === 0 ? (
          <p className="fleet-staging-empty">No alternate site folders are configured.</p>
        ) : (
          aliases.map(([site, folders]) => (
            <div key={site} className="fleet-find-only-site">
              <h4>{site}</h4>
              <div className="fleet-find-only-list">
                {folders.map((folder) => (
                  <label key={folder}>
                    <input
                      type="checkbox"
                      checked={(findOnly[site] ?? []).includes(folder)}
                      onChange={() => toggle(site, folder)}
                    />
                    <span>{folder}</span>
                  </label>
                ))}
              </div>
            </div>
          ))
        )}
        {aliases.length > 0 && (
          <div className="fleet-staging-actions">
            <button type="button" className="fleet-register-button" onClick={() => void save()} disabled={isSaving || draft === null}>
              {isSaving ? 'Saving...' : 'Save find-only folders'}
            </button>
            {notice && <p role={notice.kind}>{notice.text}</p>}
          </div>
        )}
      </div>
    </section>
  );
}
