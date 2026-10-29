import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react';
import type { PluginRecord } from '../../../api/types/plugins';
import type { usePluginsPageController } from '../hooks/usePluginsPageController';
import { PluginLifecycleActions } from './PluginLifecycleActions';
import { PluginManifestEditor } from './PluginManifestEditor';
import { PluginRuntimeDetails } from './PluginRuntimeDetails';
import { PluginSettingsPanel } from './PluginSettingsPanel';
import './PluginSplitWorkspace.css';

type Controller = ReturnType<typeof usePluginsPageController>;
type Tab = 'overview' | 'settings' | 'access' | 'manifest';
const TABS: Tab[] = ['overview', 'settings', 'access', 'manifest'];

function pendingAccess(plugin: PluginRecord) {
  return !!(plugin.pending_capabilities?.length || plugin.pending_scopes?.length);
}
function needsAttention(plugin: PluginRecord) {
  return pendingAccess(plugin) || (plugin.setup_required && !plugin.setup_ready) ||
    plugin.status === 'invalid' || plugin.status === 'missing' ||
    ['incompatible', 'invalid', 'missing', 'approval_required'].includes(plugin.health_status ?? '');
}
function healthLabel(plugin: PluginRecord) {
  if (plugin.status === 'invalid' || plugin.status === 'missing') return plugin.status;
  if (pendingAccess(plugin)) return 'Approval required';
  if (plugin.setup_required && !plugin.setup_ready) return 'Setup required';
  return (plugin.health_status ?? (plugin.status === 'disabled' ? 'disabled' : 'unknown')).replaceAll('_', ' ');
}
function Health({ plugin }: { plugin: PluginRecord }) {
  const tone = plugin.status === 'invalid' || plugin.status === 'missing' ? 'danger' : needsAttention(plugin) ? 'warning' : plugin.health_status === 'healthy' || plugin.health_status === 'starting' ? 'accent' : 'muted';
  return <span className={`psi-health psi-health--${tone}`}><span />{healthLabel(plugin)}</span>;
}
function Mark({ plugin }: { plugin: PluginRecord }) {
  const words = plugin.display_name.replace(/([a-z])([A-Z])/g, '$1 $2').split(/[\s_-]+/).filter(Boolean);
  const initials = words.length > 1 ? words.slice(0, 2).map((word) => word[0]).join('') : plugin.display_name.slice(0, 2);
  return <span aria-hidden="true" className={`psi-mark ${plugin.status === 'enabled' ? 'psi-mark--active' : ''}`}>{initials.toUpperCase()}</span>;
}
function Overview({ plugin }: { plugin: PluginRecord }) {
  return <>
    <h3 className="psi-section-title">At a glance</h3>
    <dl className="psi-facts">
      <div><dt>Status</dt><dd>{plugin.status}</dd></div>
      <div><dt>Health</dt><dd><Health plugin={plugin} /></dd></div>
      <div><dt>Version</dt><dd>{plugin.plugin_version}</dd></div>
      <div><dt>Manifest revision</dt><dd>{plugin.revision}</dd></div>
      <div><dt>Storage</dt><dd>{plugin.runtime_storage ?? '—'}</dd></div>
      <div><dt>Pending deliveries</dt><dd>{plugin.delivery_queue?.pending ?? '—'}</dd></div>
      <div><dt>SDK version</dt><dd>{plugin.sdk_version ?? '—'}</dd></div>
      <div><dt>UI mode</dt><dd>{plugin.ui_mode ?? '—'}</dd></div>
    </dl>
    {plugin.health_message && <p className="psi-health-message">{plugin.health_message}</p>}
    {plugin.last_error && <p className="psi-error" role="alert">{plugin.last_error}</p>}
    <div className="psi-runtime"><PluginRuntimeDetails plugin={plugin} /></div>
  </>;
}
function Access({ plugin }: { plugin: PluginRecord }) {
  const requested = plugin.requested_capabilities ?? plugin.capabilities;
  return <>
    <div className="psi-section-heading"><h3 className="psi-section-title">Requested access</h3><span>{plugin.granted_capabilities?.length ?? '—'} / {requested.length} granted</span></div>
    {requested.length ? <dl className="psi-capabilities">{requested.map((capability) => {
      const pending = plugin.pending_capabilities?.includes(capability);
      const granted = plugin.granted_capabilities?.includes(capability);
      return <div key={capability}><dt><code>{capability}</code></dt><dd className={pending ? 'psi-warning' : granted ? 'psi-accent' : ''}>{pending ? 'Pending' : granted ? 'Granted' : 'Requested'}</dd></div>;
    })}</dl> : <p className="psi-muted">No capabilities requested.</p>}
    {!!plugin.pending_scopes?.length && <><h3 className="psi-section-title">Pending scopes</h3><ul className="psi-scopes">{plugin.pending_scopes.map((scope) => <li key={scope}><code>{scope}</code></li>)}</ul></>}
    <dl className="psi-facts"><div><dt>UI access</dt><dd>{plugin.ui_mode === 'native' ? 'Trusted application code' : plugin.ui_mode === 'sandbox' ? 'Isolated custom UI' : plugin.ui_mode === 'declarative' ? 'Host-rendered contributions' : '—'}</dd></div><div><dt>USR compatibility</dt><dd>{plugin.usr_compatibility ?? '—'}</dd></div></dl>
  </>;
}

