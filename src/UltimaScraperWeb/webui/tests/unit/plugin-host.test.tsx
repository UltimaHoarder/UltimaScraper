import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ActivePluginWebUI } from '../../src/api/types/plugins';
import { PluginRegistry, initPluginHost, pluginRegistry } from '../../src/features/plugins/lib/pluginHost';
import { PluginResourceHost } from '../../src/features/plugins/lib/pluginResources';
import { PluginSlot } from '../../src/features/plugins/components/PluginSlot';

function descriptor(id = 'test-plugin', version = '1'): ActivePluginWebUI {
  return { plugin_id: id, display_name: id, plugin_version: version, package_digest: version,
    mode: 'native', entry: `/plugins/${id}.js?v=${version}`, styles: [`/plugins/${id}.css?v=${version}`] };
}

afterEach(() => { cleanup(); pluginRegistry.deactivate('test-plugin'); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('plugin SDK lifecycle', () => {
  it('removes slots and hooks and rejects stale APIs on disable', () => {
    const registry = new PluginRegistry();
    const api = registry.activate(descriptor());
    api.registerSlot('users.card.badges', () => null);
    api.registerHook('refresh', () => 'called');
    registry.deactivate('test-plugin');
    expect(api.signal.aborted).toBe(true);
    expect(registry.getRegistrations('users.card.badges')).toEqual([]);
    expect(() => api.triggerHook('refresh')).toThrow(/disabled/);
    expect(() => api.registerSlot('users.card.badges', () => null)).toThrow(/disabled/);
  });

  it('does not unregister another plugin when an old cleanup runs', () => {
    const registry = new PluginRegistry();
    const old = registry.activate(descriptor()).registerSlot('users.card.badges', () => null, { id: 'badge' });
    registry.activate(descriptor('test-plugin', '2')).registerSlot('users.card.badges', () => null, { id: 'badge' });
    old();
    expect(registry.getRegistrations('users.card.badges')).toHaveLength(1);
  });

  it('aborts pending operations and rejects late results after an upgrade', async () => {
    const registry = new PluginRegistry();
    let resolve!: (value: unknown) => void;
    registry.setTransport(vi.fn((_id, _op, _task, _input, signal) => {
      expect(signal.aborted).toBe(false);
      return new Promise((done) => { resolve = done; });
    }));
    const api = registry.activate(descriptor());
    const pending = api.invoke('predict', {});
    registry.activate(descriptor('test-plugin', '2'));
    resolve('late');
    await expect(pending).rejects.toThrow(/replaced/);
    expect(api.signal.aborted).toBe(true);
  });

  it('projects sandbox context without leaking callbacks or ungranted fields', () => {
    const registry = new PluginRegistry();
    registry.activate({ ...descriptor(), mode: 'sandbox', access: { profile_fields: ['name'], task_types: [], outbound_domains: [], propose_profile_changes: false } });
    expect(registry.contextFor('test-plugin', { user: { name: 'Creator', password: 'private' }, setFieldValue: vi.fn(), formValues: { name: 'draft' } })).toEqual({ user: { name: 'Creator' } });
  });

  it('reconciles authenticated scripts and styles by package and removes disabled resources', async () => {
    const fetchAsset = vi.fn(async () => new Response('/* bundled asset */'));
    vi.stubGlobal('fetch', fetchAsset);
    initPluginHost();
    const host = new PluginResourceHost();
    host.sync([descriptor()]);
    await waitFor(() => expect(document.querySelectorAll('script[data-usr-plugin="test-plugin"]')).toHaveLength(1));
    const old = document.querySelector('script[data-usr-plugin="test-plugin"]');
    host.sync([descriptor()]);
    expect(document.querySelectorAll('script[data-usr-plugin="test-plugin"]')).toHaveLength(1);
    host.sync([descriptor('test-plugin', '2')]);
    expect(old?.isConnected).toBe(false);
    await waitFor(() => expect(document.querySelector('script[data-usr-plugin="test-plugin"]')?.getAttribute('data-usr-package')).toBe('2'));
    expect(fetchAsset).toHaveBeenCalledTimes(4);
    host.sync([]);
    expect(document.querySelectorAll('[data-usr-plugin="test-plugin"]')).toHaveLength(0);
    expect(() => window.USR?.forPlugin('test-plugin')).toThrow(/inactive/);
  });

  it('loads no native code from an untrusted backend until it is trusted', async () => {
    const fetchAsset = vi.fn(async () => new Response('/* bundled asset */'));
    vi.stubGlobal('fetch', fetchAsset);
    initPluginHost();
    const host = new PluginResourceHost();
    host.sync([{ ...descriptor(), contributions: [
      { contribution_id: 'c1', slot: 'users.card.badges', kind: 'badge', title: 'Badge', text: '', order: 0, task_type: null },
    ] }], { allowNative: false });
    // Host-rendered contributions stay; the plugin's own scripts and styles do not.
    expect(pluginRegistry.getRegistrations('users.card.badges')).toHaveLength(1);
    expect(fetchAsset).not.toHaveBeenCalled();
    expect(document.querySelectorAll('[data-usr-plugin="test-plugin"]')).toHaveLength(0);
    host.sync([descriptor()], { allowNative: true });
    await waitFor(() => expect(document.querySelectorAll('script[data-usr-plugin="test-plugin"]')).toHaveLength(1));
    host.sync([descriptor()], { allowNative: false });
    expect(document.querySelectorAll('[data-usr-plugin="test-plugin"]')).toHaveLength(0);
    host.dispose();
  });

  it('unmounts a rendered contribution when its plugin is disabled', () => {
    const api = pluginRegistry.activate(descriptor());
    api.registerSlot('users.card.badges', () => <span>Plugin badge</span>);
    render(<PluginSlot name="users.card.badges" context={{}} fallback={<span>Fallback</span>} />);
    expect(screen.getByText('Plugin badge')).toBeInTheDocument();
    act(() => pluginRegistry.deactivate('test-plugin'));
    expect(screen.queryByText('Plugin badge')).not.toBeInTheDocument();
    expect(screen.getByText('Fallback')).toBeInTheDocument();
  });

  it('contains a plugin render failure within the slot', () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const api = pluginRegistry.activate(descriptor());
    api.registerSlot('users.card.badges', () => { throw new Error('Plugin crash'); });
    render(<><span>Main application</span><PluginSlot name="users.card.badges" context={{}} /></>);
    expect(screen.getByText('Main application')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Plugin unavailable');
  });
});
