import { PluginContribution } from '../components/PluginContribution';
import { PluginSandbox } from '../components/PluginSandbox';
import type { ActivePluginWebUI } from '../../../api/types/plugins';
import { resolveApiUrl } from '../../../api/http';
import { forgetPluginToken } from './pluginClient';
import { pluginRegistry, type PluginContext } from './pluginHost';

export class PluginResourceHost {
  private loaded = new Map<string, { fingerprint: string; elements: HTMLElement[] }>();
  sync(plugins: ActivePluginWebUI[], { allowNative = true }: { allowNative?: boolean } = {}): void {
    const list = Array.isArray(plugins) ? plugins : [];
    const desired = new Set(list.map((plugin) => plugin.plugin_id));
    for (const id of this.loaded.keys()) if (!desired.has(id)) this.remove(id);
    for (const plugin of list) {
      const fingerprint = JSON.stringify([plugin, allowNative]);
      if (this.loaded.get(plugin.plugin_id)?.fingerprint === fingerprint) continue;
      this.remove(plugin.plugin_id);
      const api = pluginRegistry.activate({ ...plugin, mode: plugin.mode ?? 'native' });
      const elements: HTMLElement[] = [];
      this.loaded.set(plugin.plugin_id, { fingerprint, elements });
      for (const contribution of plugin.contributions ?? []) {
        const Component = (context: PluginContext) => plugin.mode === 'sandbox'
          ? <PluginSandbox plugin={plugin} context={context} />
          : <PluginContribution pluginId={plugin.plugin_id} contribution={contribution} context={context} />;
        api.registerSlot(contribution.slot, Component, { id: contribution.contribution_id, order: contribution.order });
      }
      if (plugin.mode === 'sandbox' || plugin.mode === 'declarative' || !plugin.entry) continue;
      // An untrusted backend keeps its host-rendered contributions, but its
      // scripts and styles never enter this page.
      if (!allowNative) continue;
      const load = async () => {
        const assets = await Promise.all([...plugin.styles, plugin.entry].map(async (asset) => {
          const response = await fetch(resolveApiUrl(asset), { signal: api.signal });
          if (!response.ok) throw new Error(`Plugin asset returned HTTP ${response.status}.`);
          return response.text();
        }));
        if (api.signal.aborted) return;
        for (const css of assets.slice(0, -1)) {
          const style = document.createElement('style');
          style.dataset.usrPlugin = plugin.plugin_id; style.textContent = css;
          document.head.appendChild(style); elements.push(style);
        }
        // Native UI is explicitly trusted code. Fetching first ensures assets
        // use authenticated requests and never expose the admin token in URLs.
        const script = document.createElement('script');
        script.dataset.usrPlugin = plugin.plugin_id;
        script.dataset.usrPackage = plugin.package_digest ?? plugin.plugin_version;
        script.textContent = assets.at(-1) ?? '';
        elements.push(script); document.body.appendChild(script);
      };
      void load().catch((error: unknown) => {
        if (!api.signal.aborted) {
          console.error(`[PluginHost] ${plugin.plugin_id} assets failed to load.`, error);
          this.remove(plugin.plugin_id);
        }
      });
    }
  }
  remove(pluginId: string): void {
    pluginRegistry.deactivate(pluginId);
    forgetPluginToken(pluginId);
    for (const element of this.loaded.get(pluginId)?.elements ?? []) element.remove();
    this.loaded.delete(pluginId);
  }
  dispose(): void { for (const id of [...this.loaded.keys()]) this.remove(id); }
}
