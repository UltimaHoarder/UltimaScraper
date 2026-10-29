import { useEffect, useRef, useState } from 'react';
import type { ActivePluginWebUI } from '../../../api/types/plugins';
import { resolveApiUrl } from '../../../api/http';
import { pluginRegistry, type PluginContext } from '../lib/pluginHost';

export function PluginSandbox({ plugin, context }: { plugin: ActivePluginWebUI; context: PluginContext }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [source, setSource] = useState('');
  const [failure, setFailure] = useState('');
  const latestContext = useRef(context);
  const port = useRef<MessagePort | null>(null);
  useEffect(() => { latestContext.current = context; }, [context]);
  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      const url = resolveApiUrl(plugin.entry);
      const response = await fetch(url, { signal: controller.signal });
      if (!response.ok) throw new Error('Plugin page could not load.');
      const html = await response.text();
      // Opaque sandbox origin, no application cookies/storage, and no direct
      // network access. Custom UI uses its private MessageChannel only.
      setSource('<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data:; connect-src \'none\'; form-action \'none\'; base-uri \'none\'">' + html);
    };
    void load().catch((error: unknown) => { if (!controller.signal.aborted) setFailure(error instanceof Error ? error.message : 'Plugin page failed.'); });
    return () => controller.abort();
  }, [plugin.entry]);
  useEffect(() => {
    const api = pluginRegistry.forPlugin(plugin.plugin_id);
    const channel = new MessageChannel();
    const projected = pluginRegistry.contextFor(plugin.plugin_id, latestContext.current);
    const serializable = JSON.parse(JSON.stringify(projected)) as PluginContext;
    channel.port1.onmessage = async (event: MessageEvent<unknown>) => {
      const request = event.data;
      if (!request || typeof request !== 'object') return;
      const message = request as { id?: unknown; operation?: unknown; task_type?: unknown; payload?: unknown };
      if (typeof message.id !== 'string' || message.id.length > 128 || typeof message.task_type !== 'string' || !message.payload || typeof message.payload !== 'object' || Array.isArray(message.payload)) return;
      if (message.operation !== 'invoke' && message.operation !== 'jobs') return;
      try {
        const output = message.operation === 'invoke'
          ? await api.invoke(message.task_type, message.payload as PluginContext)
          : await api.submitTask(message.task_type, message.payload as PluginContext);
        channel.port1.postMessage({ id: message.id, result: output });
      } catch (error) { channel.port1.postMessage({ id: message.id, error: error instanceof Error ? error.message : 'Operation failed.' }); }
    };
    const element = frame.current;
    port.current = channel.port1;
    const connect = () => element?.contentWindow?.postMessage({ type: 'usr.plugin.connect', sdk_version: '1.0.0', context: serializable }, '*', [channel.port2]);
    element?.addEventListener('load', connect, { once: true });
    return () => { element?.removeEventListener('load', connect); channel.port1.close(); channel.port2.close(); port.current = null; };
  }, [source, plugin.plugin_id, plugin.package_digest]);
  useEffect(() => {
    port.current?.postMessage({ type: 'usr.plugin.context', context: JSON.parse(JSON.stringify(pluginRegistry.contextFor(plugin.plugin_id, context))) });
  }, [context, plugin.plugin_id]);
  return failure ? <p role="alert">{failure}</p>
    : <iframe ref={frame} title={plugin.display_name} sandbox="allow-scripts" srcDoc={source} referrerPolicy="no-referrer" style={{ width: '100%', border: 0, minHeight: 240 }} />;
}
