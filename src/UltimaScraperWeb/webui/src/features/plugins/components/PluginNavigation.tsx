import { useSyncExternalStore } from 'react';
import { NavLink } from 'react-router-dom';
import { pluginRegistry } from '../lib/pluginHost';

export function PluginNavigation({ onNavigate }: { onNavigate: () => void }) {
  useSyncExternalStore(pluginRegistry.subscribe, pluginRegistry.getSnapshot, pluginRegistry.getSnapshot);
  const pages = pluginRegistry.getRegistrations('navigation.pages');
  if (!pages.length) return null;
  return <section className="nav-section plugin-navigation" aria-label="Plugin pages">
    <div className="nav-section-title">Plugin pages</div>
    {pages.map(({ id, pluginId }) => {
      const descriptor = pluginRegistry.descriptor(pluginId);
      const title = descriptor?.contributions?.find((item) => item.contribution_id === id)?.title ?? descriptor?.display_name ?? pluginId;
      return <NavLink key={`${pluginId}:${id}`} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
        to={`/plugins/${encodeURIComponent(pluginId)}/${encodeURIComponent(id)}`} onClick={onNavigate}>{title}</NavLink>;
    })}
  </section>;
}
