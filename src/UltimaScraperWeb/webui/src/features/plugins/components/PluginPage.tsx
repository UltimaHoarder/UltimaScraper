import { NavLink, useParams } from 'react-router-dom';
import { PluginSlot } from './PluginSlot';

export function PluginPage() {
  const { pluginId, contributionId } = useParams();
  return <main className="plugin-page">
    <NavLink to="/plugins">Plugins</NavLink>
    <PluginSlot name="navigation.pages" context={{}} pluginId={pluginId} contributionId={contributionId}
      fallback={<p role="status">This plugin page is unavailable or disabled.</p>} />
  </main>;
}
