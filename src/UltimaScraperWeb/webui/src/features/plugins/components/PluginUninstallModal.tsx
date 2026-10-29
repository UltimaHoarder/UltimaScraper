import { useState } from 'react';
import { uninstallPlugin } from '../../../api/plugins';
import type { PluginRecord } from '../../../api/types/plugins';
import { PluginDialog } from './PluginDialog';
import { pluginError } from '../lib/pluginErrors';

export function PluginUninstallModal({ plugin, onClose, onUninstalled }: { plugin: PluginRecord; onClose: () => void; onUninstalled: (id: string) => void }) {
  const [deleteData, setDeleteData] = useState(false);
  const [confirmation, setConfirmation] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const uninstall = async () => {
    setBusy(true); setError('');
    try { await uninstallPlugin(plugin.plugin_id, deleteData, confirmation); onUninstalled(plugin.plugin_id); }
    catch (failure) { setError(pluginError(failure)); setBusy(false); }
  };
  return <PluginDialog title={`Uninstall ${plugin.display_name}`} busy={busy} onClose={onClose}>
    <p>Stops this plugin and removes its runtime installation. The source repository remains in USRPlugins.</p>
    <p>Configuration, credentials, state, and history are retained for reinstall.</p>
    <label className="plugin-dialog-check"><input type="checkbox" checked={deleteData} disabled={busy} onChange={(event) => { setDeleteData(event.target.checked); setConfirmation(''); }} />Delete retained data</label>
    {deleteData && <label>Type {plugin.plugin_id} to permanently delete retained data<input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} disabled={busy} autoComplete="off" /></label>}
    {error && <p role="alert">{error}</p>}
    <div className="plugin-dialog-actions"><button type="button" className="plugin-dialog-danger" disabled={busy || (deleteData && confirmation !== plugin.plugin_id)} onClick={() => void uninstall()}>{busy ? 'Uninstalling…' : deleteData ? 'Uninstall and delete data' : 'Uninstall'}</button><button type="button" disabled={busy} onClick={onClose}>Cancel</button></div>
  </PluginDialog>;
}
