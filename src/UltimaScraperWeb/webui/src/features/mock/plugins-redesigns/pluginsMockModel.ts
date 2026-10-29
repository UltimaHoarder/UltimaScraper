import { useState } from 'react';
import type { PluginRecord } from '../../../api/types/plugins';

export interface MockPlugin extends PluginRecord {
  description: string;
  mark: string;
  kind: string;
  domain: string;
  configuration: { service_url?: string; webhook_url?: string; sync_interval_seconds?: number };
}

function record(id: string, name: string, mark: string, kind: string, capabilities: string[], extra: Partial<MockPlugin>): MockPlugin {
  return {
    plugin_id: id, display_name: name, plugin_version: '1.0.0', mark, kind,
    description: '', domain: 'localhost', configuration: {}, status: 'enabled',
    capabilities, requested_capabilities: capabilities, granted_capabilities: capabilities,
    pending_capabilities: [], pending_scopes: [], loaded_at: '2026-10-13T09:30:00Z',
    enabled_at: '2026-10-13T09:30:00Z', disabled_at: null, last_error: null, revision: 4,
    health_status: 'healthy', runtime_storage: 'postgresql', sdk_version: '1.1.0',
    ui_mode: 'declarative', has_settings: true, setup_ready: true,
    delivery_queue: { pending: 0, oldest_pending_at: null, counts: { delivered: 24, exhausted: 0 } },
    ...extra,
  };
}

function seedPlugins(): MockPlugin[] {
  return [
    record('ultima-ai', 'UltimaAI', 'AI', 'Intelligence', ['jobs.submit', 'webui.extend', 'webui.native', 'profiles.read', 'profiles.propose'], {
      description: 'Classify creator profiles with UltimaAI.', ui_mode: 'native', manifest_schema_version: 2,
      domain: 'localhost · 127.0.0.1', configuration: { service_url: 'http://localhost:8029' },
      active_package: { digest: 'sample-ai-v1', previous_digest: 'sample-ai-previous' },
    }),
    record('webshare-proxy', 'WebshareProxy', 'WP', 'Network', ['jobs.submit', 'jobs.schedule', 'runtime.process', 'http.request', 'proxies.sync'], {
      description: 'Sync Webshare proxies and keep account assignments.', domain: 'proxy.webshare.io',
      status: 'disabled', health_status: 'disabled', enabled_at: null, manifest_schema_version: 2,
      setup_required: true, setup_ready: false, configuration: { sync_interval_seconds: 3600 },
      schedules: [{ schedule_id: 'sync', task_type: 'webshare-proxy.sync', last_result: { status: 'success', added: 12, updated: 3, retained_assigned: 2 } }],
    }),
    record('usweb-remote', 'USWeb', 'UW', 'Remote submitter', ['events.read', 'auth.credentials.export', 'remote.jobs.submit'], {
      description: 'Submit remote jobs to the USWeb control plane.', configuration: { service_url: 'http://localhost:8086' },
      delivery_queue: { pending: 2, oldest_pending_at: '2026-10-13T09:41:00Z', counts: { delivered: 18, pending: 2, exhausted: 0 } },
    }),
    record('usweb-admin', 'USWebAdmin', 'UA', 'Remote executor', ['events.read', 'auth.credentials.import', 'webhooks.register', 'remote.jobs.execute', 'remote.callbacks.receive'], {
      description: 'Claim remote work and mirror job progress.', configuration: { service_url: 'http://localhost:8086' },
    }),
    record('example-webhook-relay', 'Webhook Relay', 'WH', 'Events', ['events.read', 'webhooks.register', 'workers.status.read'], {
      description: 'Relay job lifecycle and worker health events.', plugin_version: '0.1.0',
      status: 'disabled', health_status: 'approval_required', enabled_at: null,
      granted_capabilities: ['events.read'], pending_capabilities: ['webhooks.register', 'workers.status.read'],
      domain: 'example.com', configuration: { webhook_url: 'https://example.com/webhooks/usr-events' },
      delivery_queue: { pending: 4, oldest_pending_at: '2026-10-13T09:38:00Z', counts: { pending: 3, retrying: 1, delivered: 42, exhausted: 0 } },
    }),
  ];
}

export interface MockActivity { id: number; time: string; pluginId: string; message: string }
function seedActivity(): MockActivity[] {
  return [
    { id: 3, time: '09:42:00', pluginId: 'usweb-remote', message: 'Two outbound deliveries pending' },
    { id: 2, time: '09:38:00', pluginId: 'example-webhook-relay', message: 'Two capabilities require approval' },
    { id: 1, time: '09:30:00', pluginId: 'ultima-ai', message: 'Plugin enabled · native UI loaded' },
  ];
}

export function needsApproval(plugin: MockPlugin) { return !!(plugin.pending_capabilities?.length || plugin.pending_scopes?.length); }
export function readiness(plugin: MockPlugin) {
  if (needsApproval(plugin)) return 'Approval required';
  if (plugin.setup_required && !plugin.setup_ready) return 'Setup required';
  return plugin.status === 'enabled' ? 'Healthy' : 'Ready to enable';
}

