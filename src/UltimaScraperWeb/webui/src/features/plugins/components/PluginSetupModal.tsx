import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { createPortal } from 'react-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { approvePluginCapabilities, getPluginSetup, savePluginSetup } from '../../../api/plugins';
import type { PluginRecord } from '../../../api/types/plugins';
import { SettingsFields } from './PluginSettingsPanel';
import './plugin-sdk.css';
import './PluginDialog.css';

function message(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : error instanceof Error ? error.message : 'Plugin setup failed.';
}

export function PluginSetupModal({ plugin, enable, onClose }: { plugin: PluginRecord; enable: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const id = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const busyRef = useRef(false);
  const [draft, setDraft] = useState<Record<string, unknown> | null>(null);
  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [approved, setApproved] = useState(false);
  const query = useQuery({ queryKey: ['plugin-setup', plugin.plugin_id], queryFn: () => getPluginSetup(plugin.plugin_id), refetchOnWindowFocus: false });
  const permissionsPending = !approved && ((plugin.pending_capabilities?.length ?? 0) > 0 || (plugin.pending_scopes?.length ?? 0) > 0);

  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const node = dialog.current;
    node?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); if (!busyRef.current) onClose(); }
      if (event.key === 'Tab' && node) {
        const elements = Array.from(node.querySelectorAll<HTMLElement>('*')).filter((element) => element.matches('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]'));
        const first = elements[0], last = elements.at(-1);
        if (event.shiftKey && (document.activeElement === first || document.activeElement === node)) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || document.activeElement === node)) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener('keydown', keydown);
    return () => { document.removeEventListener('keydown', keydown); previous?.focus(); };
  }, [onClose]);

  const setWorking = (value: boolean) => { busyRef.current = value; setBusy(value); };
  const approve = async () => {
    setWorking(true); setError('');
    try { await approvePluginCapabilities(plugin.plugin_id); setApproved(true); await queryClient.invalidateQueries({ queryKey: ['plugins'] }); }
    catch (failure) { setError(message(failure)); }
    finally { setWorking(false); }
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (permissionsPending || Object.values(fieldErrors).some(Boolean)) return;
    setWorking(true); setError('');
    try {
      await savePluginSetup(plugin.plugin_id, { configuration: draft ?? query.data?.values ?? {}, credentials, enable });
      setCredentials({});
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['plugins'] }),
        queryClient.invalidateQueries({ queryKey: ['plugin-setup', plugin.plugin_id] }),
        queryClient.invalidateQueries({ queryKey: ['plugin-settings', plugin.plugin_id] }),
        queryClient.invalidateQueries({ queryKey: ['active-plugins-webui'] }),
      ]);
      onClose();
    } catch (failure) { setCredentials({}); setError(message(failure)); }
    finally { setWorking(false); }
  };

  return createPortal(<div className="plugin-setup-backdrop">
    <div ref={dialog} className="plugin-setup-modal" role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} tabIndex={-1}>
      <h2 id={`${id}-title`}>{plugin.display_name} setup</h2>
      {query.isLoading && <p role="status">Loading setup…</p>}
      {query.error && <p role="alert">{message(query.error)}</p>}
      {query.data && <form onSubmit={(event) => void submit(event)}>
        <h3>Requested access</h3>
        <ul className="plugin-dialog-permissions">{(plugin.requested_capabilities ?? plugin.capabilities).map((capability) => <li key={capability}><code>{capability}</code></li>)}{plugin.pending_scopes?.map((scope) => <li key={scope}><code>{scope}</code></li>)}</ul>
        <fieldset disabled={busy}>
          {query.data.credentials.map((field) => <div className="plugin-settings-field" key={field.name}>
            <label htmlFor={`${id}-credential-${field.name}`}>{field.title}</label>
            <input id={`${id}-credential-${field.name}`} type="password" autoComplete="new-password" required={field.required && !field.configured} value={credentials[field.name] ?? ''} onChange={(event) => setCredentials((current) => ({ ...current, [field.name]: event.target.value }))} aria-describedby={`${id}-help-${field.name}`} />
            <small id={`${id}-help-${field.name}`}>{field.description}{field.configured ? ' Configured. Leave blank to keep the current key.' : ''}</small>
          </div>)}
          {query.data.schema && <SettingsFields schema={query.data.schema} root={query.data.schema} values={draft ?? query.data.values} onChange={setDraft} path={id} disabled={busy} errors={fieldErrors} onError={(key, value) => setFieldErrors((current) => ({ ...current, [key]: value }))} />}
        </fieldset>
        {permissionsPending && <div>
          <p>Review and approve access before validating setup.</p>
          <p>{[...(plugin.pending_capabilities ?? []), ...(plugin.pending_scopes ?? [])].join(', ')}</p>
          <button type="button" disabled={busy} onClick={() => void approve()}>Approve permissions</button>
        </div>}
        {error && <p role="alert">{error}</p>}
        <div className="plugin-settings-actions">
          <button type="submit" disabled={busy || permissionsPending}>{busy ? 'Validating…' : enable ? 'Validate and enable' : 'Validate and save'}</button>
          <button type="button" disabled={busy} onClick={onClose}>Cancel</button>
        </div>
      </form>}
      {!query.data && <button type="button" onClick={onClose}>Cancel</button>}
    </div>
  </div>, document.body);
}
