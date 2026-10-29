import { useState } from 'react';
import type { SettingsResponse } from '../../../api/types/settings';
import {
  STAGING_POLICIES,
  STAGING_POLICY_LABELS,
  STAGING_USAGES,
  type StagingDirectory,
  type StagingPolicy,
  type StagingUsage,
} from '../../../api/types/setup';
import { FormatTokenList } from '../../../components/shared/FormatTokens';
import './DirectoriesSettingsSection.css';

const KNOWN_SITE_DIRECTORY_KEYS = [
  { key: 'onlyfans', label: 'OnlyFans' },
  { key: 'fansly', label: 'Fansly' },
] as const;

interface DirectoriesSettingsSectionProps {
  settings: SettingsResponse;
  getNestedValue: (section: string, key: string) => unknown;
  onNestedChange: (section: string, key: string, value: unknown) => void;
}

export function DirectoriesSettingsSection({
  settings,
  getNestedValue,
  onNestedChange,
}: DirectoriesSettingsSectionProps) {
  const altDirectoryFormats =
    (getNestedValue('download_setup', 'alt_directory_formats') as string[] | undefined) ??
    settings.download_setup?.alt_directory_formats ??
    [];
  const [aliasDrafts, setAliasDrafts] = useState<Record<string, string>>({});
  const siteDirectoryAliases =
    (getNestedValue('download_setup', 'site_directory_aliases') as Record<string, string[]> | undefined) ??
    settings.download_setup?.site_directory_aliases ??
    {};
  const siteDirectoryAliasSites = [
    ...KNOWN_SITE_DIRECTORY_KEYS,
    ...Object.keys(siteDirectoryAliases)
      .filter((key) => !KNOWN_SITE_DIRECTORY_KEYS.some((site) => site.key === key))
      .map((key) => ({ key, label: key })),
  ];
  const updateSiteDirectoryAliases = (siteKey: string, aliases: string[]) => {
    const nextAliases = { ...siteDirectoryAliases };
    if (aliases.length === 0) {
      delete nextAliases[siteKey];
    } else {
      nextAliases[siteKey] = aliases;
    }
    onNestedChange('download_setup', 'site_directory_aliases', nextAliases);
  };
  const setAliasDraft = (siteKey: string, value: string) => {
    setAliasDrafts((previous) => ({ ...previous, [siteKey]: value }));
  };
  const addSiteDirectoryAlias = (siteKey: string) => {
    const alias = (aliasDrafts[siteKey] ?? '').trim();
    if (!alias) return;
    const aliases = siteDirectoryAliases[siteKey] ?? [];
    if (!aliases.some((value) => value.trim().toLowerCase() === alias.toLowerCase())) {
      updateSiteDirectoryAliases(siteKey, [...aliases, alias]);
    }
    setAliasDraft(siteKey, '');
  };
  const stagingDirectories =
    (getNestedValue('download_setup', 'staging_directories') as StagingDirectory[] | undefined) ??
    settings.download_setup?.staging_directories ??
    [];
  const updateAltDirectoryFormats = (nextFormats: string[]) =>
    onNestedChange('download_setup', 'alt_directory_formats', nextFormats);
  const updateStagingDirectories = (nextDirectories: StagingDirectory[]) =>
    onNestedChange('download_setup', 'staging_directories', nextDirectories);
  const addAltDirectoryFormat = () =>
    updateAltDirectoryFormats([...altDirectoryFormats, '']);
  const addStagingDirectory = () =>
    updateStagingDirectories([
      ...stagingDirectories,
      {
        path: '',
        usage: ['downloads', 'merge', 'drm'],
        policy: [],
      },
    ]);
  const updateStagingDirectory = <K extends keyof StagingDirectory>(
    index: number,
    field: K,
    value: StagingDirectory[K]
  ) =>
    updateStagingDirectories(
      stagingDirectories.map((directory, currentIndex) =>
        currentIndex === index ? { ...directory, [field]: value } : directory
      )
    );
  const removeStagingDirectory = (index: number) =>
    updateStagingDirectories(stagingDirectories.filter((_, currentIndex) => currentIndex !== index));
  const updateAltDirectoryFormat = (index: number, value: string) =>
    updateAltDirectoryFormats(
      altDirectoryFormats.map((format, currentIndex) =>
        currentIndex === index ? value : format
      )
    );
  const removeAltDirectoryFormat = (index: number) =>
    updateAltDirectoryFormats(
      altDirectoryFormats.filter((_, currentIndex) => currentIndex !== index)
    );
  const toggleStagingPolicy = (index: number, policy: StagingPolicy) => {
    const { policy: currentPolicy } = stagingDirectories[index];
    updateStagingDirectory(
      index,
      'policy',
      currentPolicy.includes(policy)
        ? currentPolicy.filter((value) => value !== policy)
        : [...currentPolicy, policy]
    );
  };
  const toggleStagingUsage = (index: number, usage: StagingUsage) => {
    const directory = stagingDirectories[index];
    const hasUsage = directory.usage.includes(usage);
    const nextUsage = hasUsage
      ? directory.usage.filter((value) => value !== usage)
      : [...directory.usage, usage];
    if (nextUsage.length === 0) return;
    updateStagingDirectory(index, 'usage', nextUsage);
  };

  const directoryFormat =
    (getNestedValue('download_setup', 'directory_format') as string)
    ?? settings.download_setup?.directory_format
    ?? '';
  const filenameFormat =
    (getNestedValue('download_setup', 'filename_format') as string)
    ?? settings.download_setup?.filename_format
    ?? '';

  return (
    <div className="settings-section">
      <h2>Download Setup</h2>

      <div className="setting-item">
        <label htmlFor="directory-format">Directory Format</label>
        <input
          id="directory-format"
          type="text"
          value={directoryFormat}
          onChange={(event) =>
            onNestedChange('download_setup', 'directory_format', event.target.value)}
          placeholder="{site_name}/{user_username}/{content_type}/{content_value}/{media_type}"
        />
        <FormatTokenList field="directory" className="setting-description" value={directoryFormat} />
      </div>

      <div className="setting-item">
        <label htmlFor="filename-format">Filename Format</label>
        <input
          id="filename-format"
          type="text"
          value={filenameFormat}
          onChange={(event) =>
            onNestedChange('download_setup', 'filename_format', event.target.value)}
          placeholder="{media_id}_{media_filename}.{media_ext}"
        />
        <FormatTokenList field="filename" className="setting-description" value={filenameFormat} />
      </div>

      <h3>Alt Directory Formats</h3>
      <p className="setting-description">
        Alt formats only match the performer folder and must include {'{user_username}'} or{' '}
        {'{user_id}'}. <FormatTokenList field="altDirectory" value={altDirectoryFormats} />
      </p>
      <div className="drives-list">
        {altDirectoryFormats.map((format, index) => (
          <div key={index} className="drive-item">
            <input
              type="text"
              value={format}
              onChange={(event) => updateAltDirectoryFormat(index, event.target.value)}
              placeholder="{site_name}/{user_username}/{content_type}/{content_value}/{media_type}"
            />
            <button type="button" onClick={() => removeAltDirectoryFormat(index)}>
              Remove
            </button>
          </div>
        ))}
        <button type="button" onClick={addAltDirectoryFormat}>
          Add alt directory format
        </button>
      </div>

      <h3>Site Directory Aliases</h3>
      <p className="setting-description">
        Keep existing performer folders under alternate site folder names. The canonical
        folder is still checked first; each alias is a single folder name, not a path.
      </p>
      <div className="site-directory-aliases-list">
        {siteDirectoryAliasSites.map(({ key: siteKey, label }) => {
          const aliases = siteDirectoryAliases[siteKey] ?? [];
          return (
            <div key={siteKey} className="site-directory-alias-row">
              <div className="site-directory-alias-heading">
                <strong>{label}</strong>
                <span className="setting-description">
                  Canonical folder: <code>{label}</code>
                </span>
              </div>
              <div className="site-directory-alias-values">
                {aliases.length > 0 ? aliases.map((alias, index) => (
                  <div key={`${siteKey}-${index}`} className="site-directory-alias-value">
                    <input
                      type="text"
                      aria-label={`${label} directory alias ${index + 1}`}
                      value={alias}
                      onChange={(event) => {
                        const nextAliases = [...aliases];
                        nextAliases[index] = event.target.value;
                        updateSiteDirectoryAliases(siteKey, nextAliases);
                      }}
                    />
                    <button
                      type="button"
                      className="site-directory-alias-remove"
                      onClick={() => updateSiteDirectoryAliases(
                        siteKey,
                        aliases.filter((_, currentIndex) => currentIndex !== index),
                      )}
                    >
                      Remove
                    </button>
                  </div>
                )) : (
                  <span className="site-directory-alias-empty">No alternate folder names configured.</span>
                )}
              </div>
              <div className="site-directory-alias-add">
                <input
                  type="text"
                  aria-label={`New ${label} directory alias`}
                  value={aliasDrafts[siteKey] ?? ''}
                  onChange={(event) => setAliasDraft(siteKey, event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') {
                      event.preventDefault();
                      addSiteDirectoryAlias(siteKey);
                    }
                  }}
                  placeholder={`e.g. ${label}Images`}
                />
                <button type="button" onClick={() => addSiteDirectoryAlias(siteKey)}>
                  Add alias
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <div className="setting-item">
        <label htmlFor="text-length">Text Length Limit</label>
        <input
          id="text-length"
          type="number"
          min="0"
          max="255"
          value={
            (getNestedValue('download_setup', 'text_length') as number)
            ?? settings.download_setup?.text_length
            ?? 255
          }
          onChange={(event) =>
            onNestedChange('download_setup', 'text_length', parseInt(event.target.value, 10))}
        />
      </div>

      <div className="setting-item">
        <label htmlFor="date-format">Date Format</label>
        <input
          id="date-format"
          type="text"
          value={
            (getNestedValue('download_setup', 'date_format') as string)
            ?? settings.download_setup?.date_format
            ?? ''
          }
          onChange={(event) =>
            onNestedChange('download_setup', 'date_format', event.target.value)}
          placeholder="%Y-%m-%d"
        />
      </div>

      <div className="setting-item checkbox">
        <label>
          <input
            type="checkbox"
            checked={
              (getNestedValue('download_setup', 'overwrite_files') as boolean)
              ?? settings.download_setup?.overwrite_files
              ?? false
            }
            onChange={(event) =>
              onNestedChange('download_setup', 'overwrite_files', event.target.checked)}
          />
          Overwrite Files
        </label>
        <span className="setting-description">Overwrite existing downloaded files</span>
      </div>

      <h3>Download Drives</h3>
      <div className="drives-list">
        {(settings.download_setup?.drives || []).map((drive, index) => (
          <div key={index} className="drive-item">
            <span className="drive-directories">
              {drive.directories.join(', ') || 'No directories'}
            </span>
            <span className="drive-info">
              {drive.store ? '✓ Store' : '✗ No Store'} | {drive.overflow ? ' ✓ Overflow' : ' ✗ No Overflow'} | Min:{' '}
              {Math.round(drive.minimum_space / 1024 / 1024 / 1024)} GB
            </span>
          </div>
        ))}
      </div>

      <h3>Staging Directories</h3>
      <div className="drives-list">
        {stagingDirectories.map((directory, index) => (
          <div key={index} className="drive-item">
            <input
              type="text"
              value={directory.path}
              onChange={(event) => updateStagingDirectory(index, 'path', event.target.value)}
              placeholder="/path/to/staging"
            />
            <div className="setting-description">
              {STAGING_USAGES.map((usage) => (
                <label key={usage} style={{ marginRight: '1rem' }}>
                  <input
                    type="checkbox"
                    checked={directory.usage.includes(usage)}
                    onChange={() => toggleStagingUsage(index, usage)}
                  />{' '}
                  {usage}
                </label>
              ))}
              {STAGING_POLICIES.map((policy) => (
                <label key={policy} style={{ marginRight: '1rem' }} title={STAGING_POLICY_LABELS[policy]}>
                  <input
                    type="checkbox"
                    checked={directory.policy.includes(policy)}
                    onChange={() => toggleStagingPolicy(index, policy)}
                  />{' '}
                  {policy}
                </label>
              ))}
              <label>
                Keep free (GB){' '}
                <input
                  type="number"
                  min={0}
                  value={Math.floor((directory.min_free_bytes ?? 0) / (1024 * 1024 * 1024))}
                  onChange={(event) =>
                    updateStagingDirectory(
                      index,
                      'min_free_bytes',
                      (parseInt(event.target.value, 10) || 0) * 1024 * 1024 * 1024
                    )
                  }
                />
              </label>
            </div>
            <button type="button" onClick={() => removeStagingDirectory(index)}>
              Remove
            </button>
          </div>
        ))}
        <button type="button" onClick={addStagingDirectory}>
          Add staging directory
        </button>
      </div>

      <h2>Metadata Setup</h2>
      <div className="setting-item">
        <label htmlFor="metadata-dir-format">Metadata Directory Format</label>
        <input
          id="metadata-dir-format"
          type="text"
          value={
            (getNestedValue('metadata_setup', 'directory_format') as string)
            ?? settings.metadata_setup?.directory_format
            ?? ''
          }
          onChange={(event) =>
            onNestedChange('metadata_setup', 'directory_format', event.target.value)}
        />
      </div>

      <h3>Metadata Drives</h3>
      <div className="drives-list">
        {(settings.metadata_setup?.drives || []).map((drive, index) => (
          <div key={index} className="drive-item">
            <span className="drive-directories">
              {drive.directories.join(', ') || 'No directories'}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