function Inspector({ plugin, controller }: { plugin: PluginRecord; controller: Controller }) {
  const id = useId();
  const tabButtons = useRef<(HTMLButtonElement | null)[]>([]);
  const [tab, setTab] = useState<Tab>('overview');
  const [settingsOpened, setSettingsOpened] = useState(false);
  const busy = controller.isSavingManifest || controller.isSavingSecret;
  const settingsAvailable = plugin.has_settings || plugin.manifest_schema_version === 2;

  function openTab(next: Tab) {
    setTab(next);
    if (next === 'settings') setSettingsOpened(true);
    if (next === 'manifest' && plugin.status !== 'missing' && controller.editingPluginId !== plugin.plugin_id &&
        (!controller.isLoadingManifest || controller.loadingManifestPluginId !== plugin.plugin_id)) {
      controller.handleEdit(plugin.plugin_id);
    }
  }
  function navigateTabs(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next: number;
    if (event.key === 'ArrowRight') next = (index + 1) % TABS.length;
    else if (event.key === 'ArrowLeft') next = (index + TABS.length - 1) % TABS.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = TABS.length - 1;
    else return;
    event.preventDefault();
    if (busy) return;
    openTab(TABS[next]);
    tabButtons.current[next]?.focus();
  }

  return <section className="psi-inspector" aria-labelledby={`${id}-title`}>
    <header className="psi-inspector-header">
      <Mark plugin={plugin} />
      <div><h2 id={`${id}-title`}>{plugin.display_name}</h2><code>{plugin.plugin_id}</code></div>
      <span className="psi-version">v{plugin.plugin_version}</span>
    </header>
    <div className="psi-inspector-state"><Health plugin={plugin} /><span>{plugin.status}</span></div>
    <nav role="tablist" aria-label="Plugin details" className="psi-tabs">
      {TABS.map((item, index) => <button key={item} ref={(node) => { tabButtons.current[index] = node; }}
        type="button" role="tab" id={`${id}-tab-${item}`} aria-controls={`${id}-panel-${item}`} aria-selected={tab === item}
        tabIndex={tab === item ? 0 : -1} disabled={busy} onClick={() => openTab(item)} onKeyDown={(event) => navigateTabs(event, index)}>
        {item}{item === 'access' && pendingAccess(plugin) && <span className="psi-access-dot" aria-hidden="true" />}
      </button>)}
    </nav>
    <div id={`${id}-panel-overview`} role="tabpanel" aria-labelledby={`${id}-tab-overview`} className="psi-panel" hidden={tab !== 'overview'}><Overview plugin={plugin} /></div>
    <div id={`${id}-panel-settings`} role="tabpanel" aria-labelledby={`${id}-tab-settings`} className="psi-panel" hidden={tab !== 'settings'}>
      {settingsOpened && (settingsAvailable ? <PluginSettingsPanel key={`${plugin.plugin_id}:${plugin.active_package?.digest ?? 'legacy'}`} plugin={plugin} embedded
        onClose={() => setTab('overview')} onManageCredentials={() => openTab('manifest')} /> : <p className="psi-muted">This plugin does not declare any settings.</p>)}
      {plugin.setup_required && <div className="psi-setup-callout"><span>{plugin.setup_ready ? 'Managed credentials configured' : 'Setup required'}</span></div>}
    </div>
    <div id={`${id}-panel-access`} role="tabpanel" aria-labelledby={`${id}-tab-access`} className="psi-panel" hidden={tab !== 'access'}><Access plugin={plugin} /></div>
    <div id={`${id}-panel-manifest`} role="tabpanel" aria-labelledby={`${id}-tab-manifest`} className="psi-panel" hidden={tab !== 'manifest'}>
      {plugin.status === 'missing' ? <p className="psi-muted">The plugin manifest is missing. Restore the package, then reload the plugin.</p> :
        controller.editingPluginId === plugin.plugin_id ? <PluginManifestEditor pluginId={plugin.plugin_id}
          manifestYaml={controller.editingManifestYaml} secrets={controller.editingSecrets} secretDrafts={controller.secretDrafts}
          onChange={controller.setEditingManifestYaml} onSave={controller.handleManifestSave}
          onSecretDraftChange={controller.updateSecretDraft} onSetSecret={controller.handleSetSecret}
          onCancel={() => { controller.cancelEdit(); setTab('overview'); }}
          isLoading={controller.isLoadingManifest} isSaving={controller.isSavingManifest} isSavingSecret={controller.isSavingSecret} /> :
          controller.isLoadingManifest && controller.loadingManifestPluginId === plugin.plugin_id ? <p role="status">Loading manifest…</p> :
            <button type="button" className="plugin-action-btn" onClick={() => controller.handleEdit(plugin.plugin_id)}>Edit manifest</button>}
    </div>
    <footer className="psi-inspector-footer">
      <PluginLifecycleActions plugin={plugin}
        onEnable={controller.handleEnable} onDisable={controller.handleDisable} onReload={controller.handleReload}
        onEdit={() => openTab('manifest')} onUninstall={() => controller.setUninstallTarget(plugin)} />
      {plugin.status !== 'missing' && <button type="button" className="plugin-action-btn" onClick={() => controller.setSetupTarget({ pluginId: plugin.plugin_id, enable: false })}>Setup</button>}
    </footer>
  </section>;
}

