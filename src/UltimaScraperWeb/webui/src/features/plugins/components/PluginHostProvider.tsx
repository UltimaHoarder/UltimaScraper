import { useEffect, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { listActiveWebUI } from '../../../api/plugins';
import { initPluginHost, pluginRegistry } from '../lib/pluginHost';
import { pluginTransport } from '../lib/pluginClient';
import { PluginResourceHost } from '../lib/pluginResources';
import { useNativePluginTrust } from '../lib/useNativePluginTrust';
import { useDevMode } from '../../settings/hooks/useWebUIPreferences';
import './plugin-sdk.css';

export function PluginHostProvider({ children }: { children: ReactNode }) {
  const [host] = useState(() => new PluginResourceHost());
  useEffect(() => {
    initPluginHost();
    pluginRegistry.setTransport(pluginTransport);
    return () => host.dispose();
  }, [host]);

  // Plugins only run while Developer mode is on.
  const devMode = useDevMode();
  const { data: activePlugins, isError } = useQuery({
    queryKey: ['active-plugins-webui'],
    enabled: devMode,
    queryFn: listActiveWebUI,
    staleTime: 10_000,
    refetchInterval: 10_000,
  });

  const { allowed: allowNative, known: trustKnown } = useNativePluginTrust();

  useEffect(() => {
    if (!devMode || isError) host.sync([]);
    // Native code waits until this backend's trust is known.
    else if (activePlugins && trustKnown) host.sync(activePlugins, { allowNative });
  }, [activePlugins, allowNative, devMode, host, isError, trustKnown]);

  return <>{children}</>;
}
