import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { getPluginSettings, setPluginConfiguration, testPluginConnection } from '../../../api/plugins';
import type { PluginRecord } from '../../../api/types/plugins';
import './plugin-sdk.css';

type Schema = Record<string, unknown>;
type Values = Record<string, unknown>;
const object = (value: unknown): Values => value && typeof value === 'object' && !Array.isArray(value) ? value as Values : {};
const labelFor = (key: string, schema: Schema) => typeof schema.title === 'string' ? schema.title : key.replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase());

function resolve(schema: Schema, root: Schema): Schema {
  let current = schema;
  const seen = new Set<string>();
  while (typeof current.$ref === 'string' && current.$ref.startsWith('#/') && !seen.has(current.$ref)) {
    seen.add(current.$ref);
    const referenced = current.$ref.slice(2).split('/').reduce<unknown>((value, part) => object(value)[part.replaceAll('~1', '/').replaceAll('~0', '~')], root);
    current = { ...object(referenced), ...Object.fromEntries(Object.entries(current).filter(([key]) => key !== '$ref')) };
  }
  return current;
}

function defaults(schema: Schema, root: Schema, depth = 0): unknown {
  schema = resolve(schema, root);
  if (schema.default !== undefined) return structuredClone(schema.default);
  if (schema.type === 'object' && depth < 8) {
    return Object.fromEntries(Object.entries(object(schema.properties)).flatMap(([key, field]) => {
      const value = defaults(object(field), root, depth + 1);
      return value === undefined ? [] : [[key, value]];
    }));
  }
  return undefined;
}

function errorMessage(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : error instanceof Error ? error.message : 'Request failed.';
}

export function SettingsFields({ schema, root, values, onChange, path, disabled, errors, onError, depth = 0 }: {
  schema: Schema; root: Schema; values: Values; onChange: (value: Values) => void;
  path: string; disabled: boolean; errors: Record<string, string>; onError: (key: string, error: string) => void; depth?: number;
}) {
  return <>{Object.entries(object(schema.properties)).map(([key, definition]) => {
    const field = resolve(object(definition), root);
    const id = `${path}-${key}`;
    const types = Array.isArray(field.type) ? field.type : [field.type];
    const type = types.find((item) => item !== 'null');
    const value = values[key];
    const required = Array.isArray(schema.required) && schema.required.includes(key) && !types.includes('null');
    const readOnly = disabled || field.readOnly === true;
    const update = (next: unknown) => {
      const updated = { ...values };
      if (next === undefined) delete updated[key]; else updated[key] = next;
      onChange(updated);
    };
    const common = { id, disabled: readOnly, required, 'aria-describedby': typeof field.description === 'string' ? `${id}-help` : undefined };
    let control;
    if (type === 'object' && field.properties && depth < 8) {
      control = <fieldset disabled={readOnly}><legend>{labelFor(key, field)}</legend><SettingsFields schema={field} root={root} values={object(value)} onChange={update} path={id} disabled={readOnly} errors={errors} onError={onError} depth={depth + 1} /></fieldset>;
    } else if (Array.isArray(field.enum)) {
      const selected = field.enum.findIndex((option) => JSON.stringify(option) === JSON.stringify(value));
      control = <select {...common} value={selected < 0 ? '' : String(selected)} onChange={(event) => update(event.target.value === '' ? undefined : (field.enum as unknown[])[Number(event.target.value)])}>
        <option value="">Choose a value</option>{field.enum.map((option, index) => <option key={index} value={index}>{String(option)}</option>)}
      </select>;
    } else if (type === 'boolean') {
      control = <input id={id} type="checkbox" disabled={readOnly} checked={value === true} onChange={(event) => update(event.target.checked)} />;
    } else if (type === 'number' || type === 'integer') {
      control = <input {...common} type="number" value={typeof value === 'number' ? value : ''} min={typeof field.minimum === 'number' ? field.minimum : undefined} max={typeof field.maximum === 'number' ? field.maximum : undefined} step={typeof field.multipleOf === 'number' ? field.multipleOf : type === 'integer' ? 1 : 'any'} onChange={(event) => update(event.target.value === '' ? undefined : event.target.valueAsNumber)} />;
    } else if (type === 'string') {
      control = <input {...common} type={field.format === 'uri' ? 'url' : field.format === 'email' ? 'email' : 'text'} value={typeof value === 'string' ? value : ''} minLength={typeof field.minLength === 'number' ? field.minLength : undefined} maxLength={typeof field.maxLength === 'number' ? field.maxLength : undefined} ref={(node) => {
        if (!node) return;
        let matches = true;
        if (node.value && typeof field.pattern === 'string') {
          try { matches = new RegExp(field.pattern).test(node.value); } catch { /* Server validation handles unsupported expressions. */ }
        }
        node.setCustomValidity(matches ? '' : 'Enter a value that matches this setting’s required format.');
      }} onChange={(event) => update(event.target.value === '' && !required ? undefined : event.target.value)} />;
    } else {
      control = <textarea {...common} rows={4} defaultValue={value === undefined ? '' : JSON.stringify(value, null, 2)} onChange={(event) => {
        try { update(event.target.value.trim() ? JSON.parse(event.target.value) : undefined); onError(id, ''); }
        catch { onError(id, 'Enter valid JSON for this field.'); }
      }} />;
    }
    return <div className="plugin-settings-field" key={id}>
      {type !== 'object' && <label htmlFor={id}>{labelFor(key, field)}{required && <span aria-hidden="true"> *</span>}</label>}
      {control}
      {typeof field.description === 'string' && <small id={`${id}-help`}>{field.description}</small>}
      {field.default !== undefined && <small>Default: {typeof field.default === 'object' ? JSON.stringify(field.default) : String(field.default)}</small>}
      {errors[id] && <small role="alert">{errors[id]}</small>}
    </div>;
  })}</>;
}

