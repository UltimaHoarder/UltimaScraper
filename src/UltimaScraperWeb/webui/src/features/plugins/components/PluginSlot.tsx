import { Component, useSyncExternalStore, type ReactNode } from 'react';
import { pluginRegistry, type PluginContext, type PluginSlotName } from '../lib/pluginHost';

interface PluginSlotProps {
  name: PluginSlotName;
  context: PluginContext;
  fallback?: ReactNode;
  pluginId?: string;
  contributionId?: string;
}

class PluginBoundary extends Component<{ children: ReactNode; pluginId: string }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error) { console.error(`[PluginHost] ${this.props.pluginId} render failed`, error); }
  render() {
    return this.state.failed
      ? <span role="status" title={`${this.props.pluginId} could not render`}>Plugin unavailable</span>
      : this.props.children;
  }
}

export function PluginSlot({
  name,
  context,
  fallback = null,
  pluginId: selectedPlugin,
  contributionId,
}: PluginSlotProps) {
  useSyncExternalStore(pluginRegistry.subscribe, pluginRegistry.getSnapshot, pluginRegistry.getSnapshot);
  const registrations = pluginRegistry.getRegistrations(name).filter((item) => (!selectedPlugin || item.pluginId === selectedPlugin) && (!contributionId || item.id === contributionId));
  if (registrations.length === 0) {
    return <>{fallback}</>;
  }

  return (
    <>
      {registrations.map(({ id, pluginId, component: Contribution }) => (
        <PluginBoundary key={`${pluginId}:${id}:${pluginRegistry.descriptor(pluginId)?.package_digest ?? ''}`} pluginId={pluginId}>
          <Contribution {...pluginRegistry.contextFor(pluginId, context)} />
        </PluginBoundary>
      ))}
    </>
  );
}