/** All actions stay in React state; this model has no API or plugin-host dependency. */
export function usePluginsMockModel(initialId = 'ultima-ai') {
  const [plugins, setPlugins] = useState(seedPlugins);
  const [activity, setActivity] = useState(seedActivity);
  const [notice, setNotice] = useState('');
  const [selectedId, setSelectedId] = useState(initialId);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const selected = plugins.find((plugin) => plugin.plugin_id === selectedId) ?? plugins[0];
  const visible = plugins.filter((plugin) => {
    const matchesText = `${plugin.display_name} ${plugin.plugin_id} ${plugin.kind} ${plugin.capabilities.join(' ')}`.toLowerCase().includes(search.toLowerCase());
    return matchesText && (filter === 'all' || (filter === 'attention' ? needsApproval(plugin) || (plugin.setup_required && !plugin.setup_ready) : plugin.status === filter));
  });
  function update(id: string, patch: Partial<MockPlugin>, message: string) {
    setPlugins((current) => current.map((plugin) => plugin.plugin_id === id ? { ...plugin, ...patch } : plugin));
    setNotice(message);
    setActivity((current) => [{ id: (current[0]?.id ?? 0) + 1, time: new Date().toISOString().slice(11, 19), pluginId: id, message }, ...current].slice(0, 20));
  }
  function approve(plugin: MockPlugin) {
    update(plugin.plugin_id, { pending_capabilities: [], pending_scopes: [], granted_capabilities: [...plugin.capabilities], health_status: plugin.status === 'enabled' ? 'healthy' : 'disabled' }, `${plugin.display_name}: access approved in preview`);
  }
  function toggle(plugin: MockPlugin) {
    if (needsApproval(plugin) || (plugin.setup_required && !plugin.setup_ready)) {
      setSelectedId(plugin.plugin_id); setNotice(`${plugin.display_name}: ${readiness(plugin).toLowerCase()} before enabling`); return;
    }
    const enabled = plugin.status !== 'enabled';
    update(plugin.plugin_id, { status: enabled ? 'enabled' : 'disabled', health_status: enabled ? 'healthy' : 'disabled', ...(enabled ? { enabled_at: new Date().toISOString() } : { disabled_at: new Date().toISOString() }) }, `${plugin.display_name}: ${enabled ? 'enabled' : 'disabled'} in preview`);
  }
  function reset() { setPlugins(seedPlugins()); setActivity(seedActivity()); setNotice('Preview reset'); setSelectedId('ultima-ai'); setSearch(''); setFilter('all'); }
  return {
    plugins, visible, selected, selectedId, setSelectedId, search, setSearch, filter, setFilter, notice, activity,
    enabled: plugins.filter((plugin) => plugin.status === 'enabled').length,
    attention: plugins.filter((plugin) => needsApproval(plugin) || (plugin.setup_required && !plugin.setup_ready)).length,
    pending: plugins.reduce((total, plugin) => total + (plugin.delivery_queue?.pending ?? 0), 0),
    approve, toggle, update, reset,
    reload: (plugin: MockPlugin) => update(plugin.plugin_id, { revision: plugin.revision + 1 }, `${plugin.display_name}: manifest reloaded in preview`),
    configure: (plugin: MockPlugin, configuration: MockPlugin['configuration']) => update(plugin.plugin_id, { configuration }, `${plugin.display_name}: settings saved in preview`),
    setup: (plugin: MockPlugin) => update(plugin.plugin_id, { setup_ready: true }, `${plugin.display_name}: sample credential validated`),
    sync: (plugin: MockPlugin) => update(plugin.plugin_id, { schedules: plugin.schedules?.map((schedule) => ({ ...schedule, next_at: new Date(Date.now() + (plugin.configuration.sync_interval_seconds ?? 3600) * 1000).toISOString(), last_result: { status: 'success', added: 2, updated: 1, retained_assigned: 2 } })) }, `${plugin.display_name}: sample sync complete · 2 added, 1 updated`),
    rollback: (plugin: MockPlugin) => update(plugin.plugin_id, { plugin_version: '0.9.0', active_package: { digest: plugin.active_package!.previous_digest!, previous_digest: null } }, `${plugin.display_name}: previous sample package restored`),
    create: (name: string, id: string) => {
      if (!name.trim() || !/^[a-z][a-z0-9-]*$/.test(id) || plugins.some((plugin) => plugin.plugin_id === id)) return false;
      const plugin = record(id, name, 'PL', 'Custom', [], { description: 'A new sample plugin manifest.', status: 'disabled', health_status: 'disabled', has_settings: false, revision: 1 });
      setPlugins((current) => [...current, plugin]); setSelectedId(id); setNotice(`${name}: sample manifest created`); return true;
    },
  };
}
export type PluginsMockModel = ReturnType<typeof usePluginsMockModel>;
