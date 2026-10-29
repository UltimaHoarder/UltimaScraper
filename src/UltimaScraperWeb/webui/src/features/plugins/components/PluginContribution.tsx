import { useState } from 'react';
import type { PluginUIContribution } from '../../../api/types/plugins';
import { pluginRegistry, type PluginContext } from '../lib/pluginHost';

export function PluginContribution({ pluginId, contribution, context }: {
  pluginId: string; contribution: PluginUIContribution; context: PluginContext;
}) {
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<unknown>();
  const [error, setError] = useState('');
  const run = async () => {
    if (!contribution.task_type) return;
    setPending(true); setError('');
    const user = context.user ?? context.item;
    const payload = user && typeof user === 'object' ? user as PluginContext : {};
    try {
      const api = pluginRegistry.forPlugin(pluginId);
      const output = contribution.kind === 'action'
        ? await api.submitTask(contribution.task_type, payload)
        : await api.invoke(contribution.task_type, payload);
      if (!api.signal.aborted) setResult(output);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Plugin operation failed.'); }
    finally { setPending(false); }
  };
  if (contribution.kind === 'badge') return <span className="plugin-contribution-badge" title={contribution.text}>{contribution.title}</span>;
  const fields = result && typeof result === 'object' && 'fields' in result
    ? (result as { fields: unknown }).fields : null;
  const apply = () => {
    if (!fields || typeof fields !== 'object' || typeof context.setFieldValue !== 'function') return;
    const form = context.formValues && typeof context.formValues === 'object' ? context.formValues : {};
    for (const [field, value] of Object.entries(fields)) {
      if (Object.hasOwn(form, field) && typeof value === 'string') context.setFieldValue(field, value);
    }
  };
  return <section className="plugin-contribution" aria-label={contribution.title}>
    {contribution.kind !== 'action' && <><strong>{contribution.title}</strong><p>{contribution.text}</p></>}
    {contribution.task_type && <button type="button" disabled={pending} onClick={() => void run()}>{pending ? 'Working…' : contribution.title}</button>}
    {error && <p role="alert">{error}</p>}
    {result !== undefined && <pre>{JSON.stringify(result, null, 2)}</pre>}
    {fields && typeof context.setFieldValue === 'function' ? <button type="button" onClick={apply}>Apply suggestions to draft</button> : null}
  </section>;
}