export function PluginSettingsPanel({ plugin, onClose, onManageCredentials, embedded = false }: { plugin: PluginRecord; onClose: () => void; onManageCredentials: () => void; embedded?: boolean }) {
  const client = useQueryClient();
  const id = useId();
  const section = useRef<HTMLElement>(null);
  const [draft, setDraft] = useState<Values | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState('');
  const [resetRevision, setResetRevision] = useState(0);
  const query = useQuery({ queryKey: ['plugin-settings', plugin.plugin_id], queryFn: () => getPluginSettings(plugin.plugin_id), refetchOnWindowFocus: false, refetchOnReconnect: false });
  const values = draft ?? query.data?.values ?? {};
  useEffect(() => { if (!embedded) { section.current?.focus({ preventScroll: true }); section.current?.scrollIntoView?.({ block: 'nearest' }); } }, [embedded]);
  const save = useMutation({
    mutationFn: () => setPluginConfiguration(plugin.plugin_id, values),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['plugin-settings', plugin.plugin_id] });
      setDraft(null);
      setNotice('Settings saved.');
      void client.invalidateQueries({ queryKey: ['plugins'] });
      void client.invalidateQueries({ queryKey: ['active-plugins-webui'] });
    },
  });
  const test = useMutation({ mutationFn: (target: string) => testPluginConnection(plugin.plugin_id, target, values) });
  const schema = query.data?.schema;
  const valid = !!schema && !Object.values(errors).some(Boolean);
  const dirty = !!query.data && JSON.stringify(values) !== JSON.stringify(query.data.values);
  const busy = save.isPending || test.isPending;
  const submit = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); setNotice(''); test.reset(); if (valid) save.mutate(); };
  const edit = (next: Values) => { setDraft(next); setNotice(''); save.reset(); test.reset(); };

  return <section ref={section} tabIndex={-1} className="plugin-settings-panel" aria-labelledby={`${id}-title`}>
    <div className="plugin-settings-heading"><h2 id={`${id}-title`}>{embedded ? 'Plugin settings' : `${plugin.display_name} settings`}</h2>{!embedded && <button type="button" onClick={onClose}>Close settings</button>}</div>
    {query.isLoading && <p role="status">Loading settings…</p>}
    {query.error && <p role="alert">{errorMessage(query.error)}</p>}
    {query.data && !schema && <p>This plugin does not declare any settings.</p>}
    {schema && <form onSubmit={submit}>
      {typeof schema.description === 'string' && <p>{schema.description}</p>}
      <SettingsFields key={resetRevision} schema={schema} root={schema} values={values} onChange={edit} path={id} disabled={busy} errors={errors} onError={(key, error) => setErrors((previous) => ({ ...previous, [key]: error }))} />
      <div className="plugin-settings-actions">
        <button type="submit" disabled={busy || !valid || !dirty}>{save.isPending ? 'Saving…' : 'Save settings'}</button>
        <button type="button" disabled={busy} onClick={() => { edit(object(defaults(schema, schema))); setErrors({}); setResetRevision((current) => current + 1); }}>Use defaults</button>
        {query.data?.connections.map((connection) => <button type="button" key={connection.name} disabled={busy || !valid} title={connection.label} onClick={(event) => { if (event.currentTarget.form?.reportValidity()) test.mutate(connection.name); }}>{query.data!.connections.length === 1 ? 'Test connection' : `Test ${connection.label}`}</button>)}
        <button type="button" onClick={onManageCredentials}>Manage credentials</button>
      </div>
      {dirty && <p className="plugin-settings-hint">Unsaved changes. Connection tests use these values without saving them.</p>}
      {(save.error || test.error) && <p role="alert">{errorMessage(save.error || test.error)}</p>}
      {(notice || test.data?.message) && <p role="status">{notice || test.data?.message}</p>}
    </form>}
  </section>;
}
