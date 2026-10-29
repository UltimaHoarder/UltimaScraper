import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { saveWebhookConfiguration } from '../../../api/webhooks';
import type { SiteWebhookRouting, WebhookConfiguration, WebhookDestination, WebhookRule, WebhooksResponse, WebhookSite } from '../../../api/types/webhooks';
import { webhookConfiguration, routingError } from '../lib/webhookConfiguration';
import { siteLabels } from '../lib/webhooksUtils';
import { Icon, Panel, Tag } from './WebhooksDesignWorkspace';
import './WebhookConfigurationEditor.css';

interface Props {
  data: WebhooksResponse;
  onSaved: (configuration: WebhookConfiguration) => void;
  onReload: () => Promise<WebhooksResponse>;
}

function newRule(site: WebhookSite, id = `new-${site}`): WebhookRule {
  return { id, name: `${siteLabels[site]} alerts`, hooks: [], destination_ids: [], active: true, hide_info: [] };
}

export function WebhookConfigurationEditor({ data, onSaved, onReload }: Props) {
  const [baseline, setBaseline] = useState(() => webhookConfiguration(data));
  const [drafts, setDrafts] = useState(() => structuredClone(baseline.sites));
  const [site, setSite] = useState<WebhookSite>('onlyfans');
  const [selection, setSelection] = useState<Partial<Record<WebhookSite, string>>>({});
  const [formError, setFormError] = useState('');
  const [status, setStatus] = useState('');
  const [reloading, setReloading] = useState(false);
  const routing = drafts[site];
  const selectedRule = routing.rules.find((rule) => rule.id === selection[site]) ?? (selection[site] ? undefined : routing.rules[0]);
  const rule = selectedRule ?? newRule(site);
  const hooks = baseline.catalog.filter((hook) => hook.sites.includes(site));
  const dirty = JSON.stringify(routing) !== JSON.stringify(baseline.sites[site]);
  const save = useMutation({
    mutationFn: ({ selectedSite, draft }: { selectedSite: WebhookSite; draft: SiteWebhookRouting }) => saveWebhookConfiguration(selectedSite, draft, baseline.version!),
    onSuccess: (configuration, variables) => {
      setBaseline(structuredClone(configuration));
      setDrafts((current) => ({ ...current, [variables.selectedSite]: structuredClone(configuration.sites[variables.selectedSite]) }));
      setStatus(`${siteLabels[variables.selectedSite]} configuration saved.`);
      onSaved(configuration);
    },
  });

  function updateRouting(next: SiteWebhookRouting) {
    setDrafts((current) => ({ ...current, [site]: next }));
    setFormError(''); setStatus(''); save.reset();
  }
  function updateRule(change: Partial<WebhookRule>) {
    const next = { ...rule, ...change };
    updateRouting({ ...routing, rules: selectedRule ? routing.rules.map((item) => item.id === next.id ? next : item) : [...routing.rules, next] });
    setSelection((current) => ({ ...current, [site]: next.id }));
  }
  function updateDestination(id: string, change: Partial<WebhookDestination>) {
    updateRouting({ ...routing, destinations: routing.destinations.map((destination) => destination.id === id ? { ...destination, ...change } : destination) });
  }
  function addDestination() {
    const destination: WebhookDestination = { id: crypto.randomUUID(), name: '', url: '', format: 'json' };
    const nextRule = { ...rule, destination_ids: [...rule.destination_ids, destination.id] };
    updateRouting({ destinations: [...routing.destinations, destination], rules: selectedRule ? routing.rules.map((item) => item.id === rule.id ? nextRule : item) : [...routing.rules, nextRule] });
    setSelection((current) => ({ ...current, [site]: rule.id }));
  }
  function removeDestination(id: string) {
    updateRouting({ destinations: routing.destinations.filter((destination) => destination.id !== id), rules: routing.rules.map((item) => ({ ...item, destination_ids: item.destination_ids.filter((destinationId) => destinationId !== id) })) });
  }
  function submit() {
    const error = routingError(routing);
    if (error) { setFormError(error); return; }
    setFormError(''); setStatus('');
    save.mutate({ selectedSite: site, draft: structuredClone(routing) });
  }
  async function reload() {
    setReloading(true);
    try {
      const next = webhookConfiguration(await onReload());
      setBaseline(next); setDrafts(structuredClone(next.sites)); setSelection({});
      setFormError(''); setStatus('Configuration reloaded.'); save.reset();
    } catch (error) { setFormError(error instanceof Error ? error.message : 'Could not reload configuration.'); }
    finally { setReloading(false); }
  }

  return <div className="wh-config-editor">
    <Panel title="1 · Choose a site" action={<Tag>{dirty ? 'Unsaved changes' : 'Saved configuration'}</Tag>}>
      <div className="wh-config-sites">{(['onlyfans', 'fansly'] as const).map((item) => <button type="button" key={item} aria-label={`Configure ${siteLabels[item]}`} aria-pressed={site === item} onClick={() => { setSite(item); setFormError(''); setStatus(''); save.reset(); }} disabled={save.isPending || reloading}><span className={`wh-site-mark wh-site-mark--${item}`} aria-hidden="true">{item === 'onlyfans' ? 'OF' : 'FY'}</span><span><strong>{siteLabels[item]}</strong><small>{drafts[item].rules.length} rules · {drafts[item].destinations.length} destinations</small></span><Icon name="arrow" /></button>)}</div>
    </Panel>
    <div className="wh-config-layout">
      <aside className="wh-config-rules"><Panel title="Routing rules" action={<button type="button" className="wh-text-btn" disabled={save.isPending} onClick={() => { const next = newRule(site, crypto.randomUUID()); next.name = `Rule ${routing.rules.length + 1}`; updateRouting({ ...routing, rules: [...routing.rules, next] }); setSelection((current) => ({ ...current, [site]: next.id })); }}>＋ Add rule</button>}>
        {routing.rules.length ? <div className="wh-config-rule-list">{routing.rules.map((item) => <button type="button" key={item.id} aria-pressed={rule.id === item.id} onClick={() => setSelection((current) => ({ ...current, [site]: item.id }))}><strong>{item.name || 'Unnamed rule'}</strong><span>{item.hooks.length} hooks → {item.destination_ids.length} destinations</span><Tag tone={item.active ? 'accent' : 'muted'}>{item.active ? 'Enabled' : 'Disabled'}</Tag></button>)}</div> : <p className="wh-footnote">Choose hooks and add a destination to create your first rule.</p>}
      </Panel><p className="wh-footnote">A rule sends its selected hooks to every selected destination.</p></aside>
      <div className="wh-config-form"><fieldset disabled={save.isPending || reloading} className="wh-config-fields">
        <div className="wh-config-rule-heading"><label className="wh-config-field"><span>Rule name</span><input aria-label="Rule name" maxLength={100} value={rule.name} onChange={(event) => updateRule({ name: event.target.value })} /></label><label className="wh-check"><input type="checkbox" checked={rule.active} onChange={(event) => updateRule({ active: event.target.checked })} />Rule enabled</label>{selectedRule && <button type="button" className="wh-text-btn" onClick={() => { updateRouting({ ...routing, rules: routing.rules.filter((item) => item.id !== rule.id) }); setSelection((current) => ({ ...current, [site]: undefined })); }}>Remove rule</button>}</div>
        <Panel title="2 · Choose hooks" action={<Tag>{rule.hooks.length} selected</Tag>}>
          {site === 'fansly' && <p className="wh-footnote">Site message hooks are currently available for OnlyFans. Fansly supports account changes and download results.</p>}
          <div className="wh-config-hook-grid">{hooks.map((hook) => <label className={`wh-config-choice ${rule.hooks.includes(hook.id) ? 'is-selected' : ''}`} key={hook.id}><input type="checkbox" aria-label={`Hook: ${hook.label}`} checked={rule.hooks.includes(hook.id)} onChange={(event) => updateRule({ hooks: event.target.checked ? [...rule.hooks, hook.id] : rule.hooks.filter((item) => item !== hook.id) })} /><span><strong>{hook.label}</strong><small>{hook.description}</small></span></label>)}</div>
        </Panel>
        <Panel title="3 · Choose destinations" action={<button type="button" className="wh-text-btn" onClick={addDestination}>＋ Add destination</button>}>
          {!routing.destinations.length && <div className="wh-empty"><Icon name="route" /><strong>No destinations yet</strong><span>Add a URL, then choose where these hooks should go.</span><button type="button" className="wh-btn" onClick={addDestination}>Add first destination</button></div>}
          <div className="wh-config-destinations">{routing.destinations.map((destination, index) => <div className="wh-config-destination" key={destination.id}>
            <div className="wh-config-destination-head"><label className="wh-check"><input type="checkbox" aria-label={`Send to ${destination.name || `destination ${index + 1}`}`} checked={rule.destination_ids.includes(destination.id)} onChange={(event) => updateRule({ destination_ids: event.target.checked ? [...rule.destination_ids, destination.id] : rule.destination_ids.filter((id) => id !== destination.id) })} />{destination.name || `Destination ${index + 1}`}</label><button type="button" className="wh-text-btn" aria-label={`Remove destination ${index + 1}`} onClick={() => removeDestination(destination.id)}>Remove</button></div>
            <div className="wh-config-destination-fields"><label className="wh-config-field"><span>Name</span><input aria-label={`Destination ${index + 1} name`} maxLength={100} placeholder="e.g. Operations" value={destination.name} onChange={(event) => updateDestination(destination.id, { name: event.target.value })} /></label><label className="wh-config-field"><span>Payload</span><select aria-label={`Destination ${index + 1} payload`} value={destination.format} onChange={(event) => updateDestination(destination.id, { format: event.target.value as WebhookDestination['format'] })}><option value="json">JSON</option><option value="discord">Discord</option></select></label><label className="wh-config-field wh-config-url"><span>Destination URL</span><input type="url" aria-label={`Destination ${index + 1} URL`} placeholder="https://…" value={destination.url} onChange={(event) => updateDestination(destination.id, { url: event.target.value })} /></label></div>
          </div>)}</div>
        </Panel>
        <details className="wh-config-advanced"><summary>Fields to omit</summary><label className="wh-config-field"><span>Omit these fields from this rule’s payloads</span><input aria-label="Fields to omit" value={rule.hide_info.join(', ')} placeholder="username, directory" onChange={(event) => updateRule({ hide_info: event.target.value.split(',').map((value) => value.trim()) })} /><small>Separate field names with commas. Credentials are always omitted.</small></label></details>
      </fieldset>
      <div className="wh-config-save"><div><strong>{rule.hooks.length} hooks → {rule.destination_ids.length} destinations</strong><span>{dirty ? `Unsaved changes for ${siteLabels[site]}` : `Configuration for ${siteLabels[site]}`}</span></div><button type="button" className="wh-btn wh-btn--quiet" disabled={save.isPending || reloading} onClick={() => void reload()}>{reloading ? 'Reloading…' : 'Discard changes and reload'}</button><button type="button" className="wh-btn wh-btn--primary" disabled={!dirty || save.isPending || reloading || baseline.version === null} onClick={submit}>{save.isPending ? 'Saving…' : 'Save configuration'}</button></div>
      {baseline.version === null && <p className="wh-footnote" role="status">Saving webhook routes is unavailable on this backend.</p>}
      {(formError || save.error) && <p className="wh-config-error" role="alert">{formError || (save.error instanceof Error ? save.error.message : 'Could not save configuration.')}</p>}
      {status && <p className="wh-footnote" role="status">{status}</p>}
      </div>
    </div>
  </div>;
}
