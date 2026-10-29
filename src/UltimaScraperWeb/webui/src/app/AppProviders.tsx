import type { ReactNode } from 'react';
import { WebhookStreamProvider } from '../hooks/useWebhookStream';
import { ThemeProvider } from './theme/ThemeProvider';
import { AppBootstrapProvider } from './bootstrap/AppBootstrapProvider';
import { PluginHostProvider } from '../features/plugins/components/PluginHostProvider';
import { BackendScope } from './backends/BackendScope';

/**
 * The app's providers for one backend. Render them with key={connectionId} so
 * a switch starts each backend fresh.
 */
export function AppProviders({ children, connectionId }: { children: ReactNode; connectionId: string }) {
  return (
    <BackendScope connectionId={connectionId}>
      <ThemeProvider>
        <AppBootstrapProvider>
          <PluginHostProvider>
            <WebhookStreamProvider>{children}</WebhookStreamProvider>
          </PluginHostProvider>
        </AppBootstrapProvider>
      </ThemeProvider>
    </BackendScope>
  );
}
