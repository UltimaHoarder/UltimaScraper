import type { PluginRecord } from '../../../api/types/plugins';

export function PluginLifecycleActions({
  plugin,
  onEnable,
  onDisable,
  onReload,
  onEdit,
  onUninstall,
}: {
  plugin: PluginRecord;
  onEnable: (id: string) => void;
  onDisable: (id: string) => void;
  onReload: (id: string) => void;
  onEdit: (id: string) => void;
  onUninstall: (id: string) => void;
}) {
  const { plugin_id, status } = plugin;
  return (
    <div className="plugin-actions">
      {status !== 'missing' && (
        <button className="plugin-action-btn" onClick={() => onEdit(plugin_id)}>
          Edit
        </button>
      )}
      {status === 'disabled' && (
        <button
          className="plugin-action-btn plugin-action-btn--enable"
          onClick={() => onEnable(plugin_id)}
        >
          Enable
        </button>
      )}
      {status === 'enabled' && (
        <button
          className="plugin-action-btn plugin-action-btn--disable"
          onClick={() => onDisable(plugin_id)}
        >
          Disable
        </button>
      )}
      <button className="plugin-action-btn" onClick={() => onReload(plugin_id)}>
        Reload
      </button>
      <button type="button" className="plugin-action-btn plugin-action-btn--purge" onClick={() => onUninstall(plugin_id)}>Uninstall</button>
    </div>
  );
}
