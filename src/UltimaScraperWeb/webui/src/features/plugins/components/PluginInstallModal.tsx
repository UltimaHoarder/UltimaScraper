import { useCallback, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { cancelPluginInstall, confirmPluginInstall, listPluginSources, preparePluginInstall } from '../../../api/plugins';
import type { PluginInstallPreview, PluginRecord } from '../../../api/types/plugins';
import { PluginDialog } from './PluginDialog';
import { pluginError } from '../lib/pluginErrors';

export function PluginInstallModal({ onClose, onInstalled }: { onClose: () => void; onInstalled: (plugin: PluginRecord) => void }) {
  const [kind, setKind] = useState<'local' | 'git'>('local');
  const [sourceId, setSourceId] = useState('');
  const [url, setUrl] = useState('');
  const [revision, setRevision] = useState('');
  const [preview, setPreview] = useState<PluginInstallPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const query = useQuery({ queryKey: ['plugin-sources'], queryFn: listPluginSources, retry: false });
  const close = useCallback(async () => {
    if (preview) {
      setBusy(true);
      try { await cancelPluginInstall(preview); }
      catch (failure) { setError(pluginError(failure)); setBusy(false); return; }
    }
    onClose();
  }, [preview, onClose]);
  const prepare = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('');
    try { setPreview(await preparePluginInstall(kind === 'local' ? { kind, source_id: sourceId } : { kind, url: url.trim(), revision: revision.trim() || undefined })); }
    catch (failure) { setError(pluginError(failure)); }
    finally { setBusy(false); }
  };
  const install = async () => {
    if (!preview) return;
    setBusy(true); setError('');
    try { onInstalled(await confirmPluginInstall(preview)); }
    catch (failure) { setError(pluginError(failure)); setBusy(false); }
  };
  return <PluginDialog title="Install plugin" busy={busy} onClose={close}>
    {!preview ? <>
      <div className="plugin-install-sources" aria-label="Installation source">
        <button type="button" aria-pressed={kind === 'local'} disabled={busy} onClick={() => { setKind('local'); setError(''); }}>Local folder</button>
        <button type="button" aria-pressed={kind === 'git'} disabled={busy} onClick={() => { setKind('git'); setError(''); }}>Git repository</button>
      </div>
      <form onSubmit={(event) => void prepare(event)}>
        {kind === 'local' ? <>
          {query.isLoading && <p role="status">Loading plugin sources…</p>}
          {query.error && <p role="alert">{pluginError(query.error)}</p>}
          <label>Source folder<select value={sourceId} required disabled={busy || !query.data?.length} onChange={(event) => setSourceId(event.target.value)}>
            <option value="">Choose a plugin</option>{query.data?.map((source) => <option key={source.source_id} value={source.source_id} disabled={source.installed}>{source.display_name} · {source.source_id}{source.installed ? ' · Installed' : source.data_retained ? ' · Data retained' : ''}</option>)}
          </select></label>
          {query.data?.length === 0 && <p>No source repositories found in USRPlugins. Choose Git repository to add one.</p>}
        </> : <><label>Git URL<input value={url} onChange={(event) => setUrl(event.target.value)} required disabled={busy} placeholder="https://github.com/owner/plugin.git" /></label>
          <label>Revision<input value={revision} onChange={(event) => setRevision(event.target.value)} disabled={busy} placeholder="Default branch, tag, or commit" /></label><small>Authentication uses the server’s existing Git configuration.</small></>}
        {error && <p role="alert">{error}</p>}
        <div className="plugin-dialog-actions"><button type="submit" className="plugin-dialog-primary" disabled={busy || (kind === 'local' ? !sourceId : !url.trim())}>{busy ? 'Preparing…' : 'Review package'}</button><button type="button" disabled={busy} onClick={() => void close()}>Cancel</button></div>
      </form>
    </> : <>
      <h3>{preview.display_name}</h3><dl><div><dt>Plugin</dt><dd><code>{preview.plugin_id}</code></dd></div><div><dt>Version</dt><dd>{preview.plugin_version}</dd></div><div><dt>Commit</dt><dd><code>{preview.source.revision}</code>{preview.source.dirty && ' · Local changes'}</dd></div><div><dt>Package</dt><dd><code>{preview.package_digest}</code></dd></div></dl>
      <h3>Requested access</h3><ul className="plugin-dialog-permissions">{preview.requested_capabilities.map((capability) => <li key={capability}><code>{capability}</code></li>)}{Object.entries(preview.requested_scopes).flatMap(([scope, values]) => Array.isArray(values) ? values.map((value) => <li key={`${scope}:${value}`}><code>{scope}:{value}</code></li>) : values ? [<li key={scope}><code>{scope}</code></li>] : [])}</ul>
      <p>Install disabled, then complete setup and approve access before enabling.</p>
      {error && <p role="alert">{error}</p>}
      <div className="plugin-dialog-actions"><button type="button" className="plugin-dialog-primary" disabled={busy} onClick={() => void install()}>{busy ? 'Installing…' : 'Install and set up'}</button><button type="button" disabled={busy} onClick={() => void close()}>Cancel</button></div>
    </>}
  </PluginDialog>;
}