export function PluginSplitWorkspace({ controller }: { controller: Controller }) {
  const { selectedPluginId: selectedId, setSelectedPluginId: setSelectedId } = controller;
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all');
  const { plugins } = controller;
  useEffect(() => {
    if (!plugins.some((plugin) => plugin.plugin_id === selectedId)) {
      setSelectedId(plugins[0]?.plugin_id ?? null);
    }
  }, [plugins, selectedId, setSelectedId]);
  // Selection follows identity, not list order or filters, when polling refreshes records.
  const selected = plugins.find((plugin) => plugin.plugin_id === selectedId) ?? plugins[0];
  const visible = plugins.filter((plugin) => {
    const haystack = [plugin.display_name, plugin.plugin_id, ...(plugin.requested_capabilities ?? plugin.capabilities)].join(' ').toLowerCase();
    return haystack.includes(search.trim().toLowerCase()) && (filter === 'all' || (filter === 'attention' ? needsAttention(plugin) : plugin.status === filter));
  });
  const busy = controller.isSavingManifest || controller.isSavingSecret;

  return <div className="psi-workspace">
    <div className="psi-toolbar">
      <label className="psi-search"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><circle cx="8" cy="8" r="5.5" /><path d="m12 12 5 5" /></svg><input aria-label="Search plugins" placeholder="Search plugins, capabilities…" value={search} onChange={(event) => setSearch(event.target.value)} /></label>
      <select aria-label="Filter plugins" value={filter} onChange={(event) => setFilter(event.target.value)}><option value="all">All plugins</option><option value="enabled">Enabled</option><option value="disabled">Disabled</option><option value="attention">Needs attention</option><option value="invalid">Invalid</option><option value="missing">Missing</option></select>
      <span className="psi-result-count">{visible.length} / {plugins.length}</span>
    </div>
    <div className="psi-split">
      <aside className="psi-picker" aria-label="Plugin list">
        <header><h2>Plugins</h2><span>{visible.length}</span></header>
        <div className="psi-picker-scroll">
          {visible.map((plugin) => <button type="button" key={plugin.plugin_id} className="psi-picker-item"
            aria-pressed={selected?.plugin_id === plugin.plugin_id} disabled={busy}
            onClick={() => { if (selected?.plugin_id !== plugin.plugin_id) { controller.cancelEdit(); setSelectedId(plugin.plugin_id); } }}>
            <Mark plugin={plugin} /><span><strong>{plugin.display_name}</strong><code>{plugin.plugin_id}</code><small>{healthLabel(plugin)}</small></span>
            <span className={`psi-picker-dot ${needsAttention(plugin) ? 'psi-warning' : plugin.status === 'enabled' ? 'psi-accent' : ''}`} />
          </button>)}
          {!visible.length && <div className="psi-no-results"><p>No plugins match.</p><button type="button" className="plugin-action-btn" onClick={() => { setSearch(''); setFilter('all'); }}>Clear filters</button></div>}
        </div>
        <footer>Select a plugin to inspect</footer>
      </aside>
      {selected && <Inspector key={selected.plugin_id} plugin={selected} controller={controller} />}
    </div>
  </div>;
}
